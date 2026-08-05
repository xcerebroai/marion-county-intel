#!/usr/bin/env python3
"""v5.3.0 Gap 7 invariant — §02 Build Mode Protocol and the MASTER_PROMPT §4.34
pointer must be present and complete.

Run: python3 scaffold/tests/v5_3_0/test_build_mode_protocol_present.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROTOCOL = ROOT / "knowledge_base" / "protocols" / "02_build_mode_protocol.md"
MASTER_PROMPT = ROOT / "MASTER_PROMPT.md"


def _norm(text: str) -> str:
    """Lowercase and drop backticks for tolerant phrase checks."""
    return text.replace("`", "").lower()


def check_protocol(failures: list) -> None:
    if not PROTOCOL.is_file():
        failures.append(f"§02 not found at {PROTOCOL}")
        return
    norm = _norm(PROTOCOL.read_text(encoding="utf-8"))

    if "build mode entry preconditions" not in norm:
        failures.append("§02 missing 'Build Mode entry preconditions'")

    for cls in ("FULL_BUILD", "PARTIAL_BUILD", "DEFERRED_BUILD"):
        if cls.lower() not in norm:
            failures.append(f"§02 missing build classification: {cls}")

    for kw in ("translator", "aggregator", "*_leads_base.json", "matched_leads.json",
               "dashboard"):
        if kw.lower() not in norm:
            failures.append(f"§02 pipeline contract missing keyword: {kw!r}")

    for kw in ("mechanical verification", "semantic verification", "deploy_ok",
               "deploy_blocked", "needs_operator_review"):
        if kw not in norm:
            failures.append(f"§02 deploy-gate sequencing missing: {kw!r}")

    for ref in ("§17", "§18", "§13.14"):
        if ref.lower() not in norm:
            failures.append(f"§02 translator obligations missing reference: {ref}")
    for ref in ("§18", "§19"):
        if ref.lower() not in norm:
            failures.append(f"§02 aggregator obligations missing reference: {ref}")

    if "patch 2" not in norm:
        failures.append("§02 missing Patch 2 absorption note ('Patch 2')")
    if not ("absorbs" in norm or "absorbed" in norm):
        failures.append("§02 absorption note missing 'absorbs'/'absorbed'")
    if "without applying" not in norm:
        failures.append("§02 absorption note missing 'without applying'")
    if "stash" not in norm:
        failures.append("§02 absorption note missing 'stash'")

    if "halt conditions" not in norm:
        failures.append("§02 missing a halt-conditions section")


def check_master_prompt(failures: list) -> None:
    if not MASTER_PROMPT.is_file():
        failures.append(f"MASTER_PROMPT.md not found at {MASTER_PROMPT}")
        return
    text = MASTER_PROMPT.read_text(encoding="utf-8")

    start = text.find("## 4.34.")
    if start == -1:
        failures.append("MASTER_PROMPT.md has no §4.34 section")
        return
    end = text.find("## 4.35.", start)
    block = text[start:end] if end != -1 else text[start:]
    norm = _norm(block)

    if "build mode protocol" not in norm:
        failures.append("§4.34 is not the Build Mode Protocol section")
    if "build mode entry preconditions" not in norm:
        failures.append("§4.34 missing 'Build Mode entry preconditions'")
    for cls in ("FULL_BUILD", "PARTIAL_BUILD", "DEFERRED_BUILD"):
        if cls.lower() not in norm:
            failures.append(f"§4.34 missing build classification: {cls}")
    if "02_build_mode_protocol.md" not in norm:
        failures.append("§4.34 does not reference knowledge_base/protocols/"
                        "02_build_mode_protocol.md")
    # The §4.34 slot must hold real content, not a reserved-gap placeholder.
    if "reserved for" in norm and "session a4" in norm:
        failures.append("§4.34 still contains a reserved-gap placeholder")


def main() -> int:
    failures: list = []
    check_protocol(failures)
    check_master_prompt(failures)

    if failures:
        print("FAIL: Gap 7 — Build Mode Protocol invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 7 — §02 Build Mode Protocol and §4.34 pointer present and complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
