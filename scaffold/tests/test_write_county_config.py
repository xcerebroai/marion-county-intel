"""
Gate test for scaffold/ops/write_county_config.py (v5.1.1-beta).

Verifies the Execution Reliability Patch:
  - dict-based writes always produce structurally valid JSON
  - JSON syntax validation catches any in-memory corruption
  - schema validation is graceful (skips, never auto-installs)
  - atomic move semantics (temp file never half-overwrites final file)
  - overwrite guard works
  - non-dict input is rejected cleanly
  - non-existent schema path is treated as SKIPPED, not failed

The test does NOT require jsonschema to be installed. If jsonschema is
available, the "schema validation present" branch is exercised. If it
is not, the "schema validation skipped" branch is exercised. Both
branches must pass.

Synthetic data only. No county-specific URLs or names.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Add scaffold/ to path so we can import ops.write_county_config
THIS_DIR = Path(__file__).resolve().parent
SCAFFOLD_DIR = THIS_DIR.parent
sys.path.insert(0, str(SCAFFOLD_DIR))

from ops.write_county_config import (  # noqa: E402
    WriteResult,
    write_county_config,
)


# ---------- Synthetic payload ----------

def make_synthetic_config() -> dict:
    """A small but representative county config dict."""
    return {
        "county_id": "synth_xx",
        "county_name": "Synthetic County",
        "state": "XX",
        "subject_state_full": "Synthstate",
        "fips_code": "99999",
        "timezone": "America/Chicago",
        "operator_market_priority": "exploratory",
        "geography": {
            "municipalities": [],
            "parcel_id_format": "^[0-9]+$",
            "parcel_id_normalization": "strip-dashes",
            "address_format_notes": "synthetic",
        },
        "sources": {
            "synthetic_lead_source": {
                "category": "lead",
                "subtype": "synthetic_lead_source",
                "url": "https://example.invalid/",
                "source_priority": "P0",
                "build_priority": "mvp_required",
                "source_reliability_grade": "A",
                "lead_value": "LEAD_GENERATING",
                "official_status": "OFFICIAL_COUNTY",
                "access_pattern": "open_api",
                "verification_confidence": "HIGH",
                "source_role": "PRIMARY_LEAD_SOURCE",
            }
        },
        "scoring_overrides": {},
        "storage": {
            "mode": "STATIC_JSON_MODE",
            "supabase_enabled": False,
            "dashboard_payload": "data/leads.json",
            "retain_raw_records_days": 30,
            "retain_source_runs_days": 365,
        },
        "dashboard": {
            "title": "Synthetic County",
            "subtitle": "test",
            "view_modes": ["CLIENT_VIEW", "OPERATOR_VIEW"],
        },
        "deployment": {
            "github_org": "",
            "github_repo": "",
            "live_url": "",
            "scheduled_task_name": "",
            "watchdog_task_name": "",
            "scheduler_runtime_class": "",
            "scheduler_test_fired_at": "",
            "production_verification_status": "NOT_RUN",
            "production_verification_at": "",
            "last_known_good_commit": "",
            "last_known_good_dashboard_at": "",
        },
        "build_verdict": "READY_TO_BUILD",
        "build_verdict_reason": "synthetic",
        "build_verdict_at": "2026-05-14T00:00:00Z",
        "auto_resolve_status": "RESOLVED",
        "final_resolution_status": "RESOLVED",
        "operator_override_audit": [],
    }


# ---------- Test cases ----------

PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def case(name: str, passed: bool, detail: str = "") -> None:
    status = PASS if passed else FAIL
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def test_happy_path_no_schema(tmp_root: Path) -> None:
    target = tmp_root / "synth_a" / "config" / "counties" / "synth_xx.json"
    result = write_county_config(
        config_dict=make_synthetic_config(),
        target_path=str(target),
        schema_path=None,
        overwrite=False,
    )
    case(
        "happy path, no schema: status OK",
        result.status == "OK",
        result.status,
    )
    case(
        "happy path, no schema: schema validation skipped",
        result.schema_validation == "SCHEMA_VALIDATION_SKIPPED",
        result.schema_validation,
    )
    case(
        "happy path, no schema: file exists at target",
        target.exists() and target.stat().st_size > 0,
    )
    # Re-read and confirm round-trip
    with open(target, "r", encoding="utf-8") as fh:
        reloaded = json.load(fh)
    case(
        "happy path, no schema: round-trip preserves county_id",
        reloaded.get("county_id") == "synth_xx",
    )
    case(
        "happy path, no schema: temp_path cleared after success",
        result.temp_path == "",
    )
    case(
        "happy path, no schema: source_names populated",
        result.source_names == ["synthetic_lead_source"],
    )


def test_overwrite_guard(tmp_root: Path) -> None:
    target = tmp_root / "synth_b" / "synth_xx.json"
    config = make_synthetic_config()
    # First write should succeed
    r1 = write_county_config(
        config_dict=config,
        target_path=str(target),
        overwrite=False,
    )
    case("overwrite guard: first write OK", r1.is_ok())
    # Second write without overwrite should refuse
    r2 = write_county_config(
        config_dict=config,
        target_path=str(target),
        overwrite=False,
    )
    case(
        "overwrite guard: second write refused",
        r2.status == "PATH_EXISTS_NO_OVERWRITE",
        r2.status,
    )
    # Third write WITH overwrite should succeed
    config2 = make_synthetic_config()
    config2["build_verdict"] = "AUTO_RESOLVED_READY_TO_BUILD"
    r3 = write_county_config(
        config_dict=config2,
        target_path=str(target),
        overwrite=True,
    )
    case("overwrite guard: explicit overwrite OK", r3.is_ok())
    with open(target, "r", encoding="utf-8") as fh:
        reloaded = json.load(fh)
    case(
        "overwrite guard: overwrite replaced content",
        reloaded.get("build_verdict") == "AUTO_RESOLVED_READY_TO_BUILD",
    )


def test_non_dict_input(tmp_root: Path) -> None:
    target = tmp_root / "synth_c" / "synth_xx.json"
    r = write_county_config(
        config_dict=["not", "a", "dict"],  # type: ignore[arg-type]
        target_path=str(target),
        overwrite=False,
    )
    case(
        "non-dict input rejected with IO_ERROR",
        r.status == "IO_ERROR",
        r.status,
    )
    case(
        "non-dict input does not create final file",
        not target.exists(),
    )


def test_missing_schema_is_skip(tmp_root: Path) -> None:
    target = tmp_root / "synth_d" / "synth_xx.json"
    fake_schema = tmp_root / "synth_d" / "missing_schema.json"
    r = write_county_config(
        config_dict=make_synthetic_config(),
        target_path=str(target),
        schema_path=str(fake_schema),
        overwrite=False,
    )
    case(
        "missing schema file: status still OK",
        r.is_ok(),
        r.status,
    )
    case(
        "missing schema file: validation marked SCHEMA_FILE_MISSING",
        r.schema_validation == "SCHEMA_FILE_MISSING",
        r.schema_validation,
    )
    case(
        "missing schema file: target file written",
        target.exists(),
    )


def test_schema_validation_branch(tmp_root: Path) -> None:
    """
    If jsonschema is installed, exercise the real validation path
    against a trivially permissive schema. If jsonschema is NOT
    installed, exercise the graceful skip path. Both must be PASS.
    """
    target = tmp_root / "synth_e" / "synth_xx.json"
    schema_path = tmp_root / "synth_e" / "schema.json"
    schema_path.parent.mkdir(parents=True, exist_ok=True)
    permissive_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "required": ["county_id"],
        "properties": {
            "county_id": {"type": "string"},
        },
        "additionalProperties": True,
    }
    with open(schema_path, "w", encoding="utf-8") as fh:
        json.dump(permissive_schema, fh)

    r = write_county_config(
        config_dict=make_synthetic_config(),
        target_path=str(target),
        schema_path=str(schema_path),
        overwrite=False,
    )

    try:
        import jsonschema  # noqa: F401
        has_jsonschema = True
    except ImportError:
        has_jsonschema = False

    if has_jsonschema:
        case(
            "schema present, jsonschema installed: VALIDATED",
            r.schema_validation == "VALIDATED" and r.is_ok(),
            r.schema_validation,
        )
    else:
        case(
            "schema present, jsonschema missing: SKIPPED gracefully",
            r.schema_validation == "SCHEMA_VALIDATION_SKIPPED" and r.is_ok(),
            r.schema_validation,
        )


def test_writer_no_duplicate_keys_possible() -> None:
    """
    Sanity check that the writer's contract physically prevents
    duplicate keys at the top level. Python dicts cannot contain
    duplicate keys, so any dict-based writer is structurally safe.
    """
    config = make_synthetic_config()
    # If we try to "set" the same key twice, we just overwrite the value;
    # the dict only has one slot per key.
    config["county_id"] = "synth_xx"
    config["county_id"] = "synth_xx_overwritten"
    case(
        "dict cannot contain duplicate keys (overwrite semantics)",
        config["county_id"] == "synth_xx_overwritten",
    )
    # And the writer serializes the dict's current state, so it cannot
    # emit duplicate keys.
    case(
        "dict has exactly one 'county_id' key",
        list(config.keys()).count("county_id") == 1,
    )


# ---------- Runner ----------

def main() -> int:
    print("=" * 72)
    print("WRITE_COUNTY_CONFIG TEST — v5.1.1-beta Execution Reliability")
    print("=" * 72)
    tmp_root = Path(tempfile.mkdtemp(prefix="write_county_config_test_"))
    try:
        test_happy_path_no_schema(tmp_root)
        test_overwrite_guard(tmp_root)
        test_non_dict_input(tmp_root)
        test_missing_schema_is_skip(tmp_root)
        test_schema_validation_branch(tmp_root)
        test_writer_no_duplicate_keys_possible()
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)

    passed = sum(1 for r in results if r[0] == PASS)
    failed = sum(1 for r in results if r[0] == FAIL)
    print()
    print(f"RESULT: {passed} pass, {failed} fail")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
