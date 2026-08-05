"""
test_owner_name_signal_integration.py — SUPERSEDED by the v5.4.0 cutover.

Through v5.1.2-beta this test was an end-to-end smoke test of the monolith's
`run_pipeline(mode="production", ...)` — it asserted that owner-name-pattern
signals (ESTATE OF / LIVING TRUST detected on parcel-master owner strings)
stacked with foreclosure signals from the foreclosure_notices_map translator
to produce a multi-pattern lead with stack_depth >= 2 and an elevated score.

v5.4.0 Session 10 retired the monolith's signal→identity→aggregation
orchestration. The equivalent coverage now lives in the staged-pipeline
tests gated by `scaffold/tests/run_all.py`:

  - `scaffold/tests/test_owner_name_patterns.py`
      unit-tests `owner_name_patterns.emit_owner_name_signals_for_parcels`,
      asserting the derived signal shape (estate / living_trust / TRUST
      excluded from entity-owned).
  - `scaffold/tests/v5_4_0/test_staged_pipeline_end_to_end.py`
      proves the §17 → §18 → §19 → §20 staged engine stacks multiple
      same-parcel signals into one matched_lead carrying both source's
      `canonical_doc_type` groups.
  - `scaffold/tests/v5_4_0/test_staged_with_scoring_end_to_end.py`
      proves the seam (`scoring_seam`) derives the combined `pattern_set`
      and `stack_depth` on the matched_lead and elevates the score, with
      both ENRICHED and UNENRICHED variants.
  - `scaffold/tests/test_golden_path.py`
      the framework's single end-to-end gate test, rewritten in Session 10
      to drive the staged + seam pipeline.

The legacy monolith helpers this test imported (`_apply_parcel_master_matching`,
`normalize_signal`, `derive_synthetic_signals`, the old shape of
`run_pipeline`) were retired in Session 10. The legacy test logic referenced
county-specific fixtures (SAN ANTONIO, TX, bexar_tx.json) that are out of
scope for universal framework tests; the new staged tests use the universal
`<synthetic>` / `ZZ` / Synthtown placeholders enforced by
`test_county_agnostic_regression.py`.

This stub remains so a stale link or operator script that points at this
file produces a clear redirect rather than an ImportError. It is not wired
into the framework gate and intentionally performs no assertions.
"""

from __future__ import annotations


def main() -> int:
    print(__doc__.strip())
    print()
    print("PASS: superseded by the v5.4.0 staged-pipeline tests in "
          "scaffold/tests/v5_4_0/ and the rewritten test_golden_path.py "
          "(both wired into scaffold/tests/run_all.py).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
