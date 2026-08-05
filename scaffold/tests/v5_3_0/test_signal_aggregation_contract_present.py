#!/usr/bin/env python3
"""v5.3.0 Gap 6 invariant — §18 Signal Aggregation Contract must be present and
complete.

Run: python3 scaffold/tests/v5_3_0/test_signal_aggregation_contract_present.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

DOC = (Path(__file__).resolve().parents[3]
       / "knowledge_base" / "architecture" / "18_signal_aggregation_contract.md")


def _norm(text: str) -> str:
    return text.replace("`", "").lower()


def main() -> int:
    if not DOC.is_file():
        print(f"FAIL: §18 not found at {DOC}")
        return 1
    norm = _norm(DOC.read_text(encoding="utf-8"))

    failures = []

    for phrase in ("(parcel_id, canonical_doc_type, signal_type)", "aggregation key",
                   "instrument_numbers", "source_urls", "anti-collapse"):
        if phrase.lower() not in norm:
            failures.append(f"missing required phrase: {phrase!r}")

    if "cross-source aggregation" not in norm:
        failures.append("missing cross-source aggregation section")

    if not ("legitimate stacking" in norm and "dedup failure" in norm):
        failures.append("missing legitimate-stacking vs dedup-failure distinction")

    if failures:
        print("FAIL: Gap 6 — §18 Signal Aggregation Contract invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 6 — §18 Signal Aggregation Contract present and complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
