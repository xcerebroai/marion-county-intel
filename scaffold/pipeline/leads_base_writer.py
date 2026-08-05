"""
leads_base_writer — v5.4.0 staged pipeline, stage 3 (the base-file writer).

STATUS: IMPLEMENTED in v5.4.0 Session 3. This stage takes debtor-resolved
records (debtor_resolved_record.schema.json), stamps each with its §18.B
aggregation key and resolved signal_type, attaches the §13.14 status pair
(parcel_resolution_status, enrichment_status) and the §18.J confidence_status,
and writes the stable per-source base file `<source>_leads_base.json`
(leads_base_record.schema.json).

Contracts:
  - knowledge_base/architecture/18_signal_aggregation_contract.md (the key,
    and the §18.J Session 3 amendment)
  - knowledge_base/architecture/19_aggregator_idempotency_rule.md (base files)
  - knowledge_base/protocols/02_build_mode_protocol.md §02.4 (writer duties)
  - knowledge_base/architecture/13_lead_origination_contract.md §13.14
    (parcel_resolution_status / enrichment_status decoupling)

§19.C makes the base file the load-bearing artifact: it is the ONLY input the
aggregator reads. Each base file is per-source and stable; the aggregator
re-derives `matched_leads.json` from the base files on every run, never from
its own previous output. One base record is written per debtor-resolved event —
within-source and cross-source grouping is the aggregator's job (§19), not
pre-collapsed here, so aggregation stays idempotent from a stable base.

§18.J — confidence_status: a record's confidence is rolled up ONCE here, by
`derive_confidence_status`, from the §08 evidence-ledger entries the record's
evidence_ids point to (the dashboard never computes confidence itself). The
roll-up is the weakest-evidence rule: a lead is never labelled more confident
than its least-supported claim.

Every base record MUST carry `source_url`, `instrument_number`, `recorded_date`,
and `evidence_ids` (§02.4). A lead is NEVER dropped because enrichment failed
(§13.14); the base record is written before enrichment runs, so
`enrichment_status` is always UNENRICHED at this stage.

This module is universal framework code: the `<source>_leads_base.json` naming
convention, the confidence roll-up rule, and the §13.14 status derivation are
universal; the per-county signal_type labels are passed in at call time. No
county / state / vendor literal appears here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

from jsonschema import Draft202012Validator

from scaffold.pipeline import aggregation_key_engine
from scaffold.pipeline.contracts import schema_path
from scaffold.pipeline.contracts.records import owner_block_from

# §18.J confidence roll-up tables.
#
# The four §08 prime-directive labels, ranked strongest -> weakest. A record's
# confidence_status is the WEAKEST label across its evidence entries.
_CONFIDENCE_RANK: dict[str, int] = {
    "Confirmed": 4,
    "Estimated": 3,
    "Possible": 2,
    "Unknown": 1,
}

# §08 evidence `status` -> prime-directive confidence label. The four prime
# labels map to themselves; "Needs Review" and "Unsupported" are not a positive
# confidence claim, so both count as Unknown.
_EVIDENCE_STATUS_TO_CONFIDENCE: dict[str, str] = {
    "Confirmed": "Confirmed",
    "Estimated": "Estimated",
    "Possible": "Possible",
    "Unknown": "Unknown",
    "Needs Review": "Unknown",
    "Unsupported": "Unknown",
}

_DEFAULT_CONFIDENCE = "Unknown"

# Lazy-cached JSON Schema validator for the leads-base record.
_VALIDATOR_CACHE: dict[str, Draft202012Validator] = {}


def _leads_base_validator() -> Draft202012Validator:
    if "v" not in _VALIDATOR_CACHE:
        schema = json.loads(
            schema_path("leads_base_record").read_text(encoding="utf-8")
        )
        _VALIDATOR_CACHE["v"] = Draft202012Validator(schema)
    return _VALIDATOR_CACHE["v"]


def _validate_base_record(record: dict) -> dict:
    """Validate a leads-base record against leads_base_record.schema.json.

    Raises ValueError when the record does not conform — a writer bug, which
    must fail loudly rather than write a malformed base file.
    """
    errors = sorted(
        _leads_base_validator().iter_errors(record), key=lambda e: list(e.path)
    )
    if errors:
        detail = "; ".join(
            f"{list(e.path) or '<root>'}: {e.message}" for e in errors
        )
        raise ValueError(
            "leads_base_writer: record violates leads_base_record.schema.json: "
            f"{detail}"
        )
    return record


def derive_confidence_status(
    evidence_ids: Sequence[str],
    *,
    evidence_ledger: Optional[dict] = None,
) -> str:
    """Roll up a record's §18.J confidence_status from its evidence (§18.J).

    The rule is explicit and deterministic:

      1. For every evidence-ledger entry the record's `evidence_ids` point to,
         map its §08 `status` to a prime-directive confidence label —
         Confirmed/Estimated/Possible/Unknown map to themselves; `Needs Review`
         and `Unsupported`, which are not a positive confidence claim, map to
         Unknown; a referenced-but-missing entry or unrecognised status also
         counts as Unknown.
      2. `confidence_status` is the WEAKEST (lowest-ranked) of those labels —
         Confirmed > Estimated > Possible > Unknown. A lead is never labelled
         more confident than its least-supported claim.
      3. A record with no evidence entries — or built with no evidence ledger
         available — is `Unknown`. Absence of evidence is not confidence.

    Args:
        evidence_ids: The record's evidence_ids.
        evidence_ledger: A mapping evidence_id -> evidence-ledger entry dict
            (each carrying a `status`). None or empty -> confidence is Unknown.

    Returns:
        One of "Confirmed", "Estimated", "Possible", "Unknown".
    """
    if not evidence_ids:
        return _DEFAULT_CONFIDENCE
    ledger = evidence_ledger or {}
    weakest_rank: Optional[int] = None
    weakest_label = _DEFAULT_CONFIDENCE
    for evidence_id in evidence_ids:
        entry = ledger.get(evidence_id)
        status = entry.get("status") if isinstance(entry, dict) else None
        label = _EVIDENCE_STATUS_TO_CONFIDENCE.get(status, _DEFAULT_CONFIDENCE)
        rank = _CONFIDENCE_RANK[label]
        if weakest_rank is None or rank < weakest_rank:
            weakest_rank, weakest_label = rank, label
    return weakest_label


def build_base_record(
    debtor_resolved_record: dict,
    *,
    signal_type_labels: dict,
    evidence_ledger: Optional[dict] = None,
) -> dict:
    """Build one leads-base record from a debtor-resolved record (§18 / §13.14).

    The contract:
      - resolve `signal_type` from `canonical_doc_type` (§18.B / §18.I);
      - compute the §18.B `aggregation_key` — its `parcel_id` is the resolved
        parcel id only when the parcel is RESOLVED, else null;
      - carry forward owner_name, owner_type, filer_entity, review_reason,
        source_url, instrument_number, recorded_date, event_date, evidence_ids,
        and property_refs from the debtor-resolved record;
      - set `parcel_resolution_status` (§13.14): REVIEW_REQUIRED when the
        debtor-resolved record's `debtor_resolution_status` is REVIEW_REQUIRED
        (the §17 engine writes no parcel-stage field — finding F-1); else
        RESOLVED when a parcel id is present, else UNRESOLVED;
      - set `enrichment_status` = UNENRICHED — the base record is written
        before enrichment runs; a lead is never dropped for enrichment failure;
      - roll up `confidence_status` via `derive_confidence_status` (§18.J).

    The output is validated against leads_base_record.schema.json.

    Args:
        debtor_resolved_record: A debtor-resolved record conforming to
            debtor_resolved_record.schema.json.
        signal_type_labels: The per-county canonical_doc_type -> display-label
            map.
        evidence_ledger: Optional mapping evidence_id -> evidence-ledger entry,
            used for the §18.J confidence roll-up. When omitted, confidence is
            Unknown.

    Returns:
        One leads-base record conforming to leads_base_record.schema.json.

    Raises:
        ValueError: if the writer produces a non-conforming record.
    """
    drr = debtor_resolved_record
    canonical_doc_type = drr.get("canonical_doc_type")
    signal_type = aggregation_key_engine.resolve_signal_type(
        canonical_doc_type, signal_type_labels=signal_type_labels or {}
    )

    property_refs = drr.get("property_refs") or {}
    parcel_id = property_refs.get("parcel_id")
    parcel_id = parcel_id if (parcel_id is not None and str(parcel_id).strip()) else None

    # §13.14 — parcel_resolution_status. The §17 engine wrote no parcel-stage
    # field (finding F-1); the writer derives it here.
    debtor_status = drr.get("debtor_resolution_status")
    if debtor_status == "REVIEW_REQUIRED":
        parcel_resolution_status = "REVIEW_REQUIRED"
    elif parcel_id is not None:
        parcel_resolution_status = "RESOLVED"
    else:
        parcel_resolution_status = "UNRESOLVED"

    # The aggregation-key parcel_id is non-null only on a RESOLVED parcel.
    key_parcel_id = parcel_id if parcel_resolution_status == "RESOLVED" else None
    aggregation_key = aggregation_key_engine.compute_aggregation_key(
        parcel_id=key_parcel_id,
        canonical_doc_type=canonical_doc_type,
        signal_type=signal_type,
    )

    evidence_ids = list(drr.get("evidence_ids") or [])
    confidence_status = derive_confidence_status(
        evidence_ids, evidence_ledger=evidence_ledger
    )

    raw_event_id = drr.get("raw_event_id")
    record = {
        "base_record_id": f"base_{raw_event_id}",
        "raw_event_id": raw_event_id,
        "source_id": drr.get("source_id"),
        "source_role": drr.get("source_role"),
        "canonical_doc_type": canonical_doc_type,
        "signal_type": signal_type,
        "aggregation_key": aggregation_key,
        "owner_name": drr.get("owner_name"),
        "owner_type": drr.get("owner_type"),
        "filer_entity": drr.get("filer_entity"),
        "review_reason": drr.get("review_reason"),
        "parcel_resolution_status": parcel_resolution_status,
        "enrichment_status": "UNENRICHED",
        "confidence_status": confidence_status,
        "instrument_number": drr.get("instrument_number"),
        "recorded_date": drr.get("recorded_date"),
        "event_date": drr.get("event_date"),
        "source_url": drr.get("source_url"),
        "evidence_ids": evidence_ids,
        "property_refs": {
            "parcel_id": property_refs.get("parcel_id"),
            "situs_address": property_refs.get("situs_address"),
            "legal_description": property_refs.get("legal_description"),
            "case_number": property_refs.get("case_number"),
        },
    }
    # v5.4.0 Session 7A — carry the debtor-resolved record's multi-owner block
    # forward (co-owners are never dropped between stages); derive SINGLE_OWNER
    # for a pre-7A single-owner debtor-resolved record.
    record.update(owner_block_from(
        drr,
        owner_name=drr.get("owner_name"),
        name_type=drr.get("expected_debtor_name_type"),
        role="debtor",
        resolution_status=drr.get("debtor_resolution_status"),
    ))
    return _validate_base_record(record)


def write_leads_base(
    source_id: str,
    base_records: Sequence[dict],
    *,
    output_dir: Path,
) -> Path:
    """Write the stable per-source base file `<source>_leads_base.json`.

    The output file is `<output_dir>/<source_id>_leads_base.json` — the
    §19.C / §19.G naming convention. The write is deterministic: records are
    ordered by `base_record_id` and keys are sorted, so re-running the writer
    on unchanged inputs produces a byte-identical file — the property that
    makes the downstream §19.D aggregator idempotency invariant achievable.

    Every record is validated against leads_base_record.schema.json before the
    file is written. A translator / writer MUST NOT modify another source's
    base file (§02.4).

    Args:
        source_id: The source identifier — the `<source>` in the filename.
        base_records: Leads-base records conforming to
            leads_base_record.schema.json.
        output_dir: Directory the base file is written to.

    Returns:
        The path to the written `<source_id>_leads_base.json` file.

    Raises:
        ValueError: if `source_id` is empty or a record does not conform.
    """
    if not isinstance(source_id, str) or not source_id.strip():
        raise ValueError("write_leads_base: source_id must be a non-empty string")

    records = [_validate_base_record(dict(r)) for r in base_records]
    records.sort(key=lambda r: r.get("base_record_id") or "")

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{source_id}_leads_base.json"
    path.write_text(
        json.dumps(records, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path
