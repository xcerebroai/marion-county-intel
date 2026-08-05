#!/usr/bin/env python3
"""v5.6.0 Gap 7 invariant — the county recon protocol must require that source
freshness be verified against the maximum ACTUAL record date rather than the
advertised or catalog-reported cadence, and must forbid a FROZEN source from
satisfying the P0 gate.

Run: python3 scaffold/tests/v5_6_0/test_recon_requires_freshness_check.py
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

    for needle in ("Source freshness verification",):
        if needle.lower() not in low:
            failures.append(f"missing required phrase: {needle!r}")

    # Required recorded fields.
    for needle in ("max_event_date", "min_event_date", "observed_lag",
                   "claimed_cadence", "freshness_verdict"):
        if needle not in text:
            failures.append(f"missing required freshness field: {needle!r}")

    # Required verdict enum.
    for needle in ("LIVE", "LAGGING", "FROZEN", "UNKNOWN"):
        if needle not in text:
            failures.append(f"missing freshness verdict: {needle!r}")

    # Claim vs evidence framing.
    if "is a CLAIM" not in text or "is the EVIDENCE" not in text:
        failures.append("protocol does not frame advertised cadence as a claim "
                        "and max record date as the evidence")

    # A frozen source must not satisfy the P0 gate.
    if "MUST NOT satisfy the P0 gate" not in text:
        failures.append("protocol does not forbid a FROZEN source from "
                        "satisfying the P0 gate")

    # A stale bulk extract must not displace a live authoritative portal.
    if "displace the authoritative live one" not in low:
        failures.append("protocol does not require recording both a frozen "
                        "extract and the live portal exposing the same records")

    if not any(k in text for k in ("MUST", "Required Step")):
        failures.append("freshness verification present but not marked "
                        "required (no 'MUST' / 'Required Step')")

    if failures:
        print("FAIL: Gap 7 — source freshness verification invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 7 — recon protocol requires evidence-based source "
          "freshness verification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
