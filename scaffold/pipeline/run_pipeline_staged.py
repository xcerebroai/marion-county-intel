"""
run_pipeline_staged — v5.4.0 staged pipeline orchestrator (Cutover Part 1).

STATUS: NEW MODULE in v5.4.0 Session 9. This module orchestrates the staged
pipeline end-to-end:

  raw events
    → §17 debtor_party_engine        → debtor_resolved records
    → §18 leads_base_writer          → <source>_leads_base.json
    → §19 aggregator                 → matched_leads.json   (immutable)
    → §20 semantic_verify            → deploy verdict       (gate)
    → SEAM (scoring_seam.score_matched_leads)
    → scored_lead records             (scored_leads.json)
    → dashboard projection            (data.json)

The §20 verdict is the gate: scoring + dashboard run only when §20 returns
`DEPLOY_OK`, or `NEEDS_OPERATOR_REVIEW` with explicit approval (per the
Session 6 seam design §4 and Session 9 task §4).

This orchestrator EXISTS ALONGSIDE the monolith's `build_leads.py`. Both
are runnable concurrently — the monolith is the safety net until Session 10
proves the staged path and retires the monolith core. Do NOT delete or
disable build_leads.py from this module; the call sites are independent.

Enrichment is OPTIONAL per R3(iii) / §13.14. The orchestrator accepts an
optional enrichment_provider; if absent, scoring runs UNENRICHED and the
dashboard renders without parcel-display fields. A lead is never dropped,
blocked, or held for missing enrichment.

This module is universal framework code: no county / state / vendor literal
appears here. The county-agnostic regression scanner enforces that.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Callable, Optional, Sequence

from scaffold.pipeline import aggregator
from scaffold.pipeline import debtor_party_engine
from scaffold.pipeline import evidence_ledger as evidence_ledger_mod
from scaffold.pipeline import leads_base_writer
from scaffold.pipeline import scoring_seam
from scaffold.pipeline import semantic_verify


def _group_by_source(raw_events: Sequence[dict]) -> dict:
    """Group raw events by source_id so leads_base_writer can produce one
    `<source>_leads_base.json` per source (§02.4 / §18 / §19.C contract)."""
    out: dict = {}
    for ev in raw_events:
        sid = ev.get("source_id") or "unknown"
        out.setdefault(sid, []).append(ev)
    return out


def run_staged_pipeline(
    raw_events: Sequence[dict],
    *,
    evidence_entries: Sequence[dict] = (),
    signal_type_labels: Optional[dict] = None,
    workdir: Path,
    as_of: Optional[date] = None,
    enrichment_provider: Optional[scoring_seam.EnrichmentProvider] = None,
    approve_needs_review: bool = False,
    debtor_party_rules: Optional[dict] = None,
    additional_suppressions: tuple = (),
    scoring_overrides: Optional[dict] = None,
    lis_pendens_mode: Optional[str] = None,
) -> dict:
    """Drive raw_events through §17 → §18 → §19 → §20 → seam → scoring.

    Returns a result dict carrying:
      - debtor_resolved          — the §17 outputs (list of dict)
      - leads_base               — the §18 outputs (list of dict per source)
      - leads_base_paths         — per-source base-file paths written
      - matched_leads            — the §19 output (list of dict)
      - matched_leads_path       — Path to matched_leads.json
      - evidence_ledger_path     — Path to evidence_ledger.json
      - semantic_report          — §20 verification report
      - semantic_verdict         — §20 deploy verdict
      - scored_leads             — the seam outputs (list of dict) — empty
                                   when the verdict blocked scoring
      - scored_leads_path        — Path to scored_leads.json (None if blocked)

    Raises:
      scoring_seam.SemanticGateBlocked       — §20 verdict DEPLOY_BLOCKED.
      scoring_seam.SemanticGateNeedsReview   — §20 verdict NEEDS_OPERATOR_REVIEW
                                                without approve_needs_review=True.
    """
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    signal_type_labels = signal_type_labels or {}

    # --- §17 debtor party engine ------------------------------------------
    debtor_resolved = [
        debtor_party_engine.resolve_debtor_party(
            ev,
            debtor_party_rules=debtor_party_rules,
            additional_suppressions=additional_suppressions,
        )
        for ev in raw_events
    ]

    # --- §18 evidence ledger + leads-base writer --------------------------
    ledger = evidence_ledger_mod.build_evidence_ledger(evidence_entries)
    base_records = [
        leads_base_writer.build_base_record(
            drr,
            signal_type_labels=signal_type_labels,
            evidence_ledger=ledger,
        )
        for drr in debtor_resolved
    ]

    base_paths: list[Path] = []
    for source_id, source_drrs in _group_by_source(debtor_resolved).items():
        source_base = [
            leads_base_writer.build_base_record(
                drr,
                signal_type_labels=signal_type_labels,
                evidence_ledger=ledger,
            )
            for drr in source_drrs
        ]
        base_paths.append(
            leads_base_writer.write_leads_base(
                source_id, source_base, output_dir=workdir
            )
        )

    # --- §19 aggregator → matched_leads.json (immutable) ------------------
    matched_leads_path = workdir / "matched_leads.json"
    matched_leads = aggregator.aggregate(base_paths, output_path=matched_leads_path)
    evidence_ledger_path = evidence_ledger_mod.write_evidence_ledger(
        evidence_entries, output_dir=workdir
    )

    # --- §20 semantic verification (gate) ---------------------------------
    semantic_report = semantic_verify.run_semantic_verification(
        matched_leads,
        leads_base_records=base_records,
        evidence_ledger=ledger,
    )
    # Raises if §20 blocked / needs-review-without-approval.
    semantic_verdict = scoring_seam.gate_on_semantic_verdict(
        semantic_report, approve_needs_review=approve_needs_review
    )

    # --- SEAM + retained scoring / classify / title / review --------------
    scored_leads = scoring_seam.score_matched_leads(
        matched_leads,
        as_of=as_of,
        enrichment_provider=enrichment_provider,
        scoring_overrides=scoring_overrides,
        lis_pendens_mode=lis_pendens_mode,
    )
    scored_leads_path = workdir / "scored_leads.json"
    scored_leads_path.write_text(
        json.dumps(scored_leads, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    return {
        "debtor_resolved": debtor_resolved,
        "leads_base": base_records,
        "leads_base_paths": base_paths,
        "matched_leads": matched_leads,
        "matched_leads_path": matched_leads_path,
        "evidence_ledger_path": evidence_ledger_path,
        "semantic_report": semantic_report,
        "semantic_verdict": semantic_verdict,
        "scored_leads": scored_leads,
        "scored_leads_path": scored_leads_path,
    }


# ---------------------------------------------------------------------------
# Dashboard projection — staged-pipeline-shaped scored_lead → dashboard row.
# Adapter mirrors dashboard.project_lead's contract but consumes scored_lead's
# parcel_display directly (no separate parcel-master dict required).
# ---------------------------------------------------------------------------

def project_scored_lead(scored_lead: dict) -> dict:
    """Dashboard projection from a scored_lead. The R3(iii) enrichment-optional
    rule: when scored_lead is UNENRICHED, display fields are empty strings /
    None (the dashboard renders without them); when ENRICHED, the
    parcel_display block populates them. Two-Truths-compatible: pattern_counts
    / attribute_counts re-derive cleanly from these rows."""
    parcel = scored_lead.get("parcel_display") or {}
    return {
        "lead_id": scored_lead["lead_id"],
        "scored_lead_id": scored_lead["scored_lead_id"],
        "primary_parcel_id": scored_lead.get("primary_parcel_id"),
        "display_address": ", ".join(
            v for v in (
                parcel.get("situs_address"),
                parcel.get("situs_city"),
                parcel.get("situs_state"),
            ) if v
        ),
        "display_owner": scored_lead.get("owner_name") or "Unknown",
        "display_score": scored_lead.get("score", 0),
        "display_tier": scored_lead.get("tier") or "",
        "display_patterns": list(scored_lead.get("display_patterns") or []),
        "stack_contrib_patterns": list(scored_lead.get("patterns") or []),
        "display_pattern_set": list(scored_lead.get("pattern_set") or []),
        "display_attributes": list(scored_lead.get("attributes") or []),
        "display_deal_paths": [
            dp.get("path") for dp in scored_lead.get("deal_paths", [])
        ],
        "display_deal_path_details": list(scored_lead.get("deal_paths") or []),
        "display_title_complexity_tier": scored_lead.get(
            "title_complexity_tier", ""
        ),
        "display_lead_status": scored_lead.get("lead_status", "STACKED_LEAD"),
        "display_assessed_value": parcel.get("assessed_value"),
        "display_last_sale_price": parcel.get("last_sale_price"),
        "display_last_sale_date": parcel.get("last_sale_date"),
        "display_year_built": parcel.get("year_built"),
        "display_match_confidence": scored_lead.get("match_confidence") or 0,
        "stack_depth": scored_lead.get("stack_depth", 0),
        "score_reasons": list(scored_lead.get("score_reasons") or []),
        "evidence_ids": list(scored_lead.get("evidence_ids") or []),
        "primary_event_date": scored_lead.get("primary_event_date"),
        "review_flags": list(scored_lead.get("review_flags") or []),
        "enrichment_status": scored_lead.get("enrichment_status"),
    }


def build_dashboard_payload(
    scored_leads: Sequence[dict],
    *,
    semantic_verdict: str,
    county: str = "<synthetic>",
    state: str = "ZZ",
    mode: str = "synthetic",
    build_label: str = "FULL_BUILD",
) -> dict:
    """Build the staged-pipeline dashboard payload from a list of scored_leads.

    The §20 verdict is recorded on the payload for operator visibility. The
    payload shape mirrors dashboard.build_payload's distribution maps so a
    staged-pipeline dashboard can render with the same data shape the monolith
    dashboard expects."""
    from collections import Counter
    from datetime import datetime, timezone

    rows = [project_scored_lead(s) for s in scored_leads]

    pattern_counts: Counter = Counter()
    for s in scored_leads:
        for p in s.get("display_patterns") or []:
            pattern_counts[p] += 1

    attribute_counts: Counter = Counter()
    for s in scored_leads:
        for a in s.get("attributes") or []:
            attribute_counts[a] += 1

    stack_depth_distribution: Counter = Counter()
    for s in scored_leads:
        stack_depth_distribution[str(s.get("stack_depth", 0))] += 1

    score_tier_distribution: Counter = Counter()
    for s in scored_leads:
        score_tier_distribution[s.get("tier", "Archive")] += 1

    deal_path_distribution: Counter = Counter()
    for s in scored_leads:
        for dp in s.get("deal_paths") or []:
            deal_path_distribution[dp.get("path") or ""] += 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ).replace("+00:00", "Z"),
        "build_label": build_label,
        "mode": mode,
        "county": county,
        "state": state,
        "semantic_verdict": semantic_verdict,
        "lead_total": len(scored_leads),
        "enrichment_breakdown": {
            "ENRICHED": sum(
                1 for s in scored_leads
                if s.get("enrichment_status") == "ENRICHED"
            ),
            "UNENRICHED": sum(
                1 for s in scored_leads
                if s.get("enrichment_status") == "UNENRICHED"
            ),
        },
        "pattern_counts": dict(sorted(pattern_counts.items())),
        "attribute_counts": dict(sorted(attribute_counts.items())),
        "stack_depth_distribution": dict(sorted(stack_depth_distribution.items())),
        "score_tier_distribution": dict(sorted(score_tier_distribution.items())),
        "deal_path_distribution": dict(sorted(deal_path_distribution.items())),
        "records": rows,
    }
