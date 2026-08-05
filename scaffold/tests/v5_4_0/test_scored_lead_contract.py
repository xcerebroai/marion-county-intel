#!/usr/bin/env python3
"""v5.4.0 Session 9 unit tests — the scored_lead contract.

Wired into run_all.py via scaffold/tests/v5_4_0/. Verifies the Session 9
scored_lead_record (Option Y seam):

  - the JSON Schema validates a representative ENRICHED scored_lead;
  - the JSON Schema validates a representative UNENRICHED scored_lead;
  - the schema rejects ENRICHED without parcel_display;
  - the schema rejects UNENRICHED with parcel_display non-null;
  - the schema rejects an invalid score tier;
  - the dataclass __post_init__ enforces the same enrichment/parcel_display
    consistency rule the schema enforces.

Run: python3 scaffold/tests/v5_4_0/test_scored_lead_contract.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator

from scaffold.pipeline.contracts import schema_path, ScoredLeadRecord, ParcelDisplay


def _base_record(**overrides) -> dict:
    """A minimal valid scored_lead record (UNENRICHED by default)."""
    rec = {
        "scored_lead_id": "scored_test_0001",
        "lead_id": "lead_parcel_P1",
        "primary_parcel_id": "P1",
        "owner_name": "DOE, MARGARET R",
        "owner_type": "INDIVIDUAL",
        "score": 70,
        "tier": "Strong",
        "score_reasons": [
            {"factor": "base_HOSPITAL_LIEN", "delta": 25},
            {"factor": "stack_depth_3", "delta": 24},
        ],
        "deal_paths": [
            {"path": "wholesale", "confidence": "moderate",
             "rationale": "Multi-signal stack."},
        ],
        "title_complexity_score": 0,
        "title_complexity_tier": "None",
        "title_complexity_contributors": [],
        "pattern_set": ["lien", "foreclosure"],
        "patterns": ["lien", "lien", "foreclosure"],
        "display_patterns": ["lien", "lien", "foreclosure"],
        "stack_depth": 3,
        "recent_flag": False,
        "attributes": [],
        "review_flags": [],
        "lead_status": "APPROVED_FOR_DASHBOARD",
        "enrichment_status": "UNENRICHED",
        "evidence_ids": ["ev1", "ev2"],
        "source_ids": ["clerk_recordings"],
    }
    rec.update(overrides)
    return rec


def _validate(record: dict) -> list:
    schema = json.loads(schema_path("scored_lead_record").read_text())
    validator = Draft202012Validator(schema)
    return list(validator.iter_errors(record))


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    # --- UNENRICHED — schema accepts ---------------------------------------
    record = _base_record()
    errors = _validate(record)
    check("UNENRICHED scored_lead (no parcel_display) validates", not errors)

    # --- ENRICHED + parcel_display — schema accepts ------------------------
    record = _base_record(
        enrichment_status="ENRICHED",
        attributes=["high_equity", "absentee"],
        parcel_display={
            "situs_address": "100 EXAMPLE WAY",
            "situs_city": "EXAMPLECITY",
            "situs_state": "ZZ",
            "owner_mailing_address": "999 OUT OF AREA",
            "owner_mailing_city": "ELSEWHERE",
            "owner_mailing_state": "ZZ",
            "owner_mailing_zip": "00000",
            "assessed_value": 200000.0,
            "last_sale_price": 80000.0,
            "last_sale_date": "2009-04-15",
            "year_built": 1975,
        },
    )
    errors = _validate(record)
    check("ENRICHED scored_lead with parcel_display validates", not errors)

    # --- ENRICHED without parcel_display — schema rejects (R3-iii rule) ----
    record = _base_record(enrichment_status="ENRICHED")
    errors = _validate(record)
    check("ENRICHED scored_lead WITHOUT parcel_display is rejected "
          "(R3-iii enrichment-optional rule)", bool(errors))

    # --- UNENRICHED with parcel_display non-null — schema rejects ----------
    record = _base_record(
        parcel_display={"situs_address": "100 EXAMPLE WAY"},
    )
    errors = _validate(record)
    check("UNENRICHED scored_lead WITH parcel_display non-null is rejected",
          bool(errors))

    # --- invalid tier — schema rejects -------------------------------------
    record = _base_record(tier="NotATier")
    errors = _validate(record)
    check("invalid score tier is rejected", bool(errors))

    # --- invalid lead_status — schema rejects ------------------------------
    record = _base_record(lead_status="RAW_RECORD")
    errors = _validate(record)
    check("a pre-scoring lead_status (RAW_RECORD) is rejected; only the "
          "post-scoring lifecycle subset is allowed", bool(errors))

    # --- dataclass __post_init__ enforces the same rule --------------------
    ok = True
    try:
        ScoredLeadRecord(
            scored_lead_id="x", lead_id="lead_x", primary_parcel_id="P1",
            owner_name="X", owner_type="INDIVIDUAL", score=70, tier="Strong",
            score_reasons=(), deal_paths=(), title_complexity_score=0,
            title_complexity_tier="None", title_complexity_contributors=(),
            pattern_set=("lien",), patterns=("lien",), display_patterns=("lien",),
            stack_depth=1, recent_flag=False, attributes=(),
            review_flags=(), lead_status="APPROVED_FOR_DASHBOARD",
            enrichment_status="UNENRICHED",
            evidence_ids=(), source_ids=("clerk",),
        )
    except Exception:  # noqa: BLE001
        ok = False
    check("dataclass: a consistent UNENRICHED record constructs", ok)

    ok = True
    try:
        ScoredLeadRecord(
            scored_lead_id="x", lead_id="lead_x", primary_parcel_id="P1",
            owner_name="X", owner_type="INDIVIDUAL", score=70, tier="Strong",
            score_reasons=(), deal_paths=(), title_complexity_score=0,
            title_complexity_tier="None", title_complexity_contributors=(),
            pattern_set=("lien",), patterns=("lien",), display_patterns=("lien",),
            stack_depth=1, recent_flag=False, attributes=("high_equity",),
            review_flags=(), lead_status="APPROVED_FOR_DASHBOARD",
            enrichment_status="ENRICHED",
            evidence_ids=(), source_ids=("clerk",),
            parcel_display=ParcelDisplay(situs_address="100 EXAMPLE WAY",
                                          assessed_value=200000.0),
        )
    except Exception:  # noqa: BLE001
        ok = False
    check("dataclass: a consistent ENRICHED record constructs", ok)

    raised = False
    try:
        ScoredLeadRecord(
            scored_lead_id="x", lead_id="lead_x", primary_parcel_id="P1",
            owner_name="X", owner_type="INDIVIDUAL", score=70, tier="Strong",
            score_reasons=(), deal_paths=(), title_complexity_score=0,
            title_complexity_tier="None", title_complexity_contributors=(),
            pattern_set=("lien",), patterns=("lien",), display_patterns=("lien",),
            stack_depth=1, recent_flag=False, attributes=(),
            review_flags=(), lead_status="APPROVED_FOR_DASHBOARD",
            enrichment_status="ENRICHED",
            evidence_ids=(), source_ids=("clerk",),
        )
    except ValueError:
        raised = True
    check("dataclass __post_init__ raises ValueError on ENRICHED without "
          "parcel_display (R3-iii enforcement)", raised)

    raised = False
    try:
        ScoredLeadRecord(
            scored_lead_id="x", lead_id="lead_x", primary_parcel_id="P1",
            owner_name="X", owner_type="INDIVIDUAL", score=70, tier="Strong",
            score_reasons=(), deal_paths=(), title_complexity_score=0,
            title_complexity_tier="None", title_complexity_contributors=(),
            pattern_set=("lien",), patterns=("lien",), display_patterns=("lien",),
            stack_depth=1, recent_flag=False, attributes=(),
            review_flags=(), lead_status="APPROVED_FOR_DASHBOARD",
            enrichment_status="UNENRICHED",
            evidence_ids=(), source_ids=("clerk",),
            parcel_display=ParcelDisplay(situs_address="X"),
        )
    except ValueError:
        raised = True
    check("dataclass __post_init__ raises ValueError on UNENRICHED with "
          "parcel_display non-null", raised)

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")
    if failed:
        print(f"FAIL: scored_lead contract — {len(failed)} of {len(checks)} "
              f"checks failed")
        return 1
    print(f"PASS: scored_lead contract (v5.4.0 Session 9) — all {len(checks)} "
          f"checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
