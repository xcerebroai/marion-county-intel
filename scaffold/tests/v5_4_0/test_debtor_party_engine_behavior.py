#!/usr/bin/env python3
"""v5.4.0 behavioral spec — §17 debtor party engine.

PROMOTED in v5.4.0 Session 2 — debtor_party_engine is implemented and this
spec passes. Wired into run_all.py via scaffold/tests/v5_4_0/.

This is a behavioral spec, not a doc-presence check. It calls the real
engine and asserts the real output.

The case — LAKEVIEW -> CANTY lis pendens:
  A lis pendens names a plaintiff and a defendant. The plaintiff,
  LAKEVIEW LOAN SERVICING LLC, is a mortgage servicer — it FILES the suit.
  The defendant, CANTY, is the homeowner being sued — the LEAD SUBJECT.
  §17.C: lis_pendens -> expected_debtor = DF (defendant). A naive translator
  that takes the first-named party would emit LAKEVIEW as the owner; the §17
  engine MUST emit CANTY.

Run: python3 scaffold/tests/v5_4_0/test_debtor_party_engine_behavior.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The §17.C debtor_party_rules row for lis_pendens. Session 2 will ship the
# full universal table; this test pins the row its case depends on.
DEBTOR_PARTY_RULES = {
    "lis_pendens": {
        "expected_debtor_name_type": "DF",
        "fallback_debtor_name_type": "TP",
        "filer_name_types": ["PL"],
        "known_filer_role": "plaintiff",
        "missing_debtor_behavior": "REVIEW_REQUIRED",
    },
}

# The LAKEVIEW -> CANTY lis pendens raw event record
# (conforms to raw_event_record.schema.json).
LAKEVIEW_CANTY_LIS_PENDENS = {
    "raw_event_id": "raw_lp_lakeview_canty_0001",
    "source_id": "district_court_lis_pendens",
    "source_role": "PRIMARY_EVENT_SOURCE",
    "canonical_doc_type": "lis_pendens",
    "raw_doc_type": "LIS PEND",
    "instrument_number": "LP-2026-0098117",
    "recorded_date": "2026-03-14",
    "event_date": "2026-03-12",
    "source_url": "https://example.court/lis-pendens/LP-2026-0098117",
    "parties": [
        {"name": "LAKEVIEW LOAN SERVICING LLC", "name_type": "PL",
         "raw_role": "PLAINTIFF"},
        {"name": "CANTY, ROBERT J", "name_type": "DF",
         "raw_role": "DEFENDANT"},
    ],
    "document_body_text": None,
    "property_refs": {
        "parcel_id": None,
        "situs_address": "418 MAPLE HOLLOW DR",
        "legal_description": None,
        "case_number": "2026-CI-04471",
    },
    "amounts": [],
    "evidence_ids": ["ev_lp_lakeview_canty_0001"],
    "parser_name": "lis_pendens_translator",
    "parser_version": "1.0.0",
    "parser_confidence": 96,
    "captured_at": "2026-03-20T15:00:00Z",
}


def main() -> int:
    from scaffold.pipeline import debtor_party_engine

    try:
        resolved = debtor_party_engine.resolve_debtor_party(
            LAKEVIEW_CANTY_LIS_PENDENS,
            debtor_party_rules=DEBTOR_PARTY_RULES,
        )
    except NotImplementedError as exc:
        print("FAIL (pending v5.4.0 Session 2): debtor_party_engine."
              "resolve_debtor_party is not implemented yet")
        print(f"  {exc}")
        return 1

    owner = str(resolved.get("owner_name", "")).upper()
    filer = str(resolved.get("filer_entity", "") or "").upper()

    checks = [
        ("owner_name is the defendant CANTY (the lead subject)",
         "CANTY" in owner),
        ("owner_name is NOT the plaintiff/lender LAKEVIEW",
         "LAKEVIEW" not in owner),
        ("debtor_resolution_status is RESOLVED",
         resolved.get("debtor_resolution_status") == "RESOLVED"),
        ("filer_entity captures the plaintiff LAKEVIEW LOAN SERVICING",
         "LAKEVIEW" in filer),
        ("parcel_resolution_status is not REVIEW_REQUIRED "
         "(a real debtor was found)",
         resolved.get("parcel_resolution_status") != "REVIEW_REQUIRED"),
        ("owner_type classifies CANTY as INDIVIDUAL",
         resolved.get("owner_type") == "INDIVIDUAL"),
        ("expected_debtor_name_type recorded as DF",
         resolved.get("expected_debtor_name_type") == "DF"),
    ]

    failed = [desc for desc, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: §17 debtor party engine — {len(failed)} assertion(s) failed")
        print(f"  resolved record: {resolved!r}")
        return 1

    print("PASS: §17 debtor party engine resolves the LAKEVIEW -> CANTY "
          "lis pendens to the defendant")
    return 0


if __name__ == "__main__":
    sys.exit(main())
