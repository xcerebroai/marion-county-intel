"""
Dashboard-projection layer.

Per architecture/09_output_schemas.md §6, the dashboard reads a
projection of each lead (NOT the raw lead object). The projection
contains operator-facing labels only and is the input the static
dashboard consumes.

Production output is a single JSON document with:

    {
      "generated_at":          ISO 8601,
      "build_label":           FULL_BUILD | PARTIAL_BUILD | ...,
      "lead_total":            int,
      "total_signals_active":  int,
      "pattern_counts":        {pattern: count},
      "attribute_counts":      {attribute: count},
      "stack_depth_distribution": {"1": n1, "2": n2, "3": n3},
      "score_tier_distribution":  {tier: count},
      "deal_path_distribution":   {path: count},
      "quality_metrics":          {...},
      "records":                  [dashboard_row, ...]
    }

The `pattern_counts` are re-derived from `records[]` and asserted to
match the header (the Two-Truths invariant — see MASTER_PROMPT §5).
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone


def project_lead(lead: dict, parcel: dict) -> dict:
    return {
        "lead_id": lead["lead_id"],
        "primary_parcel_id": lead["primary_parcel_id"],
        "display_address": ", ".join(
            [
                v
                for v in [
                    parcel.get("situs_address"),
                    parcel.get("situs_city"),
                    parcel.get("situs_state"),
                ]
                if v
            ]
        ),
        "display_owner": parcel.get("owner_name") or "Unknown",
        "display_score": lead["score"],
        "display_tier": lead.get("tier") or "",
        # display_patterns drives the dashboard pattern chips. Falls back to
        # the stack-contributing patterns when no collapse occurred.
        "display_patterns": lead.get("display_patterns") or lead.get("patterns", []),
        "stack_contrib_patterns": lead.get("patterns", []),
        "display_pattern_set": lead.get("pattern_set", []),
        "display_attributes": lead.get("attributes", []),
        "display_deal_paths": [dp["path"] for dp in lead.get("deal_paths", [])],
        "display_deal_path_details": lead.get("deal_paths", []),
        "display_title_complexity_tier": lead.get("title_complexity_tier", ""),
        "display_lead_status": lead.get("lead_status", "STACKED_LEAD"),
        "display_assessed_value": parcel.get("assessed_value"),
        "display_last_sale_price": parcel.get("last_sale_price"),
        "display_last_sale_date": parcel.get("last_sale_date"),
        "display_year_built": parcel.get("year_built"),
        "display_match_confidence": lead.get("match_confidence", 0),
        "stack_depth": lead.get("stack_depth", 0),
        "score_reasons": lead.get("score_reasons", []),
        "evidence_ids": lead.get("evidence_ids", []),
        "primary_source_urls": sorted(
            {
                s.get("source_url", "")
                for s in lead.get("_active_signals", [])
                if s.get("source_url")
            }
        ),
        "primary_event_date": lead.get("primary_event_date"),
        "expected_sale_date": lead.get("expected_sale_date"),
        "parcel_master_status": lead.get("parcel_master_status", ""),
        "parcel_master_status_note": lead.get("parcel_master_status_note", ""),
        "parcel_master_match_method": lead.get("parcel_master_match_method", ""),
        "candidate_parcel_ids": lead.get("candidate_parcel_ids", []),
        "review_flags": lead.get("review_flags", []),
    }


def build_payload(
    *,
    leads: list,
    parcels_by_id: dict,
    suppressed_count: int,
    quality_metrics: dict,
    build_label: str = "FULL_BUILD",
    county: str = "<synthetic>",
    state: str = "ZZ",
    mode: str = "synthetic",
    deployment: dict | None = None,
) -> dict:
    rows = [project_lead(lead, parcels_by_id[lead["primary_parcel_id"]]) for lead in leads]

    # Aggregate pattern_counts is derived from display_patterns (the chip-
    # eligible patterns including any collapse marker). This keeps the
    # Two-Truths invariant aligned with what the dashboard chips show.
    pattern_counts = Counter()
    for lead in leads:
        for p in (lead.get("display_patterns") or lead.get("patterns", [])):
            pattern_counts[p] += 1

    attribute_counts = Counter()
    for lead in leads:
        for a in lead.get("attributes", []):
            attribute_counts[a] += 1

    stack_depth_distribution = Counter()
    for lead in leads:
        stack_depth_distribution[str(lead.get("stack_depth", 0))] += 1

    score_tier_distribution = Counter()
    for lead in leads:
        score_tier_distribution[lead.get("tier", "Archive")] += 1

    deal_path_distribution = Counter()
    for lead in leads:
        for dp in lead.get("deal_paths", []):
            deal_path_distribution[dp["path"]] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "build_label": build_label,
        "mode": mode,
        "county": county,
        "state": state,
        "deployment": deployment or {},
        "lead_total": len(leads),
        "total_signals_active": sum(len(lead.get("_active_signals", [])) for lead in leads),
        "total_signals_suppressed": suppressed_count,
        "pattern_counts": dict(sorted(pattern_counts.items())),
        "attribute_counts": dict(sorted(attribute_counts.items())),
        "stack_depth_distribution": dict(sorted(stack_depth_distribution.items())),
        "score_tier_distribution": dict(sorted(score_tier_distribution.items())),
        "deal_path_distribution": dict(sorted(deal_path_distribution.items())),
        "quality_metrics": quality_metrics,
        "records": rows,
    }


def assert_two_truths(payload: dict) -> None:
    """
    Re-derive header counts from records[] and assert they match.
    Two-Truths invariant per MASTER_PROMPT §5.
    """
    rederived_patterns = Counter()
    rederived_attrs = Counter()
    rederived_deals = Counter()
    rederived_tiers = Counter()
    rederived_depths = Counter()
    for row in payload["records"]:
        for p in row["display_patterns"]:
            rederived_patterns[p] += 1
        for a in row["display_attributes"]:
            rederived_attrs[a] += 1
        for dp in row["display_deal_paths"]:
            rederived_deals[dp] += 1
        rederived_tiers[row["display_tier"]] += 1
        rederived_depths[str(row["stack_depth"])] += 1

    if dict(sorted(rederived_patterns.items())) != payload["pattern_counts"]:
        raise AssertionError(
            "Two-Truths failure: pattern_counts header != rederived from records[]"
        )
    if dict(sorted(rederived_attrs.items())) != payload["attribute_counts"]:
        raise AssertionError(
            "Two-Truths failure: attribute_counts header != rederived from records[]"
        )
    if dict(sorted(rederived_deals.items())) != payload["deal_path_distribution"]:
        raise AssertionError(
            "Two-Truths failure: deal_path_distribution header != rederived from records[]"
        )
    if dict(sorted(rederived_tiers.items())) != payload["score_tier_distribution"]:
        raise AssertionError(
            "Two-Truths failure: score_tier_distribution header != rederived from records[]"
        )
    if dict(sorted(rederived_depths.items())) != payload["stack_depth_distribution"]:
        raise AssertionError(
            "Two-Truths failure: stack_depth_distribution header != rederived from records[]"
        )
