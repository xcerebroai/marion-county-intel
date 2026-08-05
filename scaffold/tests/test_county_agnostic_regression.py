"""
test_county_agnostic_regression.py — fail if real county/state examples leak into
universal framework files.

v5.1.2-beta MAJOR UPDATE:
  - Enforce MASTER_PROMPT §4.31 Universality Contract.
  - Scan adds: vendor names (BCAD, HCAD, etc.), portal hostnames
    (publicsearch.us, tylertech.cloud, etc.), state statute references
    (Tex. Prop. Code, Cal. Civ. Code, etc.), and additional county names.
  - Exemption paths expanded to include: data/, .claude/, dashboard/,
    scrapers/, scaffold/tests/fixtures/, scaffold/data/. These are
    county-scoped or operator-scoped or framework-canonical test
    fixtures, not universal pipeline code.

This test is now a gate. The framework must run county-agnostic
or v5.1.2-beta is wrong.

Run with: python3 scaffold/tests/test_county_agnostic_regression.py
"""

import re
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent

# Phrases that match on word boundaries — case-insensitive.
PHRASE_BLOCKLIST = [
    # County / city names
    r"\bOcean\b",
    r"\bBexar\b",
    r"\bSan Antonio\b",
    r"\bMaricopa\b",
    r"\bPhoenix\b",
    r"\bHouston\b",
    r"\bCuyahoga\b",
    r"\bCleveland\b",
    r"\bPinellas\b",
    r"\bSuffolk\b",
    r"\bMiami\s*Dade\b",
    r"\bBroward\b",
    r"\bNew Hanover\b",
    # State full names
    r"\bNew Jersey\b",
    r"\bTexas\b",
    r"\bArizona\b",
    r"\bFlorida\b",
    r"\bCalifornia\b",
    r"\bOhio\b",
    r"\bGeorgia\b",
    r"\bPennsylvania\b",
    # State-specific record-acts and authorities
    r"\bOPRA\b",
    r"\bPublic Information Act\b",
    r"\bNJ Courts\b",
    r"\bNJ DOIT\b",
    # Vendor / portal names
    r"\bBCAD\b",
    r"\bHCAD\b",
    r"\bMCAD\b",
    r"\bDCAD\b",
    r"\bTCAD\b",
    r"\bWCAD\b",
    r"\bTyler Tech",
    r"\bTyler Odyssey",
    r"\bPublicSearch\b",
    r"\bpublicsearch\.us\b",
    r"\btylertech\.cloud\b",
    r"\bharrisgovern\b",
    r"\bbexar\.org\b",
    r"\bbexar\.tx\b",
    # Statute references
    r"\bTex\.\s*Prop\.\s*Code\b",
    r"\bTexas Property Code\b",
    r"\bCal\.\s*Civ\.\s*Code\b",
    r"\bCalifornia Civil Code\b",
    r"\bOh\.\s*Rev\.\s*Code\b",
    r"\bGa\.\s*Code\b",
    r"\bN\.J\.\s*Stat\b",
    r"\bArizona Revised Statutes\b",
    r"\bA\.R\.S\.\s*",
]

STATE_CODES = ["NJ", "TX", "CA", "AZ", "FL", "NY", "OH", "GA", "PA"]

# v5.3.0 fix — directories whose contents are never framework files:
# virtualenvs, vendored third-party packages, build artifacts, VCS
# internals, and tool caches. The scanner walked .venv/ and flagged
# strings inside packages like cryptography and pip as "county-specific
# leaks" (174 false-positive hits at baseline), making the suite
# unusable as a real gate. A path is exempt if ANY of its components
# is one of these names. Resolves v5.1.2-beta-final-additions.md item G.
EXCLUDED_DIR_COMPONENTS = {
    ".venv",
    "venv",
    "site-packages",
    "node_modules",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "dist",
    "build",
    ".tox",
    ".eggs",
}


