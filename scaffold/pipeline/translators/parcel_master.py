"""
parcel_master translator (built-in, v5.1.2-beta-r2+).

Converts NORMALIZED parcel-master records (produced by a county-side
scraper) into framework parcel records ready for the matcher.

Parcel-master sources are ENRICHMENT, not lead-generating. This translator
returns ([], parcels, {}) — no signals, only parcels.

This translator consumes the framework-canonical RAW RECORD shape declared
in MASTER_PROMPT §4.32 (v5.1.2-beta-r2+):

    {
        "raw_record_id": "<unique id, often derived from parcel_id>",
        "source_id": "<source id, e.g. 'parcel_master'>",
        "source_fetched_at": "<ISO timestamp>",
        "raw_payload": {
            "parcel_id": "<county-canonical parcel id, with prefix>",
            "address": "<situs address, uppercase canonical>",
            "owner_name": "<owner string as recorded>",
            "owner_mailing_address": "<mailing addr line 1>",
            "owner_mailing_city": "<mailing city>",
            "owner_mailing_state": "<2-letter state>",
            "owner_mailing_zip": "<5-digit ZIP>",
            "city": "<situs city>",
            "zip": "<situs zip>",
            "assessed_value": <int>,
            "land_value": <int>,
            "improvement_value": <int>,
            "year_built": <int>,
            "exempt_homestead": <bool>,
            "exempt_over_65": <bool>,
            "exempt_disabled": <bool>,
            "exempt_veteran": <bool>,
            "property_use": "<class code>",
            "acres": <float>,
            "legal_description": "<text>"
        }
    }

NOTE on exemption fields: this translator consumes pre-parsed boolean
exempt_* flags directly from raw_payload. The scraper is responsible for
parsing the source's exemption string (e.g. "HS, OV65, DV") into the
canonical boolean fields BEFORE writing the JSONL. This keeps source-
specific exemption code lists out of the universal translator.

If a county's scraper instead emits a raw `exemptions` string and an
`exemption_codes` map in translator_config, the translator falls back to
parsing inline (legacy compatibility mode).

Renamed in v5.1.2-beta-r2: dropped the vendor-protocol prefix from the
translator name. The translator is no longer protocol-specific.

Expected `source_config` structure (minimal — scraper produces canonical names):

    {
        "translator": "parcel_master",
        "parcel_id_prefix": "CAD-"
    }

Expected `source_config` structure with field_map (v5.1.2-beta-r3+, when
the scraper's normalized field names differ from canonical):

    {
        "translator": "parcel_master",
        "parcel_id_prefix": "CAD-",
        "field_map": {
            "address": "situs_address",
            "city": "situs_city",
            "zip": "situs_zip",
            "owner_mailing_address": "owner_mailing_addr1",
            "property_use": "property_class"
            # Other canonical names that match identically can be omitted.
        }
    }

`field_map` is OPTIONAL. Keys are the canonical field names the translator
expects; values are the actual field names the scraper writes to raw_payload.
If a key is absent from field_map (or field_map itself is absent), identity
mapping applies — the translator reads the canonical name directly from
raw_payload.

Exemption boolean keys (`exempt_homestead`, `exempt_over_65`, `exempt_disabled`,
`exempt_veteran`) are NOT field-mapped. The scraper either emits these
canonical boolean keys directly or doesn't emit them at all — the framework
defines exemption semantics, not per-source exemption nomenclature.

Legacy-compatibility config (when scraper emits raw exemptions string):

    {
        "translator": "parcel_master",
        "translator_config": {
            "exemption_codes": {
                "homestead": ["HS"],
                "over_65": ["OV65", "O65"],
                "disabled": ["DV", "DIS"],
                "veteran": ["VET", "DAV"]
            }
        }
    }

Returns: ([], parcels, {})
"""

from __future__ import annotations
from typing import Any

from scaffold.pipeline.translators import register


