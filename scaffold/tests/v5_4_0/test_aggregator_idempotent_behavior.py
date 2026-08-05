#!/usr/bin/env python3
"""v5.4.0 behavioral spec — §19 aggregator idempotency.

PROMOTED in v5.4.0 Session 4 — the aggregator is implemented and this spec
passes. Wired into run_all.py via scaffold/tests/v5_4_0/.

This is a behavioral spec, not a doc-presence check. It writes real
<source>_leads_base.json files, runs the real aggregator against them, and
asserts the §19 idempotency contract.

The cases:
  - §19.D: running the aggregator twice on the same base files produces
    identical output.
  - §19.C: the aggregator reads ONLY *_leads_base.json files. It MUST refuse
    (raise ValueError) when handed matched_leads.json as input — reading its
    own output is the bug §19 exists to prevent.

Run: python3 scaffold/tests/v5_4_0/test_aggregator_idempotent_behavior.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def _base_record(base_id, raw_id, source_id, doc_type, signal_type,
                 parcel_id, instrument, recorded_date):
    """One leads_base record conforming to leads_base_record.schema.json."""
    return {
        "base_record_id": base_id,
        "raw_event_id": raw_id,
        "source_id": source_id,
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": doc_type,
        "signal_type": signal_type,
        "aggregation_key": {
            "parcel_id": parcel_id,
            "canonical_doc_type": doc_type,
            "signal_type": signal_type,
        },
        "owner_name": "DOE, JANE",
        "owner_type": "INDIVIDUAL",
        "filer_entity": None,
        "review_reason": None,
        "parcel_resolution_status": "RESOLVED",
        "enrichment_status": "UNENRICHED",
        "confidence_status": "Confirmed",
        "instrument_number": instrument,
        "recorded_date": recorded_date,
        "source_url": f"https://example.source/{source_id}/{instrument}",
        "evidence_ids": [f"ev_{base_id}"],
        "property_refs": {
            "parcel_id": parcel_id,
            "situs_address": "props 77 CEDAR LANE",
            "legal_description": None,
            "case_number": None,
        },
    }


def _write_base_files(workdir):
    """Write two <source>_leads_base.json files. Returns their paths."""
    clerk = [
        _base_record("b1", "r1", "clerk_recordings", "hospital_lien",
                     "Hospital Lien", "PARCEL-001", "2026-0001", "2026-01-05"),
        _base_record("b2", "r2", "clerk_recordings", "hospital_lien",
                     "Hospital Lien", "PARCEL-001", "2026-0002", "2026-02-11"),
    ]
    notices = [
        _base_record("b3", "r3", "foreclosure_notices", "foreclosure_notice",
                     "Foreclosure Notice", "PARCEL-001", "2026-0003",
                     "2026-03-09"),
    ]
    clerk_path = workdir / "clerk_recordings_leads_base.json"
    notices_path = workdir / "foreclosure_notices_leads_base.json"
    clerk_path.write_text(json.dumps(clerk, indent=2), encoding="utf-8")
    notices_path.write_text(json.dumps(notices, indent=2), encoding="utf-8")
    return [clerk_path, notices_path]


def main() -> int:
    from scaffold.pipeline import aggregator

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        base_paths = _write_base_files(workdir)

        # §19.D — run the aggregator twice; output must be identical.
        try:
            first = aggregator.aggregate(base_paths)
            second = aggregator.aggregate(base_paths)
        except NotImplementedError as exc:
            print("FAIL (pending v5.4.0 Session 4): aggregator.aggregate "
                  "is not implemented yet")
            print(f"  {exc}")
            return 1

        first_json = json.dumps(first, sort_keys=True, default=str)
        second_json = json.dumps(second, sort_keys=True, default=str)

        # §19.C — the aggregator must refuse to read its own output.
        matched_leads_path = workdir / "matched_leads.json"
        matched_leads_path.write_text(json.dumps(first, default=str),
                                      encoding="utf-8")
        refused_own_output = False
        try:
            aggregator.aggregate([matched_leads_path])
        except ValueError:
            refused_own_output = True
        except NotImplementedError:
            refused_own_output = False

    checks = [
        ("§19.D: two aggregation runs on the same base files are identical",
         first_json == second_json),
        ("the aggregator returned a list of matched leads",
         isinstance(first, list)),
        ("§19.C: the aggregator refuses matched_leads.json as input "
         "(raises ValueError)",
         refused_own_output),
    ]

    failed = [desc for desc, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: §19 aggregator idempotency — {len(failed)} "
              f"assertion(s) failed")
        return 1

    print("PASS: §19 aggregator is idempotent and refuses to read its own "
          "output")
    return 0


if __name__ == "__main__":
    sys.exit(main())
