#!/usr/bin/env python3
"""v5.4.0 unit tests — §19 idempotent aggregator.

Added in v5.4.0 Session 4. Wired into run_all.py via scaffold/tests/v5_4_0/.
Exercises the §19 surface:

  - §19.C: the aggregator refuses to read its own output (matched_leads.json),
    a dashboard artifact, a non-base-file, or an input equal to output_path;
  - §19.D / §19.E: aggregate run twice is byte-identical; idempotency_self_check
    confirms it;
  - F-3: two distinct null-parcel properties do NOT merge through the aggregator;
  - §18.E: legitimate stacking (distinct instruments) is preserved as count > 1;
    a true duplicate (same instrument twice) collapses to count 1;
  - §18.F: distinct doc types on one property stay distinct signals;
  - §18.D: the same key from two sources merges into one cross-source signal;
  - every matched lead validates against matched_lead_record.schema.json.

Run: python3 scaffold/tests/v5_4_0/test_aggregator_units.py
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

from scaffold.pipeline import aggregator
from scaffold.pipeline.contracts import schema_path


def _lbr(*, base_id, source_id, doc_type, signal_type, parcel_id, instrument,
         recorded_date="2026-04-01", owner_name="DOE, JANE A",
         parcel_resolution_status="RESOLVED"):
    """One leads-base record conforming to leads_base_record.schema.json."""
    return {
        "base_record_id": base_id,
        "raw_event_id": f"raw_{base_id}",
        "source_id": source_id,
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": doc_type,
        "signal_type": signal_type,
        "aggregation_key": {
            "parcel_id": parcel_id,
            "canonical_doc_type": doc_type,
            "signal_type": signal_type,
        },
        "owner_name": owner_name,
        "owner_type": "INDIVIDUAL",
        "filer_entity": None,
        "review_reason": None,
        "parcel_resolution_status": parcel_resolution_status,
        "enrichment_status": "UNENRICHED",
        "confidence_status": "Confirmed",
        "instrument_number": instrument,
        "recorded_date": recorded_date,
        "event_date": None,
        "source_url": f"https://example.test/{source_id}/{base_id}",
        "evidence_ids": [f"ev_{base_id}"],
        "property_refs": {
            "parcel_id": parcel_id,
            "situs_address": "100 EXAMPLE WAY",
            "legal_description": None,
            "case_number": None,
        },
    }


def _write(workdir: Path, source_id: str, records: list) -> Path:
    path = workdir / f"{source_id}_leads_base.json"
    path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return path


def _raises_value_error(fn) -> bool:
    try:
        fn()
    except ValueError:
        return True
    except Exception:
        return False
    return False


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    matched_lead_validator = Draft202012Validator(
        json.loads(schema_path("matched_lead_record").read_text(encoding="utf-8"))
    )

    # --- §19.C: the aggregator never reads its own output -------------------
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        base = _write(workdir, "clerk_recordings", [
            _lbr(base_id="g1", source_id="clerk_recordings",
                 doc_type="hospital_lien", signal_type="Hospital Lien",
                 parcel_id="P-1", instrument="I-1"),
        ])
        ml_path = workdir / "matched_leads.json"
        ml_path.write_text("[]", encoding="utf-8")
        check("§19.C: aggregate refuses matched_leads.json as input",
              _raises_value_error(lambda: aggregator.aggregate([ml_path])))

        other = workdir / "something.json"
        other.write_text("[]", encoding="utf-8")
        check("§19.C: aggregate refuses a non-<source>_leads_base.json input",
              _raises_value_error(lambda: aggregator.aggregate([other])))

        check("§19.C: aggregate refuses an input path equal to output_path",
              _raises_value_error(
                  lambda: aggregator.aggregate([base], output_path=base)))

        dash = workdir / "dashboard"
        dash.mkdir()
        data_json = dash / "data.json"
        data_json.write_text("[]", encoding="utf-8")
        check("§19.C: aggregate refuses dashboard/data.json as input",
              _raises_value_error(lambda: aggregator.aggregate([data_json])))

    # --- §19.D/E idempotency + §18.F anti-collapse + §18.E stacking ---------
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        clerk = _write(workdir, "clerk_recordings", [
            _lbr(base_id="b1", source_id="clerk_recordings",
                 doc_type="hospital_lien", signal_type="Hospital Lien",
                 parcel_id="P-1", instrument="I-1", recorded_date="2026-01-05"),
            _lbr(base_id="b2", source_id="clerk_recordings",
                 doc_type="hospital_lien", signal_type="Hospital Lien",
                 parcel_id="P-1", instrument="I-2", recorded_date="2026-02-11"),
            _lbr(base_id="b3", source_id="clerk_recordings",
                 doc_type="executors_deed", signal_type="Estate-Titled Property",
                 parcel_id="P-1", instrument="I-3", recorded_date="2026-03-01"),
        ])
        out = workdir / "matched_leads.json"
        first = aggregator.aggregate([clerk], output_path=out)
        first_bytes = out.read_bytes()
        second = aggregator.aggregate([clerk], output_path=out)
        second_bytes = out.read_bytes()

        check("§19.D: aggregate run twice → byte-identical matched_leads.json",
              first_bytes == second_bytes)
        check("§19.D: aggregate run twice → identical return value",
              json.dumps(first, sort_keys=True)
              == json.dumps(second, sort_keys=True))
        check("§19.E: idempotency_self_check confirms the write is idempotent",
              aggregator.idempotency_self_check([clerk], output_path=out) is True)
        check("every matched lead validates against "
              "matched_lead_record.schema.json",
              all(not list(matched_lead_validator.iter_errors(m))
                  for m in first))
        check("one property (P-1) → exactly one matched_lead", len(first) == 1)

        lead = first[0]
        check("§18.F anti-collapse: hospital_lien + executors_deed on one "
              "parcel → 2 distinct signals", len(lead["signals"]) == 2)
        hosp = [s for s in lead["signals"]
                if s["canonical_doc_type"] == "hospital_lien"][0]
        check("§18.E legitimate stacking: 2 distinct hospital-lien instruments "
              "→ count 2, preserved (not deduplicated)",
              hosp["count"] == 2 and len(hosp["instrument_numbers"]) == 2)

    # --- §18.E true duplicate collapses -------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        clerk = _write(workdir, "clerk_recordings", [
            _lbr(base_id="d1", source_id="clerk_recordings",
                 doc_type="hospital_lien", signal_type="Hospital Lien",
                 parcel_id="P-D", instrument="I-DUP"),
            _lbr(base_id="d2", source_id="clerk_recordings",
                 doc_type="hospital_lien", signal_type="Hospital Lien",
                 parcel_id="P-D", instrument="I-DUP"),
        ])
        leads = aggregator.aggregate([clerk])
        check("§18.E true duplicate: same parcel+doc+instrument → 1 matched_lead",
              len(leads) == 1)
        dup_signal = leads[0]["signals"][0]
        check("§18.E true duplicate collapses: count 1, one instrument_number",
              dup_signal["count"] == 1
              and dup_signal["instrument_numbers"] == ["I-DUP"])

    # --- F-3 null-parcel records do NOT merge through the aggregator --------
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        src = _write(workdir, "clerk_recordings", [
            _lbr(base_id="n1", source_id="clerk_recordings",
                 doc_type="hospital_lien", signal_type="Hospital Lien",
                 parcel_id=None, instrument="I-N1",
                 parcel_resolution_status="UNRESOLVED"),
            _lbr(base_id="n2", source_id="clerk_recordings",
                 doc_type="hospital_lien", signal_type="Hospital Lien",
                 parcel_id=None, instrument="I-N2",
                 parcel_resolution_status="UNRESOLVED"),
        ])
        leads = aggregator.aggregate([src])
        check("F-3: two null-parcel records with distinct instruments → "
              "2 matched_leads (distinct properties NOT merged)",
              len(leads) == 2)
        check("F-3: null-parcel matched_leads carry primary_parcel_id null",
              all(lead["primary_parcel_id"] is None for lead in leads))

    # --- §18.D cross-source merge -------------------------------------------
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        clerk = _write(workdir, "clerk_recordings", [
            _lbr(base_id="x1", source_id="clerk_recordings",
                 doc_type="foreclosure_notice", signal_type="Foreclosure Notice",
                 parcel_id="P-X", instrument="I-X1"),
        ])
        notices = _write(workdir, "foreclosure_notices", [
            _lbr(base_id="x2", source_id="foreclosure_notices",
                 doc_type="foreclosure_notice", signal_type="Foreclosure Notice",
                 parcel_id="P-X", instrument="I-X2"),
        ])
        leads = aggregator.aggregate([clerk, notices])
        check("§18.D cross-source: same key from 2 sources → 1 matched_lead, "
              "1 signal", len(leads) == 1 and len(leads[0]["signals"]) == 1)
        check("§18.D cross-source: the merged signal carries both source_ids",
              sorted(leads[0]["signals"][0]["source_ids"])
              == ["clerk_recordings", "foreclosure_notices"])

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: §19 aggregator unit tests — "
              f"{len(failed)} of {len(checks)} checks failed")
        return 1

    print(f"PASS: §19 aggregator unit tests — all {len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
