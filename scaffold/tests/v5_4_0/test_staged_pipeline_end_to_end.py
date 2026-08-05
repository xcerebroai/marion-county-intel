#!/usr/bin/env python3
"""v5.4.0 end-to-end proof — the staged pipeline §17 → §18 → §19 → §20.

Added in v5.4.0 Session 5 (STEP 3). Wired into run_all.py via
scaffold/tests/v5_4_0/. This test runs the COMPLETE staged pipeline on
synthetic data, in order:

  raw events
    → §17 debtor party engine        (resolve_debtor_party)
    → §18 leads-base writer          (build_base_record / write_leads_base)
    → §19 idempotent aggregator      (aggregate → matched_leads.json)
    → §20 semantic verification      (run_semantic_verification)

and wires the evidence ledger through, confirming every matched-lead claim
traces to an evidence entry. It proves the staged engine produces correct
matched leads end-to-end and that §20 returns a deploy verdict — the gate the
Session 6 monolith cutover depends on.

Run: python3 scaffold/tests/v5_4_0/test_staged_pipeline_end_to_end.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.pipeline import aggregator
from scaffold.pipeline import debtor_party_engine
from scaffold.pipeline import evidence_ledger as evidence_ledger_mod
from scaffold.pipeline import leads_base_writer
from scaffold.pipeline import semantic_verify

SIGNAL_TYPE_LABELS = {
    "hospital_lien": "Hospital Lien",
    "foreclosure_notice": "Foreclosure Notice",
    "executors_deed": "Estate-Titled Property",
}


def _raw_event(*, raw_event_id, canonical_doc_type, parcel_id, instrument,
               recorded_date, evidence_id, parties=None,
               document_body_text=None):
    """A synthetic raw_event_record — the staged pipeline's stage-1 input."""
    return {
        "raw_event_id": raw_event_id,
        "source_id": "clerk_recordings",
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": canonical_doc_type,
        "raw_doc_type": canonical_doc_type.upper(),
        "instrument_number": instrument,
        "recorded_date": recorded_date,
        "event_date": None,
        "source_url": f"https://example.test/clerk_recordings/{instrument}",
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
        "parser_name": "end_to_end_test",
        "parser_version": "1.0.0",
        "parser_confidence": 95,
        "captured_at": "2026-03-20T12:00:00Z",
    }


def _evidence_entry(evidence_id, record_id):
    """A synthetic evidence_ledger_entry backing one raw event."""
    return {
        "evidence_id": evidence_id,
        "record_id": record_id,
        "field": "owner_name",
        "value": "synthetic",
        "status": "Confirmed",
        "source_id": "clerk_recordings",
        "source_reliability_grade": "A",
        "source_url": f"https://example.test/clerk_recordings/{record_id}",
        "captured_at": "2026-03-20T12:00:00Z",
    }


