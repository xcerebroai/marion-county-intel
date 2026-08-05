"""
v5.4.0 pipeline inter-stage data contracts — frozen Python typed structures.

This module is the executable Python mirror of the JSON Schema files in this
package. Every shape that crosses a stage boundary in the v5.4.0 staged engine
has both a `.schema.json` file (for data validation) and a frozen dataclass
here (for typed construction and the engine's own type hints).

The five inter-stage shapes, in pipeline order:

    RawEventRecord       stage 1 — output of a source translator
                         (raw_event_record.schema.json)
    DebtorResolvedRecord stage 2 — output of the debtor party engine (17)
                         (debtor_resolved_record.schema.json)
    LeadsBaseRecord      stage 3 — one record in <source>_leads_base.json,
                         output of the leads-base writer
                         (leads_base_record.schema.json)
    MatchedLeadRecord    stage 4 — one record in matched_leads.json,
                         output of the idempotent aggregator (19)
                         (matched_lead_record.schema.json)
    EvidenceLedgerEntry  evidence ledger stage — one evidence object (08)
                         (evidence_ledger_entry.schema.json)

These dataclasses are `frozen=True, kw_only=True`: instances are immutable, and
every field must be supplied by name. Collection fields are tuples, not lists,
so a constructed contract instance is fully immutable.

These are the design lock for v5.4.0 Sessions 2-5. No engine logic lives here —
this file defines shapes only. See knowledge_base/architecture/16-20 and
knowledge_base/protocols/02 for the governing contracts.

This module is universal framework code: it contains no county-specific,
state-specific, or vendor-specific literal. The county-agnostic regression
scanner enforces that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

# ---------------------------------------------------------------------------
# Enum value sets — the controlled vocabularies the contracts reference.
# Kept as tuples so they are importable, immutable, and testable.
# ---------------------------------------------------------------------------

SOURCE_ROLES: tuple[str, ...] = (
    "PRIMARY_EVENT_SOURCE",
    "SUPPORTING_EVENT_SOURCE",
    "ENRICHMENT_SOURCE",
    "REFERENCE_SOURCE",
    "BLOCKED_SOURCE",
)
"""16.E source-role contract. Only PRIMARY_EVENT_SOURCE originates a lead."""

NAME_TYPES: tuple[str, ...] = ("TP", "DF", "GR", "GE", "PL", "OTHER")
"""Party role codes. 17.C defines TP/DF/GR/GE; PL and OTHER are added by this
contract (see contract finding F-2 — 17.C names plaintiff filers but gives no
name_type code for them)."""

OWNER_TYPES: tuple[str, ...] = (
    "ENTITY",
    "ESTATE",
    "TRUST",
    "INDIVIDUAL",
    "UNKNOWN",
)
"""17.F owner-type classifier outputs. Precedence ENTITY > ESTATE > TRUST >
INDIVIDUAL; UNKNOWN only for empty / punctuation-only names."""

DEBTOR_RESOLUTION_STATUSES: tuple[str, ...] = ("RESOLVED", "REVIEW_REQUIRED")
"""The debtor party engine's own verdict (v5.4.0 inter-stage field — finding F-1)."""

DEBTOR_EXTRACTION_METHODS: tuple[str, ...] = (
    "STRUCTURED_NAME_TYPE",
    "FALLBACK_NAME_TYPE",
    "DOCUMENT_BODY",
    "REVIEW_ROUTED",
)
"""How owner_name was derived by the debtor party engine."""

PARCEL_RESOLUTION_STATUSES: tuple[str, ...] = (
    "RESOLVED",
    "UNRESOLVED",
    "REVIEW_REQUIRED",
)
"""13.14.1 parcel resolution status. REVIEW_REQUIRED is the 17.E debtor-routing
value."""

ENRICHMENT_STATUSES: tuple[str, ...] = ("ENRICHED", "UNENRICHED")
"""13.14.1 enrichment status. ENRICHED requires a RESOLVED parcel."""

