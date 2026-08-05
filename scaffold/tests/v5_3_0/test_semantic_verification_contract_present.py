#!/usr/bin/env python3
"""v5.3.0 Gap 4 invariant — §20 Semantic Verification Contract and its reference
implementation template must be present and complete.

Run: python3 scaffold/tests/v5_3_0/test_semantic_verification_contract_present.py
Exit 0 = pass, non-zero = fail.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "knowledge_base" / "architecture" / "20_semantic_verification_contract.md"
TEMPLATE = ROOT / "scaffold" / "ops" / "semantic_verify_template.py"


def _norm(text: str) -> str:
    """Lowercase and drop backticks for tolerant phrase checks."""
    return text.replace("`", "").lower()


# The 12 universal check classes — a distinctive phrase per §20.C check.
CHECK_PHRASES = [
    "debtor attribution",
    "owner type classification",
    "parcel-resolution plausibility",
    "enrichment status decoupling",
    "signal aggregation integrity",
    "cross-source aggregation",
    "ocr confidence routing",
    "csv output schema",
    "source proof link",
    "dashboard row integrity",
    "methodology consistency",
    "universal filer patterns",
]


def check_doc(failures: list) -> None:
    if not DOC.is_file():
        failures.append(f"§20 not found at {DOC}")
        return
    norm = _norm(DOC.read_text(encoding="utf-8"))

    for phrase in ("mechanical verification", "semantic verification"):
        if phrase not in norm:
            failures.append(f"§20 missing phrase: {phrase!r}")

    for phrase in CHECK_PHRASES:
        if phrase not in norm:
            failures.append(f"§20 missing check class phrase: {phrase!r}")

    for token in ("VALID", "INVALID", "AMBIGUOUS"):
        if token.lower() not in norm:
            failures.append(f"§20 missing three-state outcome value: {token}")

    for token in ("DEPLOY_OK", "DEPLOY_BLOCKED", "NEEDS_OPERATOR_REVIEW"):
        if token.lower() not in norm:
            failures.append(f"§20 missing deploy verdict: {token}")

    if "scaffold/ops/semantic_verify_template.py" not in norm:
        failures.append("§20 does not reference scaffold/ops/semantic_verify_template.py")

    if not ("documentation-grade" in norm or "not a production" in norm):
        failures.append("§20 does not state the template is documentation-grade / "
                        "not a production tool")


def _is_notimplemented_stub(fn: ast.FunctionDef) -> bool:
    """True if the function body is essentially a single raise NotImplementedError."""
    stmts = [s for s in fn.body if not isinstance(s, ast.Expr)
             or not isinstance(getattr(s, "value", None), ast.Constant)]
    # The body, ignoring a leading docstring, must be exactly one raise.
    if len(stmts) != 1 or not isinstance(stmts[0], ast.Raise):
        return False
    exc = stmts[0].exc
    if isinstance(exc, ast.Call) and isinstance(exc.func, ast.Name):
        return exc.func.id == "NotImplementedError"
    if isinstance(exc, ast.Name):
        return exc.id == "NotImplementedError"
    return False


def check_template(failures: list) -> None:
    if not TEMPLATE.is_file():
        failures.append(f"template not found at {TEMPLATE}")
        return
    src = TEMPLATE.read_text(encoding="utf-8")
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        failures.append(f"template does not parse as Python: {exc}")
        return

    norm = _norm(src)
    for enum_name, members in (
        ("class CheckOutcome", ("VALID", "INVALID", "AMBIGUOUS")),
        ("class DeployVerdict",
         ("DEPLOY_OK", "DEPLOY_BLOCKED", "NEEDS_OPERATOR_REVIEW")),
    ):
        if enum_name.lower() not in norm:
            failures.append(f"template missing enum: {enum_name}")
        for m in members:
            if m.lower() not in norm:
                failures.append(f"template missing enum member: {m}")

    funcs = {n.name: n for n in ast.walk(tree)
             if isinstance(n, ast.FunctionDef)}
    for i in range(1, 13):
        prefix = f"check_{i:02d}"
        match = [name for name in funcs if name.startswith(prefix)]
        if not match:
            failures.append(f"template missing check function: {prefix}*")
            continue
        fn = funcs[match[0]]
        stub = _is_notimplemented_stub(fn)
        if i == 12:
            if stub:
                failures.append("template check_12 must have a real implementation, "
                                "not a NotImplementedError stub")
        else:
            if not stub:
                failures.append(f"template {match[0]} should be a "
                                "NotImplementedError stub (specialize per county)")


def main() -> int:
    failures: list = []
    check_doc(failures)
    check_template(failures)

    if failures:
        print("FAIL: Gap 4 — §20 Semantic Verification Contract invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: Gap 4 — §20 Semantic Verification Contract and template present "
          "and complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
