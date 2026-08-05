#!/usr/bin/env python3
"""v5.3.0 Gap 3 invariant — the county recon protocol must require every source's
bulk-data availability to be classified.

Run: python3 scaffold/tests/v5_3_0/test_recon_requires_bulk_classification.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

PROTOCOL = (Path(__file__).resolve().parents[3]
            / "knowledge_base" / "protocols" / "01_county_recon.md")


def main() -> int:
    if not PROTOCOL.is_file():
        print(f"FAIL: protocol not found at {PROTOCOL}")
        return 1
    text = PROTOCOL.read_text(encoding="utf-8")
    low = text.lower()

    failures = []

    for needle in ("Bulk-Data Availability Classification", "FULL_COUNTY_BULK",
                   "BATCH_QUERY", "PER_RECORD_ONLY"):
        if needle.lower() not in low:
            failures.append(f"missing required phrase: {needle!r}")

    # The classification must be mandatory for every source.
    if "must classify" not in low:
        failures.append("bulk classification is present but not marked mandatory "
                         "(no 'MUST classify')")

    if failures:
        print("FAIL: Gap 3 — bulk-data availability classification invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 3 — recon protocol requires bulk-data availability classification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
