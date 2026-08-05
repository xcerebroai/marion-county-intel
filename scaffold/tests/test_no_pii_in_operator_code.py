"""
test_no_pii_in_operator_code.py — fail if real person-level PII leaks into
operator-authored county code or committed data.

WHY THIS EXISTS
---------------
The schema and engine never touch live data, and `.gitignore` keeps the
immutable raw pulls (`data/raw/`, `data/runs/*/raw/`, evidence PDFs) out of
history. But when an operator writes a county adapter/scraper, it is easy for a
real record — owner name, decedent name, street address, phone, email, SSN — to
end up baked into a selftest fixture or a docstring example and then committed.
Once it is in git history it is there permanently. No existing gate catches
this: `test_county_agnostic_regression` only scans for *jurisdiction* names
(county/state/vendor) in *universal* files, and it explicitly EXEMPTS the very
directories operator code lives in (`scrapers/`, `runs/`, `data/`).

This test is the missing guard. It scans OPERATOR-authored surfaces for PII and
fails the framework gate if any is found.

SCOPE (what gets scanned)
-------------------------
  - scrapers/           — operator-written adapters (the #1 leak surface)
  - data/*.json,*.jsonl — committed lead/evidence outputs (leads.json etc.)
  - runs/               — per-county notes / launch files
The immutable raw directories are gitignored and never reach history, so they
are out of scope by construction.

NOT SCANNED (framework-canonical synthetic harness, authored + reviewed)
------------------------------------------------------------------------
  - scaffold/           — the synthetic fixtures + tests INTENTIONALLY carry
                          name/address-shaped data (TEST_OWNER_*, DOE JOHN,
                          100 SYNTHETIC LN, ...). They are the framework's own
                          fake data and are reviewed. Scanning them would
                          reproduce the ".venv false-positive explosion" that
                          made the agnostic test unusable as a gate.

DESIGN NOTE — false positives are the enemy
-------------------------------------------
A PII gate that fires on synthetic markers is worse than no gate (operators
learn to ignore it). So this scanner is deliberately conservative:
  - High-confidence identifiers (SSN, phone, email) are flagged outright —
    these effectively never appear by accident in clean code.
  - Name/address FIELD VALUES are flagged ONLY when the quoted value is NOT a
    recognized synthetic marker (TEST_*, SYN_*, placeholder DOE/SMITH, etc.).
  - The allowlist is calibrated against the markers the framework's own
    fixtures actually use.

Run with: python3 scaffold/tests/test_no_pii_in_operator_code.py
Exit 0 = clean, exit 1 = PII found.
"""

import re
import sys
from pathlib import Path

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent.parent

# ---------------------------------------------------------------------------
# Scope: directories/files that ARE operator-authored and DO get scanned.
# A path is in scope if it matches one of these prefixes (repo-relative,
# forward-slash normalized).
# ---------------------------------------------------------------------------
IN_SCOPE_PREFIXES = (
    "scrapers/",
    "runs/",
    "data/",
)

# Within in-scope dirs, only these suffixes carry text worth scanning.
SCANNED_SUFFIXES = (".py", ".json", ".jsonl", ".md", ".txt", ".csv")

# ---------------------------------------------------------------------------
# Exemptions — framework-canonical or non-text. scaffold/ is the synthetic
# harness (reviewed fake data); .git / caches / build dirs are never code.
# ---------------------------------------------------------------------------
EXCLUDED_DIR_COMPONENTS = {
    ".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env", "ENV", "node_modules", "dist", "build", ".tox",
    ".eggs", "htmlcov",
    # gitignored raw pulls — belt-and-suspenders even though .gitignore covers
    # them, in case the test is run on a dirty tree before commit.
    # "samples" holds the §01.22 sample-document pulls a recon must fetch and
    # inspect (runs/<slug>/recon/samples/). Those are raw source records by
    # definition — real owner names, situs addresses, party names — so they are
    # gitignored like data/raw/ and excluded here for the same reason. Recon is
    # REQUIRED to fetch them (§01.22) and equally required not to commit them.
    "raw", "logs", "tmp", ".cache", "evidence", "samples",
}

