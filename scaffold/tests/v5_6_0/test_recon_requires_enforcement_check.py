#!/usr/bin/env python3
"""v5.6.0 Gap 4 invariant — the county recon protocol must require that an
access control be tested for ENFORCEMENT before a source is classified blocked,
and must define the single-layer / multi-layer enforcement tiering that makes an
operator-assisted source recoverable rather than unbuildable.

Run: python3 scaffold/tests/v5_6_0/test_recon_requires_enforcement_check.py
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

    # The present-vs-enforced distinction must be explicit.
    for needle in ("Access-control enforcement verification",
                   "CONTROL PRESENT",
                   "CONTROL ENFORCED",
                   "Enforcement tested"):
        if needle.lower() not in low:
            failures.append(f"missing required phrase: {needle!r}")

    # The enforcement tiering that keeps a human-verifiable source buildable.
    for needle in ("SINGLE_LAYER_HUMAN_VERIFIABLE",
                   "MULTI_LAYER",
                   "PER_REQUEST_CHALLENGE"):
        if needle not in text:
            failures.append(f"missing enforcement tier: {needle!r}")

    # A single-layer human-verifiable control must NOT be a build blocker.
    if "is NOT a build blocker" not in text:
        failures.append("protocol does not state that a single-layer "
                        "human-verifiable control is not a build blocker")

    # Operator-assisted session handoff must be an accepted resolution path.
    if "operator-assisted" not in low:
        failures.append("missing operator-assisted resolution path")
    if "session handoff" not in low:
        failures.append("missing session handoff requirement")

    if not any(k in text for k in ("MUST", "Required Step")):
        failures.append("enforcement verification present but not marked "
                        "required (no 'MUST' / 'Required Step')")

    if failures:
        print("FAIL: Gap 4 — access-control enforcement verification invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 4 — recon protocol requires access-control enforcement "
          "verification and defines operator-recoverable tiering")
    return 0


if __name__ == "__main__":
    sys.exit(main())
