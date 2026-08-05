"""
aggregator — v5.4.0 staged pipeline, stage 4 (the idempotent §19 aggregator).

STATUS: IMPLEMENTED in v5.4.0 Session 4. This stage reads the stable per-source
base files (`<source>_leads_base.json`) and produces `matched_leads.json`,
applying the §18 aggregation rules under the §19 idempotency contract.

Contracts:
  - knowledge_base/architecture/18_signal_aggregation_contract.md
  - knowledge_base/architecture/19_aggregator_idempotency_rule.md

Two-level grouping:

  1. SIGNAL grouping (§18.B) — leads-base records are grouped by the §18
     aggregation-key tuple (canonical_doc_type is the authoritative grouping
     discriminator, per the Session 3 F-4 resolution). Null-parcel records use
     the §18 F-3 fallback identity (instrument_number, else raw_event_id), so
     two distinct unresolved properties never collapse into one signal. Each
     group is merged into one signal by `merge_signal_group` (§18.C).
  2. LEAD grouping — signals are grouped into one matched lead per property:
     by parcel_id for RESOLVED parcels, by the F-3 fallback identity for
     null-parcel records.

§18.E / §18.F: a signal's `count` is the number of DISTINCT events — distinct
non-null instrument_numbers plus each null-instrument record. Two records that
share an instrument number are the same event ingested twice (a true
duplicate) and collapse to one; records with distinct instruments are
legitimate signal stacking and are each counted. Distinct doc types on one
property stay distinct signals (§18.F anti-collapse).

§19 idempotency — the load-bearing invariant:
  - the aggregator reads ONLY `*_leads_base.json` files (§19.C);
  - it NEVER reads its own output (`matched_leads.json`, `dashboard/data.json`)
    — `aggregate` refuses such an input with ValueError (§19.B / §19.C);
  - every step is deterministic (stable sorts, stable ids), so running twice
    on the same base files yields byte-identical `matched_leads.json` (§19.D);
  - when `aggregate` writes output it runs the §19.E self-check and refuses to
    deploy (raises) if the second run differs.

The matched-lead owner-identity fields (owner_name, owner_type, filer_entity,
review_reason, parcel_resolution_status, enrichment_status) are taken from a
deterministic representative leads-base record — the one with the
lexicographically smallest base_record_id in the property group. §18/§19 do
not specify multi-record owner derivation; this rule is deterministic, which
§19.D requires. Within a real property group the owner fields agree; the rule
only ever acts as a stable tie-break.

This module is universal framework code: the `<source>_leads_base.json` naming
convention and the aggregation rules are universal; the per-county base-file
inventory is read from config/counties/<county_slug>.json. No county / state /
vendor literal appears here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

from jsonschema import Draft202012Validator

from scaffold.pipeline import aggregation_key_engine
from scaffold.pipeline.contracts import schema_path
from scaffold.pipeline.contracts.records import owner_block_from

# §19.C — names the aggregator must never accept as input (its own output).
_OWN_OUTPUT_NAMES = {"matched_leads.json"}

_VALIDATOR_CACHE: dict[str, Draft202012Validator] = {}


def _validator(contract_name: str) -> Draft202012Validator:
    if contract_name not in _VALIDATOR_CACHE:
        schema = json.loads(
            schema_path(contract_name).read_text(encoding="utf-8")
        )
        _VALIDATOR_CACHE[contract_name] = Draft202012Validator(schema)
    return _VALIDATOR_CACHE[contract_name]


def _validate(record: dict, contract_name: str, what: str) -> dict:
    errors = sorted(
        _validator(contract_name).iter_errors(record), key=lambda e: list(e.path)
    )
    if errors:
        detail = "; ".join(
            f"{list(e.path) or '<root>'}: {e.message}" for e in errors
        )
        raise ValueError(
            f"aggregator: {what} violates {contract_name}.schema.json: {detail}"
        )
    return record


def _serialize(matched_leads: list) -> str:
    """Deterministic serialization of matched_leads.json (§19.D)."""
    return json.dumps(
        matched_leads, indent=2, sort_keys=True, ensure_ascii=False
    ) + "\n"


def _guard_input_paths(
    paths: Sequence[Path], output_path: Optional[Path]
) -> None:
    """Enforce §19.C — the aggregator reads only stable base files.

    Raises ValueError if any input is the aggregator's own output, a dashboard
    artifact, equal to output_path, or not a `<source>_leads_base.json` file.
    """
    resolved_output = (
        Path(output_path).resolve() if output_path is not None else None
    )
    for path in paths:
        name = path.name
        if name in _OWN_OUTPUT_NAMES:
            raise ValueError(
                f"§19.C: the aggregator MUST NEVER read its own output — input "
                f"path '{path}' is matched_leads.json. Reading the aggregate "
                f"as input re-aggregates prior leads and inflates counts on "
                f"every run (§19.B)."
            )
        if name == "data.json" and path.parent.name == "dashboard":
            raise ValueError(
                f"§19.C: the aggregator MUST NEVER read dashboard/data.json — "
                f"input path '{path}' is a dashboard artifact, not a base file."
            )
        if resolved_output is not None and path.resolve() == resolved_output:
            raise ValueError(
                f"§19.C: input path '{path}' equals output_path — the "
                f"aggregator cannot read its own output."
            )
        if not name.endswith("_leads_base.json"):
            raise ValueError(
                f"§19.C: aggregator inputs must be stable "
                f"<source>_leads_base.json files — '{path}' is not. The "
                f"aggregator reads only per-source base files."
            )


def _read_base_file(path: Path) -> list[dict]:
    """Read and schema-validate one `<source>_leads_base.json` file."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ValueError(f"aggregator: base file not found — {path}")
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"aggregator: base file is not valid JSON — {path}: {exc}"
        )
    if not isinstance(data, list):
        raise ValueError(
            f"aggregator: a base file must be a JSON array of leads-base "
            f"records — {path}"
        )
    for record in data:
        if not isinstance(record, dict):
            raise ValueError(
                f"aggregator: base file {path} contains a non-object record"
            )
        _validate(record, "leads_base_record", "an input leads-base record")
    return data


