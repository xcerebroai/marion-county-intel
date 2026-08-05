"""
evidence_ledger — v5.4.0 staged pipeline, the §08 evidence-ledger artifact.

STATUS: IMPLEMENTED in v5.4.0 Session 5. The staged pipeline (§17 → §18 → §19)
carries `evidence_ids` — string references — on every record from the raw event
through the matched lead. This module wires the evidence ledger itself through:
it builds, validates, writes, and traces the `evidence_ledger_entry` objects
(evidence_ledger_entry.schema.json) those ids point to, so that every claim on
every matched lead resolves to a real evidence entry (§08 — every field shown,
stored, exported, or scored must have backing evidence).

Contract: knowledge_base/architecture/08_evidence_ledger.md and the Session 1
evidence_ledger_entry.schema.json.

`build_evidence_ledger` validates entries and indexes them by evidence_id.
`verify_evidence_traceability` confirms every evidence_id referenced by a
matched lead (and its signals) resolves to an indexed entry — an untraceable
claim is a §08 violation. `write_evidence_ledger` writes the stable
`evidence_ledger.json` artifact alongside `matched_leads.json`, deterministically
(stable ordering) so re-runs are byte-identical.

This module is universal framework code: no county / state / vendor literal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional, Sequence

from jsonschema import Draft202012Validator

from scaffold.pipeline.contracts import schema_path

_VALIDATOR_CACHE: dict[str, Draft202012Validator] = {}


def _entry_validator() -> Draft202012Validator:
    if "v" not in _VALIDATOR_CACHE:
        schema = json.loads(
            schema_path("evidence_ledger_entry").read_text(encoding="utf-8")
        )
        _VALIDATOR_CACHE["v"] = Draft202012Validator(schema)
    return _VALIDATOR_CACHE["v"]


def _validate_entry(entry: dict) -> dict:
    """Validate one evidence-ledger entry against evidence_ledger_entry.schema.json."""
    errors = sorted(
        _entry_validator().iter_errors(entry), key=lambda e: list(e.path)
    )
    if errors:
        detail = "; ".join(
            f"{list(e.path) or '<root>'}: {e.message}" for e in errors
        )
        raise ValueError(
            f"evidence_ledger: an entry violates "
            f"evidence_ledger_entry.schema.json: {detail}"
        )
    return entry


def build_evidence_ledger(entries: Sequence[dict]) -> dict:
    """Validate evidence entries and index them by evidence_id.

    Every entry is validated against evidence_ledger_entry.schema.json. A
    duplicate evidence_id is a hard error — an evidence id must identify one
    evidence object.

    Args:
        entries: Evidence-ledger entry dicts.

    Returns:
        A mapping evidence_id -> evidence entry.

    Raises:
        ValueError: on a non-conforming entry or a duplicate evidence_id.
    """
    ledger: dict[str, dict] = {}
    for entry in entries:
        _validate_entry(entry)
        evidence_id = entry["evidence_id"]
        if evidence_id in ledger:
            raise ValueError(
                f"evidence_ledger: duplicate evidence_id '{evidence_id}' — an "
                f"evidence id must identify exactly one evidence object."
            )
        ledger[evidence_id] = entry
    return ledger


def verify_evidence_traceability(
    matched_leads: Sequence[dict],
    evidence_ledger: dict,
) -> dict:
    """Confirm every matched-lead claim traces to an evidence-ledger entry (§08).

    Every evidence_id referenced by a matched lead — at the lead level and on
    each of its signals — must resolve to an entry in `evidence_ledger`. An
    unresolved reference is a §08 violation: a claim with no backing evidence.

    Args:
        matched_leads: The aggregator's matched-lead records.
        evidence_ledger: An evidence_id -> entry index from
            `build_evidence_ledger`.

    Returns:
        A result dict — `traceable` (bool), `evidence_refs_checked`,
        `leads_checked`, and `missing` (the unresolved references).
    """
    missing = []
    refs_checked = 0
    for lead in matched_leads:
        referenced = set(lead.get("evidence_ids") or [])
        for signal in lead.get("signals") or []:
            referenced.update(signal.get("evidence_ids") or [])
        for evidence_id in sorted(referenced):
            refs_checked += 1
            if evidence_id not in evidence_ledger:
                missing.append({
                    "lead_id": lead.get("lead_id"),
                    "evidence_id": evidence_id,
                })
    return {
        "traceable": not missing,
        "leads_checked": len(matched_leads),
        "evidence_refs_checked": refs_checked,
        "missing": missing,
        "detail": (
            f"{refs_checked} evidence reference(s) across "
            f"{len(matched_leads)} matched lead(s) all resolve to evidence "
            f"entries."
            if not missing else
            f"{len(missing)} evidence reference(s) do not resolve to an "
            f"evidence-ledger entry — a §08 untraceable-claim violation."
        ),
    }


def write_evidence_ledger(
    entries: Sequence[dict],
    *,
    output_dir: Path,
) -> Path:
    """Write the stable `evidence_ledger.json` artifact.

    Every entry is validated and the file is written deterministically —
    entries ordered by evidence_id, keys sorted — so a re-run on unchanged
    input is byte-identical, the same idempotency property §19.D requires of
    matched_leads.json.

    Args:
        entries: Evidence-ledger entry dicts.
        output_dir: Directory the ledger file is written to.

    Returns:
        The path to the written `evidence_ledger.json`.

    Raises:
        ValueError: on a non-conforming entry.
    """
    validated = [_validate_entry(dict(e)) for e in entries]
    validated.sort(key=lambda e: e.get("evidence_id") or "")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "evidence_ledger.json"
    path.write_text(
        json.dumps(validated, indent=2, sort_keys=True, ensure_ascii=False)
        + "\n",
        encoding="utf-8",
    )
    return path