EVIDENCE_STATUSES: tuple[str, ...] = (
    "Confirmed",
    "Estimated",
    "Possible",
    "Unknown",
    "Needs Review",
    "Unsupported",
)
"""08 evidence status labels."""

CONFIDENCE_STATUSES: tuple[str, ...] = (
    "Confirmed",
    "Estimated",
    "Possible",
    "Unknown",
)
"""18.J rolled-up confidence label for a leads-base record — the four 08
prime-directive labels. Derived from a record's evidence-ledger entries by the
weakest-evidence roll-up rule (leads_base_writer.derive_confidence_status)."""

MULTI_OWNER_STATUSES: tuple[str, ...] = (
    "SINGLE_OWNER",
    "MULTIPLE_OWNERS_PRIMARY_CLEAR",
    "MULTIPLE_OWNERS_PRIMARY_UNCLEAR",
)
"""v5.4.0 Session 7A multi-owner cardinality status (see 17.K). DESCRIPTIVE
only — owner count and primary clarity. NOT a review verdict: the needs-review
verdict stays debtor_resolution_status (debtor-resolved record) / a
REVIEW_REQUIRED parcel_resolution_status (downstream). There is deliberately no
REVIEW_REQUIRED value here; the descriptive and verdict fields can never
contradict."""

SOURCE_CLASSES: tuple[str, ...] = (
    "lead_generating",
    "enrichment",
    "negative_signal",
    "review_required",
)
"""08 / domain 02 source classes."""

SOURCE_RELIABILITY_GRADES: tuple[str, ...] = ("A", "B", "C", "D", "E")
"""08 source reliability grades."""

LEAD_STATUSES: tuple[str, ...] = (
    "RAW_RECORD",
    "NORMALIZED_SIGNAL",
    "MATCHED_PARCEL",
    "STACKED_LEAD",
    "REVIEW_REQUIRED",
    "APPROVED_FOR_DASHBOARD",
    "EXPORTED_TO_CRM",
    "CONTACTED",
    "DEAD",
    "ARCHIVED",
)
"""FRAMEWORK_VERSION.json lead_status_lifecycle."""

# Literal type aliases for field annotations.
SourceRole = Literal[
    "PRIMARY_EVENT_SOURCE",
    "SUPPORTING_EVENT_SOURCE",
    "ENRICHMENT_SOURCE",
    "REFERENCE_SOURCE",
    "BLOCKED_SOURCE",
]
NameType = Literal["TP", "DF", "GR", "GE", "PL", "OTHER"]
OwnerType = Literal["ENTITY", "ESTATE", "TRUST", "INDIVIDUAL", "UNKNOWN"]
DebtorResolutionStatus = Literal["RESOLVED", "REVIEW_REQUIRED"]
DebtorExtractionMethod = Literal[
    "STRUCTURED_NAME_TYPE", "FALLBACK_NAME_TYPE", "DOCUMENT_BODY", "REVIEW_ROUTED"
]
ParcelResolutionStatus = Literal["RESOLVED", "UNRESOLVED", "REVIEW_REQUIRED"]
EnrichmentStatus = Literal["ENRICHED", "UNENRICHED"]
EvidenceStatus = Literal[
    "Confirmed", "Estimated", "Possible", "Unknown", "Needs Review", "Unsupported"
]
ConfidenceStatus = Literal["Confirmed", "Estimated", "Possible", "Unknown"]
MultiOwnerStatus = Literal[
    "SINGLE_OWNER",
    "MULTIPLE_OWNERS_PRIMARY_CLEAR",
    "MULTIPLE_OWNERS_PRIMARY_UNCLEAR",
]


# ---------------------------------------------------------------------------
# Shared nested shapes.
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class Party:
    """A name-type-tagged party carried in a source row (17.C)."""

    name: str
    name_type: NameType
    raw_role: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class PropertyRefs:
    """Property identifiers carried in a source row. parcel_id may be null
    when the source does not link to a parcel (13.14)."""

    parcel_id: Optional[str] = None
    situs_address: Optional[str] = None
    legal_description: Optional[str] = None
    case_number: Optional[str] = None