def _party(name, name_type):
    return {"name": name, "name_type": name_type, "raw_role": name_type}


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    # Synthetic raw events: PARCEL-100 carries two stacked hospital liens and a
    # foreclosure notice; PARCEL-200 carries an executor's deed.
    raw_events = [
        _raw_event(raw_event_id="raw_hl_1", canonical_doc_type="hospital_lien",
                   parcel_id="PARCEL-100", instrument="I-HL-1",
                   recorded_date="2026-01-05", evidence_id="ev-hl-1",
                   parties=[_party("MARGARET DOE", "TP")]),
        _raw_event(raw_event_id="raw_hl_2", canonical_doc_type="hospital_lien",
                   parcel_id="PARCEL-100", instrument="I-HL-2",
                   recorded_date="2026-02-09", evidence_id="ev-hl-2",
                   parties=[_party("MARGARET DOE", "TP")]),
        _raw_event(raw_event_id="raw_fn_1",
                   canonical_doc_type="foreclosure_notice",
                   parcel_id="PARCEL-100", instrument="I-FN-1",
                   recorded_date="2026-03-01", evidence_id="ev-fn-1",
                   document_body_text="NOTICE OF FORECLOSURE SALE\n"
                                      "MORTGAGOR: MARGARET DOE\n"),
        _raw_event(raw_event_id="raw_ed_1", canonical_doc_type="executors_deed",
                   parcel_id="PARCEL-200", instrument="I-ED-1",
                   recorded_date="2026-02-20", evidence_id="ev-ed-1",
                   parties=[_party("ESTATE OF HAROLD DOE", "GR")]),
    ]
    evidence_entries = [
        _evidence_entry(rev["evidence_ids"][0], rev["raw_event_id"])
        for rev in raw_events
    ]

    # --- §17 — debtor party engine -----------------------------------------
    debtor_resolved = [
        debtor_party_engine.resolve_debtor_party(rev) for rev in raw_events
    ]
    check("§17: all four raw events resolve to RESOLVED debtor records",
          all(d["debtor_resolution_status"] == "RESOLVED"
              for d in debtor_resolved))
    owners = {d["raw_event_id"]: d["owner_name"] for d in debtor_resolved}
    check("§17: hospital-lien debtor is the taxpayer MARGARET DOE",
          owners["raw_hl_1"] == "MARGARET DOE")
    check("§17: foreclosure-notice debtor extracted from the document body "
          "is the mortgagor, not a filer",
          owners["raw_fn_1"] == "MARGARET DOE")
    check("§17: executor-deed debtor is the estate",
          owners["raw_ed_1"] == "ESTATE OF HAROLD DOE")

    # --- §18 — evidence ledger + leads-base writer --------------------------
    ledger = evidence_ledger_mod.build_evidence_ledger(evidence_entries)
    base_records = [
        leads_base_writer.build_base_record(
            drr, signal_type_labels=SIGNAL_TYPE_LABELS, evidence_ledger=ledger)
        for drr in debtor_resolved
    ]
    check("§18: four leads-base records produced, all parcel RESOLVED",
          len(base_records) == 4
          and all(b["parcel_resolution_status"] == "RESOLVED"
                  for b in base_records))
    check("§18: confidence_status rolled up from Confirmed evidence",
          all(b["confidence_status"] == "Confirmed" for b in base_records))

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        base_path = leads_base_writer.write_leads_base(
            "clerk_recordings", base_records, output_dir=workdir)
        ledger_path = evidence_ledger_mod.write_evidence_ledger(
            evidence_entries, output_dir=workdir)

        # --- §19 — idempotent aggregator -----------------------------------
        out_path = workdir / "matched_leads.json"
        matched_leads = aggregator.aggregate([base_path], output_path=out_path)

        check("§19: artifacts written — matched_leads.json + evidence_ledger.json",
              out_path.is_file() and ledger_path.is_file())
        check("§19: aggregation produced two matched leads "
              "(PARCEL-100, PARCEL-200)", len(matched_leads) == 2)

        by_parcel = {m["primary_parcel_id"]: m for m in matched_leads}
        p100 = by_parcel.get("PARCEL-100")
        p200 = by_parcel.get("PARCEL-200")
        check("§19: PARCEL-100 carries two distinct signals "
              "(§18.F anti-collapse: hospital_lien + foreclosure_notice)",
              p100 is not None and len(p100["signals"]) == 2)
        hosp = next((s for s in (p100 or {}).get("signals", [])
                     if s["canonical_doc_type"] == "hospital_lien"), None)
        check("§19: the two stacked hospital liens aggregate to count 2",
              hosp is not None and hosp["count"] == 2
              and len(hosp["instrument_numbers"]) == 2)
        check("§19: PARCEL-200 is one matched lead, owner the estate, "
              "owner_type ESTATE",
              p200 is not None and p200["owner_name"] == "ESTATE OF HAROLD DOE"
              and p200["owner_type"] == "ESTATE")

        # --- §20 — semantic verification -----------------------------------
        report = semantic_verify.run_semantic_verification(
            matched_leads, leads_base_records=base_records,
            evidence_ledger=ledger)
        check("§20: mechanical pre-gate passed (matched leads schema-valid)",
              report["mechanical_ok"] is True)
        check("§20: the six data-shape checks (1,2,4,5,6,12) all returned VALID",
              all(r["status"] == "VALID" for r in report["checks"]
                  if r["check"] in (1, 2, 4, 5, 6, 12)))
        check("§20: returned a deploy verdict of DEPLOY_OK",
              report["verdict"] == "DEPLOY_OK")

        # --- evidence wire-through -----------------------------------------
        trace = evidence_ledger_mod.verify_evidence_traceability(
            matched_leads, ledger)
        check("evidence: every matched-lead claim traces to an evidence entry",
              trace["traceable"] is True and trace["evidence_refs_checked"] >= 4)

        # --- §19.D idempotency end-to-end ----------------------------------
        rerun = aggregator.aggregate([base_path])
        check("§19.D: a second aggregation run is byte-identical "
              "(idempotent end-to-end)",
              json.dumps(matched_leads, sort_keys=True)
              == json.dumps(rerun, sort_keys=True))

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: staged pipeline end-to-end — "
              f"{len(failed)} of {len(checks)} checks failed")
        return 1

    print(f"PASS: staged pipeline §17→§18→§19→§20 proven end-to-end — "
          f"all {len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
