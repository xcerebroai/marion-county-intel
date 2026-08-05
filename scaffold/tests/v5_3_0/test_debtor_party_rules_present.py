#!/usr/bin/env python3
"""v5.3.0 Gap 5 invariant — §17 Debtor Party Rules contract must be present and
complete.

Run: python3 scaffold/tests/v5_3_0/test_debtor_party_rules_present.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

DOC = (Path(__file__).resolve().parents[3]
       / "knowledge_base" / "architecture" / "17_debtor_party_rules.md")


def _norm(text: str) -> str:
    """Lowercase and drop backticks so phrase checks ignore markdown emphasis."""
    return text.replace("`", "").lower()


def main() -> int:
    if not DOC.is_file():
        print(f"FAIL: §17 not found at {DOC}")
        return 1
    norm = _norm(DOC.read_text(encoding="utf-8"))

    failures = []

    for phrase in ("debtor_party_rules", "expected_debtor_name_type", "known_filers",
                   "review_required"):
        if phrase.lower() not in norm:
            failures.append(f"missing required phrase: {phrase!r}")

    for doc_type in ("hospital_lien", "code_lien", "federal_tax_lien",
                     "state_tax_lien", "mechanic_lien", "lis_pendens",
                     "civil_judgment", "executor_deed", "administrator_deed",
                     "affidavit_of_heirship", "foreclosure_notice"):
        if doc_type not in norm:
            failures.append(f"rules table missing canonical_doc_type: {doc_type}")

    if "filer suppression" not in norm:
        failures.append("missing filer-suppression section ('filer suppression')")
    if "must never appear as owner_name" not in norm:
        failures.append("missing suppression rule "
                         "('MUST NEVER appear as owner_name')")

    for owner_type in ("ENTITY", "ESTATE", "TRUST", "INDIVIDUAL", "UNKNOWN"):
        if owner_type.lower() not in norm:
            failures.append(f"owner_type classifier missing: {owner_type}")

    if failures:
        print("FAIL: Gap 5 — §17 Debtor Party Rules invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 5 — §17 Debtor Party Rules contract present and complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
