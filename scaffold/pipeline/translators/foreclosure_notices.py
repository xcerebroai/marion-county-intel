"""
foreclosure_notices translator (built-in, v5.1.2-beta-r2+).

Converts NORMALIZED foreclosure-notice records (produced by a county-side
scraper) into framework signals + placeholder parcels.

This translator consumes the framework-canonical RAW RECORD shape declared
in MASTER_PROMPT §4.32 (Scraper-to-Translator Data Contract, v5.1.2-beta-r2+):

    {
        "raw_record_id": "<unique id>",
        "source_id": "<source id from county config>",
        "source_url": "<deep link if available>",
        "source_fetched_at": "<ISO timestamp>",
        "parser_confidence": <0..100>,
        "raw_payload": {
            "address": "<situs address, uppercase canonical>",
            "doc_number": "<recording document number>",
            "recording_year": <int>,
            "recording_month": <int>,
            "city": "<situs city, uppercase canonical>",
            "zip": "<5-digit ZIP>",
            "layer_id": <int>,  # which doc-type bucket this record came from
            "<any other source-specific normalized fields>": ...
        }
    }

The translator is PROTOCOL-AGNOSTIC. It does not know whether the underlying
data was pulled via REST API, public-records portal, court e-portal, manual
CSV, or any other access pattern. The county-side scraper handles portal
protocol AND field-name normalization.

Renamed in v5.1.2-beta-r2: dropped the vendor-protocol prefix from the
translator name. The translator is no longer protocol-specific.

Expected `source_config` structure:

    {
        "translator": "foreclosure_notices",
        "translator_config": {
            "layer_doc_type_map": {
                "0": {
                    "canonical": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
                    "subtype_label": "Notice of Substitute Trustee's Sale",
                    "pattern": "foreclosure"
                },
                "1": {
                    "canonical": "TAX_FORECLOSURE_NOTICE",
                    "subtype_label": "Tax Foreclosure Notice",
                    "pattern": "tax"
                }
            }
        },
        "parcel_id_prefix": "BX-ADDR-",
        "field_map": {
            "address": "<source's actual address field name in raw_payload>",
            "doc_number": "<source's actual doc_number field name>",
            "recording_year": "<source's actual year field>",
            "recording_month": "<source's actual month field>",
            "city": "<source's actual city field>",
            "zip": "<source's actual zip field>",
            "layer_id": "<source's actual layer_id field>"
        }
    }

`field_map` is OPTIONAL (v5.1.2-beta-r3+). Keys are the canonical field
names the translator expects; values are the actual field names the
scraper writes to raw_payload. If a key is absent from field_map (or
field_map itself is absent), identity mapping applies — the translator
reads the canonical name directly from raw_payload. This bridges the
gap when a scraper normalizes to its own conventions
(e.g. `situs_address` instead of `address`) rather than to the
translator's canonical names.

Layer-based doc-type dispatch is OPTIONAL. If `layer_doc_type_map` is
omitted, the translator uses a single default `canonical` declared at
the top level of translator_config. Counties whose scrapers don't have
layer semantics can use the simpler config.

Cross-county-leak detection: reads
county_config.geography.accepted_municipalities[] and
county_config.geography.cross_county_policy. Address `city` is compared
against accepted_municipalities; unknown cities trigger the configured
unknown_city_action (drop / flag_for_review / accept_with_warning).

Sale-date derivation: reads county_config.geography.sale_date_rule and
dispatches to scaffold.pipeline.sale_date_rules.

Returns: (signals, parcels, per_signal_meta_by_url)
"""

from __future__ import annotations
import hashlib
from datetime import date
from typing import Any

from scaffold.pipeline.translators import register
from scaffold.pipeline.sale_date_rules import derive_expected_sale_date


def _make_parcel_id(prefix: str, address: str) -> str:
    """Build a stable placeholder parcel ID from a prefix + address hash."""
    h = hashlib.sha1(address.upper().strip().encode("utf-8")).hexdigest()[:12].upper()
    return f"{prefix}{h}" if prefix.endswith("-") else f"{prefix}-{h}"


def _city_check(
    city: str,
    accepted_municipalities: list,
    cross_county_policy: dict,
) -> tuple[list[str], str]:
    """
    Apply cross-county-leak detection per geography.accepted_municipalities.

    Returns:
        (preset_review_flags, action) — action is 'keep' or 'drop'.
    """
    if not city:
        return [], "keep"
    if not accepted_municipalities:
        return [], "keep"
    city_upper = city.upper().strip()
    accepted_names = {m["name"].upper() for m in accepted_municipalities}
    if city_upper in accepted_names:
        return [], "keep"
    action = (cross_county_policy or {}).get("unknown_city_action", "flag_for_review")
    if action == "drop":
        return [], "drop"
    elif action == "accept_with_warning":
        return ["potential_cross_county_leak"], "keep"
    else:
        return ["potential_cross_county_leak"], "keep"