@dataclass(frozen=True, kw_only=True)
class MonetaryAmount:
    """A labelled monetary amount carried in a source row."""

    label: str
    value: Optional[float] = None


@dataclass(frozen=True, kw_only=True)
class AggregationKey:
    """The 18.B aggregation key tuple (parcel_id, canonical_doc_type,
    signal_type) — the dedup boundary for signal aggregation."""

    parcel_id: Optional[str]
    canonical_doc_type: str
    signal_type: str


@dataclass(frozen=True, kw_only=True)
class Owner:
    """One distressed owner on a record's multi-owner block (v5.4.0 Session 7A).

    Co-owners are never dropped — every owner the engine identifies is an Owner
    in the record's `owners` tuple. `name_type` uses the existing NAME_TYPES
    enum, unextended (None when the document gives no role code)."""

    name: str
    is_primary: bool
    role: Optional[str] = None
    name_type: Optional[NameType] = None
    confidence: Optional[str] = None
    source_field: Optional[str] = None
    resolution_status: Optional[str] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Stage 1 — raw event record (output of a source translator).
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class RawEventRecord:
    """A normalized, source-specific raw event, before debtor-party resolution.
    Input to the debtor party engine. Mirror of raw_event_record.schema.json."""

    raw_event_id: str
    source_id: str
    source_role: SourceRole
    canonical_doc_type: str
    source_url: str
    recorded_date: Optional[str]
    instrument_number: Optional[str]
    parties: tuple[Party, ...] = ()
    property_refs: PropertyRefs = field(default_factory=PropertyRefs)
    raw_doc_type: Optional[str] = None
    event_date: Optional[str] = None
    document_body_text: Optional[str] = None
    amounts: tuple[MonetaryAmount, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    parser_confidence: Optional[float] = None
    captured_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Stage 2 — debtor-party-resolved record (output of the 17 engine).
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class DebtorResolvedRecord:
    """A raw event record with the 17 debtor identity attached. Mirror of
    debtor_resolved_record.schema.json.

    v5.4.0 finding F-1, RATIFIED Session 2: the 17 engine's verdict lives in
    `debtor_resolution_status` only. This record carries NO parcel-stage field
    — `parcel_resolution_status` first appears on LeadsBaseRecord."""

    raw_event_id: str
    source_id: str
    source_role: SourceRole
    canonical_doc_type: str
    source_url: str
    recorded_date: Optional[str]
    instrument_number: Optional[str]
    property_refs: PropertyRefs
    owner_name: str
    owner_type: OwnerType
    filer_entity: Optional[str]
    debtor_resolution_status: DebtorResolutionStatus
    review_reason: Optional[str]
    debtor_extraction_method: DebtorExtractionMethod
    expected_debtor_name_type: Optional[str] = None
    event_date: Optional[str] = None
    evidence_ids: tuple[str, ...] = ()
    owners: tuple[Owner, ...] = ()
    primary_owner_name: Optional[str] = None
    additional_owner_names: tuple[str, ...] = ()
    owner_count: Optional[int] = None
    multi_owner_status: Optional[MultiOwnerStatus] = None

    def __post_init__(self) -> None:
        _enforce_multi_owner_consistency(self)


# ---------------------------------------------------------------------------
# Stage 3 — leads-base record (one record in <source>_leads_base.json).
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class LeadsBaseRecord:
    """One record in the stable per-source base file <source>_leads_base.json.
    Mirror of leads_base_record.schema.json."""

    base_record_id: str
    raw_event_id: str
    source_id: str
    source_role: SourceRole
    canonical_doc_type: str
    signal_type: str
    aggregation_key: AggregationKey
    owner_name: str
    owner_type: OwnerType
    filer_entity: Optional[str]
    review_reason: Optional[str]
    parcel_resolution_status: ParcelResolutionStatus
    enrichment_status: EnrichmentStatus
    confidence_status: ConfidenceStatus
    instrument_number: Optional[str]
    recorded_date: Optional[str]
    source_url: str
    property_refs: PropertyRefs
    evidence_ids: tuple[str, ...] = ()
    event_date: Optional[str] = None
    owners: tuple[Owner, ...] = ()
    primary_owner_name: Optional[str] = None
    additional_owner_names: tuple[str, ...] = ()
    owner_count: Optional[int] = None
    multi_owner_status: Optional[MultiOwnerStatus] = None

    def __post_init__(self) -> None:
        _enforce_multi_owner_consistency(self)


# ---------------------------------------------------------------------------
# Stage 4 — matched-lead record (one record in matched_leads.json).
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class SignalGroup:
    """One aggregated signal on a matched lead — a group of leads-base records
    that shared the full 18.B aggregation key, merged per 18.C."""

    aggregation_key: AggregationKey
    signal_type: str
    canonical_doc_type: str
    count: int
    instrument_numbers: tuple[str, ...] = ()
    source_urls: tuple[str, ...] = ()
    evidence_ids: tuple[str, ...] = ()
    source_ids: tuple[str, ...] = ()
    earliest_recorded_date: Optional[str] = None
    latest_recorded_date: Optional[str] = None
    recorded_date_range: tuple[Optional[str], Optional[str]] = (None, None)


@dataclass(frozen=True, kw_only=True)
class MatchedLeadRecord:
    """One record in matched_leads.json, the idempotent aggregator output.
    Mirror of matched_lead_record.schema.json."""

    lead_id: str
    primary_parcel_id: Optional[str]
    owner_name: str
    owner_type: OwnerType
    filer_entity: Optional[str]
    review_reason: Optional[str]
    parcel_resolution_status: ParcelResolutionStatus
    enrichment_status: EnrichmentStatus
    signals: tuple[SignalGroup, ...]
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...] = ()
    lead_status: Optional[str] = None
    owners: tuple[Owner, ...] = ()
    primary_owner_name: Optional[str] = None
    additional_owner_names: tuple[str, ...] = ()
    owner_count: Optional[int] = None
    multi_owner_status: Optional[MultiOwnerStatus] = None

    def __post_init__(self) -> None:
        _enforce_multi_owner_consistency(self)


