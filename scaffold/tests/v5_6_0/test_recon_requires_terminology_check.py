#!/usr/bin/env python3
"""v5.6.0 Gap 5 invariant — the county recon protocol must require that each
canonical lead type be checked against the jurisdiction's OWN vocabulary, and
must require separating the originating event from downstream stages of the
same distress process.

Run: python3 scaffold/tests/v5_6_0/test_recon_requires_terminology_check.py
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

    for needle in ("Canonical lead-type terminology verification",
                   "Originating event",
                   "downstream stage",
                   "Local name"):
        if needle.lower() not in low:
            failures.append(f"missing required phrase: {needle!r}")

    # Framework vocabulary must be explicitly disclaimed as non-local.
    if "are FRAMEWORK vocabulary" not in text:
        failures.append("protocol does not state that lead type names are "
                        "framework vocabulary rather than local vocabulary")

    # Terminology must be empirical, not inferred.
    if "empirically" not in low:
        failures.append("protocol does not require terminology be established "
                        "empirically from the source's own vocabulary")

    # Structurally-absent lead types get their own verdict, not NOT_FOUND.
    if "NOT_APPLICABLE_IN_JURISDICTION" not in text:
        failures.append("missing NOT_APPLICABLE_IN_JURISDICTION verdict for "
                        "lead types absent under the local legal regime")

    if not any(k in text for k in ("MUST", "Required Step")):
        failures.append("terminology verification present but not marked "
                        "required (no 'MUST' / 'Required Step')")

    if failures:
        print("FAIL: Gap 5 — lead-type terminology verification invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 5 — recon protocol requires local terminology "
          "verification and originating-event identification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
