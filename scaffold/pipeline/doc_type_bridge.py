"""
doc_type_bridge — v5.4.0 Session 8 three-namespace doc-type reconciliation.

STATUS: BUILT in v5.4.0 Session 8. This module is the explicit, tested bridge
between the three doc-type namespaces the v5.4.0 cutover has to keep in sync:

  1. The monolith's `normalize_doc_type` output (`scaffold/pipeline/normalize.py`)
     — UPPERCASE registry keys (e.g. `TAX_DEED`, `NOTICE_OF_SALE`).
  2. The canonical_doc_types.json registry
     (`knowledge_base/domain/canonical_doc_types.json`) — the same UPPERCASE
     keys; the bridge lowercases them for the staged engine's input.
  3. §16's lead-type taxonomy
     (`knowledge_base/architecture/16_source_of_record_matrix.md`) — 27
     Title-Case lead-type names (e.g. `Tax Sale`, `Eviction`).

Contracts:
  - knowledge_base/architecture/22_doc_type_bridge.md (the Session 8 bridge
    design note — the rationale, the gap log, and the bridge's totality rule).
  - knowledge_base/architecture/17_debtor_party_rules.md §17.K (the Session 8
    amendment recording the plural-key rename and the 7-key reconciliation).

What the bridge guarantees (the cutover gate):
  - **Totality over normalize.py.** Every UPPERCASE value `normalize.py` can
    emit lowercases to a registry-aligned canonical_doc_type the staged engine
    accepts. There is no monolith output the bridge silently drops.
  - **Determinism.** The bridge is a static mapping module; the same input
    produces the same output every call. No regex heuristics, no fuzzy match.
  - **Explicit gaps.** Where a registry doc type has NO §16 lead_type
    (enrichment, negative signal, sub-type), the mapping value is `None` and
    the reason is documented in REGISTRY_WITHOUT_LEAD_TYPE_REASONS. Where a §16
    lead type has no registry equivalent (currently only "Tax Delinquency",
    which is a tax-roll status not a recorded document), it is listed in
    LEAD_TYPES_WITHOUT_REGISTRY_REASONS. NO mapping is invented to fill a gap.
  - **County-agnostic.** This module contains no county / state / vendor
    literal. The county-agnostic regression scanner enforces that.

This module is universal framework code: the three taxonomies are universal,
and the bridge between them is universal. Per-county doc-type synonyms layer
on top via the existing `county_synonyms` argument of
`normalize.normalize_doc_type`, not here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from scaffold.pipeline.debtor_party_engine import BROAD_KEY_REGISTRY_ALIASES

# ---------------------------------------------------------------------------
# Registry source.
# ---------------------------------------------------------------------------

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "knowledge_base"
    / "domain"
    / "canonical_doc_types.json"
)


def _load_registry() -> dict:
    return json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))


_REGISTRY = _load_registry()
REGISTRY_UPPER_KEYS: frozenset[str] = frozenset(_REGISTRY["canonical_types"].keys())
"""Every UPPERCASE canonical key in the canonical_doc_types.json registry —
exactly the set of values `normalize.normalize_doc_type` can emit (verified by
the bridge totality test)."""

REGISTRY_LOWER_KEYS: frozenset[str] = frozenset(
    k.lower() for k in REGISTRY_UPPER_KEYS
)
"""The same registry keys lowercased — the namespace the staged engine
(`debtor_party_engine`, `aggregation_key_engine`, `aggregator`, `leads_base_writer`)
consumes."""

# ---------------------------------------------------------------------------
# Bridge layer 1 — monolith UPPERCASE → registry lowercased.
# ---------------------------------------------------------------------------

def monolith_to_registry(normalized_doc_type: Optional[str]) -> Optional[str]:
    """Bridge a monolith UPPERCASE normalized_doc_type to the staged engine's
    lowercased registry canonical_doc_type.

    Returns the lowercased registry key, OR None when the input is None or
    not a recognised registry value (an unknown_doc_type that
    `normalize.normalize_doc_type` itself returned None for, or a custom
    string that did not pass through normalization). The bridge never invents
    a mapping — an unrecognised input maps to None and is the caller's
    responsibility (typically routed to operator review by the staged engine's
    F-5 default rule once it arrives there).
    """
    if not isinstance(normalized_doc_type, str):
        return None
    upper = normalized_doc_type.strip().upper()
    if upper not in REGISTRY_UPPER_KEYS:
        return None
    return upper.lower()


# ---------------------------------------------------------------------------
# Bridge layer 2 — registry lowercased → §16 lead_type (Title Case).
#
# §16.B enumerates exactly 27 canonical lead types (the recon sweep). Many
# registry doc types map directly to one (e.g. `eviction_filing` → "Eviction");
# several §16 lead types span several finer registry doc types (e.g. "Probate"
# spans letters_testamentary / letters_of_administration / determination_of_heirship
# / muniment_of_title). The remaining ~37 registry types are enrichment, negative
# signals, or sub-types not in the §16 sweep — they map to None and the reason
# is recorded in REGISTRY_WITHOUT_LEAD_TYPE_REASONS.
# ---------------------------------------------------------------------------

REGISTRY_TO_LEAD_TYPE: dict[str, Optional[str]] = {
    # --- Foreclosure family ------------------------------------------------
    "notice_of_default": "Foreclosure",
    "notice_of_sale": "Notice of Trustee Sale",
    "notice_of_substitute_trustee_sale": "Notice of Substitute Trustee Sale",
    "final_judgment_of_foreclosure": "Foreclosure",
    "appointment_of_substitute_trustee": "Foreclosure",
    "deed_in_lieu_of_foreclosure": "Foreclosure",
    "sheriff_deed": "Sheriff Sale",
    "sheriff_sale": "Sheriff Sale",
    "trustees_deed_upon_sale": "Trustee Sale",
    # --- Tax-related -------------------------------------------------------
    "tax_deed": "Tax Sale",
    "tax_foreclosure_notice": "Tax Lien Foreclosure",
    "tax_sale_certificate": "Tax Sale Certificate",
    "federal_tax_lien": "Federal Tax Lien",
    "state_tax_lien": "State Tax Lien",
    # --- Court / judgment / lis pendens -----------------------------------
    "lis_pendens": "Lis Pendens",
    # §16 distinguishes "Civil Judgment" from "Abstract of Judgment" but the
    # registry carries a single `judgment_lien` (with "Abstract of Judgment"
    # as a common abbreviation). The bridge maps to the broader "Civil
    # Judgment" §16 category; an abstract-of-judgment recording falls under
    # the same registry instrument.
    "judgment_lien": "Civil Judgment",
    # --- Liens (construction / mechanic) ----------------------------------
    "mechanics_lien": "Mechanic Lien",
    "construction_lien": "Construction Lien",
    # --- Probate / estate --------------------------------------------------
    "letters_testamentary": "Probate",
    "letters_of_administration": "Probate",
    "determination_of_heirship": "Probate",
    "muniment_of_title": "Probate",
    "affidavit_of_heirship": "Affidavit of Heirship",
    "executors_deed": "Executor Deed",
    "administrators_deed": "Administrator Deed",
    # --- Code / municipal --------------------------------------------------
    "code_violation_notice": "Code Lien",
    "municipal_lien": "Code Lien",
    "demolition_order": "Demolition",
    "condemnation_notice": "Condemnation",
    # --- Eviction ----------------------------------------------------------
    "eviction_filing": "Eviction",
    "writ_of_possession": "Eviction",
    # --- Divorce -----------------------------------------------------------
    "divorce_filing": "Divorce",
    "final_decree_of_divorce": "Divorce",
    "marital_property_division": "Divorce",
    # --- Bankruptcy / surplus ---------------------------------------------
    "bankruptcy_petition": "Bankruptcy",
    "sheriff_sale_surplus": "Surplus",
    # --- Registry types with NO §16 lead_type (enrichment / negative /
    # sub-type / derived signal). The bridge MUST be total over the registry,
    # so every key is listed; the value None records that no §16 lead type
    # exists for it. The reason is in REGISTRY_WITHOUT_LEAD_TYPE_REASONS.
    "warranty_deed": None,
    "special_warranty_deed": None,
    "quitclaim_deed": None,
    "trustee_deed": None,
    "transfer_on_death_deed": None,
    "personal_representative_deed": None,
    "correction_deed": None,
    "bargain_and_sale_deed": None,
    "gift_deed": None,
    "mortgage": None,
    "deed_of_trust": None,
    "mortgage_modification": None,
    "assignment_of_mortgage": None,
    "satisfaction_of_mortgage": None,
    "reconveyance": None,
    "release_of_lis_pendens": None,
    "release_of_federal_tax_lien": None,
    "release_of_lien": None,
    "vacated_judgment": None,
    "hoa_lien": None,
    "hospital_lien": None,
    "inheritance_tax_waiver": None,
    "disclaimer_of_interest": None,
    "trust_agreement": None,
    "partition_action": None,
    "quiet_title_action": None,
    "adverse_possession_claim": None,
    "receivership_order": None,
    "assignment_for_benefit_of_creditors": None,
    "water_lien": None,
    "easement": None,
    "right_of_way": None,
    "plat": None,
    "survey": None,
    "condominium_declaration": None,
    "ucc_financing_statement": None,
    "estate_owner_name_pattern": None,
    "living_trust_owner_name_pattern": None,
}
"""Total mapping registry lowercased canonical_doc_type → §16 Title-Case
lead_type, OR None when no §16 lead type covers the registry type. The bridge
totality test asserts every REGISTRY_LOWER_KEYS value is a key of this dict —
adding a new registry type without bridging it here is a build break."""

REGISTRY_WITHOUT_LEAD_TYPE_REASONS: dict[str, str] = {
    # Transfer-instrument enrichment — not a distress lead.
    "warranty_deed": "transfer enrichment",
    "special_warranty_deed": "transfer enrichment",
    "quitclaim_deed": "transfer enrichment (may signal estate / family / "
                     "divorce — captured via lead-pattern flags, not §16 sweep)",
    "trustee_deed": "transfer enrichment",
    "transfer_on_death_deed": "estate enrichment (sub-type of estate signals)",
    "personal_representative_deed": "estate enrichment (sub-type — broader §16 "
                                    "Probate / Executor Deed cover the field)",
    "correction_deed": "transfer curative enrichment",
    "bargain_and_sale_deed": "transfer enrichment",
    "gift_deed": "transfer enrichment",
    # Debt-instrument enrichment.
    "mortgage": "debt-position enrichment",
    "deed_of_trust": "debt-position enrichment",
    "mortgage_modification": "debt-position enrichment",
    "assignment_of_mortgage": "debt-position enrichment",
    # Negative signals — by definition not a lead in their own right.
    "satisfaction_of_mortgage": "negative signal (suppresses prior debt)",
    "reconveyance": "negative signal (suppresses prior debt / pre-sale fcl)",
    "release_of_lis_pendens": "negative signal (suppresses prior LP)",
    "release_of_federal_tax_lien": "negative signal (suppresses prior FTL)",
    "release_of_lien": "negative signal (generic lien release)",
    "vacated_judgment": "negative signal (suppresses prior judgment lien)",
    # Liens outside the §16 sweep.
    "hoa_lien": "lien type not in §16 27-type sweep",
    "hospital_lien": "lien type not in §16 27-type sweep",
    "water_lien": "utility-distress sub-type not in §16 27-type sweep",
    # Estate enrichment.
    "inheritance_tax_waiver": "estate enrichment (state tax-clearance step)",
    "disclaimer_of_interest": "estate enrichment (heir-step sub-signal)",
    "trust_agreement": "estate enrichment (trust mechanics, not a distress lead)",
    # Title-issue family — present in the registry as `title_issue` lead-pattern
    # signals but not enumerated as §16 lead types.
    "partition_action": "title-issue family — not a §16 27-type lead",
    "quiet_title_action": "title-issue family — not a §16 27-type lead",
    "adverse_possession_claim": "title-issue family — not a §16 27-type lead",
    # Commercial distress family — registry-tagged, but not in §16 sweep.
    "receivership_order": "commercial-distress family — not a §16 27-type lead",
    "assignment_for_benefit_of_creditors": "commercial-distress family — not a "
                                           "§16 27-type lead",
    # Pure enrichment (property-right / map / financing).
    "easement": "property-right enrichment",
    "right_of_way": "property-right enrichment",
    "plat": "subdivision-map enrichment",
    "survey": "survey enrichment",
    "condominium_declaration": "master-deed enrichment",
    "ucc_financing_statement": "personal-property security enrichment",
    # Derived signals — emitted by the pipeline itself from parcel-master
    # owner-name patterns, not a recorded document.
    "estate_owner_name_pattern": "derived signal from parcel-master owner name, "
                                 "not a recorded document",
    "living_trust_owner_name_pattern": "derived signal from parcel-master owner "
                                       "name, not a recorded document",
}
"""For every registry doc type the bridge maps to None, this dict records WHY.
The bridge test asserts every REGISTRY_TO_LEAD_TYPE entry whose value is None
has an entry here — an unexplained gap is a build break."""

LEAD_TYPES_WITHOUT_REGISTRY_REASONS: dict[str, str] = {
    # The one §16 lead type that has no canonical_doc_type registry analogue.
    # `Tax Delinquency` is the tax-roll STATUS (assessor flag that a parcel is
    # delinquent for the current cycle) — it carries no document and no
    # parties. The framework consumes it as ENRICHMENT (per §17.K Session 7),
    # not via a recorded-document doc-type. The closest recorded-document
    # analogue, `tax_foreclosure_notice`, is already bridged separately to the
    # distinct §16 lead type "Tax Lien Foreclosure".
    "Tax Delinquency": "tax-roll STATUS (enrichment), not a recorded document; "
                       "the closest recorded analogue tax_foreclosure_notice is "
                       "already bridged to the distinct §16 lead type 'Tax Lien "
                       "Foreclosure'",
}
"""§16 lead types that intentionally have NO canonical_doc_type registry
equivalent. Currently a single entry — Tax Delinquency."""

# The 27 canonical §16 lead types (mirrored from §16.B). The bridge totality
# test asserts that every §16 lead type either appears as a value of
# REGISTRY_TO_LEAD_TYPE or appears in LEAD_TYPES_WITHOUT_REGISTRY_REASONS.
LEAD_TYPES_16: tuple[str, ...] = (
    "Foreclosure",
    "Trustee Sale",
    "Notice of Trustee Sale",
    "Notice of Substitute Trustee Sale",
    "Sheriff Sale",
    "Tax Lien Foreclosure",
    "Tax Sale",
    "Tax Sale Certificate",
    "Tax Delinquency",
    "Lis Pendens",
    "Civil Judgment",
    "Abstract of Judgment",
    "Mechanic Lien",
    "Construction Lien",
    "Federal Tax Lien",
    "State Tax Lien",
    "Probate",
    "Affidavit of Heirship",
    "Executor Deed",
    "Administrator Deed",
    "Code Lien",
    "Demolition",
    "Condemnation",
    "Eviction",
    "Divorce",
    "Bankruptcy",
    "Surplus",
)

# Several §16 lead types are bridged through a SHARED registry doc type — most
# notably "Civil Judgment" and "Abstract of Judgment" both map back to
# `judgment_lien`. The bridge records these as documented many-to-one cases so
# the totality test does not flag them as a missing mapping.
LEAD_TYPES_SHARED_REGISTRY_MAPPING: dict[str, str] = {
    "Abstract of Judgment": "judgment_lien (shared with 'Civil Judgment' — the "
                            "registry carries one instrument for both; the "
                            "common abbreviation 'ABSTRACT OF JUDGMENT' is "
                            "listed on the JUDGMENT_LIEN registry entry)",
}


# ---------------------------------------------------------------------------
# Bridge API.
# ---------------------------------------------------------------------------

def registry_to_lead_type(canonical_doc_type: Optional[str]) -> Optional[str]:
    """Bridge a lowercased registry canonical_doc_type to its §16 lead_type.

    Returns the Title-Case §16 lead_type, OR None when the registry type has
    no §16 lead type (enrichment, negative signal, or sub-type — see
    REGISTRY_WITHOUT_LEAD_TYPE_REASONS for the reason). A canonical_doc_type
    not present in the registry returns None.
    """
    if not isinstance(canonical_doc_type, str):
        return None
    return REGISTRY_TO_LEAD_TYPE.get(canonical_doc_type.lower())


def lead_type_for_monolith_output(
    normalized_doc_type: Optional[str],
) -> Optional[str]:
    """End-to-end bridge: a monolith UPPERCASE normalized_doc_type to its §16
    lead_type. Composes monolith_to_registry → registry_to_lead_type."""
    return registry_to_lead_type(monolith_to_registry(normalized_doc_type))


def registry_types_for_broad_key(broad_key: str) -> tuple[str, ...]:
    """Return the registry canonical_doc_type values a §17 broad key fans out to.

    The Session-8 fan-out: each of the §17.C broad keys (`code_lien`,
    `foreclosure_notice`, `probate`, `trustee_sale`, `abstract_of_judgment`,
    `civil_judgment`, `administrative_lien`) maps to zero-or-more lowercased
    registry doc types — the same §17 rule fires on each. An empty tuple is a
    broad bucket whose registry-aligned children carry their own §17 rule rows
    (e.g. `administrative_lien`'s children federal_tax_lien / state_tax_lien /
    municipal_lien). An unrecognised broad key returns an empty tuple.
    """
    return tuple(BROAD_KEY_REGISTRY_ALIASES.get(broad_key, ()))


def bridge_totality_report() -> dict:
    """Return a structured report on the bridge's totality and gaps.

    The report is what the bridge totality test consumes and what an operator
    consults when adding a new registry doc type or a new §16 lead type. It is
    intentionally side-effect free.

    Returns a dict with:
      - registry_total                 — count of REGISTRY_LOWER_KEYS
      - registry_bridged               — count with a §16 lead type
      - registry_explicitly_unbridged  — count with value None
      - registry_missing_from_bridge   — list of registry keys absent from
                                         REGISTRY_TO_LEAD_TYPE (must be empty)
      - registry_missing_reason        — list of None-valued registry keys with
                                         no entry in
                                         REGISTRY_WITHOUT_LEAD_TYPE_REASONS
                                         (must be empty)
      - lead_types_total               — 27 (the §16 sweep)
      - lead_types_with_registry       — list of §16 lead types that appear as
                                         a value in REGISTRY_TO_LEAD_TYPE
      - lead_types_without_registry    — list of §16 lead types that do not
                                         appear; each MUST appear in
                                         LEAD_TYPES_WITHOUT_REGISTRY_REASONS or
                                         LEAD_TYPES_SHARED_REGISTRY_MAPPING
      - lead_types_unexplained         — list of without_registry lead types
                                         with no explanation (must be empty)
    """
    registry_keys = set(REGISTRY_LOWER_KEYS)
    bridge_keys = set(REGISTRY_TO_LEAD_TYPE.keys())
    missing_from_bridge = sorted(registry_keys - bridge_keys)
    none_keys = {
        k for k, v in REGISTRY_TO_LEAD_TYPE.items()
        if v is None and k in registry_keys
    }
    missing_reason = sorted(none_keys - REGISTRY_WITHOUT_LEAD_TYPE_REASONS.keys())

    bridged_lead_types = {
        v for v in REGISTRY_TO_LEAD_TYPE.values() if v is not None
    }
    with_registry = sorted(
        lt for lt in LEAD_TYPES_16 if lt in bridged_lead_types
    )
    without_registry = sorted(
        lt for lt in LEAD_TYPES_16 if lt not in bridged_lead_types
    )
    explained = (
        set(LEAD_TYPES_WITHOUT_REGISTRY_REASONS.keys())
        | set(LEAD_TYPES_SHARED_REGISTRY_MAPPING.keys())
    )
    lead_types_unexplained = sorted(
        lt for lt in without_registry if lt not in explained
    )

    return {
        "registry_total": len(registry_keys),
        "registry_bridged": sum(
            1 for k in registry_keys
            if REGISTRY_TO_LEAD_TYPE.get(k) is not None
        ),
        "registry_explicitly_unbridged": len(none_keys),
        "registry_missing_from_bridge": missing_from_bridge,
        "registry_missing_reason": missing_reason,
        "lead_types_total": len(LEAD_TYPES_16),
        "lead_types_with_registry": with_registry,
        "lead_types_without_registry": without_registry,
        "lead_types_unexplained": lead_types_unexplained,
    }
