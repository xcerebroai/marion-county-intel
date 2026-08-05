"""Foreclosure-regime resolution for lis pendens classification.

A lis pendens means different things depending on the subject jurisdiction's
foreclosure regime:

  - JUDICIAL regime: foreclosure is a lawsuit; a lis pendens often IS the
    foreclosure filing.  lead_pattern -> "foreclosure".
  - NON-JUDICIAL regime: foreclosure runs through a trustee / power-of-sale
    outside the courts; a lis pendens is OTHER civil litigation, not a
    foreclosure signal.  lead_pattern -> "lis_pendens" (routes to review).
  - HYBRID regime: ambiguous (court-supervised power of sale); a lis pendens
    may or may not be foreclosure-related, so it routes to review without an
    auto-classification.  lead_pattern -> None (the seam seeds a
    "lis_pendens_unconfirmed_regime" review flag).

This module is UNIVERSAL framework code: it contains NO jurisdiction names or
codes.  The regime is a per-county fact carried in the county config's
`state_rule_family` field (e.g. "TX_non_judicial_foreclosure",
"NY_judicial_foreclosure").  mode_from_rule_family() derives the regime mode
from that config string; resolve_lis_pendens_pattern() maps the mode to a
lead pattern.

canonical_doc_types.json stores LIS_PENDENS.lead_pattern as the sentinel
value "by_state_profile".  scoring_seam.pattern_for_canonical_doc_type
resolves the sentinel at runtime via resolve_lis_pendens_pattern().
"""

from __future__ import annotations


# Regime modes — the canonical vocabulary this module resolves against.
MODE_FORECLOSURE = "foreclosure"   # judicial: lis pendens IS the foreclosure
MODE_LITIGATION = "litigation"     # non-judicial: lis pendens is other litigation
MODE_HYBRID = "hybrid"             # ambiguous: route to review, no auto-classify


def mode_from_rule_family(rule_family: str | None) -> str | None:
    """Derive the lis-pendens regime mode from a county config's
    `state_rule_family` string.

    The config strings are underscore-joined compounds such as
    "TX_non_judicial_foreclosure" or "NY_judicial_foreclosure".  We classify
    on the regime substring, NOT on the jurisdiction prefix, so this stays
    jurisdiction-agnostic:

      - contains "non_judicial" (or "non-judicial") -> MODE_LITIGATION
      - else contains "judicial"                    -> MODE_FORECLOSURE
      - contains "hybrid"                           -> MODE_HYBRID
      - anything else / empty                       -> None (unknown)

    Returns None when the regime cannot be determined; callers treat None
    conservatively (route lis pendens to review).
    """
    if not rule_family:
        return None
    rf = rule_family.lower().replace("-", "_")
    if "hybrid" in rf:
        return MODE_HYBRID
    if "non_judicial" in rf:
        return MODE_LITIGATION
    if "judicial" in rf:
        return MODE_FORECLOSURE
    return None


def resolve_lis_pendens_pattern(mode: str | None) -> str | None:
    """Resolve the lis pendens lead_pattern from a regime mode.

    Args:
      mode: one of MODE_FORECLOSURE / MODE_LITIGATION / MODE_HYBRID, or None.
            Typically produced by mode_from_rule_family() from county config.

    Returns:
      "foreclosure"  — judicial regime: lis pendens IS foreclosure.
      "lis_pendens"  — non-judicial regime: lis pendens is litigation, not
                       foreclosure.  review.py's hard guard routes to
                       lis_pendens_review / lis_pendens_commercial.
      None           — hybrid / unknown regime: no pattern fires; the seam
                       seeds a "lis_pendens_unconfirmed_regime" review flag so
                       ALL lis pendens go to REVIEW_REQUIRED without the
                       entity split.
    """
    if mode == MODE_FORECLOSURE:
        return "foreclosure"
    if mode == MODE_LITIGATION:
        return "lis_pendens"
    if mode == MODE_HYBRID:
        return None
    # Unknown / missing regime — conservative: route to review via lis_pendens.
    return "lis_pendens"
