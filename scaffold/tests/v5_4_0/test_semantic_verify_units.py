#!/usr/bin/env python3
"""v5.4.0 unit tests — §20 semantic verification engine.

Added in v5.4.0 Session 5. Wired into run_all.py via scaffold/tests/v5_4_0/.
Exercises the §20 surface:

  - all twelve §20.C check classes appear in the report;
  - the six data-shape checks (1, 2, 4, 5, 6, 12) run on matched_leads.json;
  - the six deploy-time checks (3, 7, 8, 9, 10, 11) report SKIPPED;
  - all three §20.F verdicts — DEPLOY_OK, DEPLOY_BLOCKED, NEEDS_OPERATOR_REVIEW;
  - DEPLOY_BLOCKED via filer-as-owner (Check 1/12), owner-type misclassification
    (Check 2), No False Dashboard / enrichment-only row (Check 4), an impossible
    count (Check 5), and a signal-grouping inconsistency (Check 6);
  - NEEDS_OPERATOR_REVIEW via count > distinct instruments (Check 5 AMBIGUOUS);
  - the §20.G mechanical pre-gate blocks a schema-invalid matched lead.

Run: python3 scaffold/tests/v5_4_0/test_semantic_verify_units.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.pipeline import semantic_verify


def _signal(*, parcel_id="P-1", doc="hospital_lien", sig_type="Hospital Lien",
            count=1, instruments=("I-1",), source_ids=("clerk_recordings",),
            evidence_ids=("ev-1",), urls=("https://example.test/clerk/I-1",),
            earliest="2026-01-01", latest="2026-01-01"):
    return {
        "aggregation_key": {
            "parcel_id": parcel_id,
            "canonical_doc_type": doc,
            "signal_type": sig_type,
        },
        "signal_type": sig_type,
        "canonical_doc_type": doc,
        "count": count,
        "instrument_numbers": list(instruments),
        "source_urls": list(urls),
        "evidence_ids": list(evidence_ids),
        "source_ids": list(source_ids),
        "earliest_recorded_date": earliest,
        "latest_recorded_date": latest,
        "recorded_date_range": [earliest, latest],
    }


def _matched_lead(*, lead_id="lead_parcel_P-1", parcel_id="P-1",
                  owner_name="DOE, JANE A", owner_type="INDIVIDUAL",
                  filer_entity=None, review_reason=None,
                  parcel_resolution_status="RESOLVED",
                  enrichment_status="UNENRICHED", signals=None,
                  source_ids=("clerk_recordings",), evidence_ids=("ev-1",)):
    return {
        "lead_id": lead_id,
        "primary_parcel_id": parcel_id,
        "owner_name": owner_name,
        "owner_type": owner_type,
        "filer_entity": filer_entity,
        "review_reason": review_reason,
        "parcel_resolution_status": parcel_resolution_status,
        "enrichment_status": enrichment_status,
        "signals": [_signal()] if signals is None else signals,
        "source_ids": list(source_ids),
        "evidence_ids": list(evidence_ids),
    }


# A leads-base stand-in carrying just what Check 4 reads — source_id + role.
_PRIMARY_LB = [{"source_id": "clerk_recordings",
                "source_role": "PRIMARY_EVENT_SOURCE"}]


def _status(report, check_number):
    for result in report["checks"]:
        if result["check"] == check_number:
            return result["status"]
    return None


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    sv = semantic_verify

    # --- clean data → DEPLOY_OK --------------------------------------------
    clean = sv.run_semantic_verification(
        [_matched_lead()], leads_base_records=_PRIMARY_LB)
    check("clean matched_leads → verdict DEPLOY_OK",
          clean["verdict"] == "DEPLOY_OK")
    check("report carries all twelve §20.C check classes",
          sorted(r["check"] for r in clean["checks"]) == list(range(1, 13)))
    check("the six data-shape checks (1,2,4,5,6,12) ran",
          all(_status(clean, n) == "VALID" for n in (1, 2, 4, 5, 6, 12)))
    check("the six deploy-time checks (3,7,8,9,10,11) are SKIPPED",
          clean["skipped_checks"] == [3, 7, 8, 9, 10, 11])
    check("clean run reports mechanical_ok True", clean["mechanical_ok"] is True)

    # --- DEPLOY_BLOCKED — filer surfaced as owner (Check 1 + Check 12) ------
    filer_owner = sv.run_semantic_verification(
        [_matched_lead(owner_name="CITY OF EXAMPLE")],
        leads_base_records=_PRIMARY_LB)
    check("filer-as-owner → verdict DEPLOY_BLOCKED",
          filer_owner["verdict"] == "DEPLOY_BLOCKED")
    check("filer-as-owner → Check 1 INVALID", _status(filer_owner, 1) == "INVALID")
    check("filer-as-owner → Check 12 INVALID",
          _status(filer_owner, 12) == "INVALID")

    # --- DEPLOY_BLOCKED — owner-type misclassification (Check 2) ------------
    bad_type = sv.run_semantic_verification(
        [_matched_lead(owner_name="ACME HOLDINGS LLC", owner_type="INDIVIDUAL")],
        leads_base_records=_PRIMARY_LB)
    check("owner_type disagreeing with the §17.F classifier → Check 2 INVALID",
          _status(bad_type, 2) == "INVALID")
    check("owner-type misclassification → verdict DEPLOY_BLOCKED",
          bad_type["verdict"] == "DEPLOY_BLOCKED")

    # --- DEPLOY_BLOCKED — No False Dashboard / enrichment-only row (Check 4)
    enrichment_only = sv.run_semantic_verification(
        [_matched_lead(source_ids=("cad_enrichment",),
                       signals=[_signal(source_ids=("cad_enrichment",))])],
        leads_base_records=[{"source_id": "cad_enrichment",
                             "source_role": "ENRICHMENT_SOURCE"}])
    check("enrichment-only matched lead (no PRIMARY signal) → Check 4 INVALID",
          _status(enrichment_only, 4) == "INVALID")
    check("No False Dashboard violation → verdict DEPLOY_BLOCKED",
          enrichment_only["verdict"] == "DEPLOY_BLOCKED")

    # --- DEPLOY_BLOCKED — impossible signal count (Check 5 INVALID) ---------
    bad_count = sv.run_semantic_verification(
        [_matched_lead(signals=[_signal(count=1, instruments=("I-1", "I-2"))])],
        leads_base_records=_PRIMARY_LB)
    check("count below distinct instrument count → Check 5 INVALID",
          _status(bad_count, 5) == "INVALID")
    check("impossible count → verdict DEPLOY_BLOCKED",
          bad_count["verdict"] == "DEPLOY_BLOCKED")

    # --- DEPLOY_BLOCKED — signal-grouping inconsistency (Check 6) -----------
    under_merge = sv.run_semantic_verification(
        [_matched_lead(signals=[_signal(), _signal()])],
        leads_base_records=_PRIMARY_LB)
    check("two signals sharing one aggregation key → Check 6 INVALID",
          _status(under_merge, 6) == "INVALID")

    # --- NEEDS_OPERATOR_REVIEW — count > distinct instruments (Check 5) -----
    ambiguous = sv.run_semantic_verification(
        [_matched_lead(signals=[_signal(count=2, instruments=("I-1",))])],
        leads_base_records=_PRIMARY_LB)
    check("count above distinct instrument count → Check 5 AMBIGUOUS",
          _status(ambiguous, 5) == "AMBIGUOUS")
    check("a Check 5 AMBIGUOUS (no INVALID) → verdict NEEDS_OPERATOR_REVIEW",
          ambiguous["verdict"] == "NEEDS_OPERATOR_REVIEW")

    # --- §20.G mechanical pre-gate blocks a schema-invalid matched lead ----
    invalid_shape = _matched_lead()
    invalid_shape["signals"] = []  # violates matched_lead schema (minItems 1)
    mech = sv.run_semantic_verification([invalid_shape],
                                        leads_base_records=_PRIMARY_LB)
    check("§20.G: a schema-invalid matched lead → mechanical_ok False",
          mech["mechanical_ok"] is False)
    check("§20.G: mechanical failure → verdict DEPLOY_BLOCKED, no semantic run",
          mech["verdict"] == "DEPLOY_BLOCKED" and mech["checks"] == [])

    # --- the three verdicts are exactly the §20.F set ----------------------
    check("§20.F verdict set is DEPLOY_OK / DEPLOY_BLOCKED / "
          "NEEDS_OPERATOR_REVIEW",
          set(semantic_verify.DEPLOY_VERDICTS)
          == {"DEPLOY_OK", "DEPLOY_BLOCKED", "NEEDS_OPERATOR_REVIEW"})

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: §20 semantic verification unit tests — "
              f"{len(failed)} of {len(checks)} checks failed")
        return 1

    print(f"PASS: §20 semantic verification unit tests — "
          f"all {len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
