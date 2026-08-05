#!/usr/bin/env python3
"""
pre-commit PII guard — blocks a commit that would introduce real person-level
PII into operator-authored county code.

Reuses the SAME scanner as the framework gate test
(scaffold/tests/test_no_pii_in_operator_code.py) so detection logic never
diverges between the commit-time hook and the gate.

Behavior:
  - Scans only STAGED files (git diff --cached), restricted to in-scope
    operator surfaces (scrapers/, data/, runs/).
  - Exit 1 (blocks the commit) if any staged file carries PII.
  - Exit 0 otherwise.
  - Override for a deliberate, reviewed exception:  git commit --no-verify

Install with:  python scaffold/ops/install_hooks.py
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCANNER_DIR = REPO_ROOT / "scaffold" / "tests"
sys.path.insert(0, str(SCANNER_DIR))

try:
    import test_no_pii_in_operator_code as scanner
except Exception as e:  # noqa: BLE001
    print(f"[pre-commit PII guard] could not load scanner: {e}", file=sys.stderr)
    print("[pre-commit PII guard] commit allowed (guard unavailable).", file=sys.stderr)
    sys.exit(0)


def staged_files():
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    for line in out.stdout.splitlines():
        rel = line.strip().replace("\\", "/")
        if not rel:
            continue
        if scanner.is_in_scope(rel):
            abs_path = REPO_ROOT / rel
            if abs_path.is_file():
                yield (abs_path, rel)


def main():
    pairs = list(staged_files())
    if not pairs:
        sys.exit(0)
    violations = scanner.scan_files(pairs)
    if not violations:
        sys.exit(0)

    print("=" * 72, file=sys.stderr)
    print("COMMIT BLOCKED — possible real PII in staged operator code", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    for v in violations:
        print(f"  {v['file']}:{v['line']}  [{v['kind']}]", file=sys.stderr)
        print(f"    match: {v['match']}", file=sys.stderr)
        if v.get("context"):
            print(f"    context: {v['context']!r}", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    print("Replace real records with synthetic markers (TEST_OWNER_*,", file=sys.stderr)
    print("100 SYNTHETIC LN, DOE JANE, ...). For a reviewed exception only:", file=sys.stderr)
    print("    git commit --no-verify", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