def is_exempt_path(rel_path):
    """v5.1.2-beta exemption rules per MASTER_PROMPT §4.31."""
    rel_str = str(rel_path).replace("\\", "/")

    # v5.3.0: virtualenvs, vendored dependencies, build artifacts, VCS
    # internals, and tool caches are never universal framework files —
    # exempt any path with such a component, never scan their contents.
    if any(part in EXCLUDED_DIR_COMPONENTS for part in rel_str.split("/")):
        return True

    # County-specific configs ARE exempt; universal templates NOT.
    if rel_str.startswith("config/counties/"):
        basename = Path(rel_str).name
        if basename in ("_template.json", "_schema.md", "_schema.json"):
            return False
        return True

    # Per-county run folders — exempt
    if rel_str.startswith("runs/"):
        return True

    # County-side scraper adapters — exempt
    if rel_str.startswith("scrapers/"):
        return True

    # Live data outputs — exempt
    if rel_str.startswith("data/"):
        return True

    # Operator-side Claude Code settings — exempt
    if rel_str.startswith(".claude/"):
        return True

    # County-built dashboards — exempt
    if rel_str.startswith("dashboard/"):
        return True

    # Test files and fixtures are intentionally county-shaped — exempt.
    # v5.3.0: broadened from scaffold/tests/fixtures/ to all of
    # scaffold/tests/. Test .py files (test_matcher.py,
    # test_owner_name_*.py, etc.) legitimately carry concrete
    # county-shaped data (parcel IDs, addresses, state codes) as test
    # input; they are not universal pipeline code.
    if rel_str.startswith("scaffold/tests/"):
        return True

    # Framework synthetic data — exempt
    if rel_str.startswith("scaffold/data/"):
        return True

    # The test file itself references all these terms by design.
    if rel_str.startswith("scaffold/tests/test_county_agnostic_regression"):
        return True

    # The sale_date_rules registry must include the rule name as
    # a registry key. The string is a rule identifier, not a
    # state-specific assertion. Exempt this single file.
    if rel_str == "scaffold/pipeline/sale_date_rules.py":
        return True

    # v5.3.0: matcher.py carries an all-US-states code set
    # (a 50-state validation frozenset). Every state code is present
    # by design — this is universal validation data, not a
    # county-specific assertion. Exempt this single file.
    if rel_str == "scaffold/pipeline/matcher.py":
        return True

    # MASTER_PROMPT.md §4.31 documents the contract by citing
    # examples — must be exempt or it's self-failing.
    if rel_str == "MASTER_PROMPT.md":
        return True

    # MIGRATION.md describes version deltas with examples.
    if rel_str == "MIGRATION.md":
        return True

    # LICENSE.md — governing-law clause references a jurisdiction.
    if rel_str == "LICENSE.md":
        return True

    # Onboarding docs use concrete examples on purpose.
    if rel_str == "START_HERE.md":
        return True
    if rel_str == "README.md":
        return True
    if rel_str == "scaffold/bootstrap_county.py":
        return True

    # The vendor portal library documents real vendors operators
    # encounter (Tyler Technologies, etc.). Its purpose is to be a
    # reference catalog, not universal pipeline code.
    if rel_str == "knowledge_base/engineering/08_vendor_portal_library.md":
        return True

    # Release notes that document specific historical migrations
    # legitimately reference the counties involved (e.g. "the Bexar
    # build that uncovered this contamination"). Exempt the version
    # notes file at the repo root.
    if rel_str.startswith("VERSION_NOTES_"):
        return True

    # docs/ — operator-facing release/migration documentation.
    # These reference real counties when describing what happened
    # and what needs to be migrated.
    if rel_str.startswith("docs/"):
        return True

    return False


def files_to_scan(root):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix not in (".md", ".json", ".jsonl", ".py", ".txt"):
            continue
        rel = p.relative_to(root)
        if is_exempt_path(rel):
            continue
        yield p, rel


def scan_file(path, rel_path):
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return []

    violations = []

    for pattern in PHRASE_BLOCKLIST:
        for m in re.finditer(pattern, text, re.IGNORECASE):
            line_no = text[:m.start()].count("\n") + 1
            line_content = text.split("\n")[line_no - 1] if line_no - 1 < len(text.split("\n")) else ""
            violations.append({
                "file": str(rel_path),
                "line": line_no,
                "match": m.group(),
                "rule": f"phrase_blocklist: {pattern}",
                "context": line_content[:140],
            })

    for code in STATE_CODES:
        pattern = r"(?<![A-Za-z0-9_])" + re.escape(code) + r"(?![A-Za-z0-9_])"
        for m in re.finditer(pattern, text):
            line_no = text[:m.start()].count("\n") + 1
            line_content = text.split("\n")[line_no - 1] if line_no - 1 < len(text.split("\n")) else ""
            violations.append({
                "file": str(rel_path),
                "line": line_no,
                "match": m.group(),
                "line_content": line_content[:120],
                "rule": f"state_code_whole_token: {code}",
            })

    return violations


def run_regression():
    all_violations = []
    files_scanned = 0
    for path, rel in files_to_scan(FRAMEWORK_ROOT):
        files_scanned += 1
        all_violations.extend(scan_file(path, rel))

    print("=" * 72)
    print("COUNTY-AGNOSTIC REGRESSION TEST (v5.1.2-beta universality contract)")
    print("=" * 72)
    print(f"Files scanned: {files_scanned}")
    print(f"Violations found: {len(all_violations)}")

    if all_violations:
        print()
        print("VIOLATIONS:")
        for v in all_violations:
            print(f"  {v['file']}:{v['line']}")
            print(f"    match: {v['match']!r}")
            print(f"    rule: {v['rule']}")
            ctx = v.get("context") or v.get("line_content", "")
            if ctx:
                print(f"    context: {ctx!r}")
            print()
        print("=" * 72)
        print(f"RESULT: FAIL — {len(all_violations)} county-specific term(s) leaked into universal files")
        print("=" * 72)
        return False
    else:
        print()
        print("=" * 72)
        print("RESULT: PASS — no county-specific terms found in universal framework files")
        print("=" * 72)
        return True


if __name__ == "__main__":
    ok = run_regression()
    sys.exit(0 if ok else 1)