def _property_identity(record: dict) -> tuple:
    """The property a leads-base record belongs to (the lead-grouping key).

    RESOLVED parcels group by parcel_id; null-parcel records group by the §18
    F-3 fallback identity, so distinct unresolved properties never merge.
    """
    key = record.get("aggregation_key") or {}
    parcel_id = key.get("parcel_id")
    if parcel_id is not None:
        return ("parcel", str(parcel_id))
    return (
        "unresolved",
        aggregation_key_engine.null_parcel_fallback_identity(record),
    )


def merge_signal_group(base_records: Sequence[dict]) -> dict:
    """Merge base records that share an aggregation key into one signal (§18.C).

    Given N leads-base records that share the full §18.B aggregation key, the
    merged signal carries the §18.C fields. `count` is the number of DISTINCT
    events (§18.E): distinct non-null instrument_numbers plus each
    null-instrument record. Records sharing an instrument number are the same
    event ingested twice — a true duplicate — and collapse to one; records
    with distinct instruments are legitimate stacking and are each counted.

    Args:
        base_records: Leads-base records that share one aggregation key.

    Returns:
        One signal-group dict conforming to the `signals[]` item shape in
        matched_lead_record.schema.json.
    """
    records = list(base_records)
    if not records:
        raise ValueError("merge_signal_group: cannot merge an empty group")

    key = records[0].get("aggregation_key") or {}
    canonical_doc_type = key.get("canonical_doc_type")
    signal_type = key.get("signal_type")

    instrument_numbers = list(
        aggregation_key_engine.distinct_instrument_numbers(records)
    )
    null_instrument_records = sum(
        1
        for r in records
        if not (r.get("instrument_number")
                and str(r.get("instrument_number")).strip())
    )
    # §18.E: count is distinct events — true duplicates (shared instrument)
    # collapse; null-instrument records cannot be deduped, so each counts once.
    count = len(instrument_numbers) + null_instrument_records

    source_urls = sorted(
        {r["source_url"] for r in records if r.get("source_url")}
    )
    evidence_ids = sorted(
        {e for r in records for e in (r.get("evidence_ids") or [])}
    )
    source_ids = sorted(
        {r["source_id"] for r in records if r.get("source_id")}
    )
    dates = sorted(
        r["recorded_date"] for r in records if r.get("recorded_date")
    )
    earliest = dates[0] if dates else None
    latest = dates[-1] if dates else None

    return {
        "aggregation_key": {
            "parcel_id": key.get("parcel_id"),
            "canonical_doc_type": canonical_doc_type,
            "signal_type": signal_type,
        },
        "signal_type": signal_type,
        "canonical_doc_type": canonical_doc_type,
        "count": count,
        "instrument_numbers": instrument_numbers,
        "source_urls": source_urls,
        "evidence_ids": evidence_ids,
        "source_ids": source_ids,
        "earliest_recorded_date": earliest,
        "latest_recorded_date": latest,
        "recorded_date_range": [earliest, latest],
    }