# ---------------------------------------------------------------------------
# Evidence ledger entry (08).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Stage 6 — scored_lead record (v5.4.0 Session 9 / Option Y seam).
# ---------------------------------------------------------------------------

SCORE_TIER_VALUES: tuple[str, ...] = (
    "Hot", "Strong", "Workable", "Low", "Archive",
)
"""Score tiers per score.py. Mirrors score.SCORE_TIERS — kept here as a
contract-side constant for the dataclass and the schema test."""

TITLE_COMPLEXITY_TIER_VALUES: tuple[str, ...] = (
    "None", "Light curative", "Moderate curative", "Heavy curative",
)
"""Title-complexity tiers per build_leads._title_complexity."""

POST_SCORING_LEAD_STATUSES: tuple[str, ...] = (
    "STACKED_LEAD", "REVIEW_REQUIRED", "APPROVED_FOR_DASHBOARD",
)
"""The three lead_status values a scored_lead may carry — the post-scoring
+ review-evaluation subset of LEAD_STATUSES."""

ScoreTier = Literal["Hot", "Strong", "Workable", "Low", "Archive"]
TitleComplexityTier = Literal[
    "None", "Light curative", "Moderate curative", "Heavy curative"
]
PostScoringLeadStatus = Literal[
    "STACKED_LEAD", "REVIEW_REQUIRED", "APPROVED_FOR_DASHBOARD"
]


@dataclass(frozen=True, kw_only=True)
class ScoreReason:
    """One factor / delta line on a scored_lead's score breakdown."""

    factor: str
    delta: int


@dataclass(frozen=True, kw_only=True)
class DealPath:
    """One deal-path classification on a scored_lead."""

    path: str
    confidence: Literal["high", "moderate", "low"]
    rationale: str


@dataclass(frozen=True, kw_only=True)
class TitleComplexityContributor:
    """One contributor / weight line on a scored_lead's title-complexity
    breakdown."""

    factor: str
    weight: int


