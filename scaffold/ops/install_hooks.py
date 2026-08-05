#!/usr/bin/env python3
"""
install_hooks.py — install the PII pre-commit guard into .git/hooks/.

Run once per clone:  python scaffold/ops/install_hooks.py

Writes a .git/hooks/pre-commit shim that invokes
scaffold/ops/pre_commit_pii_guard.py with the current Python interpreter.
Idempotent: re-running overwrites the shim. Backs up any pre-existing
non-framework hook to pre-commit.bak first.
"""

import os
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOKS_DIR = REPO_ROOT / ".git" / "hooks"
GUARD = "scaffold/ops/pre_commit_pii_guard.py"
MARKER = "# xcerebro-pii-guard"


def main():
    if not (REPO_ROOT / ".git").is_dir():
        print(f"ERROR: {REPO_ROOT} is not a git repo (no .git/).", file=sys.stderr)
        sys.exit(1)
    HOOKS_DIR.mkdir(parents=True, exist_ok=True)
    hook = HOOKS_DIR / "pre-commit"

    if hook.exists():
        existing = hook.read_text(encoding="utf-8", errors="ignore")
        if MARKER not in existing:
            backup = HOOKS_DIR / "pre-commit.bak"
            backup.write_text(existing, encoding="utf-8")
            print(f"Backed up existing pre-commit hook -> {backup}")

    # POSIX-style shim works in git-bash on Windows and on macOS/Linux.
    shim = (
        "#!/bin/sh\n"
        f"{MARKER}\n"
        "# Auto-installed by scaffold/ops/install_hooks.py — blocks commits\n"
        "# that introduce real PII into operator code. Bypass: git commit --no-verify\n"
        'python "$(git rev-parse --show-toplevel)/'
        + GUARD
        + '" || exit 1\n'
    )
    hook.write_text(shim, encoding="utf-8")
    # chmod +x
    st = os.stat(hook)
    os.chmod(hook, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Installed PII pre-commit guard -> {hook}")
    print("Test it:  echo bad | git commit ... (it scans staged operator files)")
    print("Bypass for a reviewed exception:  git commit --no-verify")


if __name__ == "__main__":
    main()
