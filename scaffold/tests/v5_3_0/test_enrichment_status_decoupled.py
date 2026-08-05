#!/usr/bin/env python3
"""v5.3.0 enrichment-decoupling invariant — §13 must decouple enrichment_status
from parcel_resolution_status; primary sources are never enrichment-gated.

Run: python3 scaffold/tests/v5_3_0/test_enrichment_status_decoupled.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

DOC = (Path(__file__).resolve().parents[3]
       / "knowledge_base" / "architecture" / "13_lead_origination_contract.md")


def _norm(text: str) -> str:
    return text.replace("`", "").lower()


def main() -> int:
    if not DOC.is_file():
        print(f"FAIL: §13 not found at {DOC}")
        return 1
    norm = _norm(DOC.read_text(encoding="utf-8"))

    failures = []

    for phrase in ("parcel_resolution_status", "enrichment_status",
                   "never enrichment-gated", "must not be dropped"):
        if phrase.lower() not in norm:
            failures.append(f"missing required phrase: {phrase!r}")

    # The four valid (parcel_resolution_status, enrichment_status) combinations
    # must be documented.
    if "four valid combinations" not in norm:
        failures.append("missing the 'four valid combinations' status matrix")
    for token in ("resolved", "unresolved", "review_required", "enriched",
                   "unenriched"):
        if token not in norm:
            failures.append(f"status matrix missing value: {token.upper()}")

    # Cross-reference to §17 (REVIEW_REQUIRED routing).
    if "§17" not in DOC.read_text(encoding="utf-8") and "17_debtor_party_rules" \
            not in norm:
        failures.append("missing cross-reference to §17 (REVIEW_REQUIRED routing)")

    if failures:
        print("FAIL: enrichment-decoupling — §13 enrichment-decoupling invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: enrichment-decoupling — §13 decouples enrichment_status from "
          "parcel_resolution_status")
    return 0


if __name__ == "__main__":
    sys.exit(main())
