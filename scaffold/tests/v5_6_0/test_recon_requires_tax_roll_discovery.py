#!/usr/bin/env python3
"""v5.6.0 Gap 6 invariant — the county recon protocol must require an explicit
search for a tax roll, a delinquency list, and a balance lookup, classified
separately, with a preference order over delivery mechanisms and a state-level
fallback.

Run: python3 scaffold/tests/v5_6_0/test_recon_requires_tax_roll_discovery.py
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

    for needle in ("Tax roll and delinquency enrichment discovery",):
        if needle.lower() not in low:
            failures.append(f"missing required phrase: {needle!r}")

    # The three artifacts must be classified separately.
    for needle in ("TAX_ROLL", "DELINQUENCY_LIST", "BALANCE_LOOKUP"):
        if needle not in text:
            failures.append(f"missing tax artifact class: {needle!r}")

    # Delivery-mechanism preference order.
    for needle in ("documented contract", "bulk download", "rate limits"):
        if needle.lower() not in low:
            failures.append(f"missing delivery-mechanism term: {needle!r}")

    # A tax sale list is NOT a substitute for a delinquency feed.
    if "already reached sale eligibility" not in low:
        failures.append("protocol does not distinguish a tax sale list from a "
                        "delinquency list")

    # State-level fallback must be an explicit search target.
    if "STATE-level" not in text:
        failures.append("protocol does not require checking the state-level "
                        "authority as a tax roll / billing source")

    # Role rules must be restated so a tax roll never originates a lead.
    if "cannot originate a lead" not in low:
        failures.append("protocol does not restate that a tax roll is "
                        "enrichment and cannot originate a lead")

    if not any(k in text for k in ("MUST", "Required Step")):
        failures.append("tax roll discovery present but not marked required "
                        "(no 'MUST' / 'Required Step')")

    if failures:
        print("FAIL: Gap 6 — tax roll / delinquency discovery invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 6 — recon protocol requires tax roll, delinquency, and "
          "balance-lookup discovery")
    return 0


if __name__ == "__main__":
    sys.exit(main())
