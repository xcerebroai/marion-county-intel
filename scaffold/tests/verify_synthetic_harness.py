"""
verify_synthetic_harness.py — SUPERSEDED by the v5.4.0 cutover.

Through v5.1.2-beta this verifier ran the monolith's
`pipeline/build_leads.py --synthetic` and compared the resulting
`data/leads_synthetic.json` against `scaffold/data/synthetic_expectations.json`
— a calibrated Phase-1 acceptance gate for the monolith's specific
lead-shape output (12 leads with hand-tuned per-parcel score / tier /
deal-path expectations).

v5.4.0 Session 10 retired the monolith's signal→identity→aggregation
orchestration. The new staged + Option-Y seam pipeline produces a
DIFFERENT output artifact set (`matched_leads.json`, `scored_leads.json`,
`evidence_ledger.json`, `dashboard.json`) under
`data/synthetic/<artifact>` and a DIFFERENT aggregation profile
(matched_lead-level rather than monolith-stack-level), so the legacy
per-parcel expectations in synthetic_expectations.json no longer apply.

The equivalent acceptance coverage now lives in the staged-pipeline gate
tests (`scaffold/tests/run_all.py`):

  - `scaffold/tests/test_golden_path.py`
      end-to-end gate test — one synthetic lead through all 9 framework
      layers via the real staged engine.
  - `scaffold/tests/v5_4_0/test_staged_pipeline_end_to_end.py`
      §17 → §18 → §19 → §20 staged engine end-to-end proof.
  - `scaffold/tests/v5_4_0/test_staged_with_scoring_end_to_end.py`
      full staged + seam + scoring proof, both ENRICHED and UNENRICHED.

Re-calibration of synthetic_expectations.json for the staged pipeline
(per-parcel scored_lead / tier / deal-path expectations against
scaffold/data/synthetic_signals.jsonl) is a follow-up; the v5.4.0 gate
does not depend on it.

This stub remains so a stale operator script that points at this file
produces a clear redirect rather than a subprocess failure. It is not
wired into the framework gate and intentionally performs no assertions.
"""

from __future__ import annotations


def run() -> int:
    print(__doc__.strip())
    print()
    print("PASS: superseded by the v5.4.0 staged-pipeline gate tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