# ---------------------------------------------------------------------------
# Synthetic-marker allowlist. A name/address field value matching ANY of these
# (case-insensitive) is treated as fake and NOT flagged. Calibrated against the
# real markers used in scaffold/ fixtures + the build doctrine.
# ---------------------------------------------------------------------------
_SYNTHETIC_TOKENS = [
    r"TEST_[A-Z0-9_]+",          # TEST_OWNER_001, TEST_HEIR_012, TEST_SPOUSE_007
    r"SYN[_A-Z0-9]*",            # SYN_LANDLORD_LLC, SYNTHETIC
    r"FORMER_OWNER_[0-9]+",
    r"HEIR_[A-Z0-9]+",
    r"\bSYNTHETIC\b",
    r"\bSYNTHTOWN\b",
    r"\bSAMPLE\b",
    r"\bEXAMPLE\b",
    r"\bACME\b",                 # classic fake-company placeholder (ACME BANK NA)
    r"\bFIELDMAP\b",
    r"\bIDENTITY OWNER\b",
    r"\bOUT OF AREA\b",
    r"\bPLACEHOLDER\b",
    r"\bREDACTED\b",
    r"\bUNKNOWN\b",
    r"\bN/A\b",                  # literal N/A placeholder ONLY (anchored — must
                                # not substring-match names like "maRIA elENA")
    # classic placeholder surnames used by the framework's own fixtures
    r"\bDOE\b",
    r"\bROE\b",
    r"\bSMITH\b",          # used as SMITH JANE / SMITH JOHN placeholders
    r"\bJOHN Q\b",
    r"\bJANE Q\b",
    # generic synthetic address forms
    r"\b[0-9]+ (SYNTHETIC|EXAMPLE|TEST|FAKE|SAMPLE) ",
    r"^100 EXAMPLE WAY$",
]
# Whole-value-only markers: a value is synthetic if it matches one of these in
# FULL (used for short/ambiguous tokens that must never substring-match a real
# name — party codes, template brackets, schema field-name echoes).
_WHOLE_VALUE_TOKENS = [
    r"[A-Z]{1,3}",                       # party-role codes: GR, GE, DF, ...
    r"<.*>",                             # "<owner string as recorded>"
    r"[a-z_]+[0-9]?",                    # field-name echo: owner_mailing_addr1
    r"999 .*",                           # 999-prefixed synthetic addresses
    r"100 (SYNTHETIC|EXAMPLE) (LN|LANE|WAY)",
    r"HEIR_[A-Z]",                       # HEIR_A / HEIR_B
    r"(HEIR_[A-Z];?\s*)+",               # HEIR_A; HEIR_B; HEIR_C
]
_ALLOW_RE = re.compile("|".join(f"(?:{t})" for t in _SYNTHETIC_TOKENS), re.IGNORECASE)
_WHOLE_VALUE_RE = re.compile(
    r"^(?:" + "|".join(f"(?:{t})" for t in _WHOLE_VALUE_TOKENS) + r")$",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# High-confidence identifier patterns — flagged outright (near-zero FP).
# ---------------------------------------------------------------------------
HIGH_CONFIDENCE = [
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]
# Emails on these domains are infrastructure, not PII — never flag.
_EMAIL_ALLOW = re.compile(
    r"@(?:example\.(?:com|org|net)|.*\.gov|.*\.us|github\.com|"
    r"anthropic\.com|noreply\.|localhost)",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# PII-bearing field names. A quoted value assigned to one of these is flagged
# unless the value is allowlisted as synthetic.
# Matches  "owner_name": "VALUE"   and   "owner_name":"VALUE"
# ---------------------------------------------------------------------------
PII_FIELDS = (
    "owner_name", "owner_mailing_address", "situs_address", "mailing_address",
    "grantor", "grantee", "debtor", "defendant", "plaintiff", "decedent",
    "deceased", "borrower", "trustor", "beneficiary", "respondent",
    "property_address", "street_address", "address", "situs_city",
)
_FIELD_RE = re.compile(
    r'"(' + "|".join(PII_FIELDS) + r')"\s*:\s*"([^"]*)"',
    re.IGNORECASE,
)

# Street-address heuristic: a number followed by words ending in a real street
# suffix. Used as a secondary signal in field VALUES only (not free text, to
# avoid flagging prose).
_STREET_RE = re.compile(
    r"\b\d{1,6}\s+[A-Za-z0-9.\s]{2,40}\b"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|"
    r"Court|Ct|Place|Pl|Way|Circle|Cir|Terrace|Ter|Trail|Trl)\b",
    re.IGNORECASE,
)


def is_in_scope(rel_path: str) -> bool:
    parts = rel_path.split("/")
    if any(p in EXCLUDED_DIR_COMPONENTS for p in parts):
        return False
    if not rel_path.startswith(IN_SCOPE_PREFIXES):
        return False
    if not any(rel_path.endswith(s) for s in SCANNED_SUFFIXES):
        return False
    return True


# Institutional-party suffixes. A grantor/grantee/beneficiary/trustee whose
# value carries one of these is an organization (bank, lender, LLC, trust),
# NOT a natural person — recorded party names of institutions are public
# business identity, not person-level PII. Applied only to party fields.
_ENTITY_SUFFIX_RE = re.compile(
    r"\b(?:N\.?A\.?|BANK|TRUST|LLC|L\.L\.C\.|INC|CORP|CO|COMPANY|"
    r"LP|L\.P\.|LLP|PLLC|MORTGAGE|LENDING|FINANCIAL|FUNDING|"
    r"SERVICING|ASSOCIATION|FSB|N\.A|HOA|CITY OF|COUNTY OF|STATE OF|"
    r"DEPARTMENT|AUTHORITY|DISTRICT)\b",
    re.IGNORECASE,
)
_PARTY_FIELDS = {"grantor", "grantee", "beneficiary", "trustor", "trustee",
                 "plaintiff", "debtor", "defendant", "respondent", "borrower"}


def _is_synthetic(value: str) -> bool:
    """True if a field value is a recognized synthetic/placeholder marker.

    Two-tier matching to avoid substring false-NEGATIVES (a real name slipping
    through because it happens to contain marker letters):
      - _WHOLE_VALUE_RE: the ENTIRE value must be the marker (party codes,
        template brackets, field-name echoes). "GR" passes; "GREGORY" does not.
      - _ALLOW_RE: a clear synthetic token appearing anywhere (TEST_OWNER_001,
        DOE, 100 SYNTHETIC LN). These are distinctive enough to substring-match
        safely because they are anchored on word boundaries.
    """
    v = value.strip()
    if not v:
        return True
    if _WHOLE_VALUE_RE.match(v):
        return True
    return bool(_ALLOW_RE.search(v))


def scan_text(text: str, rel_path: str) -> list:
    violations = []
    lines = text.split("\n")

    # 1) High-confidence identifiers anywhere in the file.
    # Exception: operator identity in gate-signoff files is a deliberate audit
    # trail (who approved the gate), not third-party PII. Exempt email there.
    _is_signoff = bool(re.search(r"/gates/.*signoff\.json$", rel_path, re.IGNORECASE))
    for label, rx in HIGH_CONFIDENCE:
        for m in rx.finditer(text):
            if label == "email" and _EMAIL_ALLOW.search(m.group()):
                continue
            if label == "email" and _is_signoff:
                continue
            line_no = text[: m.start()].count("\n") + 1
            violations.append({
                "file": rel_path, "line": line_no, "kind": label,
                "match": m.group(),
                "context": lines[line_no - 1][:140] if line_no - 1 < len(lines) else "",
            })

    # 2) PII field values that are not synthetic.
    for m in _FIELD_RE.finditer(text):
        field, value = m.group(1), m.group(2)
        if _is_synthetic(value):
            continue
        # Institutional party names (banks, lenders, LLCs, gov bodies) on a
        # party field are public business identity, not person-level PII.
        if field.lower() in _PARTY_FIELDS and _ENTITY_SUFFIX_RE.search(value):
            continue
        line_no = text[: m.start()].count("\n") + 1
        violations.append({
            "file": rel_path, "line": line_no, "kind": f"pii_field:{field}",
            "match": f'{field} = {value!r}',
            "context": lines[line_no - 1][:140] if line_no - 1 < len(lines) else "",
        })

    return violations


def scan_files(paths) -> list:
    """Scan an iterable of (abs_path, rel_path) pairs. Returns violations."""
    all_v = []
    for abs_path, rel_path in paths:
        try:
            text = Path(abs_path).read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        all_v.extend(scan_text(text, rel_path))
    return all_v


def discover_repo_files(root: Path):
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        if is_in_scope(rel):
            yield (p, rel)


def run() -> bool:
    pairs = list(discover_repo_files(FRAMEWORK_ROOT))
    violations = scan_files(pairs)

    print("=" * 72)
    print("PII-IN-OPERATOR-CODE GUARD")
    print("=" * 72)
    print(f"Files scanned (operator surfaces): {len(pairs)}")
    print(f"Violations found: {len(violations)}")

    if violations:
        print()
        print("VIOLATIONS — real PII must never be committed. Replace with a")
        print("synthetic marker (TEST_OWNER_*, 100 SYNTHETIC LN, DOE JANE, ...).")
        print()
        for v in violations:
            print(f"  {v['file']}:{v['line']}  [{v['kind']}]")
            print(f"    match: {v['match']}")
            if v["context"]:
                print(f"    context: {v['context']!r}")
            print()
        print("=" * 72)
        print(f"RESULT: FAIL — {len(violations)} possible PII leak(s) in operator code")
        print("=" * 72)
        return False

    print()
    print("=" * 72)
    print("RESULT: PASS — no person-level PII found in operator-authored code")
    print("=" * 72)
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
