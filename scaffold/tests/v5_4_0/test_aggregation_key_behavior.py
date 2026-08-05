#!/usr/bin/env python3
"""v5.4.0 behavioral spec — §18 aggregation key engine.

PROMOTED in v5.4.0 Session 3 — aggregation_key_engine is implemented and this
spec passes. Wired into run_all.py via scaffold/tests/v5_4_0/.

This is a behavioral spec, not a doc-presence check. It calls the real
engine and asserts the §18.B key behaves and the §18.F anti-collapse rule
holds.

The cases:
  - §18.B: the key is the tuple (parcel_id, canonical_doc_type, signal_type).
  - Same key  -> same tuple  -> records collapse into one signal (legitimate).
  - §18.F anti-collapse: a parcel carrying a hospital_lien AND an executors_deed
    produces TWO distinct keys, not one — distinct signal_type values must not
    collapse even when they share parcel_id.

Run: python3 scaffold/tests/v5_4_0/test_aggregation_key_behavior.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# A per-county canonical_doc_type -> display-label map (§18.I signal_type_labels).
SIGNAL_TYPE_LABELS = {
    "hospital_lien": "Hospital Lien",
    "executors_deed": "Estate-Titled Property",
    "federal_tax_lien": "Federal Tax Lien",
}


def main() -> int:
    from scaffold.pipeline import aggregation_key_engine as ake

    try:
        # signal_type resolution from canonical_doc_type (§18.B / §18.I).
        st_hospital = ake.resolve_signal_type(
            "hospital_lien", signal_type_labels=SIGNAL_TYPE_LABELS)
        st_estate = ake.resolve_signal_type(
            "executors_deed", signal_type_labels=SIGNAL_TYPE_LABELS)

        # Three keys on ONE parcel: two identical, one a different doc type.
        key_hospital_a = ake.compute_aggregation_key(
            parcel_id="PARCEL-001",
            canonical_doc_type="hospital_lien",
            signal_type=st_hospital)
        key_hospital_b = ake.compute_aggregation_key(
            parcel_id="PARCEL-001",
            canonical_doc_type="hospital_lien",
            signal_type=st_hospital)
        key_estate = ake.compute_aggregation_key(
            parcel_id="PARCEL-001",
            canonical_doc_type="executors_deed",
            signal_type=st_estate)

        tup_hospital_a = ake.aggregation_key_tuple(key_hospital_a)
        tup_hospital_b = ake.aggregation_key_tuple(key_hospital_b)
        tup_estate = ake.aggregation_key_tuple(key_estate)
    except NotImplementedError as exc:
        print("FAIL (pending v5.4.0 Session 3): aggregation_key_engine "
              "is not implemented yet")
        print(f"  {exc}")
        return 1

    distinct_tuples = {tup_hospital_a, tup_hospital_b, tup_estate}

    checks = [
        ("resolve_signal_type maps hospital_lien -> 'Hospital Lien'",
         st_hospital == "Hospital Lien"),
        ("the key carries the §18.B tuple components",
         key_hospital_a.get("parcel_id") == "PARCEL-001"
         and key_hospital_a.get("canonical_doc_type") == "hospital_lien"
         and key_hospital_a.get("signal_type") == "Hospital Lien"),
        ("two records with the same key produce the SAME tuple "
         "(legitimate collapse)",
         tup_hospital_a == tup_hospital_b),
        ("§18.F anti-collapse: hospital_lien and executors_deed on the same "
         "parcel produce DIFFERENT keys",
         tup_hospital_a != tup_estate),
        ("the three keys collapse to exactly 2 distinct signals, not 1",
         len(distinct_tuples) == 2),
        ("the key tuple is hashable (usable for grouping)",
         isinstance(hash(tup_hospital_a), int)),
    ]

    failed = [desc for desc, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: §18 aggregation key — {len(failed)} assertion(s) failed")
        return 1

    print("PASS: §18 aggregation key groups same-key records and keeps "
          "distinct signal types distinct (anti-collapse)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
