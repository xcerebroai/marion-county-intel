#!/usr/bin/env python3
"""v5.3.0 Gap 1 invariant — the county recon protocol must require PDF / sample
document inspection before a source is deferred or marked limited-coverage.

Run: python3 scaffold/tests/v5_3_0/test_recon_requires_pdf_inspection.py
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

    # The Gap 1 requirement must be present.
    for needle in ("PDF/Sample Document Inspection",
                   "sample documents inspected",
                   "3 sample source documents"):
        if needle.lower() not in low:
            failures.append(f"missing required phrase: {needle!r}")

    # The requirement must be positioned as mandatory.
    if not any(k in text for k in ("MUST", "Required Step", "required sub-step")):
        failures.append("PDF inspection is present but not marked as required "
                         "(no 'MUST' / 'Required Step' / 'required sub-step')")

    if failures:
        print("FAIL: Gap 1 — PDF/sample document inspection invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 1 — recon protocol requires PDF/sample document inspection")
    return 0


if __name__ == "__main__":
    sys.exit(main())
