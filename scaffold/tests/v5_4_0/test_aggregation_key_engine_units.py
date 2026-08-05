#!/usr/bin/env python3
"""v5.4.0 unit tests — §18 aggregation key engine + leads-base writer.

Added in v5.4.0 Session 3. Wired into run_all.py via scaffold/tests/v5_4_0/.
Exercises the §18 surface:

  - F-4: the aggregation key shape (parcel_id, canonical_doc_type, signal_type);
  - F-3: null-parcel records do NOT collapse — distinct instruments stay
    distinct, a true duplicate (same instrument) collapses, and a null-parcel
    key with no fallback identity is a hard error;
  - §18.F anti-collapse: distinct doc types on one parcel stay distinct;
  - §18.E: legitimate stacking (distinct instruments) is not deduplicated;
    a true duplicate (same instrument twice) collapses;
  - the leads-base writer produces schema-valid records — including an F-5
    default REVIEW_REQUIRED record with filer_entity null (the Option A
    reconciliation);
  - §18.J confidence_status roll-up (weakest-evidence rule);
  - write_leads_base is deterministic (byte-identical on re-run).

Run: python3 scaffold/tests/v5_4_0/test_aggregation_key_engine_units.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator

from scaffold.pipeline import aggregation_key_engine as ake
from scaffold.pipeline import leads_base_writer
from scaffold.pipeline.contracts import schema_path

SIGNAL_TYPE_LABELS = {
    "hospital_lien": "Hospital Lien",
    "executors_deed": "Estate-Titled Property",
}


def _debtor_resolved(*, raw_event_id, canonical_doc_type,
                     owner_name="DOE, JANE A", owner_type="INDIVIDUAL",
                     parcel_id=None, debtor_resolution_status="RESOLVED",
                     filer_entity=None, review_reason=None,
                     instrument_number="INSTR-0001", evidence_ids=None,
                     debtor_extraction_method="STRUCTURED_NAME_TYPE",
                     expected_debtor_name_type="TP"):
    """A debtor-resolved record (debtor_resolved_record.schema.json shape)."""
    return {
        "raw_event_id": raw_event_id,
        "source_id": "unit_test_source",
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": canonical_doc_type,
        "instrument_number": instrument_number,
        "recorded_date": "2026-04-01",
        "event_date": None,
        "source_url": f"https://example.test/{raw_event_id}",
        "property_refs": {
            "parcel_id": parcel_id,
            "situs_address": "100 EXAMPLE WAY",
            "legal_description": None,
            "case_number": None,
        },
        "evidence_ids": list(evidence_ids or []),
        "owner_name": owner_name,
        "owner_type": owner_type,
        "filer_entity": filer_entity,
        "debtor_resolution_status": debtor_resolution_status,
        "review_reason": review_reason,
        "expected_debtor_name_type": expected_debtor_name_type,
        "debtor_extraction_method": debtor_extraction_method,
    }


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    leads_base_validator = Draft202012Validator(
        json.loads(schema_path("leads_base_record").read_text(encoding="utf-8"))
    )

    # --- F-4: aggregation key shape -----------------------------------------
    key = ake.compute_aggregation_key(
        parcel_id="PARCEL-1", canonical_doc_type="hospital_lien",
        signal_type="Hospital Lien")
    check("F-4: compute_aggregation_key returns the 3-component key dict",
          key == {"parcel_id": "PARCEL-1",
                  "canonical_doc_type": "hospital_lien",
                  "signal_type": "Hospital Lien"})
    tup = ake.aggregation_key_tuple(key)
    check("F-4: aggregation_key_tuple returns the (parcel, doc, signal) tuple",
          tup == ("PARCEL-1", "hospital_lien", "Hospital Lien"))
    check("F-4: the key tuple is hashable", isinstance(hash(tup), int))

    # --- resolve_signal_type: county map, then titlecase fallback -----------
    check("resolve_signal_type uses the county signal_type_labels map",
          ake.resolve_signal_type("hospital_lien",
                                  signal_type_labels=SIGNAL_TYPE_LABELS)
          == "Hospital Lien")
    check("resolve_signal_type falls back to a titlecased default label",
          ake.resolve_signal_type("federal_tax_lien", signal_type_labels={})
          == "Federal Tax Lien")

    # --- §18.F anti-collapse: distinct doc types on one parcel --------------
    k_hosp = ake.compute_aggregation_key(
        parcel_id="PARCEL-1", canonical_doc_type="hospital_lien",
        signal_type="Hospital Lien")
    k_estate = ake.compute_aggregation_key(
        parcel_id="PARCEL-1", canonical_doc_type="executors_deed",
        signal_type="Estate-Titled Property")
    check("§18.F anti-collapse: hospital_lien and executors_deed on the same "
          "parcel produce DIFFERENT key tuples",
          ake.aggregation_key_tuple(k_hosp)
          != ake.aggregation_key_tuple(k_estate))

    # --- F-3: null-parcel records do not collapse ---------------------------
    null_key = ake.compute_aggregation_key(
        parcel_id=None, canonical_doc_type="hospital_lien",
        signal_type="Hospital Lien")
    t_a = ake.aggregation_key_tuple(null_key, fallback_identity="INSTR-A")
    t_b = ake.aggregation_key_tuple(null_key, fallback_identity="INSTR-B")
    t_a2 = ake.aggregation_key_tuple(null_key, fallback_identity="INSTR-A")
    check("F-3: two null-parcel records with DIFFERENT instruments do NOT "
          "merge (distinct tuples)", t_a != t_b)
    check("F-3: two null-parcel records with the SAME instrument merge "
          "(same tuple)", t_a == t_a2)
    check("F-3: a null-parcel tuple never equals a non-null-parcel tuple",
          t_a != ake.aggregation_key_tuple(k_hosp))
    raised = False
    try:
        ake.aggregation_key_tuple(null_key)
    except ValueError:
        raised = True
    check("F-3: a null-parcel key with no fallback_identity raises ValueError "
          "(loud failure, never a silent over-merge)", raised)

    # --- null_parcel_fallback_identity priority -----------------------------
    check("null_parcel_fallback_identity prefers instrument_number",
          ake.null_parcel_fallback_identity(
              {"instrument_number": "INST-9", "raw_event_id": "raw-9"})
          == "INST-9")
    check("null_parcel_fallback_identity falls back to raw_event_id",
          ake.null_parcel_fallback_identity(
              {"instrument_number": None, "raw_event_id": "raw-9"})
          == "raw-9")

    # --- §18.E: legitimate stacking vs true duplicate -----------------------
    stack = [{"instrument_number": "INSTR-A"}, {"instrument_number": "INSTR-B"}]
    dup = [{"instrument_number": "INSTR-A"}, {"instrument_number": "INSTR-A"}]
    stack_distinct = ake.distinct_instrument_numbers(stack)
    dup_distinct = ake.distinct_instrument_numbers(dup)
    check("§18.E legitimate stacking: 2 records, 2 distinct instruments → "
          "not collapsed (2 distinct)",
          len(stack_distinct) == 2 and len(stack_distinct) == len(stack))
    check("§18.E true duplicate: 2 records, same instrument → collapses "
          "(1 distinct, below the record count)",
          len(dup_distinct) == 1 and len(dup_distinct) < len(dup))

    # --- leads-base writer: schema-valid records ----------------------------
    evidence_ledger = {
        "ev-confirmed": {"status": "Confirmed"},
        "ev-possible": {"status": "Possible"},
        "ev-needsreview": {"status": "Needs Review"},
    }

    resolved_drr = _debtor_resolved(
        raw_event_id="raw-resolved-1", canonical_doc_type="hospital_lien",
        parcel_id="PARCEL-7", evidence_ids=["ev-confirmed"])
    base_resolved = leads_base_writer.build_base_record(
        resolved_drr, signal_type_labels=SIGNAL_TYPE_LABELS,
        evidence_ledger=evidence_ledger)
    check("build_base_record: RESOLVED debtor + parcel → "
          "parcel_resolution_status RESOLVED",
          base_resolved["parcel_resolution_status"] == "RESOLVED")
    check("build_base_record: RESOLVED record validates against "
          "leads_base_record.schema.json",
          not list(leads_base_validator.iter_errors(base_resolved)))
    check("build_base_record: aggregation_key.parcel_id is set on a RESOLVED "
          "parcel", base_resolved["aggregation_key"]["parcel_id"] == "PARCEL-7")

    unresolved_drr = _debtor_resolved(
        raw_event_id="raw-unresolved-1", canonical_doc_type="hospital_lien",
        parcel_id=None, evidence_ids=["ev-confirmed"])
    base_unresolved = leads_base_writer.build_base_record(
        unresolved_drr, signal_type_labels=SIGNAL_TYPE_LABELS,
        evidence_ledger=evidence_ledger)
    check("build_base_record: RESOLVED debtor, no parcel → "
          "parcel_resolution_status UNRESOLVED",
          base_unresolved["parcel_resolution_status"] == "UNRESOLVED")
    check("build_base_record: UNRESOLVED record validates against schema",
          not list(leads_base_validator.iter_errors(base_unresolved)))
    check("build_base_record: aggregation_key.parcel_id is null when UNRESOLVED",
          base_unresolved["aggregation_key"]["parcel_id"] is None)

    # F-5 default — REVIEW_REQUIRED with filer_entity null (Option A).
    f5_drr = _debtor_resolved(
        raw_event_id="raw-f5-1", canonical_doc_type="tax_sale",
        owner_name="tax_sale against unidentified party", owner_type="UNKNOWN",
        debtor_resolution_status="REVIEW_REQUIRED", filer_entity=None,
        review_reason="no_debtor_rule_for_doc_type",
        debtor_extraction_method="REVIEW_ROUTED",
        expected_debtor_name_type=None, evidence_ids=[])
    base_f5 = leads_base_writer.build_base_record(
        f5_drr, signal_type_labels=SIGNAL_TYPE_LABELS)
    check("build_base_record: F-5 default → parcel_resolution_status "
          "REVIEW_REQUIRED", base_f5["parcel_resolution_status"]
          == "REVIEW_REQUIRED")
    check("F-5 / Option A: a REVIEW_REQUIRED record with filer_entity=null "
          "validates against leads_base_record.schema.json",
          base_f5["filer_entity"] is None
          and not list(leads_base_validator.iter_errors(base_f5)))

    # --- §18.J confidence_status roll-up ------------------------------------
    check("§18.J confidence: all-Confirmed evidence → Confirmed",
          leads_base_writer.derive_confidence_status(
              ["ev-confirmed"], evidence_ledger=evidence_ledger) == "Confirmed")
    check("§18.J confidence: weakest governs — Confirmed + Possible → Possible",
          leads_base_writer.derive_confidence_status(
              ["ev-confirmed", "ev-possible"],
              evidence_ledger=evidence_ledger) == "Possible")
    check("§18.J confidence: a 'Needs Review' evidence entry → Unknown",
          leads_base_writer.derive_confidence_status(
              ["ev-confirmed", "ev-needsreview"],
              evidence_ledger=evidence_ledger) == "Unknown")
    check("§18.J confidence: no evidence_ids → Unknown",
          leads_base_writer.derive_confidence_status(
              [], evidence_ledger=evidence_ledger) == "Unknown")
    check("§18.J confidence: no evidence ledger → Unknown",
          leads_base_writer.derive_confidence_status(
              ["ev-confirmed"], evidence_ledger=None) == "Unknown")
    check("§18.J confidence: build_base_record stamps confidence_status "
          "(Confirmed here)", base_resolved["confidence_status"] == "Confirmed")

    # --- write_leads_base: deterministic output -----------------------------
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        path1 = leads_base_writer.write_leads_base(
            "unit_test_source", [base_resolved, base_unresolved],
            output_dir=workdir)
        first_bytes = path1.read_bytes()
        path2 = leads_base_writer.write_leads_base(
            "unit_test_source", [base_unresolved, base_resolved],
            output_dir=workdir)
        second_bytes = path2.read_bytes()
    check("write_leads_base: file is named <source>_leads_base.json",
          path1.name == "unit_test_source_leads_base.json")
    check("write_leads_base: re-running on the same records (any order) "
          "produces a byte-identical file (§19.D enabler)",
          first_bytes == second_bytes)

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: §18 aggregation key engine unit tests — "
              f"{len(failed)} of {len(checks)} checks failed")
        return 1

    print(f"PASS: §18 aggregation key engine unit tests — "
          f"all {len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
