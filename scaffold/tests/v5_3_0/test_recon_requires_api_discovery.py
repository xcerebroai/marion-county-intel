#!/usr/bin/env python3
"""v5.3.0 Gap 2 invariant — the county recon protocol must require a documented
API discovery search before settling on HTML scraping.

Run: python3 scaffold/tests/v5_3_0/test_recon_requires_api_discovery.py
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

    for needle in ("Documented API Discovery", "/api", "/swagger", "/docs",
                   "Postman"):
        if needle.lower() not in low:
            failures.append(f"missing required phrase: {needle!r}")

    if not any(k in text for k in ("MUST", "Required Step", "required sub-step")):
        failures.append("API discovery is present but not marked as required "
                         "(no 'MUST' / 'Required Step' / 'required sub-step')")

    if failures:
        print("FAIL: Gap 2 — documented API discovery invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 2 — recon protocol requires documented API discovery")
    return 0


if __name__ == "__main__":
    sys.exit(main())
