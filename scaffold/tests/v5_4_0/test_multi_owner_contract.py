#!/usr/bin/env python3
"""v5.4.0 Session 7A unit tests — the multi-owner contract extension.

Wired into run_all.py via scaffold/tests/v5_4_0/. Verifies the multi-owner
block added to debtor_resolved_record / leads_base_record / matched_lead_record
(see §17.K):

  - each multi_owner_status value (SINGLE_OWNER, MULTIPLE_OWNERS_PRIMARY_CLEAR,
    MULTIPLE_OWNERS_PRIMARY_UNCLEAR) validates against all three schemas;
  - the consistency rules — bad cardinality / primary-clarity is rejected;
  - the no-contradiction guarantee — MULTIPLE_OWNERS_PRIMARY_UNCLEAR with the
    needs-review verdict field NOT REVIEW_REQUIRED is rejected;
  - co-owners are never dropped — owner_count always equals len(owners);
  - single-owner backward compatibility — a pre-7A record with no multi-owner
    block validates against all three extended schemas;
  - the records.py dataclass __post_init__ raises on a contradiction.

Run: python3 scaffold/tests/v5_4_0/test_multi_owner_contract.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator

from scaffold.pipeline.contracts import schema_path
from scaffold.pipeline.contracts import records as r

_VALIDATORS = {
    name: Draft202012Validator(
        json.loads(schema_path(name).read_text(encoding="utf-8"))
    )
    for name in ("debtor_resolved_record", "leads_base_record",
                 "matched_lead_record")
}


def _valid(record: dict, schema_name: str) -> bool:
    return not list(_VALIDATORS[schema_name].iter_errors(record))


def _owner(name, is_primary, *, resolution_status="RESOLVED"):
    return {
        "name": name, "role": "owner", "name_type": "TP",
        "is_primary": is_primary, "confidence": None, "source_field": None,
        "resolution_status": resolution_status, "notes": None,
    }


def _debtor_resolved(*, owner_name, block=None,
                     debtor_resolution_status="RESOLVED",
                     review_reason=None,
                     debtor_extraction_method="STRUCTURED_NAME_TYPE"):
    rec = {
        "raw_event_id": "r1", "source_id": "s",
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": "hospital_lien", "source_url": "https://x.test/1",
        "recorded_date": "2026-01-01", "instrument_number": "I1",
        "property_refs": {"parcel_id": "P1", "situs_address": None,
                          "legal_description": None, "case_number": None},
        "owner_name": owner_name, "owner_type": "INDIVIDUAL",
        "filer_entity": None,
        "debtor_resolution_status": debtor_resolution_status,
        "review_reason": review_reason,
        "debtor_extraction_method": debtor_extraction_method,
        "expected_debtor_name_type": "TP",
    }
    if block:
        rec.update(block)
    return rec


def _leads_base(*, owner_name, block=None,
                parcel_resolution_status="RESOLVED", review_reason=None):
    rec = {
        "base_record_id": "b1", "raw_event_id": "r1", "source_id": "s",
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": "hospital_lien", "signal_type": "Hospital Lien",
        "aggregation_key": {"parcel_id": "P1",
                            "canonical_doc_type": "hospital_lien",
                            "signal_type": "Hospital Lien"},
        "owner_name": owner_name, "owner_type": "INDIVIDUAL",
        "filer_entity": None, "review_reason": review_reason,
        "parcel_resolution_status": parcel_resolution_status,
        "enrichment_status": "UNENRICHED", "confidence_status": "Confirmed",
        "instrument_number": "I1", "recorded_date": "2026-01-01",
        "source_url": "https://x.test/1", "evidence_ids": ["ev1"],
        "property_refs": {"parcel_id": "P1", "situs_address": None,
                          "legal_description": None, "case_number": None},
    }
    if block:
        rec.update(block)
    return rec


def _signal():
    return {
        "aggregation_key": {"parcel_id": "P1",
                            "canonical_doc_type": "hospital_lien",
                            "signal_type": "Hospital Lien"},
        "signal_type": "Hospital Lien", "canonical_doc_type": "hospital_lien",
        "count": 1, "instrument_numbers": ["I1"],
        "source_urls": ["https://x.test/1"], "evidence_ids": ["ev1"],
        "source_ids": ["s"], "earliest_recorded_date": "2026-01-01",
        "latest_recorded_date": "2026-01-01",
        "recorded_date_range": ["2026-01-01", "2026-01-01"],
    }


def _matched_lead(*, owner_name, block=None,
                  parcel_resolution_status="RESOLVED", review_reason=None):
    rec = {
        "lead_id": "lead_parcel_P1", "primary_parcel_id": "P1",
        "owner_name": owner_name, "owner_type": "INDIVIDUAL",
        "filer_entity": None, "review_reason": review_reason,
        "parcel_resolution_status": parcel_resolution_status,
        "enrichment_status": "UNENRICHED", "signals": [_signal()],
        "source_ids": ["s"], "evidence_ids": ["ev1"],
    }
    if block:
        rec.update(block)
    return rec


# Multi-owner blocks.
_SINGLE = {
    "owners": [_owner("DOE, JANE A", True)],
    "primary_owner_name": "DOE, JANE A",
    "additional_owner_names": [],
    "owner_count": 1,
    "multi_owner_status": "SINGLE_OWNER",
}
_CLEAR = {
    "owners": [_owner("DOE, JANE A", True), _owner("DOE, JOHN B", False)],
    "primary_owner_name": "DOE, JANE A",
    "additional_owner_names": ["DOE, JOHN B"],
    "owner_count": 2,
    "multi_owner_status": "MULTIPLE_OWNERS_PRIMARY_CLEAR",
}
_PLACEHOLDER = "hospital_lien against unidentified party"
_UNCLEAR = {
    "owners": [_owner("DOE, JANE A", False), _owner("DOE, JOHN B", False)],
    "primary_owner_name": _PLACEHOLDER,
    "additional_owner_names": ["DOE, JANE A", "DOE, JOHN B"],
    "owner_count": 2,
    "multi_owner_status": "MULTIPLE_OWNERS_PRIMARY_UNCLEAR",
}


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    # --- each multi_owner_status value validates on all three schemas -------
    check("SINGLE_OWNER record validates on all three extended schemas",
          _valid(_debtor_resolved(owner_name="DOE, JANE A", block=_SINGLE),
                 "debtor_resolved_record")
          and _valid(_leads_base(owner_name="DOE, JANE A", block=_SINGLE),
                     "leads_base_record")
          and _valid(_matched_lead(owner_name="DOE, JANE A", block=_SINGLE),
                     "matched_lead_record"))
    check("MULTIPLE_OWNERS_PRIMARY_CLEAR record validates on all three schemas",
          _valid(_debtor_resolved(owner_name="DOE, JANE A", block=_CLEAR),
                 "debtor_resolved_record")
          and _valid(_leads_base(owner_name="DOE, JANE A", block=_CLEAR),
                     "leads_base_record")
          and _valid(_matched_lead(owner_name="DOE, JANE A", block=_CLEAR),
                     "matched_lead_record"))
    check("MULTIPLE_OWNERS_PRIMARY_UNCLEAR record (verdict REVIEW_REQUIRED) "
          "validates on all three schemas",
          _valid(_debtor_resolved(
                     owner_name=_PLACEHOLDER, block=_UNCLEAR,
                     debtor_resolution_status="REVIEW_REQUIRED",
                     review_reason="multiple owners, primary unclear",
                     debtor_extraction_method="REVIEW_ROUTED"),
                 "debtor_resolved_record")
          and _valid(_leads_base(
                     owner_name=_PLACEHOLDER, block=_UNCLEAR,
                     parcel_resolution_status="REVIEW_REQUIRED",
                     review_reason="multiple owners, primary unclear"),
                     "leads_base_record")
          and _valid(_matched_lead(
                     owner_name=_PLACEHOLDER, block=_UNCLEAR,
                     parcel_resolution_status="REVIEW_REQUIRED",
                     review_reason="multiple owners, primary unclear"),
                     "matched_lead_record"))

    # --- backward compatibility — a pre-7A record with no block validates --
    check("backward compatible: a single-owner record with NO multi-owner "
          "block validates on all three extended schemas",
          _valid(_debtor_resolved(owner_name="DOE, JANE A"),
                 "debtor_resolved_record")
          and _valid(_leads_base(owner_name="DOE, JANE A"),
                     "leads_base_record")
          and _valid(_matched_lead(owner_name="DOE, JANE A"),
                     "matched_lead_record"))

    # --- consistency rules — the schema rejects violations -----------------
    bad_count = dict(_SINGLE)
    bad_count["owner_count"] = 2
    check("schema rejects SINGLE_OWNER with owner_count 2",
          not _valid(_debtor_resolved(owner_name="DOE, JANE A",
                                      block=bad_count),
                     "debtor_resolved_record"))
    two_owner_single = {
        "owners": [_owner("DOE, JANE A", True), _owner("DOE, JOHN B", False)],
        "primary_owner_name": "DOE, JANE A", "additional_owner_names": [],
        "owner_count": 2, "multi_owner_status": "SINGLE_OWNER",
    }
    check("schema rejects SINGLE_OWNER with two owners",
          not _valid(_debtor_resolved(owner_name="DOE, JANE A",
                                      block=two_owner_single),
                     "debtor_resolved_record"))
    unclear_with_primary = dict(_UNCLEAR)
    unclear_with_primary["owners"] = [_owner("DOE, JANE A", True),
                                      _owner("DOE, JOHN B", False)]
    check("schema rejects MULTIPLE_OWNERS_PRIMARY_UNCLEAR with an is_primary "
          "owner (ownership priority is never invented)",
          not _valid(_debtor_resolved(
                         owner_name=_PLACEHOLDER, block=unclear_with_primary,
                         debtor_resolution_status="REVIEW_REQUIRED",
                         review_reason="x",
                         debtor_extraction_method="REVIEW_ROUTED"),
                     "debtor_resolved_record"))
    clear_count_1 = dict(_CLEAR)
    clear_count_1["owner_count"] = 1
    check("schema rejects MULTIPLE_OWNERS_PRIMARY_CLEAR with owner_count 1",
          not _valid(_debtor_resolved(owner_name="DOE, JANE A",
                                      block=clear_count_1),
                     "debtor_resolved_record"))

    # --- the no-contradiction guarantee ------------------------------------
    check("no-contradiction (debtor-resolved): UNCLEAR with "
          "debtor_resolution_status RESOLVED is rejected by the schema",
          not _valid(_debtor_resolved(
                         owner_name=_PLACEHOLDER, block=_UNCLEAR,
                         debtor_resolution_status="RESOLVED"),
                     "debtor_resolved_record"))
    check("no-contradiction (matched lead): UNCLEAR with "
          "parcel_resolution_status RESOLVED is rejected by the schema",
          not _valid(_matched_lead(
                         owner_name=_PLACEHOLDER, block=_UNCLEAR,
                         parcel_resolution_status="RESOLVED"),
                     "matched_lead_record"))

    # --- records.py consistency helper -------------------------------------
    check("multi_owner_consistency_errors: a consistent SINGLE_OWNER record "
          "has no errors",
          r.multi_owner_consistency_errors(
              _debtor_resolved(owner_name="DOE, JANE A", block=_SINGLE)) == [])
    check("multi_owner_consistency_errors: an old-style record (no block) "
          "has no errors (backward compatible)",
          r.multi_owner_consistency_errors(
              _debtor_resolved(owner_name="DOE, JANE A")) == [])
    mismatch = dict(_SINGLE)
    mismatch["primary_owner_name"] = "SOMEONE ELSE"
    check("multi_owner_consistency_errors flags primary_owner_name != "
          "owner_name (schema cannot express field equality)",
          bool(r.multi_owner_consistency_errors(
              _debtor_resolved(owner_name="DOE, JANE A", block=mismatch))))
    dropped = {
        "owners": [_owner("DOE, JANE A", True), _owner("DOE, JOHN B", False)],
        "primary_owner_name": "DOE, JANE A",
        "additional_owner_names": ["DOE, JOHN B"],
        "owner_count": 3,
        "multi_owner_status": "MULTIPLE_OWNERS_PRIMARY_CLEAR",
    }
    check("co-owner-never-dropped: owner_count must equal len(owners)",
          any("co-owners are never dropped" in e
              for e in r.multi_owner_consistency_errors(
                  _debtor_resolved(owner_name="DOE, JANE A", block=dropped))))

    # --- the dataclass __post_init__ enforces consistency ------------------
    single_owner_obj = (r.Owner(name="DOE, JANE A", is_primary=True),)
    dataclass_ok = True
    try:
        r.DebtorResolvedRecord(
            raw_event_id="r1", source_id="s",
            source_role="PRIMARY_EVENT_SOURCE",
            canonical_doc_type="hospital_lien", source_url="https://x.test/1",
            recorded_date="2026-01-01", instrument_number="I1",
            property_refs=r.PropertyRefs(parcel_id="P1"),
            owner_name="DOE, JANE A", owner_type="INDIVIDUAL",
            filer_entity=None, debtor_resolution_status="RESOLVED",
            review_reason=None, debtor_extraction_method="STRUCTURED_NAME_TYPE",
            owners=single_owner_obj, primary_owner_name="DOE, JANE A",
            additional_owner_names=(), owner_count=1,
            multi_owner_status="SINGLE_OWNER")
        # an old-style instance with no multi-owner block constructs fine
        r.DebtorResolvedRecord(
            raw_event_id="r1", source_id="s",
            source_role="PRIMARY_EVENT_SOURCE",
            canonical_doc_type="hospital_lien", source_url="https://x.test/1",
            recorded_date="2026-01-01", instrument_number="I1",
            property_refs=r.PropertyRefs(parcel_id="P1"),
            owner_name="DOE, JANE A", owner_type="INDIVIDUAL",
            filer_entity=None, debtor_resolution_status="RESOLVED",
            review_reason=None, debtor_extraction_method="STRUCTURED_NAME_TYPE")
    except Exception:  # noqa: BLE001
        dataclass_ok = False
    check("dataclass: a consistent SINGLE_OWNER and an old-style "
          "DebtorResolvedRecord both construct", dataclass_ok)

    raised = False
    try:
        r.DebtorResolvedRecord(
            raw_event_id="r1", source_id="s",
            source_role="PRIMARY_EVENT_SOURCE",
            canonical_doc_type="hospital_lien", source_url="https://x.test/1",
            recorded_date="2026-01-01", instrument_number="I1",
            property_refs=r.PropertyRefs(parcel_id="P1"),
            owner_name="DOE, JANE A", owner_type="INDIVIDUAL",
            filer_entity=None, debtor_resolution_status="RESOLVED",
            review_reason=None, debtor_extraction_method="STRUCTURED_NAME_TYPE",
            owners=single_owner_obj, primary_owner_name="DOE, JANE A",
            additional_owner_names=(), owner_count=2,
            multi_owner_status="SINGLE_OWNER")
    except ValueError:
        raised = True
    check("dataclass __post_init__ raises ValueError on a multi-owner "
          "contradiction (owner_count 2 with SINGLE_OWNER)", raised)

    # --- multi_owner_status is descriptive — no REVIEW_REQUIRED value ------
    check("multi_owner_status enum is exactly the 3 descriptive values — "
          "no REVIEW_REQUIRED",
          set(r.MULTI_OWNER_STATUSES) == {
              "SINGLE_OWNER", "MULTIPLE_OWNERS_PRIMARY_CLEAR",
              "MULTIPLE_OWNERS_PRIMARY_UNCLEAR"}
          and "REVIEW_REQUIRED" not in r.MULTI_OWNER_STATUSES)

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: multi-owner contract — {len(failed)} of {len(checks)} "
              f"checks failed")
        return 1

    print(f"PASS: multi-owner contract (v5.4.0 Session 7A) — "
          f"all {len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
