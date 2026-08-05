"""
run_all.py — single entry point to run all framework gate tests.

Runs:
  1. The monolith gate tests:
       scaffold/tests/test_golden_path.py
       scaffold/tests/test_county_agnostic_regression.py
       scaffold/tests/test_write_county_config.py   (v5.1.1-beta+)
       scaffold/tests/test_translator_registry.py    (v5.1.2-beta+)
  2. Every scaffold/tests/v5_3_0/test_*.py — the §16-§20 / §02 architecture-
     contract invariant tests (auto-discovered; v5.3.0+).
  3. Every scaffold/tests/v5_4_0/test_*.py — the v5.4.0 pipeline-engine
     contract-shape / scaffolding tests, "Group A" (auto-discovered; v5.4.0+).

NOT run: scaffold/tests/v5_4_0_pending/ — the v5.4.0 "Group B" behavioral
specs. They are red until the staged engine is built and are intentionally
quarantined out of the default gate. Each is promoted into v5_4_0/ by the
session that implements its stage (see v5_4_0_pending/README.md).

All wired tests must pass for the framework to be shippable. Exits 0 only when
every test exits 0. Operator-friendly output preserved from each underlying
script.

Usage:
  python scaffold/tests/run_all.py

Each underlying script can still be run directly for focused work, e.g.:
  python scaffold/tests/test_golden_path.py
  python scaffold/tests/v5_3_0/test_debtor_party_rules_present.py
  python scaffold/tests/v5_4_0/test_contract_schemas.py
"""

import subprocess
import sys
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable

TESTS = [
    ("Golden path", TESTS_DIR / "test_golden_path.py"),
    ("County-agnostic regression", TESTS_DIR / "test_county_agnostic_regression.py"),
    ("Atomic county config writer (v5.1.1-beta)", TESTS_DIR / "test_write_county_config.py"),
    ("Translator registry (v5.1.2-beta)", TESTS_DIR / "test_translator_registry.py"),
    ("PII guard — operator code", TESTS_DIR / "test_no_pii_in_operator_code.py"),
]

# v5.3.0+ — §16-§20 / §02 architecture-contract invariant tests. Auto-discovered
# so newly added invariants are gated without editing this file. (These shipped
# in v5.3.0 but were never wired into run_all.py; wired here in v5.4.0 so the
# default gate covers them.)
for _script in sorted((TESTS_DIR / "v5_3_0").glob("test_*.py")):
    TESTS.append((f"v5.3.0 invariant — {_script.stem}", _script))

# v5.4.0+ — pipeline-engine contract-shape / scaffolding tests ("Group A").
# Auto-discovered. v5_4_0_pending/ ("Group B" behavioral specs) is deliberately
# NOT discovered here — see v5_4_0_pending/README.md.
_v5_4_0_dir = TESTS_DIR / "v5_4_0"
if _v5_4_0_dir.is_dir():
    for _script in sorted(_v5_4_0_dir.glob("test_*.py")):
        TESTS.append((f"v5.4.0 contract-shape — {_script.stem}", _script))

# v5.6.0+ — recon-protocol invariants for the Gap 4-7 required steps
# (access-control enforcement, lead-type terminology, tax roll / delinquency
# discovery, source freshness). Auto-discovered, same as v5_3_0.
_v5_6_0_dir = TESTS_DIR / "v5_6_0"
if _v5_6_0_dir.is_dir():
    for _script in sorted(_v5_6_0_dir.glob("test_*.py")):
        TESTS.append((f"v5.6.0 invariant — {_script.stem}", _script))


def main():
    results = []
    for label, script in TESTS:
        print()
        print("#" * 72)
        print(f"# RUNNING: {label} — {script.name}")
        print("#" * 72)
        proc = subprocess.run([PYTHON, str(script)])
        results.append((label, script.name, proc.returncode))

    # Summary
    print()
    print("=" * 72)
    print("FRAMEWORK GATE TEST SUMMARY")
    print("=" * 72)
    any_failed = False
    for label, name, code in results:
        marker = "PASS" if code == 0 else "FAIL"
        if code != 0:
            any_failed = True
        print(f"  [{marker}] {label} ({name}) — exit code {code}")
    print("=" * 72)

    if any_failed:
        print("RESULT: FAIL — one or more gate tests failed. Framework is not shippable.")
        sys.exit(1)
    else:
        print("RESULT: PASS — all gate tests green. Framework gate satisfied.")
        sys.exit(0)


if __name__ == "__main__":
    main()