@dataclass(frozen=True, kw_only=True)
class ParcelDisplay:
    """The optional parcel-master snapshot a scored_lead carries when
    enrichment is present (R3(iii) modifier path). Absent (None) when the
    scored_lead is UNENRICHED — the dashboard renders without one."""

    situs_address: Optional[str] = None
    situs_city: Optional[str] = None
    situs_state: Optional[str] = None
    owner_mailing_address: Optional[str] = None
    owner_mailing_city: Optional[str] = None
    owner_mailing_state: Optional[str] = None
    owner_mailing_zip: Optional[str] = None
    assessed_value: Optional[float] = None
    last_sale_price: Optional[float] = None
    last_sale_date: Optional[str] = None
    year_built: Optional[int] = None


@dataclass(frozen=True, kw_only=True)
class ScoredLeadRecord:
    """One record in scored_leads.json. v5.4.0 Session 9 (Option Y).

    A scored_lead WRAPS a matched_lead BY REFERENCE — it carries the
    matched_lead's `lead_id` and the seam-derived scoring / classification /
    title-complexity / review output, plus an optional parcel-display
    enrichment snapshot. matched_lead is the immutable §19 output of record;
    scored_lead never mutates it.

    Enrichment is OPTIONAL (R3(iii) / §13.14): scoring runs on distress
    signals from the staged pipeline. Parcel-master enrichment is a MODIFIER
    applied when present, absent without blocking. `enrichment_status`
    records honestly whether enrichment was attached; a UNENRICHED lead is
    still scored, still review-evaluated, still reaches the dashboard."""

    scored_lead_id: str
    lead_id: str
    primary_parcel_id: Optional[str]
    owner_name: str
    owner_type: OwnerType
    score: int
    tier: ScoreTier
    score_reasons: tuple[ScoreReason, ...]
    deal_paths: tuple[DealPath, ...]
    title_complexity_score: int
    title_complexity_tier: TitleComplexityTier
    title_complexity_contributors: tuple[TitleComplexityContributor, ...]
    pattern_set: tuple[str, ...]
    patterns: tuple[str, ...]
    display_patterns: tuple[str, ...]
    stack_depth: int
    recent_flag: bool
    attributes: tuple[str, ...]
    review_flags: tuple[str, ...]
    lead_status: PostScoringLeadStatus
    enrichment_status: EnrichmentStatus
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    primary_event_date: Optional[str] = None
    match_confidence: Optional[int] = None
    doc_type_normalization: Optional[dict] = None
    parcel_display: Optional[ParcelDisplay] = None
    lead_status_history: tuple[dict, ...] = ()

    def __post_init__(self) -> None:
        # R3(iii) enrichment-optional consistency: parcel_display is present
        # iff enrichment_status is ENRICHED. Catches construction bugs early.
        if self.enrichment_status == "UNENRICHED" and self.parcel_display is not None:
            raise ValueError(
                "scored_lead contract violation: UNENRICHED scored_lead must "
                "have parcel_display = None"
            )
        if self.enrichment_status == "ENRICHED" and self.parcel_display is None:
            raise ValueError(
                "scored_lead contract violation: ENRICHED scored_lead must "
                "carry a parcel_display block"
            )


@dataclass(frozen=True, kw_only=True)
class EvidenceLedgerEntry:
    """One evidence object backing one claim (08). Mirror of
    evidence_ledger_entry.schema.json."""

    evidence_id: str
    record_id: str
    field: str
    value: Any
    status: EvidenceStatus
    source_id: str
    source_reliability_grade: str
    source_url: str
    captured_at: str
    source_name: Optional[str] = None
    source_class: Optional[str] = None
    source_document_id: Optional[str] = None
    source_row_id: Optional[str] = None
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    parser_confidence: Optional[float] = None
    match_confidence: Optional[float] = None
    derivation: Optional[dict] = None
    notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Contract registry — maps each contract name to its schema file and dataclass.
# Sessions 2-5 and the v5_4_0 contract-shape tests resolve schemas through this.
# ---------------------------------------------------------------------------

