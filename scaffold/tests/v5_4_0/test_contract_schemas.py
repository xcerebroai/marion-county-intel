#!/usr/bin/env python3
"""v5.4.0 Group A (green) — contract JSON Schemas are present and are
themselves valid schema documents.

This is a SHAPE / SCAFFOLDING test, not a behavioral test. It asserts only
that the inter-stage contract schemas exist under
scaffold/pipeline/contracts/ and each is a well-formed JSON Schema
(Draft 2020-12). It does NOT validate any pipeline data against them — that
is the engine's job.

v5.4.0 Session 9 extension: scored_lead_record.schema.json is added — the
seam stage's output contract (Option Y).

This test is wired into scaffold/tests/run_all.py and must stay green.

Run: python3 scaffold/tests/v5_4_0/test_contract_schemas.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

CONTRACTS_DIR = REPO_ROOT / "scaffold" / "pipeline" / "contracts"

# The inter-stage contracts the v5.4.0 staged engine is built against:
# the five Session-1 contracts (Sessions 2-5 built engines against them)
# plus the Session-9 scored_lead_record (Option Y — the seam's output).
EXPECTED_SCHEMAS = [
    "raw_event_record.schema.json",
    "debtor_resolved_record.schema.json",
    "leads_base_record.schema.json",
    "matched_lead_record.schema.json",
    "scored_lead_record.schema.json",
    "evidence_ledger_entry.schema.json",
]

REQUIRED_TOP_KEYS = ("$schema", "$id", "title", "type")


def main() -> int:
    failures = []

    try:
        from jsonschema import Draft202012Validator
    except ImportError as exc:
        print(f"FAIL: jsonschema is not importable — {exc}")
        return 1

    if not CONTRACTS_DIR.is_dir():
        print(f"FAIL: contracts directory missing — {CONTRACTS_DIR}")
        return 1

    for name in EXPECTED_SCHEMAS:
        path = CONTRACTS_DIR / name
        if not path.is_file():
            failures.append(f"missing contract schema file: {name}")
            continue

        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{name}: not valid JSON — {exc}")
            continue

        if not isinstance(schema, dict):
            failures.append(f"{name}: top level is not a JSON object")
            continue

        for key in REQUIRED_TOP_KEYS:
            if key not in schema:
                failures.append(f"{name}: missing top-level key {key!r}")

        # The load-bearing assertion: the file is itself a valid JSON Schema.
        try:
            Draft202012Validator.check_schema(schema)
        except Exception as exc:  # jsonschema.exceptions.SchemaError
            failures.append(f"{name}: not a valid Draft 2020-12 schema — {exc}")

    # The contracts package must agree with what is on disk.
    try:
        from scaffold.pipeline.contracts import CONTRACT_SCHEMA_FILES, schema_path
    except Exception as exc:
        failures.append(f"scaffold.pipeline.contracts is not importable — {exc}")
        CONTRACT_SCHEMA_FILES = {}
        schema_path = None

    registered = sorted(CONTRACT_SCHEMA_FILES.values())
    if registered != sorted(EXPECTED_SCHEMAS):
        failures.append(
            f"CONTRACT_SCHEMA_FILES {registered} != expected "
            f"{sorted(EXPECTED_SCHEMAS)}"
        )

    if schema_path is not None:
        for contract_name, filename in CONTRACT_SCHEMA_FILES.items():
            resolved = schema_path(contract_name)
            if not resolved.is_file():
                failures.append(
                    f"schema_path({contract_name!r}) -> {resolved} does not exist"
                )

    if failures:
        print("FAIL: v5.4.0 contract-schema shape test")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: v5.4.0 contract schemas present and valid")
    print(f"  {len(EXPECTED_SCHEMAS)} schemas under "
          f"scaffold/pipeline/contracts/, all valid Draft 2020-12 documents:")
    for name in EXPECTED_SCHEMAS:
        print(f"    - {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
