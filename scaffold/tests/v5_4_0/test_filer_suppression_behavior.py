#!/usr/bin/env python3
"""v5.4.0 behavioral spec — §17.D / §17.E filer suppression.

PROMOTED in v5.4.0 Session 2 — debtor_party_engine is implemented and this
spec passes. Wired into run_all.py via scaffold/tests/v5_4_0/.

This is a behavioral spec, not a doc-presence check. It calls the real
engine and asserts a known filer is never emitted as owner_name.

The case:
  A code lien is filed by a municipal agency against a property owner.
  §17.C: code_lien -> expected_debtor = TP. In this record the TP party is
  missing; the only fallback party is the filing agency, CITY OF EXAMPLE.
  §17.D lists `CITY OF <*>` as a known filer that MUST NEVER appear as
  owner_name. §17.E therefore routes the record to REVIEW_REQUIRED: owner_name
  becomes the placeholder, filer_entity captures CITY OF EXAMPLE, and the lead
  is NOT dropped.

Run: python3 scaffold/tests/v5_4_0/test_filer_suppression_behavior.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEBTOR_PARTY_RULES = {
    "code_lien": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "GE",
        "filer_name_types": ["GR"],
        "known_filer_role": "municipal agency",
        "missing_debtor_behavior": "REVIEW_REQUIRED",
    },
}

# A code lien whose only structured party is the filing municipal agency —
# the taxpayer/owner party is absent. (conforms to raw_event_record.schema.json)
CODE_LIEN_FILER_ONLY = {
    "raw_event_id": "raw_cl_cityfiler_0001",
    "source_id": "county_clerk_recordings",
    "source_role": "PRIMARY_EVENT_SOURCE",
    "canonical_doc_type": "code_lien",
    "raw_doc_type": "CODE LIEN",
    "instrument_number": "2026-0451180",
    "recorded_date": "2026-02-09",
    "event_date": None,
    "source_url": "https://example.clerk/doc/2026-0451180",
    "parties": [
        {"name": "CITY OF EXAMPLE", "name_type": "GR",
         "raw_role": "GRANTOR / FILING AGENCY"},
    ],
    "document_body_text": None,
    "property_refs": {
        "parcel_id": None,
        "situs_address": "props 1209 INDUSTRIAL ROW",
        "legal_description": None,
        "case_number": None,
    },
    "amounts": [{"label": "lien_amount", "value": 3140.55}],
    "evidence_ids": ["ev_cl_cityfiler_0001"],
    "parser_name": "clerk_recordings_translator",
    "parser_version": "1.0.0",
    "parser_confidence": 91,
    "captured_at": "2026-02-15T15:00:00Z",
}


def main() -> int:
    from scaffold.pipeline import debtor_party_engine

    # Part 1 — the §17.D suppression matcher itself.
    try:
        gov_hit = debtor_party_engine.match_known_filer("CITY OF EXAMPLE")
        person_hit = debtor_party_engine.match_known_filer("CANTY, ROBERT J")
    except NotImplementedError as exc:
        print("FAIL (pending v5.4.0 Session 2): debtor_party_engine."
              "match_known_filer is not implemented yet")
        print(f"  {exc}")
        return 1

    # Part 2 — the §17.E routing on a filer-only record.
    try:
        resolved = debtor_party_engine.resolve_debtor_party(
            CODE_LIEN_FILER_ONLY,
            debtor_party_rules=DEBTOR_PARTY_RULES,
        )
    except NotImplementedError as exc:
        print("FAIL (pending v5.4.0 Session 2): debtor_party_engine."
              "resolve_debtor_party is not implemented yet")
        print(f"  {exc}")
        return 1

    owner = str(resolved.get("owner_name", ""))
    owner_u = owner.upper()
    filer = str(resolved.get("filer_entity", "") or "").upper()
    review_reason = str(resolved.get("review_reason", "") or "")

    checks = [
        ("match_known_filer flags 'CITY OF EXAMPLE' as a known filer",
         bool(gov_hit)),
        ("match_known_filer does NOT flag an individual name",
         not person_hit),
        ("a known filer is never emitted as owner_name",
         "CITY OF EXAMPLE" not in owner_u),
        ("debtor_resolution_status is REVIEW_REQUIRED",
         resolved.get("debtor_resolution_status") == "REVIEW_REQUIRED"),
        ("owner_name is the §17.E unidentified-party placeholder",
         "unidentified party" in owner.lower()),
        ("filer_entity captures CITY OF EXAMPLE",
         "CITY OF EXAMPLE" in filer),
        ("review_reason is populated",
         len(review_reason.strip()) > 0),
        ("the lead is NOT dropped (a record was returned)",
         isinstance(resolved, dict) and bool(resolved)),
    ]

    failed = [desc for desc, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: §17 filer suppression — {len(failed)} assertion(s) failed")
        print(f"  resolved record: {resolved!r}")
        return 1

    print("PASS: §17 filer suppression routes a government filer to "
          "REVIEW_REQUIRED instead of emitting it as owner_name")
    return 0


if __name__ == "__main__":
    sys.exit(main())