CONTRACT_SCHEMA_FILES: dict[str, str] = {
    "raw_event_record": "raw_event_record.schema.json",
    "debtor_resolved_record": "debtor_resolved_record.schema.json",
    "leads_base_record": "leads_base_record.schema.json",
    "matched_lead_record": "matched_lead_record.schema.json",
    "scored_lead_record": "scored_lead_record.schema.json",
    "evidence_ledger_entry": "evidence_ledger_entry.schema.json",
}
"""Contract name -> JSON Schema filename (relative to this package)."""

CONTRACT_DATACLASSES: dict[str, type] = {
    "raw_event_record": RawEventRecord,
    "debtor_resolved_record": DebtorResolvedRecord,
    "leads_base_record": LeadsBaseRecord,
    "matched_lead_record": MatchedLeadRecord,
    "scored_lead_record": ScoredLeadRecord,
    "evidence_ledger_entry": EvidenceLedgerEntry,
}
"""Contract name -> frozen dataclass mirror."""


# ---------------------------------------------------------------------------
# v5.4.0 Session 7A — multi-owner block: consistency enforcement and helpers.
#
# Three records (DebtorResolvedRecord, LeadsBaseRecord, MatchedLeadRecord) carry
# the multi-owner block: owners[], primary_owner_name, additional_owner_names,
# owner_count, multi_owner_status. owner_name stays the required primary display
# owner (backward compatible). multi_owner_status is DESCRIPTIVE — owner
# cardinality and primary clarity — and never carries a review verdict; the
# needs-review verdict is debtor_resolution_status / parcel_resolution_status.
# ---------------------------------------------------------------------------

def _mo_get(record: Any, key: str) -> Any:
    """Read a field from a dict OR a contract dataclass instance."""
    if isinstance(record, dict):
        return record.get(key)
    return getattr(record, key, None)


def multi_owner_consistency_errors(record: Any) -> list:
    """Return the list of Session 7A multi-owner consistency violations.

    Empty when `record` carries no multi-owner block (multi_owner_status unset)
    — old single-owner records are valid (backward compatibility). Otherwise it
    enforces the 17.K rules: SINGLE_OWNER / MULTIPLE_OWNERS_PRIMARY_CLEAR /
    MULTIPLE_OWNERS_PRIMARY_UNCLEAR cardinality and primary clarity,
    owner_count == len(owners) (every identified owner is counted — co-owners
    are never dropped), and the no-contradiction guarantee: a
    MULTIPLE_OWNERS_PRIMARY_UNCLEAR record's needs-review verdict field
    (debtor_resolution_status, or parcel_resolution_status downstream) MUST be
    REVIEW_REQUIRED. Accepts a dict or a contract dataclass instance.
    """
    status = _mo_get(record, "multi_owner_status")
    if status is None:
        return []
    errors: list = []
    if status not in MULTI_OWNER_STATUSES:
        errors.append(f"multi_owner_status {status!r} is not a valid value")
        return errors

    owners = list(_mo_get(record, "owners") or [])
    owner_count = _mo_get(record, "owner_count")
    primary_owner_name = _mo_get(record, "primary_owner_name")
    owner_name = _mo_get(record, "owner_name")
    additional = list(_mo_get(record, "additional_owner_names") or [])
    n_primary = sum(1 for o in owners if bool(_mo_get(o, "is_primary")))

    if owner_count != len(owners):
        errors.append(
            f"owner_count {owner_count} != len(owners) {len(owners)} — every "
            f"identified owner must be counted (co-owners are never dropped)"
        )

    if status == "SINGLE_OWNER":
        if len(owners) != 1:
            errors.append("SINGLE_OWNER requires exactly one owner")
        if n_primary != 1:
            errors.append("SINGLE_OWNER requires exactly one is_primary owner")
        if primary_owner_name != owner_name:
            errors.append(
                "SINGLE_OWNER requires primary_owner_name == owner_name"
            )
        if additional:
            errors.append("SINGLE_OWNER requires additional_owner_names empty")
    elif status == "MULTIPLE_OWNERS_PRIMARY_CLEAR":
        if len(owners) < 2:
            errors.append(
                "MULTIPLE_OWNERS_PRIMARY_CLEAR requires more than one owner"
            )
        if n_primary != 1:
            errors.append(
                "MULTIPLE_OWNERS_PRIMARY_CLEAR requires exactly one is_primary "
                "owner"
            )
        if primary_owner_name != owner_name:
            errors.append(
                "MULTIPLE_OWNERS_PRIMARY_CLEAR requires primary_owner_name == "
                "owner_name"
            )
    elif status == "MULTIPLE_OWNERS_PRIMARY_UNCLEAR":
        if len(owners) < 2:
            errors.append(
                "MULTIPLE_OWNERS_PRIMARY_UNCLEAR requires more than one owner"
            )
        if n_primary != 0:
            errors.append(
                "MULTIPLE_OWNERS_PRIMARY_UNCLEAR requires NO owner marked "
                "is_primary (ownership priority is never guessed)"
            )
        verdict = _mo_get(record, "debtor_resolution_status")
        if verdict is None:
            verdict = _mo_get(record, "parcel_resolution_status")
        if verdict != "REVIEW_REQUIRED":
            errors.append(
                "MULTIPLE_OWNERS_PRIMARY_UNCLEAR requires the needs-review "
                "verdict field (debtor_resolution_status / "
                "parcel_resolution_status) to be REVIEW_REQUIRED — "
                "multi_owner_status describes, it never decides; the two "
                "fields must never contradict"
            )
    return errors


