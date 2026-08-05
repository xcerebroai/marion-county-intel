"""
v5.4.0 pipeline inter-stage data contracts.

This package is the design lock for the v5.4.0 staged pipeline engine. It
defines — as executable artifacts — every data shape that crosses a stage
boundary, so that Sessions 2-5 build the engine against a fixed spec.

Two parallel representations of each contract:

  - JSON Schema (`*.schema.json`) — for runtime data validation.
  - Frozen Python dataclasses (`records.py`) — for typed construction and
    for the engine modules' type hints.

The five contracts, in pipeline order (see knowledge_base/architecture/16-20
and knowledge_base/protocols/02):

  1. raw_event_record       — output of a source translator
  2. debtor_resolved_record — output of the debtor party engine (17)
  3. leads_base_record      — one record in <source>_leads_base.json
  4. matched_lead_record    — one record in matched_leads.json (aggregator out)
  5. evidence_ledger_entry  — one evidence object (08)

This package contains contract definitions only — no engine logic. The engine
modules that consume these contracts are scaffold/pipeline/debtor_party_engine,
aggregation_key_engine, aggregator, and leads_base_writer.

Universal framework code: no county / state / vendor literal appears here.
"""

from __future__ import annotations

from pathlib import Path

from scaffold.pipeline.contracts.records import (
    AggregationKey,
    CONTRACT_DATACLASSES,
    CONTRACT_SCHEMA_FILES,
    DEBTOR_EXTRACTION_METHODS,
    DEBTOR_RESOLUTION_STATUSES,
    DealPath,
    DebtorResolvedRecord,
    ENRICHMENT_STATUSES,
    EVIDENCE_STATUSES,
    EvidenceLedgerEntry,
    LeadsBaseRecord,
    LEAD_STATUSES,
    MatchedLeadRecord,
    MonetaryAmount,
    NAME_TYPES,
    OWNER_TYPES,
    ParcelDisplay,
    PARCEL_RESOLUTION_STATUSES,
    Party,
    POST_SCORING_LEAD_STATUSES,
    PropertyRefs,
    RawEventRecord,
    SCORE_TIER_VALUES,
    SOURCE_CLASSES,
    SOURCE_RELIABILITY_GRADES,
    SOURCE_ROLES,
    ScoreReason,
    ScoredLeadRecord,
    SignalGroup,
    TITLE_COMPLEXITY_TIER_VALUES,
    TitleComplexityContributor,
)

CONTRACTS_DIR = Path(__file__).resolve().parent
"""Absolute path to this package directory — where the *.schema.json files live."""


def schema_path(contract_name: str) -> Path:
    """Return the absolute path to a contract's JSON Schema file.

    Args:
        contract_name: One of the keys in CONTRACT_SCHEMA_FILES.

    Returns:
        Absolute Path to the `<contract_name>.schema.json` file.

    Raises:
        KeyError: if `contract_name` is not a recognized contract.
    """
    return CONTRACTS_DIR / CONTRACT_SCHEMA_FILES[contract_name]


__all__ = [
    "AggregationKey",
    "CONTRACTS_DIR",
    "CONTRACT_DATACLASSES",
    "CONTRACT_SCHEMA_FILES",
    "DEBTOR_EXTRACTION_METHODS",
    "DEBTOR_RESOLUTION_STATUSES",
    "DealPath",
    "DebtorResolvedRecord",
    "ENRICHMENT_STATUSES",
    "EVIDENCE_STATUSES",
    "EvidenceLedgerEntry",
    "LEAD_STATUSES",
    "LeadsBaseRecord",
    "MatchedLeadRecord",
    "MonetaryAmount",
    "NAME_TYPES",
    "OWNER_TYPES",
    "PARCEL_RESOLUTION_STATUSES",
    "POST_SCORING_LEAD_STATUSES",
    "ParcelDisplay",
    "Party",
    "PropertyRefs",
    "RawEventRecord",
    "SCORE_TIER_VALUES",
    "SOURCE_CLASSES",
    "SOURCE_RELIABILITY_GRADES",
    "SOURCE_ROLES",
    "ScoreReason",
    "ScoredLeadRecord",
    "SignalGroup",
    "TITLE_COMPLEXITY_TIER_VALUES",
    "TitleComplexityContributor",
    "schema_path",
]
