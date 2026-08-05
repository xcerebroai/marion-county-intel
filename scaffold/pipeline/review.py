"""
Review-queue rules per domain/05_review_queue_rules.md.

Lead flows: STACKED_LEAD -> (review_flags evaluated) -> APPROVED_FOR_DASHBOARD
or REVIEW_REQUIRED. The dashboard's default Client View hides
REVIEW_REQUIRED leads; Operator View shows them with the flag set.
"""

from __future__ import annotations

import re

# Entity-name tokens matched as whole words to avoid false positives
# (e.g. "VINCENT" should not match "INC").
_ENTITY_RE = re.compile(
    r"\bLLC\b|\bINC\b|\bCORP\b|\bLP\b|\bTRUST\b", re.IGNORECASE
)


def evaluate_review_queue(lead: dict, *, now: str | None = None) -> dict:
    # Preserve any preset review flags attached upstream (e.g. by a
    # source translator that already detected a cross-county leak or
    # an incomplete source record). The review-queue evaluator then
    # adds its own rule-based flags on top.
    flags = list(lead.get("review_flags") or [])
    # Suppress the generic "match_confidence_low" flag when a more
    # specific matcher flag is already present — they describe the
    # same underlying cause but the specific one is more actionable.
    _matcher_flags = {
        "multi_parcel_address",
        "address_match_uncertain",
        "parcel_not_found_in_bcad",
    }
    if lead.get("match_confidence", 100) < 80 and not _matcher_flags & set(flags):
        flags.append("match_confidence_low")
    if lead.get("doc_type_normalization", {}).get("doc_type_review_required"):
        flags.append("low_doc_type_confidence")
    if lead.get("title_complexity_score", 0) >= 60:
        flags.append("high_title_complexity_review")
    if not lead.get("patterns"):
        flags.append("no_pattern_fired")
    # Lis-pendens hard guard: never auto-promote to dial-ready.
    # Entity owners or non-residential parcels -> lis_pendens_commercial.
    # Individual owners on residential parcels -> lis_pendens_review.
    if "lis_pendens" in (lead.get("patterns") or []):
        _pd = lead.get("parcel_display") or {}
        _owner = (lead.get("owner_name") or "").upper()
        _otype = lead.get("owner_type", "UNKNOWN")
        _prop_class = (_pd.get("property_class") or "").upper()
        _is_entity = _otype == "ENTITY" or bool(_ENTITY_RE.search(_owner))
        _is_residential = "RESIDENT" in _prop_class or "SFR" in _prop_class
        if _is_entity or (_prop_class and not _is_residential):
            flags.append("lis_pendens_commercial")
        else:
            flags.append("lis_pendens_review")
    # Dedupe while preserving order.
    seen = set()
    deduped = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            deduped.append(f)
    lead["review_flags"] = deduped

    transition_to = "REVIEW_REQUIRED" if deduped else "APPROVED_FOR_DASHBOARD"
    lead["lead_status"] = transition_to
    lead.setdefault("lead_status_history", []).append(
        {
            "status": transition_to,
            "transitioned_at": now or "",
            "reason": ("; ".join(deduped)) if deduped else "no review flags triggered",
        }
    )
    return lead
