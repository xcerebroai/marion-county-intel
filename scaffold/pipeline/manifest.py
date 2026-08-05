"""
Run manifest + source heartbeat builders.

Per architecture/09_output_schemas.md §11 and §10 respectively.
Heartbeat is emitted as one record per source declared in the
county config; for the synthetic harness, one synthetic source
record is emitted per signal source label.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_run_manifest(
    *,
    county: str,
    state: str,
    started_at: str,
    sources_attempted: int,
    records_collected: int,
    records_normalized: int,
    leads_created: int,
    review_required: int,
    output_files: list,
    errors: list | None = None,
) -> dict:
    return {
        "run_id": "run_" + uuid.uuid4().hex,
        "county": county,
        "state": state,
        "started_at": started_at,
        "finished_at": _now(),
        "sources_attempted": sources_attempted,
        "records_collected": records_collected,
        "records_normalized": records_normalized,
        "leads_created": leads_created,
        "review_required": review_required,
        "errors": errors or [],
        "output_files": output_files,
    }


def build_heartbeat(
    *,
    source_id: str,
    source_name: str,
    source_class: str,
    source_priority: str,
    source_reliability_grade: str,
    build_priority: str,
    access_pattern: str,
    records_seen: int,
    records_new: int,
    parser_confidence_avg: int = 100,
    status: str = "healthy",
    strategy: str = "synthetic_jsonl_fixture",
    strategy_reason: str = "Phase 1 synthetic harness",
) -> dict:
    now = _now()
    return {
        "source_id": source_id,
        "source_name": source_name,
        "source_class": source_class,
        "source_priority": source_priority,
        "source_reliability_grade": source_reliability_grade,
        "build_priority": build_priority,
        "access_pattern": access_pattern,
        "status": status,
        "last_attempted_at": now,
        "last_successful_at": now if status == "healthy" else None,
        "last_failed_at": None,
        "last_failure_reason": None,
        "records_seen_current_run": records_seen,
        "records_new_current_run": records_new,
        "records_seen_previous_run": 0,
        "records_new_previous_run": 0,
        "parser_confidence_avg": parser_confidence_avg,
        "error_count_current_run": 0,
        "consecutive_failures": 0,
        "session_status": "not_applicable",
        "session_expires_at": None,
        "next_retry_at": None,
        "next_scheduled_run_at": None,
        "access_attempts": [
            {
                "attempt_order": 1,
                "strategy": strategy,
                "status": "SUCCESS",
                "reason": strategy_reason,
                "timestamp": now,
            }
        ],
        "final_access_strategy": strategy,
        "records_request_allowed": False,
    }
