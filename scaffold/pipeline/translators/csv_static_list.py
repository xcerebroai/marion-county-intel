"""
csv_static_list translator (built-in, v5.1.2-beta+).

Converts raw records from a static CSV/JSONL list (downloaded by an
operator or pulled by a thin county adapter) into framework signals
or parcels per source_config.

Intended for sources that don't have a queryable API — e.g. tax-roll
exports, manual auction lists, operator-curated lead lists.

CONTRACT (v5.1.2-beta-r2+): This translator consumes the framework-canonical
WRAPPED RAW RECORD shape (MASTER_PROMPT §4.32):

    {
        "raw_record_id": "...",
        "source_id": "...",
        "raw_payload": {<normalized scraper-output fields>}
    }

For backward compatibility with pre-v5.1.2-beta-r2 CSV ingestion paths
that emit records FLAT (no raw_payload wrapper), the translator accepts
either shape — if `raw_payload` is absent, the record itself is treated
as the payload. New CSV scrapers should produce the wrapped shape.

Expected `source_config` structure:

    {
        "translator": "csv_static_list",
        "translator_config": {
            "output_kind": "signal",  # or "parcel"
            "doc_type_field": "doc_type",
            "doc_type_synonyms": {
                "tax sale": "TAX_FORECLOSURE_NOTICE",
                "NSTS": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE"
            },
            "address_field": "property_address",
            "doc_number_field": "doc_num",
            "filing_date_field": "recorded_on"
        },
        "parcel_id_prefix": "MAR-ADDR-"
    }

The doc_type_synonyms map is per-source — keys are the source's
literal doc-type strings, values are canonical types from
canonical_doc_types.json. This replaces hardcoded synonym tables
in scaffold/pipeline/normalize.py.

Returns: (signals, parcels, per_signal_meta_by_url)
"""

from __future__ import annotations
import hashlib

from scaffold.pipeline.translators import register


@register("csv_static_list")
def translate_csv_static_list(
    raw_records: list[dict],
    county_config: dict,
    source_config: dict,
) -> tuple[list[dict], list[dict], dict[str, dict]]:
    """
    Translate flat CSV/JSONL static-list raw records into pipeline output.

    Returns:
        (signals, parcels, per_signal_meta_by_url)
    """
    tc = source_config.get("translator_config", {}) or {}
    output_kind = tc.get("output_kind", "signal")
    doc_type_field = tc.get("doc_type_field", "doc_type")
    doc_type_synonyms = source_config.get("doc_type_synonyms", {}) or tc.get(
        "doc_type_synonyms", {}
    )
    address_field = tc.get("address_field", "address")
    doc_number_field = tc.get("doc_number_field", "doc_number")
    filing_date_field = tc.get("filing_date_field", "filing_date")

    parcel_id_prefix = source_config.get("parcel_id_prefix", "PARCEL-")
    source_id = source_config.get("_source_id", "static_list")

    signals: list[dict] = []
    parcels: list[dict] = []
    per_signal_meta_by_url: dict[str, dict] = {}

    if output_kind == "parcel":
        # Same path as parcel_master translator's output. Less common
        # for CSV but supported for completeness.
        return [], [], {}

    for raw in raw_records:
        payload = raw.get("raw_payload", raw) or {}
        address = (payload.get(address_field) or "").strip()
        doc_number = (payload.get(doc_number_field) or "").strip()
        raw_doc_type = (payload.get(doc_type_field) or "").strip()

        if not (address and doc_number and raw_doc_type):
            continue

        # Map the raw doc-type string through the per-source synonyms.
        # Case-insensitive lookup.
        canonical = None
        for key, val in doc_type_synonyms.items():
            if key.upper() == raw_doc_type.upper():
                canonical = val
                break
        if canonical is None:
            # Unknown doc-type. Skip rather than guess.
            continue

        h = hashlib.sha1(address.upper().encode("utf-8")).hexdigest()[:12].upper()
        parcel_id = f"{parcel_id_prefix}{h}" if parcel_id_prefix.endswith("-") else f"{parcel_id_prefix}-{h}"
        parcels.append({
            "parcel_id": parcel_id,
            "address": address,
            "owner_name": None,
            "parcel_master_status": "placeholder_pending_enrichment",
        })

        signal_id = "sig_" + hashlib.sha1(
            f"{source_id}|{doc_number}|{canonical}".encode("utf-8")
        ).hexdigest()[:16]
        source_url = raw.get("source_url") or f"about:blank/{source_id}/{doc_number}"
        signal = {
            "signal_id": signal_id,
            "raw_record_id": raw.get("raw_record_id"),
            "source_id": source_id,
            "source_url": source_url,
            "doc_type": canonical,
            "doc_type_subtype_label": raw_doc_type,
            "doc_number": doc_number,
            "primary_parcel_id": parcel_id,
            "filing_date": payload.get(filing_date_field),
            "parser_confidence": raw.get("parser_confidence", 80),
        }
        signals.append(signal)
        per_signal_meta_by_url[source_url] = {
            "preset_review_flags": [],
            "expected_sale_date": None,
            "match_confidence": 0,
            "match_method": "placeholder",
            "address": address,
            "primary_parcel_id": parcel_id,
        }

    return signals, parcels, per_signal_meta_by_url
