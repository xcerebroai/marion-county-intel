"""
Owner-name pattern signal emitter (v5.1.2-beta+, county-agnostic).

Reads a parcel-master parcel's owner_name field. If the string matches
a registered pattern (estate, living_trust), emits a framework signal
that stacks on any lead-generating signals already attached to that
parcel.

CRITICAL INVARIANT (v5.1.2-beta defensive guard, audit Q9):

  This module NEVER emits a signal for a parcel that is not already
  linked to at least one lead-generating signal in the current run.
  Standalone parcels — enrichment-only records the matcher hasn't
  yet attached to a lead — cannot produce a lead row.

  Callers must pass the set of parcel IDs that already carry a
  lead-generating signal:

      emitted = emit_owner_name_signals_for_parcel(
          parcel=parcel,
          parcels_with_lead_signals=parcels_with_lead_signals,
          source_id="<id>",
      )

  If parcel["parcel_id"] is NOT in parcels_with_lead_signals, the
  emitter returns []. The pipeline's clerk-driven product rule is
  thus enforced at this layer, not just in the orchestrator.

Patterns (operator spec, formalized in canonical_doc_types.json):

  ESTATE_PATTERN:  \\b(ESTATE OF|EST OF|ESTATE|HEIRS OF|HEIRS)\\b
  -> ESTATE_OWNER_NAME_PATTERN canonical, default_confidence 75

  LIVING_TRUST_PATTERN: \\b(LIVING TRUST|FAMILY TRUST|REVOCABLE TRUST|
                             REV TRUST|TRUST|TRUSTEE)\\b
  -> LIVING_TRUST_OWNER_NAME_PATTERN canonical, default_confidence 70

The patterns themselves are framework-canonical (declared in
knowledge_base/domain/canonical_doc_types.json). Counties don't
configure these patterns; they apply universally to any
parcel-master source. If a county wants to disable owner-name-pattern
signals, they can omit the emit_owner_name_signals call from their
pipeline run (config-driven; not yet exposed but planned).
"""

from __future__ import annotations
import hashlib
import re


ESTATE_PATTERN = re.compile(
    r"\b(ESTATE\s+OF|EST\s+OF|ESTATE|HEIRS\s+OF|HEIRS)\b",
    re.IGNORECASE,
)
LIVING_TRUST_PATTERN = re.compile(
    r"\b(LIVING\s+TRUST|FAMILY\s+TRUST|REVOCABLE\s+TRUST|REV\s+TRUST|TRUST|TRUSTEE)\b",
    re.IGNORECASE,
)


def _signal_id(parts: tuple[str, ...]) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"sig_owner_{h}"


def emit_owner_name_signals_for_parcel(
    parcel: dict,
    parcels_with_lead_signals: set[str],
    source_id: str = "parcel_master",
) -> list[dict]:
    """
    Emit framework signals based on parcel.owner_name patterns.

    The DEFENSIVE GUARD (audit Q9 / v5.1.2-beta): standalone parcels
    not already linked to a lead-generating signal CANNOT produce
    a signal here. This enforces the clerk-driven product rule
    at the emitter level.

    Args:
        parcel: A parcel dict with at least `parcel_id` and `owner_name`.
        parcels_with_lead_signals: Set of parcel IDs that already carry
            at least one lead-generating signal in the current run.
            Pass an empty set to disable emission (testing only).
        source_id: Source ID stamp for the emitted signals.

    Returns:
        List of emitted signal dicts (0, 1, or 2 entries).
    """
    if not parcel.get("owner_name"):
        return []

    parcel_id = parcel.get("parcel_id")
    if not parcel_id:
        return []

    # DEFENSIVE GUARD — clerk-driven product rule.
    if parcel_id not in parcels_with_lead_signals:
        return []

    owner = parcel["owner_name"].strip()
    if not owner:
        return []

    emitted: list[dict] = []

    estate_match = ESTATE_PATTERN.search(owner)
    if estate_match:
        signal_id = _signal_id((parcel_id, "ESTATE_OWNER_NAME_PATTERN", owner))
        source_url = f"about:owner-name/{source_id}/{parcel_id}#estate"
        emitted.append({
            "signal_id": signal_id,
            "raw_record_id": f"raw_owner_name_{parcel_id}",
            "source_id": source_id,
            "source_url": source_url,
            "doc_type": "ESTATE_OWNER_NAME_PATTERN",
            "doc_type_subtype_label": "Estate owner-name pattern",
            "doc_number": f"OWNER-{parcel_id}",
            "primary_parcel_id": parcel_id,
            "filing_date": None,
            "parser_confidence": 75,
            "_owner_name_literal_match": estate_match.group(0),
            "_owner_name_full": owner,
        })

    trust_match = LIVING_TRUST_PATTERN.search(owner)
    if trust_match:
        signal_id = _signal_id((parcel_id, "LIVING_TRUST_OWNER_NAME_PATTERN", owner))
        source_url = f"about:owner-name/{source_id}/{parcel_id}#trust"
        emitted.append({
            "signal_id": signal_id,
            "raw_record_id": f"raw_owner_name_{parcel_id}",
            "source_id": source_id,
            "source_url": source_url,
            "doc_type": "LIVING_TRUST_OWNER_NAME_PATTERN",
            "doc_type_subtype_label": "Living-trust owner-name pattern",
            "doc_number": f"OWNER-{parcel_id}",
            "primary_parcel_id": parcel_id,
            "filing_date": None,
            "parser_confidence": 70,
            "_owner_name_literal_match": trust_match.group(0),
            "_owner_name_full": owner,
        })

    return emitted


def emit_owner_name_signals_for_parcels(
    parcels: list[dict],
    parcels_with_lead_signals: set[str],
    source_id: str = "parcel_master",
) -> list[dict]:
    """Batch helper. Same defensive guard applies per parcel."""
    out: list[dict] = []
    for p in parcels:
        out.extend(
            emit_owner_name_signals_for_parcel(
                p, parcels_with_lead_signals, source_id
            )
        )
    return out