def _build_matched_lead(property_identity: tuple, signal_groups: list) -> dict:
    """Build one matched-lead record from a property's signal groups."""
    signals = [merge_signal_group(group) for (_tup, group) in signal_groups]
    signals.sort(key=lambda s: (s["canonical_doc_type"], s["signal_type"]))

    all_records = [r for (_tup, group) in signal_groups for r in group]
    # Deterministic representative — the smallest base_record_id (§19.D).
    representative = min(
        all_records, key=lambda r: r.get("base_record_id") or ""
    )

    kind, identity = property_identity
    if kind == "parcel":
        lead_id = f"lead_parcel_{identity}"
        primary_parcel_id: Optional[str] = identity
    else:
        lead_id = f"lead_unresolved_{identity}"
        primary_parcel_id = None

    source_ids = sorted({s for sig in signals for s in sig["source_ids"]})
    evidence_ids = sorted({e for sig in signals for e in sig["evidence_ids"]})

    record = {
        "lead_id": lead_id,
        "primary_parcel_id": primary_parcel_id,
        "owner_name": representative.get("owner_name"),
        "owner_type": representative.get("owner_type"),
        "filer_entity": representative.get("filer_entity"),
        "review_reason": representative.get("review_reason"),
        "parcel_resolution_status": representative.get(
            "parcel_resolution_status"
        ),
        "enrichment_status": representative.get("enrichment_status"),
        "signals": signals,
        "source_ids": source_ids,
        "evidence_ids": evidence_ids,
    }
    # v5.4.0 Session 7A — carry the representative leads-base record's
    # multi-owner block onto the matched lead; derive SINGLE_OWNER for a pre-7A
    # single-owner representative.
    record.update(owner_block_from(
        representative,
        owner_name=representative.get("owner_name"),
        name_type=None,
        role="debtor",
        resolution_status=representative.get("parcel_resolution_status"),
    ))
    return record


def _build_matched_leads(records: list[dict]) -> list[dict]:
    """Group leads-base records into validated matched-lead records."""
    # Level 1 — group by the §18 aggregation-key tuple into signal groups.
    signal_groups: dict[tuple, list[dict]] = {}
    for record in records:
        key = record.get("aggregation_key") or {}
        fallback_identity = None
        if key.get("parcel_id") is None:
            fallback_identity = aggregation_key_engine.null_parcel_fallback_identity(
                record
            )
        group_tuple = aggregation_key_engine.aggregation_key_tuple(
            key, fallback_identity=fallback_identity
        )
        signal_groups.setdefault(group_tuple, []).append(record)

    # Level 2 — group signals into one matched lead per property.
    leads: dict[tuple, list] = {}
    for group_tuple, group in signal_groups.items():
        prop = _property_identity(group[0])
        leads.setdefault(prop, []).append((group_tuple, group))

    matched = [
        _build_matched_lead(prop, sig_groups)
        for prop, sig_groups in leads.items()
    ]
    matched.sort(key=lambda m: m["lead_id"])
    for lead in matched:
        _validate(lead, "matched_lead_record", "a matched-lead record")
    return matched


def aggregate(
    base_file_paths: Sequence[Path],
    *,
    output_path: Optional[Path] = None,
) -> list[dict]:
    """Aggregate per-source base files into matched-lead records (§18 / §19).

    Reads each `<source>_leads_base.json` in `base_file_paths`, groups the
    leads-base records into signals and matched leads, and returns the
    matched-lead records (sorted by lead_id — deterministic). When
    `output_path` is given, also writes `matched_leads.json` there and runs the
    §19.E idempotency self-check, raising RuntimeError if it fails.

    HARD CONTRACT (§19.C): this function reads ONLY `<source>_leads_base.json`
    inputs. It refuses — raises ValueError — if any input is matched_leads.json,
    dashboard/data.json, equal to output_path, or otherwise not a base file.

    Args:
        base_file_paths: Paths to the stable per-source base files — the ONLY
            permitted input.
        output_path: Where to write matched_leads.json. When None, the result
            is returned without being written (a dry run).

    Returns:
        A list of matched-lead records conforming to
        matched_lead_record.schema.json.

    Raises:
        ValueError: if any input path is the aggregator's own output (§19.C),
            or a base file is malformed.
        RuntimeError: if the §19.E idempotency self-check fails.
    """
    paths = [Path(p) for p in base_file_paths]
    _guard_input_paths(paths, output_path)

    records: list[dict] = []
    for path in paths:
        records.extend(_read_base_file(path))

    matched_leads = _build_matched_leads(records)

    if output_path is not None:
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_serialize(matched_leads), encoding="utf-8")
        # §19.E — self-check: a second run must reproduce the written file.
        if not idempotency_self_check(base_file_paths, output_path=output_path):
            raise RuntimeError(
                "§19.E: aggregator idempotency self-check FAILED — a second "
                "run produced different output. The aggregator is "
                "non-idempotent; refusing to deploy."
            )
    return matched_leads


def idempotency_self_check(
    base_file_paths: Sequence[Path],
    *,
    output_path: Path,
) -> bool:
    """Run the §19.E idempotency self-check.

    Re-runs `aggregate` in dry-run mode (no write) on the same base files and
    compares its serialized output byte-for-byte against the `matched_leads.json`
    already written at `output_path` (§19.D / §19.E).

    Args:
        base_file_paths: The same per-source base files passed to `aggregate`.
        output_path: The matched_leads.json written by the prior `aggregate`.

    Returns:
        True when the second run is byte-identical to `output_path`
        (idempotent); False when it differs or `output_path` is missing
        (non-idempotent — refuse deploy).
    """
    output_path = Path(output_path)
    if not output_path.is_file():
        return False
    written = output_path.read_text(encoding="utf-8")
    # Dry run — output_path omitted, so this aggregate neither writes nor
    # re-enters the self-check.
    rerun = aggregate(base_file_paths)
    return _serialize(rerun) == written
