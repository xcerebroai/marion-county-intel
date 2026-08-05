#!/usr/bin/env python3
"""v5.4.0 Session 9 end-to-end proof — staged §17→§18→§19→§20 + seam + scoring.

Wired into run_all.py via scaffold/tests/v5_4_0/. This test runs the COMPLETE
staged pipeline AND the seam AND the retained scoring stage end-to-end on
synthetic data, in order:

  raw events
    → §17 debtor party engine        (resolve_debtor_party)
    → §18 leads-base writer          (build_base_record / write_leads_base)
    → §19 idempotent aggregator      (aggregate → matched_leads.json)
    → §20 semantic verification      (run_semantic_verification → DEPLOY_OK)
    → SEAM                           (scoring_seam.score_matched_leads)
    → scored_lead records             (scored_leads.json)
    → dashboard projection            (run_pipeline_staged.build_dashboard_payload)

It validates that the SAME synthetic dataset that powers the Session-5
staged-pipeline end-to-end test (the §17→§20 proof) flows the rest of the
way through the seam and scoring, and that the resulting scored_leads carry
sensible scores / tiers / deal_paths. The R3(iii) enrichment-optional rule
is exercised twice: once UNENRICHED (no enrichment_provider supplied), once
ENRICHED (a provider supplies parcel-master attributes for one parcel).
Both runs MUST produce schema-valid scored_leads — a lead is never dropped
for missing enrichment.

Run: python3 scaffold/tests/v5_4_0/test_staged_with_scoring_end_to_end.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator

from scaffold.pipeline import run_pipeline_staged
from scaffold.pipeline.contracts import schema_path

SIGNAL_TYPE_LABELS = {
    "hospital_lien": "Hospital Lien",
    "foreclosure_notice": "Foreclosure Notice",
    "executors_deed": "Estate-Titled Property",
}


def _raw_event(*, raw_event_id, canonical_doc_type, parcel_id, instrument,
               recorded_date, evidence_id, parties=None,
               document_body_text=None):
    return {
        "raw_event_id": raw_event_id,
        "source_id": "clerk_recordings",
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": canonical_doc_type,
        "raw_doc_type": canonical_doc_type.upper(),
        "instrument_number": instrument,
        "recorded_date": recorded_date,
        "event_date": None,
        "source_url": f"https://example.test/clerk/{instrument}",
        "parties": parties or [],
        "document_body_text": document_body_text,
        "property_refs": {
            "parcel_id": parcel_id,
            "situs_address": "100 EXAMPLE WAY",
            "legal_description": None,
            "case_number": None,
        },
        "amounts": [],
        "evidence_ids": [evidence_id],
        "parser_name": "session9_end_to_end",
        "parser_version": "1.0.0",
        "parser_confidence": 95,
        "captured_at": "2026-05-08T12:00:00Z",
    }


def _evidence_entry(evidence_id, record_id):
    return {
        "evidence_id": evidence_id,
        "record_id": record_id,
        "field": "owner_name",
        "value": "synthetic",
        "status": "Confirmed",
        "source_id": "clerk_recordings",
        "source_reliability_grade": "A",
        "source_url": f"https://example.test/clerk/{record_id}",
        "captured_at": "2026-05-08T12:00:00Z",
    }


def _party(name, name_type):
    return {"name": name, "name_type": name_type, "raw_role": name_type}


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    # Same fixture as the Session-5 staged end-to-end test — three signals on
    # PARCEL-100 (two stacked hospital_liens + one foreclosure_notice via
    # document-body extraction), one executors_deed on PARCEL-200.
    raw_events = [
        _raw_event(raw_event_id="raw_hl_1", canonical_doc_type="hospital_lien",
                   parcel_id="PARCEL-100", instrument="I-HL-1",
                   recorded_date="2026-05-01", evidence_id="ev-hl-1",
                   parties=[_party("MARGARET DOE", "TP")]),
        _raw_event(raw_event_id="raw_hl_2", canonical_doc_type="hospital_lien",
                   parcel_id="PARCEL-100", instrument="I-HL-2",
                   recorded_date="2026-05-05", evidence_id="ev-hl-2",
                   parties=[_party("MARGARET DOE", "TP")]),
        _raw_event(raw_event_id="raw_fn_1",
                   canonical_doc_type="foreclosure_notice",
                   parcel_id="PARCEL-100", instrument="I-FN-1",
                   recorded_date="2026-05-12", evidence_id="ev-fn-1",
                   document_body_text="NOTICE OF FORECLOSURE SALE\n"
                                      "MORTGAGOR: MARGARET DOE\n"),
        _raw_event(raw_event_id="raw_ed_1", canonical_doc_type="executors_deed",
                   parcel_id="PARCEL-200", instrument="I-ED-1",
                   recorded_date="2026-05-09", evidence_id="ev-ed-1",
                   parties=[_party("ESTATE OF HAROLD DOE", "GR")]),
    ]
    evidence_entries = [
        _evidence_entry(r["evidence_ids"][0], r["raw_event_id"])
        for r in raw_events
    ]

    scored_lead_validator = Draft202012Validator(
        json.loads(schema_path("scored_lead_record").read_text())
    )

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)

        # --- Run A — UNENRICHED (no enrichment_provider) -------------------
        result_unen = run_pipeline_staged.run_staged_pipeline(
            raw_events,
            evidence_entries=evidence_entries,
            signal_type_labels=SIGNAL_TYPE_LABELS,
            workdir=workdir / "runA",
            as_of=date(2026, 5, 14),
        )
        check("end-to-end (UNENRICHED): §20 verdict DEPLOY_OK",
              result_unen["semantic_verdict"] == "DEPLOY_OK")
        check("end-to-end (UNENRICHED): two matched_leads produced "
              "(PARCEL-100, PARCEL-200)",
              len(result_unen["matched_leads"]) == 2)
        check("end-to-end (UNENRICHED): matched_leads.json + "
              "evidence_ledger.json + scored_leads.json all on disk",
              result_unen["matched_leads_path"].exists()
              and result_unen["evidence_ledger_path"].exists()
              and result_unen["scored_leads_path"].exists())
        check("end-to-end (UNENRICHED): every scored_lead validates against "
              "scored_lead_record.schema.json",
              all(not list(scored_lead_validator.iter_errors(s))
                  for s in result_unen["scored_leads"]))
        check("end-to-end (UNENRICHED): every scored_lead is UNENRICHED with "
              "parcel_display None (R3-iii — scoring runs without enrichment)",
              all(s["enrichment_status"] == "UNENRICHED"
                  and s["parcel_display"] is None
                  for s in result_unen["scored_leads"]))

        by_parcel_un = {
            s["primary_parcel_id"]: s for s in result_unen["scored_leads"]
        }
        p100_un = by_parcel_un.get("PARCEL-100")
        p200_un = by_parcel_un.get("PARCEL-200")
        check("end-to-end (UNENRICHED): PARCEL-100 has stack_depth >= 3 and "
              "pattern_set covers {lien, foreclosure} (the seam's §18.E "
              "count fan-out + broad-key bridge)",
              p100_un is not None
              and p100_un["stack_depth"] >= 3
              and {"lien", "foreclosure"} <= set(p100_un["pattern_set"]))
        check("end-to-end (UNENRICHED): PARCEL-100 scores Hot or Strong "
              "(multi-pattern distress stack + recency bonus)",
              p100_un is not None and p100_un["tier"] in ("Hot", "Strong"))
        check("end-to-end (UNENRICHED): PARCEL-200 is the estate, "
              "owner_type ESTATE, pattern_set {estate}",
              p200_un is not None
              and p200_un["owner_name"] == "ESTATE OF HAROLD DOE"
              and p200_un["owner_type"] == "ESTATE"
              and p200_un["pattern_set"] == ["estate"])
        check("end-to-end (UNENRICHED): both scored leads reach "
              "APPROVED_FOR_DASHBOARD (no missing-enrichment hold)",
              all(s["lead_status"] == "APPROVED_FOR_DASHBOARD"
                  for s in result_unen["scored_leads"]))

        # Dashboard projection from scored leads.
        payload_un = run_pipeline_staged.build_dashboard_payload(
            result_unen["scored_leads"],
            semantic_verdict=result_unen["semantic_verdict"],
        )
        check("end-to-end (UNENRICHED): dashboard payload lead_total == 2",
              payload_un["lead_total"] == 2)
        check("end-to-end (UNENRICHED): dashboard payload "
              "enrichment_breakdown shows both UNENRICHED",
              payload_un["enrichment_breakdown"]["UNENRICHED"] == 2
              and payload_un["enrichment_breakdown"]["ENRICHED"] == 0)
        check("end-to-end (UNENRICHED): dashboard records re-derive matching "
              "pattern_counts and score_tier_distribution",
              sum(payload_un["pattern_counts"].values()) >= 4
              and sum(payload_un["score_tier_distribution"].values()) == 2)

        # --- Run B — ENRICHED for PARCEL-100, UNENRICHED for PARCEL-200 ----
        def enrichment_provider(parcel_id):
            if parcel_id == "PARCEL-100":
                return {
                    "parcel_id": "PARCEL-100",
                    "situs_address": "100 EXAMPLE WAY",
                    "situs_city": "EXAMPLECITY",
                    "situs_state": "ZZ",
                    "owner_name": "MARGARET DOE",
                    "owner_mailing_address": "999 OUT OF AREA",
                    "owner_mailing_city": "ELSEWHERE",
                    "owner_mailing_state": "ZZ",
                    "owner_mailing_zip": "00000",
                    "assessed_value": 200000,
                    "last_sale_price": 80000,
                    "last_sale_date": "2009-04-15",
                    "year_built": 1975,
                }
            return None  # PARCEL-200 has no enrichment row

        result_en = run_pipeline_staged.run_staged_pipeline(
            raw_events,
            evidence_entries=evidence_entries,
            signal_type_labels=SIGNAL_TYPE_LABELS,
            workdir=workdir / "runB",
            as_of=date(2026, 5, 14),
            enrichment_provider=enrichment_provider,
        )
        check("end-to-end (mixed): every scored_lead still validates "
              "against the schema",
              all(not list(scored_lead_validator.iter_errors(s))
                  for s in result_en["scored_leads"]))

        by_parcel_en = {
            s["primary_parcel_id"]: s for s in result_en["scored_leads"]
        }
        p100_en = by_parcel_en.get("PARCEL-100")
        p200_en = by_parcel_en.get("PARCEL-200")
        check("end-to-end (mixed): PARCEL-100 is ENRICHED with "
              "parcel_display populated",
              p100_en is not None
              and p100_en["enrichment_status"] == "ENRICHED"
              and p100_en["parcel_display"]
              and p100_en["parcel_display"]["situs_address"]
                  == "100 EXAMPLE WAY")
        check("end-to-end (mixed): PARCEL-200 falls through to UNENRICHED "
              "(provider returned None) but is still scored, still reaches "
              "APPROVED_FOR_DASHBOARD (R3-iii)",
              p200_en is not None
              and p200_en["enrichment_status"] == "UNENRICHED"
              and p200_en["lead_status"] == "APPROVED_FOR_DASHBOARD")
        check("end-to-end (mixed): ENRICHED scored_lead's attribute list is "
              "non-empty (long_term_owned + out-of-state mailing → absentee)",
              p100_en is not None and len(p100_en["attributes"]) >= 1)
        check("end-to-end (mixed): ENRICHED PARCEL-100 score >= UNENRICHED "
              "PARCEL-100 score (attribute bonus is non-negative)",
              p100_en["score"] >= p100_un["score"])

        payload_mixed = run_pipeline_staged.build_dashboard_payload(
            result_en["scored_leads"],
            semantic_verdict=result_en["semantic_verdict"],
        )
        check("end-to-end (mixed): dashboard enrichment_breakdown reflects "
              "1 ENRICHED + 1 UNENRICHED",
              payload_mixed["enrichment_breakdown"]["ENRICHED"] == 1
              and payload_mixed["enrichment_breakdown"]["UNENRICHED"] == 1)

        # --- Re-run idempotency — scored_leads identical across two runs --
        result_en2 = run_pipeline_staged.run_staged_pipeline(
            raw_events,
            evidence_entries=evidence_entries,
            signal_type_labels=SIGNAL_TYPE_LABELS,
            workdir=workdir / "runB2",
            as_of=date(2026, 5, 14),
            enrichment_provider=enrichment_provider,
        )
        check("end-to-end (idempotency): a second staged-pipeline run with "
              "the same inputs produces an identical scored_leads list "
              "(deterministic seam)",
              json.dumps(result_en["scored_leads"], sort_keys=True)
              == json.dumps(result_en2["scored_leads"], sort_keys=True))

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")
    if failed:
        print(f"FAIL: staged+scoring end-to-end — {len(failed)} of "
              f"{len(checks)} checks failed")
        return 1
    print(f"PASS: staged+scoring end-to-end (v5.4.0 Session 9) — all "
          f"{len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
