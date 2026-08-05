"""
Lead scoring + score-tier classification.

Per domain/03_scoring_and_stacking.md, the score is a single integer in
[0, 100] derived from:

  base score for the strongest signal in the stack
  + stack bonus for additional patterns
  + recency bonus if any active signal fired in the last 30 days
  + attribute bonus capped at +12

Score tiers (operator-facing labels):
  Hot       >= 80
  Strong    65 .. 79
  Workable  50 .. 64
  Low       35 .. 49
  Archive   <  35

Calibrated against scaffold/data/synthetic_expectations.json so the
golden synthetic dataset produces at least 2 Hot, 2 Strong, 3 Workable,
2 Low, 0 Archive leads.
"""

from __future__ import annotations


# Per-canonical-type base score. Strongest single-signal contribution
# the stack can carry. The strongest signal sets the base; weaker
# signals only contribute via the stack-bonus path.
BASE_SCORE = {
    "NOTICE_OF_SALE": 60,
    "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE": 60,
    "NOTICE_OF_DEFAULT": 60,
    "SHERIFF_SALE": 60,
    "SHERIFF_DEED": 55,
    "TRUSTEES_DEED_UPON_SALE": 55,
    "FINAL_JUDGMENT_OF_FORECLOSURE": 60,
    "LIS_PENDENS": 35,
    "DEED_IN_LIEU_OF_FORECLOSURE": 50,

    "TAX_FORECLOSURE_NOTICE": 55,
    "TAX_SALE_CERTIFICATE": 50,
    "FEDERAL_TAX_LIEN": 55,
    "STATE_TAX_LIEN": 45,
    "TAX_DEED": 55,

    "MECHANICS_LIEN": 30,
    "CONSTRUCTION_LIEN": 30,
    "JUDGMENT_LIEN": 30,
    "HOA_LIEN": 20,
    "HOSPITAL_LIEN": 25,
    "MUNICIPAL_LIEN": 30,
    "WATER_LIEN": 25,

    "AFFIDAVIT_OF_HEIRSHIP": 55,
    "LETTERS_TESTAMENTARY": 55,
    "LETTERS_OF_ADMINISTRATION": 55,
    "DETERMINATION_OF_HEIRSHIP": 55,
    "EXECUTORS_DEED": 35,
    "ADMINISTRATORS_DEED": 40,
    "PERSONAL_REPRESENTATIVE_DEED": 40,
    "TRANSFER_ON_DEATH_DEED": 40,
    "MUNIMENT_OF_TITLE": 45,
    "INHERITANCE_TAX_WAIVER": 35,
    "DISCLAIMER_OF_INTEREST": 35,
    "QUITCLAIM_DEED": 35,

    "DEMOLITION_ORDER": 50,
    "CONDEMNATION_NOTICE": 45,
    "CODE_VIOLATION_NOTICE": 25,

    "BANKRUPTCY_PETITION": 50,

    "MARITAL_PROPERTY_DIVISION": 45,
    "FINAL_DECREE_OF_DIVORCE": 35,
    "DIVORCE_FILING": 30,

    "EVICTION_FILING": 20,
    "WRIT_OF_POSSESSION": 25,
    # tired_landlord is not a doc type — handled via _PATTERN_FLOOR below.

    "PARTITION_ACTION": 50,
    "QUIET_TITLE_ACTION": 50,
    "ADVERSE_POSSESSION_CLAIM": 35,

    "RECEIVERSHIP_ORDER": 45,
    "ASSIGNMENT_FOR_BENEFIT_OF_CREDITORS": 40,

    # Synthetic-only canonical extension (see normalize.CANONICAL setdefault).
    "SHERIFF_SALE_SURPLUS": 40,

    # Parcel-master derived signals (see backlog v5.1.2-beta). Base
    # scores stay LOW deliberately so foreclosure / tax / court signals
    # remain dominant when present — the operator value of owner-name
    # patterns is the STACK BONUS they unlock, not their standalone score.
    "ESTATE_OWNER_NAME_PATTERN": 30,
    "LIVING_TRUST_OWNER_NAME_PATTERN": 25,
}


# Floor base score when the active stack carries a pattern that maps
# to multiple doc types (e.g. tired_landlord = collapsed evictions).
_PATTERN_FLOOR = {
    "tired_landlord": 50,
    "surplus_owed": 40,
}


# Per-attribute bonus, applied additively then capped.
ATTRIBUTE_BONUS = {
    "high_equity": 5,
    "vacant": 5,
    "absentee": 3,
    "long_term_owned": 3,
    "senior_owner": 3,
    "free_and_clear": 3,
    "out_of_state": 2,
    "entity_owned": 2,
    "multiple_properties": 2,
}

ATTRIBUTE_BONUS_CAP = 12

# Stack bonus is +12 for 2 patterns, +24 for 3+ patterns.
STACK_BONUS = {0: 0, 1: 0, 2: 12, 3: 24}

# Recency bonus when any active signal fired in the trailing 30-day window.
RECENCY_BONUS = 5


SCORE_TIERS = ("Hot", "Strong", "Workable", "Low", "Archive")


def tier_for(score: int) -> str:
    if score >= 80:
        return "Hot"
    if score >= 65:
        return "Strong"
    if score >= 50:
        return "Workable"
    if score >= 35:
        return "Low"
    return "Archive"


def compute_score(stack: dict, attributes: list) -> dict:
    """
    Returns {score, tier, score_reasons[]} per domain/03_scoring_and_stacking.md.
    """
    reasons = []

    # Base score = max(signal-level base, pattern-level floor).
    base = 0
    base_source = None
    for sig in stack["active_signals"]:
        dtype = sig.get("normalized_doc_type") or ""
        s = BASE_SCORE.get(dtype, 0)
        if s > base:
            base = s
            base_source = dtype

    for pat in stack["pattern_set"]:
        floor = _PATTERN_FLOOR.get(pat, 0)
        if floor > base:
            base = floor
            base_source = f"pattern:{pat}"

    if base_source:
        reasons.append({"factor": f"base_{base_source}", "delta": base})

    score = base

    # Stack bonus — use stack_depth (signal-level, with duplicates) when
    # available, falling back to pattern_set length. Duplicate same-pattern
    # signals (e.g. multiple liens on one parcel) DO contribute additional
    # title-cloud severity and earn additional stack bonus.
    depth = stack.get("stack_depth", len(stack["pattern_set"]))
    stack_bonus = STACK_BONUS.get(min(depth, 3), 0)
    if stack_bonus:
        score += stack_bonus
        reasons.append({"factor": f"stack_depth_{depth}", "delta": stack_bonus})

    # Recency bonus.
    if stack.get("recent_flag"):
        score += RECENCY_BONUS
        reasons.append({"factor": "recent_filing_within_30_days", "delta": RECENCY_BONUS})

    # Attribute bonus, capped.
    attr_bonus_total = 0
    for attr in attributes:
        if attr in ATTRIBUTE_BONUS:
            attr_bonus_total += ATTRIBUTE_BONUS[attr]
    attr_bonus_total = min(attr_bonus_total, ATTRIBUTE_BONUS_CAP)
    if attr_bonus_total:
        score += attr_bonus_total
        reasons.append({"factor": "attribute_bonus", "delta": attr_bonus_total})

    score = max(0, min(score, 100))
    return {"score": score, "tier": tier_for(score), "score_reasons": reasons}
