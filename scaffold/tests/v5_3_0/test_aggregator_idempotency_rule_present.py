#!/usr/bin/env python3
"""v5.3.0 Gap 8 invariant — §19 Aggregator Idempotency Rule must be present and
complete.

Run: python3 scaffold/tests/v5_3_0/test_aggregator_idempotency_rule_present.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

DOC = (Path(__file__).resolve().parents[3]
       / "knowledge_base" / "architecture" / "19_aggregator_idempotency_rule.md")


def _norm(text: str) -> str:
    return text.replace("`", "").lower()


def main() -> int:
    if not DOC.is_file():
        print(f"FAIL: §19 not found at {DOC}")
        return 1
    norm = _norm(DOC.read_text(encoding="utf-8"))

    failures = []

    for phrase in ("idempotent", "never read from their own output", "*_base.json",
                   "self-check", "dry-run mode"):
        if phrase.lower() not in norm:
            failures.append(f"missing required phrase: {phrase!r}")

    # The pipeline contract (translators -> *_base.json -> aggregator ->
    # matched_leads.json) must be present.
    if not ("translators write to" in norm and "matched_leads.json" in norm):
        failures.append("missing pipeline contract text "
                         "(translators -> *_base.json -> aggregator -> "
                         "matched_leads.json)")

    if failures:
        print("FAIL: Gap 8 — §19 Aggregator Idempotency Rule invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 8 — §19 Aggregator Idempotency Rule present and complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
