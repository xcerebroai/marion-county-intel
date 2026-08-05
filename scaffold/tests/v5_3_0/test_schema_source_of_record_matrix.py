#!/usr/bin/env python3
"""v5.3.0 schema invariant — config/counties/_schema.json must define the
Source-of-Record-Matrix top-level properties, $defs, and enums.

Run: python3 scaffold/tests/v5_3_0/test_schema_source_of_record_matrix.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
from pathlib import Path

SCHEMA = (Path(__file__).resolve().parents[3]
          / "config" / "counties" / "_schema.json")

REQUIRED_TOP_PROPS = [
    "source_of_record_matrix", "source_coverage_map", "api_discovery",
    "enrichment_index_strategy",
]
REQUIRED_DEFS = [
    "sourceOfRecordMatrix", "candidateSource", "leadTypeEntry",
    "sourceCoverageMap", "apiDiscoveryReport", "enrichmentIndexStrategy",
]
STATUS_ENUM = [
    "LIVE_SOURCE_FOUND", "LIVE_SOURCE_FOUND_LIMITED_COVERAGE",
    "SOURCE_FOUND_BLOCKED", "SOURCE_FOUND_NEEDS_LOGIN", "SOURCE_FOUND_PAID",
    "SOURCE_FOUND_CAPTCHA", "SOURCE_NOT_FOUND", "NOT_APPLICABLE_IN_STATE",
    "NEEDS_OPERATOR_REVIEW", "ENRICHMENT_ONLY",
]
SOURCE_ROLE_ENUM = [
    "PRIMARY_EVENT_SOURCE", "SUPPORTING_EVENT_SOURCE", "ENRICHMENT_SOURCE",
    "REFERENCE_SOURCE", "BLOCKED_SOURCE",
]
ACCESS_STATUS_ENUM = [
    "OPEN_PUBLIC", "SEARCH_ONLY_PUBLIC", "FREE_ACCOUNT_REQUIRED",
    "PAID_SUBSCRIPTION_REQUIRED", "LOGIN_REQUIRED", "CAPTCHA_PROTECTED",
    "DOCUMENT_IMAGES_LOCKED", "BLOCKED", "UNKNOWN",
]
BULK_AVAILABILITY_ENUM = ["FULL_COUNTY_BULK", "BATCH_QUERY", "PER_RECORD_ONLY",
                          "UNKNOWN"]


def _enum_at(defs, def_name, prop_name):
    """Return the enum list for defs[def_name].properties[prop_name], or []."""
    return (defs.get(def_name, {})
            .get("properties", {})
            .get(prop_name, {})
            .get("enum", []))


def main() -> int:
    if not SCHEMA.is_file():
        print(f"FAIL: schema not found at {SCHEMA}")
        return 1
    try:
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"FAIL: _schema.json is not valid JSON — {exc}")
        return 1

    failures = []

    props = schema.get("properties", {})
    for p in REQUIRED_TOP_PROPS:
        if p not in props:
            failures.append(f"top-level property missing: {p}")

    defs = schema.get("$defs", {})
    for d in REQUIRED_DEFS:
        if d not in defs:
            failures.append(f"$defs missing: {d}")

    status = _enum_at(defs, "leadTypeEntry", "status")
    for v in STATUS_ENUM:
        if v not in status:
            failures.append(f"leadTypeEntry.status enum missing: {v}")

    role = _enum_at(defs, "candidateSource", "source_role")
    for v in SOURCE_ROLE_ENUM:
        if v not in role:
            failures.append(f"candidateSource.source_role enum missing: {v}")

    access = _enum_at(defs, "candidateSource", "access_status")
    for v in ACCESS_STATUS_ENUM:
        if v not in access:
            failures.append(f"candidateSource.access_status enum missing: {v}")

    bulk = _enum_at(defs, "candidateSource", "bulk_availability")
    for v in BULK_AVAILABILITY_ENUM:
        if v not in bulk:
            failures.append(f"candidateSource.bulk_availability enum missing: {v}")

    if failures:
        print("FAIL: schema source-of-record-matrix invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: schema defines source_of_record_matrix, $defs, and all enums")
    print(f"  top-level properties: {REQUIRED_TOP_PROPS}")
    print(f"  $defs: {REQUIRED_DEFS}")
    print(f"  status enum: {len(STATUS_ENUM)} values  "
          f"source_role: {len(SOURCE_ROLE_ENUM)}  "
          f"access_status: {len(ACCESS_STATUS_ENUM)}  "
          f"bulk_availability: {len(BULK_AVAILABILITY_ENUM)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