def _enforce_multi_owner_consistency(record: Any) -> None:
    """Raise ValueError if `record` violates the Session 7A multi-owner rules."""
    errors = multi_owner_consistency_errors(record)
    if errors:
        raise ValueError(
            "multi-owner contract violation (v5.4.0 Session 7A): "
            + "; ".join(errors)
        )


def single_owner_block(
    owner_name: str,
    *,
    name_type: Optional[str] = None,
    role: Optional[str] = None,
    resolution_status: Optional[str] = None,
    source_field: Optional[str] = None,
    confidence: Optional[str] = None,
) -> dict:
    """Build the SINGLE_OWNER multi-owner block — the five Session 7A fields.

    The backward-compatibility path: an engine that resolves exactly one owner
    wraps it here. Produces a consistent SINGLE_OWNER block — one owner,
    is_primary true, owner_count 1, no additional owners. The block is a dict
    (the staged engines build dict records); its `owners` entry is a dict
    carrying all eight owner-object fields.
    """
    owner = {
        "name": owner_name,
        "role": role,
        "name_type": name_type,
        "is_primary": True,
        "confidence": confidence,
        "source_field": source_field,
        "resolution_status": resolution_status,
        "notes": None,
    }
    return {
        "owners": [owner],
        "primary_owner_name": owner_name,
        "additional_owner_names": [],
        "owner_count": 1,
        "multi_owner_status": "SINGLE_OWNER",
    }


def owner_block_from(source_record: dict, **single_owner_kwargs: Any) -> dict:
    """Carry a record's multi-owner block forward, or derive SINGLE_OWNER.

    If `source_record` already carries a multi-owner block (multi_owner_status
    set), the block is copied verbatim — co-owners are never dropped between
    stages. Otherwise a SINGLE_OWNER block is derived via `single_owner_block`
    from `single_owner_kwargs` (which must include `owner_name`), so a pre-7A
    single-owner record upgrades cleanly.
    """
    if isinstance(source_record, dict) and source_record.get("multi_owner_status"):
        return {
            "owners": [dict(o) for o in (source_record.get("owners") or [])],
            "primary_owner_name": source_record.get("primary_owner_name"),
            "additional_owner_names": list(
                source_record.get("additional_owner_names") or []
            ),
            "owner_count": source_record.get("owner_count"),
            "multi_owner_status": source_record.get("multi_owner_status"),
        }
    return single_owner_block(**single_owner_kwargs)