def _parse_legacy_exemptions(
    raw_exemptions: str | None,
    exemption_codes: dict[str, list[str]],
) -> dict[str, bool]:
    """
    Parse a source's exemption STRING into framework-canonical bool flags.

    Legacy-compatibility path. New scrapers should emit exempt_* booleans
    directly in raw_payload and skip this code path.
    """
    flags = {
        "exempt_homestead": False,
        "exempt_over_65": False,
        "exempt_disabled": False,
        "exempt_veteran": False,
    }
    if not raw_exemptions:
        return flags
    parts = {p.strip().upper() for p in str(raw_exemptions).replace(";", ",").split(",")}
    for canonical_key, source_codes in (exemption_codes or {}).items():
        for code in source_codes:
            if code.upper() in parts:
                flags[f"exempt_{canonical_key}"] = True
                break
    return flags


def _try_int(value: Any) -> int | None:
    """Best-effort int conversion."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (ValueError, TypeError):
        return None


@register("parcel_master")
def translate_parcel_master(
    raw_records: list[dict],
    county_config: dict,
    source_config: dict,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """
    Translate normalized parcel-master raw records into framework parcel records.

    Returns:
        (signals=[], parcels, per_signal_meta_by_url={})
    """
    tc = source_config.get("translator_config", {}) or {}
    legacy_exemption_codes = tc.get("exemption_codes", {})

    # Field-name bridge (v5.1.2-beta-r3+). The translator reads canonical
    # framework field names from raw_payload. If a scraper's normalized
    # field names differ from canonical, source_config.field_map declares
    # the mapping: keys are canonical names the translator expects, values
    # are the actual field names the scraper writes to raw_payload.
    # If field_map is absent, identity mapping is used.
    field_map = source_config.get("field_map", {}) or {}

    def _resolve(canonical_name: str) -> str:
        """Resolve a canonical field name to the source's actual field name."""
        return field_map.get(canonical_name, canonical_name)

    parcels: list[dict] = []

    for raw in raw_records:
        # Canonical shape: raw_payload contains normalized fields.
        payload = raw.get("raw_payload", {}) or {}

        parcel_id = payload.get(_resolve("parcel_id"))
        if parcel_id is None or str(parcel_id).strip() == "":
            continue

        # Parse exemptions. Prefer pre-parsed booleans; fall back to legacy
        # string parsing if booleans absent and legacy config provided.
        # Exemption keys are framework-canonical and not field-mapped — the
        # scraper either emits them as canonical or doesn't emit them at all.
        if "exempt_homestead" in payload or "exempt_over_65" in payload:
            exemption_flags = {
                "exempt_homestead": bool(payload.get("exempt_homestead", False)),
                "exempt_over_65": bool(payload.get("exempt_over_65", False)),
                "exempt_disabled": bool(payload.get("exempt_disabled", False)),
                "exempt_veteran": bool(payload.get("exempt_veteran", False)),
            }
        else:
            raw_exemptions = payload.get(_resolve("exemptions"))
            exemption_flags = _parse_legacy_exemptions(
                raw_exemptions, legacy_exemption_codes
            )

        parcel = {
            "parcel_id": str(parcel_id).strip(),
            "address": (payload.get(_resolve("address")) or "").strip(),
            "owner_name": (payload.get(_resolve("owner_name")) or "").strip(),
            "owner_mailing_address": (payload.get(_resolve("owner_mailing_address")) or "").strip(),
            "owner_mailing_city": (payload.get(_resolve("owner_mailing_city")) or "").strip(),
            "owner_mailing_state": (payload.get(_resolve("owner_mailing_state")) or "").strip(),
            "owner_mailing_zip": (payload.get(_resolve("owner_mailing_zip")) or "").strip(),
            "city": (payload.get(_resolve("city")) or "").strip(),
            "zip": (payload.get(_resolve("zip")) or "").strip(),
            "assessed_value": _try_int(payload.get(_resolve("assessed_value"))),
            "land_value": _try_int(payload.get(_resolve("land_value"))),
            "improvement_value": _try_int(payload.get(_resolve("improvement_value"))),
            "year_built": _try_int(payload.get(_resolve("year_built"))),
            "property_use": payload.get(_resolve("property_use")) or "",
            "acres": payload.get(_resolve("acres")),
            "legal_description": (payload.get(_resolve("legal_description")) or "").strip(),
            "parcel_master_status": "matched_pending_join",
            **exemption_flags,
        }
        parcels.append(parcel)

    return [], parcels, {}