@register("foreclosure_notices")
def translate_foreclosure_notices(
    raw_records: list[dict],
    county_config: dict,
    source_config: dict,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """
    Translate normalized foreclosure-notice raw records into pipeline signals.

    Args:
        raw_records: List of raw records in canonical wrapped shape (§4.32).
        county_config: Full county config (geography, sources, etc.).
        source_config: This source's config block.

    Returns:
        (signals, parcels, per_signal_meta_by_url)
    """
    tc = source_config.get("translator_config", {}) or {}
    layer_doc_type_map: dict = tc.get("layer_doc_type_map", {}) or {}

    # Field-name bridge (v5.1.2-beta-r3+). The translator reads canonical
    # framework field names from raw_payload. If a scraper's normalized
    # field names differ from canonical, source_config.field_map declares
    # the mapping: keys are canonical names the translator expects, values
    # are the actual field names the scraper writes to raw_payload.
    # If field_map is absent, identity mapping is used (translator reads
    # canonical names directly).
    field_map = source_config.get("field_map", {}) or {}

    def _resolve(canonical_name: str) -> str:
        """Resolve a canonical field name to the source's actual field name."""
        return field_map.get(canonical_name, canonical_name)

    # If no layer map, expect a single canonical at translator_config root.
    default_canonical = tc.get("canonical")
    default_subtype = tc.get("subtype_label", default_canonical)
    default_pattern = tc.get("pattern", "foreclosure")

    parcel_id_prefix = source_config.get("parcel_id_prefix", "PARCEL-")

    geography = county_config.get("geography", {}) or {}
    accepted_municipalities = geography.get("accepted_municipalities", []) or []
    cross_county_policy = geography.get("cross_county_policy", {}) or {}
    sale_date_rule = geography.get("sale_date_rule", {}) or {}

    signals: list[dict] = []
    parcels: list[dict] = []
    per_signal_meta_by_url: dict[str, dict] = {}
    seen_parcel_ids: set[str] = set()

    source_id = source_config.get("_source_id", "foreclosure_notices")

    for raw in raw_records:
        # Canonical shape: raw_payload contains normalized fields.
        payload = raw.get("raw_payload", {}) or {}

        # Read canonical fields via field_map bridge.
        address = (payload.get(_resolve("address")) or "").strip()
        doc_number = (payload.get(_resolve("doc_number")) or "").strip()
        recording_year = payload.get(_resolve("recording_year"))
        recording_month = payload.get(_resolve("recording_month"))
        city = (payload.get(_resolve("city")) or "").strip()
        zip_code = (payload.get(_resolve("zip")) or "").strip()
        layer_id_raw = payload.get(_resolve("layer_id"))

        if not address or not doc_number:
            continue

        # Resolve doc-type. Layer-based dispatch if configured; else default.
        if layer_doc_type_map:
            # Layer IDs can be int or str; normalize to str for lookup.
            layer_key = str(layer_id_raw) if layer_id_raw is not None else "0"
            layer_mapping = layer_doc_type_map.get(layer_key)
            if not layer_mapping:
                # Unknown layer — try the first entry as a tolerant fallback.
                first_layer = sorted(layer_doc_type_map.keys())[0] if layer_doc_type_map else None
                layer_mapping = layer_doc_type_map.get(first_layer, {}) if first_layer else {}
            canonical = layer_mapping.get("canonical", "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE")
            subtype_label = layer_mapping.get("subtype_label", canonical)
            pattern = layer_mapping.get("pattern", "foreclosure")
        else:
            canonical = default_canonical or "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE"
            subtype_label = default_subtype or canonical
            pattern = default_pattern

        # Cross-county-leak detection.
        preset_flags, action = _city_check(
            city, accepted_municipalities, cross_county_policy
        )
        if action == "drop":
            continue

        # Derive expected sale date via the configured state rule.
        try:
            year_int = int(recording_year) if recording_year else None
            month_int = int(recording_month) if recording_month else None
        except (ValueError, TypeError):
            year_int = month_int = None

        expected_sale_date = None
        if year_int and month_int:
            try:
                expected_sale_date = derive_expected_sale_date(
                    year=year_int,
                    month=month_int,
                    sale_date_rule=sale_date_rule,
                )
            except Exception:
                try:
                    expected_sale_date = date(year_int, month_int, 1).isoformat()
                except Exception:
                    expected_sale_date = None

        # Build the parcel placeholder.
        parcel_id = _make_parcel_id(parcel_id_prefix, address)
        if parcel_id not in seen_parcel_ids:
            parcels.append({
                "parcel_id": parcel_id,
                "address": address,
                "city": city,
                "zip": zip_code,
                "owner_name": None,
                "parcel_master_status": "placeholder_pending_enrichment",
            })
            seen_parcel_ids.add(parcel_id)

        # Build the signal.
        signal_id = "sig_" + hashlib.sha1(
            f"{source_id}|{doc_number}|{layer_id_raw}".encode("utf-8")
        ).hexdigest()[:16]
        source_url = (
            raw.get("source_url")
            or f"about:blank/{source_id}/{doc_number}/{layer_id_raw}"
        )
        signal = {
            "signal_id": signal_id,
            "raw_record_id": raw.get("raw_record_id"),
            "source_id": source_id,
            "source_url": source_url,
            "doc_type": canonical,
            "doc_type_subtype_label": subtype_label,
            "doc_number": doc_number,
            "primary_parcel_id": parcel_id,
            "filing_date": expected_sale_date or (
                date(year_int, month_int, 1).isoformat()
                if (year_int and month_int) else None
            ),
            "parser_confidence": raw.get("parser_confidence", 95),
        }
        signals.append(signal)

        per_signal_meta_by_url[source_url] = {
            "preset_review_flags": preset_flags,
            "expected_sale_date": expected_sale_date,
            "match_confidence": 0,
            "match_method": "placeholder",
            "address": address,
            "city": city,
            "zip": zip_code,
            "primary_parcel_id": parcel_id,
        }

    return signals, parcels, per_signal_meta_by_url
