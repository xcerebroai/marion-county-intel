"""
Document-type normalization and parcel-attribute derivation.

Doc-type normalization
----------------------
Maps a raw `subtype` string (as it appears in a synthetic signal or in
a real source's `doc_type` field) to a canonical entry in
`knowledge_base/domain/canonical_doc_types.json`. The match strategy is:

  1. Exact match on the canonical key (uppercased + underscored).
  2. Exact match on any of the canonical entry's `common_abbreviations`.
  3. Heuristic match by stripping non-alphanumerics and comparing.

If no match is found, the signal is routed to the review queue rather
than being silently dropped. The framework's prime directive — never
present a fact you can't source — forbids guessing a doc type.

Parcel attribute derivation
---------------------------
Computes the 9 universal attributes recognised by the framework:

    vacant, absentee, out_of_state, long_term_owned, high_equity,
    free_and_clear, entity_owned, multiple_properties, senior_owner

For the synthetic harness, attribute presence is inferred from the
synthetic parcel master + signals; in production, additional sources
(USPS, parcel-master flags, owner-DOB proxies) refine the derivation.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

_REGISTRY_PATH = (
    Path(__file__).resolve().parents[2]
    / "knowledge_base"
    / "domain"
    / "canonical_doc_types.json"
)


def _load_registry() -> dict:
    with open(_REGISTRY_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


REGISTRY = _load_registry()
CANONICAL: dict = REGISTRY["canonical_types"]
LEAD_PATTERNS: list = REGISTRY["lead_patterns"]
SOURCE_CLASSES: list = REGISTRY["source_classes"]

_NON_ALNUM = re.compile(r"[^A-Z0-9]+")


def _slug(s: str) -> str:
    return _NON_ALNUM.sub("_", s.upper()).strip("_")


# Pre-compute lookup tables once at import time.
_BY_KEY: dict = {}
_BY_ABBREV: dict = {}
_BY_SLUG: dict = {}

for _ctype, _entry in CANONICAL.items():
    _BY_KEY[_ctype.upper()] = _ctype
    _BY_SLUG[_slug(_ctype)] = _ctype
    for _abbrev in _entry.get("common_abbreviations", []):
        _BY_ABBREV[_abbrev.upper().strip()] = _ctype
        _BY_SLUG[_slug(_abbrev)] = _ctype


# Raw subtype shortcuts. Maps subtype strings (from synthetic fixtures
# AND from production source translators) directly to canonical types
# without relying on the slug heuristic. The synthetic harness depends
# on this for determinism; production translators benefit from explicit
# label aliases (e.g. possessive vs non-possessive forms).
_RAW_SUBTYPE_MAP = {
    "Notice of Sale": "NOTICE_OF_SALE",
    "Sheriff Sale": "SHERIFF_SALE",
    "Lis Pendens": "LIS_PENDENS",
    "Foreclosure-Stay Bankruptcy": "BANKRUPTCY_PETITION",
    "Tax Sale Certificate": "TAX_SALE_CERTIFICATE",
    "Federal Tax Lien": "FEDERAL_TAX_LIEN",
    "Tax Delinquent": "TAX_FORECLOSURE_NOTICE",
    "Judgment Lien": "JUDGMENT_LIEN",
    "Mechanic's Lien": "MECHANICS_LIEN",
    "Construction Lien": "CONSTRUCTION_LIEN",
    "HOA Lien": "HOA_LIEN",
    "Discharge of Judgment Lien": "VACATED_JUDGMENT",
    "Affidavit of Heirship": "AFFIDAVIT_OF_HEIRSHIP",
    "Quitclaim Deed": "QUITCLAIM_DEED",
    "Executor's Deed": "EXECUTORS_DEED",
    "Probate Case Opened": "LETTERS_TESTAMENTARY",
    "Demolition Order": "DEMOLITION_ORDER",
    "Sale of Marital Home Order": "MARITAL_PROPERTY_DIVISION",
    "Eviction Filing": "EVICTION_FILING",
    "Sheriff Sale Surplus": "SHERIFF_SALE_SURPLUS",
    # Production-mode subtype labels emitted by the translator registry.
    # Possessive forms ("Trustee's Sale") aliased to the apostrophe-free
    # canonical key for deterministic mapping without slug heuristics.
    "Notice of Substitute Trustee's Sale": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
    "Notice of Trustee's Sale": "NOTICE_OF_SALE",
    "Tax Foreclosure Notice": "TAX_FORECLOSURE_NOTICE",
    # Owner-name-pattern derived signals (see
    # scaffold/pipeline/owner_name_patterns.py).
    "Estate owner-name pattern": "ESTATE_OWNER_NAME_PATTERN",
    "Living-trust owner-name pattern": "LIVING_TRUST_OWNER_NAME_PATTERN",
}


def normalize_doc_type(raw: str, county_synonyms: dict | None = None) -> dict:
    """Return {normalized_doc_type, confidence, reason, review_required}."""
    if not raw or not isinstance(raw, str):
        return {
            "normalized_doc_type": None,
            "confidence": 0,
            "reason": "empty_input",
            "review_required": True,
        }

    cleaned = raw.strip()
    upper = cleaned.upper()
    slug = _slug(cleaned)
    county_synonyms = county_synonyms or {}

    # Layer 0: raw-subtype shortcuts (case-sensitive match against
    # fixture and translator-emitted subtype labels in _RAW_SUBTYPE_MAP).
    if cleaned in _RAW_SUBTYPE_MAP:
        return {
            "normalized_doc_type": _RAW_SUBTYPE_MAP[cleaned],
            "confidence": 100,
            "reason": "exact_match_synthetic_fixture_subtype",
            "review_required": False,
        }

    # Layer 1: county synonyms (operator-curated overrides win).
    if upper in {k.upper(): v for k, v in county_synonyms.items()}:
        cs = {k.upper(): v for k, v in county_synonyms.items()}[upper]
        if isinstance(cs, str):
            return {
                "normalized_doc_type": cs,
                "confidence": 90,
                "reason": "exact_match_county_synonym",
                "review_required": False,
            }
        return {
            "normalized_doc_type": cs.get("normalized_doc_type"),
            "confidence": cs.get("confidence", 90),
            "reason": "exact_match_county_synonym",
            "review_required": False,
        }

    # Layer 2: canonical key exact match.
    if upper in _BY_KEY:
        return {
            "normalized_doc_type": _BY_KEY[upper],
            "confidence": 100,
            "reason": "exact_match_canonical_key",
            "review_required": False,
        }

    # Layer 3: abbreviation match.
    if upper in _BY_ABBREV:
        return {
            "normalized_doc_type": _BY_ABBREV[upper],
            "confidence": 100,
            "reason": "exact_match_abbreviation",
            "review_required": False,
        }

    # Layer 4: slug match (loose).
    if slug in _BY_SLUG:
        return {
            "normalized_doc_type": _BY_SLUG[slug],
            "confidence": 95,
            "reason": "slug_match",
            "review_required": False,
        }

    return {
        "normalized_doc_type": None,
        "confidence": 0,
        "reason": "unknown_doc_type",
        "review_required": True,
    }


# ---------------------------------------------------------------------
# Parcel attribute derivation
# ---------------------------------------------------------------------

LEAD_ATTRIBUTES = [
    "vacant",
    "absentee",
    "out_of_state",
    "long_term_owned",
    "high_equity",
    "free_and_clear",
    "entity_owned",
    "multiple_properties",
    "senior_owner",
]


from scaffold.pipeline.matcher import _VALID_US_STATE_CODES  # noqa: E402


# Entity-owner regex — operator-authoritative spec (REVIEW_GATE_4
# follow-up, 2026-05-14). TRUST / TR / TRUSTEE deliberately excluded;
# those parcels fire LIVING_TRUST_OWNER_NAME_PATTERN as a signal in
# scaffold/pipeline/owner_name_patterns.py instead of being treated
# as a generic entity. CO / ASSOC / PARTNERS dropped as too broad.
_ENTITY_SUFFIXES = re.compile(
    r"\b(LLC|INC|CORP|LP|LTD|COMPANY|HOLDINGS)\b",
    re.IGNORECASE,
)


def derive_attributes(
    parcel: dict,
    signals: list,
    *,
    as_of: date | None = None,
    multi_property_ids: set | None = None,
    scoring_overrides: dict | None = None,
) -> list:
    """
    Compute the attribute list for one parcel given its signals and
    optionally a set of parcel_ids known to share an owner (for
    multiple_properties).

    Returns a sorted unique list of attribute strings from
    LEAD_ATTRIBUTES.
    """
    overrides = scoring_overrides or {}
    today = as_of or date.today()
    attrs: set = set()

    owner = (parcel.get("owner_name") or "").upper()
    mailing_city = (parcel.get("owner_mailing_city") or "").strip().lower()
    mailing_state = (parcel.get("owner_mailing_state") or "").strip().upper()
    mailing_addr = (parcel.get("owner_mailing_address") or "").strip().lower()
    mailing_zip = (parcel.get("owner_mailing_zip") or "").strip()
    situs_addr = (parcel.get("address") or "").strip().lower()
    situs_city = (parcel.get("city") or "").strip().lower()
    situs_state = (parcel.get("situs_state") or "").strip().upper()

    # absentee — mailing address differs from situs address. A homestead
    # exemption is a strong negative signal (parcel-master HS flag
    # confirms owner-occupied).
    has_hs_exemption = parcel.get("exempt_homestead") is True
    if not has_hs_exemption and mailing_addr and (
        mailing_addr != situs_addr or mailing_city != situs_city
    ):
        attrs.add("absentee")

    # out_of_state — owner mailing state differs from situs state. Fire
    # only when the mailing state is a valid US 2-letter code that
    # disagrees with the situs state. The accompanying mailing-ZIP
    # heuristic catches the case where a parcel-master row carries an
    # in-state ZIP with a typo state code; for those rows the in-state
    # ZIP wins and the row is treated as in-state.
    in_state_zip_prefixes = (overrides.get("in_state_zip_prefixes") or [])
    in_state_code = (overrides.get("in_state_code") or "").upper()
    if mailing_state and situs_state and mailing_state != situs_state:
        likely_zip_state_mismatch = (
            in_state_zip_prefixes
            and in_state_code
            and mailing_zip
            and any(mailing_zip.startswith(p) for p in in_state_zip_prefixes)
            and mailing_state != in_state_code
        )
        if (
            _VALID_US_STATE_CODES is not None
            and mailing_state in _VALID_US_STATE_CODES
            and not likely_zip_state_mismatch
        ):
            attrs.add("out_of_state")
            attrs.add("absentee")

    # entity_owned — owner name looks like a corporation, LLC, trust, etc.
    if owner and _ENTITY_SUFFIXES.search(owner):
        attrs.add("entity_owned")

    # multiple_properties — caller passes set of parcel_ids that share owner.
    if multi_property_ids and parcel.get("parcel_id") in multi_property_ids:
        attrs.add("multiple_properties")

    # long_term_owned — last_sale_date is more than `long_term_owned_years`
    # ago. Default threshold 15y per scoring_overrides.
    threshold_years = overrides.get("long_term_owned_years", 15)
    sale_date = _parse_date(parcel.get("last_sale_date"))
    if sale_date and (today.year - sale_date.year) >= threshold_years:
        attrs.add("long_term_owned")

    # senior_owner — strongest signal is an over-65 exemption on the
    # parcel master. Fall back to the long-held-parcel + estate-signal
    # heuristic when no exemption data is available.
    if parcel.get("exempt_over_65") is True:
        attrs.add("senior_owner")
    else:
        senior_years = overrides.get("senior_owner_proxy_years", 25)
        if sale_date and (today.year - sale_date.year) >= senior_years:
            has_estate_signal = any(
                (sig.get("pattern") or "") == "estate" for sig in signals
            )
            if has_estate_signal or "DECEASED" in owner or "ESTATE OF" in owner:
                attrs.add("senior_owner")

    # high_equity — assessed_value / last_sale_price >=
    # high_equity_assessed_to_sale_ratio (default 2.0).
    ratio_threshold = overrides.get("high_equity_assessed_to_sale_ratio", 2.0)
    assessed = parcel.get("assessed_value") or 0
    last_sale = parcel.get("last_sale_price") or 0
    if assessed and last_sale and assessed >= last_sale * ratio_threshold:
        attrs.add("high_equity")

    # free_and_clear — no active mortgage / deed-of-trust signal AND
    # property held a long time. (In real builds: pulled from
    # clerk recordings; for synthetic, infer from absence of MORTGAGE-class
    # signals plus long_term_owned + high_equity hint.)
    has_mortgage_signal = any(
        (sig.get("normalized_doc_type") or "")
        in {"MORTGAGE", "DEED_OF_TRUST", "ASSIGNMENT_OF_MORTGAGE"}
        and (sig.get("lifecycle_status") or "ACTIVE") == "ACTIVE"
        for sig in signals
    )
    if (
        not has_mortgage_signal
        and "long_term_owned" in attrs
        and "high_equity" in attrs
    ):
        attrs.add("free_and_clear")

    # vacant — proxy: code violations like "Demolition Order", "Condemnation"
    # OR explicit vacant flag on parcel.
    if parcel.get("vacant_flag") is True:
        attrs.add("vacant")
    for sig in signals:
        dtype = (sig.get("normalized_doc_type") or "")
        if dtype in {"DEMOLITION_ORDER", "CONDEMNATION_NOTICE"}:
            attrs.add("vacant")
        # post-sheriff-sale surplus implies prior occupancy gone
        if (
            (sig.get("subtype") or "") == "Sheriff Sale Surplus"
            and "former" in owner.lower()
        ):
            # Skip vacant for surplus-owed persona; treated separately.
            pass

    # Lis pendens + absentee owner is a known vacancy proxy in the framework
    # (per domain/02_signals_and_sources.md attribute heuristics).
    has_lis_pendens = any(
        (sig.get("normalized_doc_type") or "") == "LIS_PENDENS"
        and (sig.get("lifecycle_status") or "ACTIVE") == "ACTIVE"
        for sig in signals
    )
    if has_lis_pendens and "absentee" in attrs:
        attrs.add("vacant")

    return sorted(attrs)


def _parse_date(s):
    if not s:
        return None
    try:
        return date.fromisoformat(str(s)[:10])
    except (ValueError, TypeError):
        return None
