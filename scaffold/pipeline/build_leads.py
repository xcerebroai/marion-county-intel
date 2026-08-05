"""
build_leads.py — Pipeline orchestrator (v5.4.0 staged + Option-Y seam).

v5.4.0 Session 10 — REWRITTEN. Through v5.1.2-beta this module orchestrated
the monolith's signal → identity → aggregation → scoring core (one inline
pipeline that lifted raw signals into stacks and emitted leads.json). The
v5.4.0 cutover replaces that core with the staged engine
(§17 debtor_party_engine → §18 leads_base_writer → §19 aggregator → §20
semantic_verify) plus the Option-Y scoring seam (scoring_seam) plus the
retained scoring / classify / title-complexity / review / dashboard stages.

This file is the post-cutover orchestrator. The retired signal-stack-lead
orchestration of the v5.1.2-beta monolith is gone — there is no second
pipeline that can be run by mistake. RETAINED upstream / downstream
modules remain reachable from here:

  - normalize.normalize_doc_type  — raw subtype → canonical_doc_type
                                     (registry-aligned UPPERCASE; the
                                     doc_type_bridge lowercases for the
                                     staged engine)
  - translators/                   — per-source raw-record → signal
                                     adapters (production mode)
  - matcher.match_signals_to_parcels — parcel-master address resolution
                                       (§13.14 parcel-resolution stage,
                                       between translators and §17)
  - score.compute_score            — invoked by scoring_seam
  - classify.classify_deal_paths   — invoked by scoring_seam
  - review.evaluate_review_queue   — invoked by scoring_seam
  - dashboard.assert_two_truths    — Two-Truths invariant on the payload
  - manifest.build_run_manifest    — run manifest
  - manifest.build_heartbeat       — per-source heartbeat
  - owner_name_patterns.emit_owner_name_signals_for_parcels — parcel-
                                     master-derived signals (production)

Usage:

    # Synthetic harness (Phase 1). Reads scaffold/data/synthetic_*.jsonl
    # and writes data/<run>.{matched_leads,scored_leads,evidence_ledger,
    # dashboard}.json plus manifests + heartbeats.
    python3 scaffold/pipeline/build_leads.py --synthetic

    # Production mode. Reads data/raw/<source>.jsonl and writes the same
    # artifact set, gated by the §20 semantic verdict.
    python3 scaffold/pipeline/build_leads.py --county-config config/counties/<county_slug>.json

Synthetic mode is mandatory before any production run on a new county
per MASTER_PROMPT §6 Phase 1.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# Allow running this module directly via `python3 scaffold/pipeline/build_leads.py`.
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.pipeline import run_pipeline_staged  # noqa: E402
from scaffold.pipeline.dashboard import assert_two_truths  # noqa: E402
from scaffold.pipeline.doc_type_bridge import monolith_to_registry  # noqa: E402
from scaffold.pipeline.manifest import (  # noqa: E402
    build_heartbeat,
    build_run_manifest,
)
from scaffold.pipeline.matcher import match_signals_to_parcels  # noqa: E402
from scaffold.pipeline.normalize import (  # noqa: E402
    CANONICAL,
    normalize_doc_type,
)
from scaffold.pipeline.owner_name_patterns import (  # noqa: E402
    emit_owner_name_signals_for_parcels,
)
from scaffold.pipeline.translators import (  # noqa: E402
    lookup as lookup_translator,
)
from scaffold.pipeline.state_profile import mode_from_rule_family  # noqa: E402

# Import county-side translator registrations if available.
try:
    import scrapers  # noqa: F401, E402
except ImportError:
    pass


SYNTHETIC_DEFAULT_AS_OF = date(2026, 5, 14)


# ---------------------------------------------------------------------------
# Small helpers — IDs, dates, JSONL I/O.
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _deterministic_id(prefix: str, *parts) -> str:
    """Stable ID from inputs — replaces uuid for reproducible synthetic runs."""
    h = hashlib.sha1(
        "|".join("" if p is None else str(p) for p in parts).encode("utf-8")
    ).hexdigest()
    return f"{prefix}_{h[:16]}"


def _read_jsonl(path: Path) -> list:
    out: list = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            out.append(json.loads(line))
    return out


def _auto_discover_county_config() -> str:
    """Resolve the active county config when --county-config is not supplied.

    Auto-discovery is for single-county working directories (the standard
    distribution pattern). Multi-county repos must pass --county-config
    explicitly per §02 Build Mode Protocol.
    """
    counties_dir = REPO_ROOT / "config" / "counties"
    matches = sorted(
        p for p in counties_dir.glob("*.json")
        if not p.name.startswith("_")
    )
    if len(matches) == 1:
        return str(matches[0].relative_to(REPO_ROOT))
    if not matches:
        raise SystemExit(
            "no county config found in config/counties/ — "
            "pass --county-config explicitly"
        )
    names = sorted(p.name for p in matches)
    raise SystemExit(
        f"multiple county configs found in config/counties/: {names} — "
        "pass --county-config explicitly to disambiguate"
    )


# ---------------------------------------------------------------------------
# Translator-output / synthetic-signal → raw_event_record adapter.
# The post-cutover §17 engine consumes raw_event_record (Session 1 contract).
# This adapter is the only signal-shape layer the orchestrator owns — the
# rest of the pipeline runs on contract-shaped records.
# ---------------------------------------------------------------------------

_NAME_TYPE_FROM_FIELD = {
    "grantor": "GR",
    "grantee": "GE",
    "plaintiff": "PL",
    "defendant": "DF",
    "taxpayer": "TP",
}


def _parties_from_signal(sig: dict) -> list:
    """Build the raw_event_record.parties list from a v5.1.2-beta-shaped
    signal's grantor / grantee / plaintiff / defendant fields. Empty list
    when no party is present — §17 then routes via DOCUMENT_BODY / REVIEW."""
    parties: list = []
    for field, name_type in _NAME_TYPE_FROM_FIELD.items():
        raw_value = sig.get(field)
        if isinstance(raw_value, str) and raw_value.strip():
            for name in (s.strip() for s in raw_value.split(";")):
                if name:
                    parties.append({
                        "name": name, "name_type": name_type,
                        "raw_role": field,
                    })
    return parties


def _signal_to_raw_event(sig: dict, *, parcels_by_id: dict,
                          source_role: str = "PRIMARY_EVENT_SOURCE") -> Optional[dict]:
    """Lift one signal-shape dict into a raw_event_record.

    Returns None when the doc-type cannot be normalized to a registry-aligned
    canonical_doc_type — those records would fail the staged engine's F-5
    default routing anyway, so the orchestrator drops them at the input seam
    and surfaces the count via the manifest.
    """
    raw_doc_type = sig.get("subtype") or sig.get("doc_type") or ""
    norm = normalize_doc_type(raw_doc_type)
    normalized_upper = norm.get("normalized_doc_type")
    if not normalized_upper:
        return None
    canonical_doc_type = monolith_to_registry(normalized_upper)
    if canonical_doc_type is None:
        return None

    parcel_id = sig.get("parcel_id") or sig.get("primary_parcel_id")
    parcel = parcels_by_id.get(parcel_id) or {}
    raw_event_id = _deterministic_id(
        "raw", sig.get("source_url"), parcel_id, raw_doc_type,
        sig.get("filing_date"),
    )
    evidence_id = "ev_" + raw_event_id[len("raw_"):]

    return {
        "raw_event_id": raw_event_id,
        "source_id": sig.get("source_id") or sig.get("source") or "unknown",
        "source_role": source_role,
        "canonical_doc_type": canonical_doc_type,
        "raw_doc_type": raw_doc_type,
        "instrument_number": sig.get("case_number") or sig.get("doc_number"),
        "recorded_date": sig.get("filing_date"),
        "event_date": None,
        "source_url": sig.get("source_url", ""),
        "parties": _parties_from_signal(sig),
        "document_body_text": sig.get("document_body_text"),
        "property_refs": {
            "parcel_id": parcel_id,
            "situs_address": parcel.get("situs_address") or sig.get("address"),
            "legal_description": parcel.get("legal_description")
                                 or sig.get("legal_description"),
            "case_number": sig.get("case_number"),
        },
        "amounts": [
            {"label": "amount", "value": sig["amount"]}
        ] if isinstance(sig.get("amount"), (int, float)) else [],
        "evidence_ids": [evidence_id],
        "parser_name": sig.get("_translator_name") or "build_leads",
        "parser_version": "5.4.0",
        "parser_confidence": int(sig.get("parser_confidence", 95)),
        "captured_at": sig.get("captured_at") or _now_iso(),
    }


def _evidence_entry_for_signal(raw_event: dict, sig: dict) -> dict:
    return {
        "evidence_id": raw_event["evidence_ids"][0],
        "record_id": raw_event["raw_event_id"],
        "field": "owner_name",
        "value": (sig.get("grantor") or sig.get("plaintiff")
                  or sig.get("defendant") or "synthetic"),
        "status": "Confirmed",
        "source_id": raw_event["source_id"],
        "source_reliability_grade": "A",
        "source_url": raw_event["source_url"]
            or f"synthetic://{raw_event['raw_event_id']}",
        "captured_at": raw_event["captured_at"],
    }


# ---------------------------------------------------------------------------
# Translator dispatch (production mode) — translator-supplied raw records →
# signal dicts. The translator registry is RETAINED unchanged from v5.1.2-beta.
# ---------------------------------------------------------------------------

def _adapt_translator_signal(sig: dict, source_id: str) -> dict:
    """Bridge translator output to the signal shape _signal_to_raw_event
    consumes. Carries forward the new-shape fields (primary_parcel_id,
    doc_type_subtype_label, doc_number) under their legacy aliases."""
    adapted = dict(sig)
    if "primary_parcel_id" in adapted:
        adapted.setdefault("parcel_id", adapted["primary_parcel_id"])
    adapted.setdefault("source", sig.get("source_id", source_id))
    adapted.setdefault(
        "subtype", sig.get("doc_type") or sig.get("doc_type_subtype_label")
    )
    adapted.setdefault("case_number", sig.get("doc_number"))
    return adapted


# ---------------------------------------------------------------------------
# Enrichment provider — wraps a per-county parcel-master into the seam's
# enrichment_provider contract. R3(iii) — a parcel without a master row
# returns None and the seam scores UNENRICHED, no block.
# ---------------------------------------------------------------------------

def _build_enrichment_provider(parcels: list):
    """Build a seam-shape enrichment_provider closure over a parcel master."""
    by_id = {p.get("parcel_id"): p for p in parcels if p.get("parcel_id")}

    def provider(parcel_id: Optional[str]) -> Optional[dict]:
        if not parcel_id:
            return None
        return by_id.get(parcel_id)
    return provider


# ---------------------------------------------------------------------------
# Public entry point — `run_pipeline`. Same name as the legacy monolith
# function; the SIGNATURE changes (legacy `mode/parcels/raw_signals/...`
# kwargs preserved for backward compatibility), but the BODY routes through
# the staged engine. Returns a dict with the same outer keys legacy callers
# expected (payload, manifest, heartbeat, evidence_records) plus the new
# staged artifacts (matched_leads, scored_leads, semantic_verdict).
# ---------------------------------------------------------------------------

def run_pipeline(
    *,
    mode: str,
    parcels: list,
    raw_signals: list,
    county_id: str = "",
    county_name: str = "",
    state: str = "",
    state_rule_family: str = "",
    scoring_overrides: Optional[dict] = None,
    as_of: Optional[date] = None,
    per_signal_meta: Optional[dict] = None,
    build_label: str = "FULL_BUILD",
    build_label_reason: str = "",
    deployment: Optional[dict] = None,
    workdir: Optional[Path] = None,
    approve_needs_review: bool = False,
) -> dict:
    """Drive a list of v5.1.2-beta-shaped raw_signals through the v5.4.0
    staged pipeline + the Option-Y scoring seam.

    The orchestrator:
      1. Adapts each signal to a raw_event_record via _signal_to_raw_event
         (normalize.normalize_doc_type for canonical_doc_type, parties from
         grantor / grantee / plaintiff / defendant fields, property_refs
         from the parcel-master row).
      2. Builds an evidence entry per raw_event_record.
      3. Calls run_pipeline_staged.run_staged_pipeline (§17 → §18 → §19 →
         §20 → seam → scored_leads.json). §20 gates scoring.
      4. Builds the dashboard payload via run_pipeline_staged.build_dashboard_payload.
      5. Asserts the Two-Truths invariant on the payload (re-derive
         pattern_counts / attribute_counts / tier and depth distributions
         from records[]).
      6. Builds the run manifest + per-source heartbeats.
    """
    as_of = as_of or date.today()
    workdir = Path(workdir) if workdir else (REPO_ROOT / "data")
    workdir.mkdir(parents=True, exist_ok=True)
    started_at = _now_iso()

    # --- adapt signals to raw_event_records + evidence entries ------------
    parcels_by_id = {
        p.get("parcel_id"): p for p in parcels if p.get("parcel_id")
    }
    raw_events: list = []
    evidence_entries: list = []
    dropped_signals = 0
    for sig in raw_signals:
        raw_event = _signal_to_raw_event(sig, parcels_by_id=parcels_by_id)
        if raw_event is None:
            dropped_signals += 1
            continue
        raw_events.append(raw_event)
        evidence_entries.append(_evidence_entry_for_signal(raw_event, sig))

    # --- per-county signal_type labels (operator-facing chip text) --------
    signal_type_labels: dict = {}
    for raw_event in raw_events:
        cdt = raw_event["canonical_doc_type"]
        if cdt and cdt not in signal_type_labels:
            entry = CANONICAL.get(cdt.upper(), {})
            signal_type_labels[cdt] = entry.get(
                "subtype", cdt.replace("_", " ").title()
            ) or cdt

    # --- staged pipeline §17→§18→§19→§20 + seam (R3-iii enrichment) ------
    enrichment_provider = _build_enrichment_provider(parcels)
    staged = run_pipeline_staged.run_staged_pipeline(
        raw_events,
        evidence_entries=evidence_entries,
        signal_type_labels=signal_type_labels,
        workdir=workdir,
        as_of=as_of,
        enrichment_provider=enrichment_provider,
        approve_needs_review=approve_needs_review,
        scoring_overrides=scoring_overrides,
        lis_pendens_mode=mode_from_rule_family(state_rule_family),
    )

    # --- dashboard payload + Two-Truths invariant -------------------------
    payload = run_pipeline_staged.build_dashboard_payload(
        staged["scored_leads"],
        semantic_verdict=staged["semantic_verdict"],
        county=county_name or "<synthetic>",
        state=state or "ZZ",
        mode=mode,
        build_label=build_label,
    )
    payload["build_label_reason"] = build_label_reason
    payload["deployment"] = deployment or {}
    payload["dropped_signals_unmapped_doc_type"] = dropped_signals
    # Re-derive header counts from records[] — the v5.1.2-beta Two-Truths
    # invariant survives the cutover unchanged.
    assert_two_truths(payload)

    # --- per-source heartbeats --------------------------------------------
    source_ids = sorted({r.get("source_id", "unknown") for r in raw_events})
    heartbeats = []
    for sid in source_ids:
        seen = sum(1 for r in raw_events if r.get("source_id") == sid)
        is_synth = mode == "synthetic"
        heartbeats.append(
            build_heartbeat(
                source_id=sid,
                source_name=f"{sid} (synthetic)" if is_synth else sid,
                source_class="lead_generating",
                source_priority="P0",
                source_reliability_grade="A",
                build_priority=(
                    "mvp_required" if "sheriff" in sid or "clerk" in sid
                    or "foreclosure" in sid else "high_value"
                ),
                access_pattern=(
                    "synthetic_jsonl_fixture" if is_synth else "open_api"
                ),
                records_seen=seen,
                records_new=seen,
                strategy=(
                    "synthetic_jsonl_fixture" if is_synth
                    else "arcgis_rest_query"
                ),
                strategy_reason=(
                    "Phase 1 synthetic harness" if is_synth
                    else f"Phase 3 production pull from {sid}"
                ),
            )
        )

    # --- run manifest -----------------------------------------------------
    review_required_count = sum(
        1 for s in staged["scored_leads"]
        if s.get("lead_status") == "REVIEW_REQUIRED"
    )
    manifest = build_run_manifest(
        county=county_name or "<synthetic>",
        state=state or "ZZ",
        started_at=started_at,
        sources_attempted=len(source_ids),
        records_collected=len(raw_signals),
        records_normalized=len(raw_events),
        leads_created=len(staged["scored_leads"]),
        review_required=review_required_count,
        output_files=[],  # filled in by main() after writing artifacts
    )

    return {
        "payload": payload,
        "heartbeat": heartbeats,
        "manifest": manifest,
        "evidence_records": evidence_entries,
        "raw_events": raw_events,
        "matched_leads": staged["matched_leads"],
        "scored_leads": staged["scored_leads"],
        "semantic_verdict": staged["semantic_verdict"],
        "semantic_report": staged["semantic_report"],
        "matched_leads_path": staged["matched_leads_path"],
        "scored_leads_path": staged["scored_leads_path"],
        "evidence_ledger_path": staged["evidence_ledger_path"],
    }


# ---------------------------------------------------------------------------
# CLI — `python3 scaffold/pipeline/build_leads.py --synthetic`
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build leads via the v5.4.0 staged + Option-Y seam pipeline.",
    )
    parser.add_argument(
        "--synthetic", action="store_true",
        help="Run against scaffold/data/synthetic_*.jsonl fixtures.",
    )
    parser.add_argument(
        "--county-config", default=None,
        help="Path to populated county config. Auto-discovered from "
             "config/counties/ when omitted (single non-underscore *.json match).",
    )
    parser.add_argument(
        "--out", default=None,
        help="Output directory. Defaults to data/<synth-or-prod>/.",
    )
    parser.add_argument(
        "--as-of", default=None,
        help="ISO date (YYYY-MM-DD) for TTL / recency. Synthetic default: "
             f"{SYNTHETIC_DEFAULT_AS_OF.isoformat()}. Production: today.",
    )
    parser.add_argument(
        "--approve-needs-review", action="store_true",
        help="Approve scoring under §20 NEEDS_OPERATOR_REVIEW verdict.",
    )
    args = parser.parse_args()

    if args.county_config is None:
        args.county_config = _auto_discover_county_config()
    config_path = REPO_ROOT / args.county_config
    if not config_path.exists():
        print(f"county config not found: {config_path}", file=sys.stderr)
        return 2
    county_config = json.loads(config_path.read_text(encoding="utf-8"))

    as_of = None
    if args.as_of:
        as_of = date.fromisoformat(args.as_of)
    elif args.synthetic:
        as_of = SYNTHETIC_DEFAULT_AS_OF

    build_label = "FULL_BUILD"
    build_label_reason = ""

    if args.synthetic:
        parcels = _read_jsonl(
            REPO_ROOT / "scaffold" / "data" / "synthetic_parcels.jsonl"
        )
        raw_signals = _read_jsonl(
            REPO_ROOT / "scaffold" / "data" / "synthetic_signals.jsonl"
        )
        out_dir = Path(args.out) if args.out else REPO_ROOT / "data" / "synthetic"
        mode = "synthetic"
    else:
        raw_dir = REPO_ROOT / "data" / "raw"
        if not raw_dir.exists():
            print(
                "data/raw/ directory not found. Run scrapers first or use --synthetic.",
                file=sys.stderr,
            )
            return 3

        all_signals: list = []
        all_parcels: list = []
        bcad_records: list = []
        translated_sources: list = []

        for source_id, source_cfg in county_config.get("sources", {}).items():
            if not source_cfg.get("enabled", True):
                continue
            translator_name = source_cfg.get("translator")
            if not translator_name:
                continue
            raw_path = raw_dir / f"{source_id}.jsonl"
            if not raw_path.exists():
                continue
            raw_records = _read_jsonl(raw_path)
            source_cfg_with_id = dict(source_cfg)
            source_cfg_with_id["_source_id"] = source_id
            translate_fn = lookup_translator(translator_name)
            signals, parcels, _per_signal_meta = translate_fn(
                raw_records, county_config, source_cfg_with_id,
            )
            adapted = [_adapt_translator_signal(s, source_id) for s in signals]
            all_signals.extend(adapted)
            is_enrichment = (
                source_cfg.get("lead_value", "").upper() == "ENRICHMENT"
                or not signals
            )
            if is_enrichment:
                bcad_records.extend(parcels)
            else:
                seen_ids = {p["parcel_id"] for p in all_parcels}
                for p in parcels:
                    if p["parcel_id"] not in seen_ids:
                        seen_ids.add(p["parcel_id"])
                        all_parcels.append(p)
            translated_sources.append({
                "source_id": source_id,
                "records": len(raw_records), "signals": len(signals),
                "parcels": len(parcels),
            })

        # Parcel-master matcher — replace placeholder parcels with real ones.
        if bcad_records and all_signals:
            enriched_signals = [
                {
                    "signal_id": s.get("raw_record_id") or s.get("source_url"),
                    "_record_address": s.get("address", ""),
                    "_record_zip": s.get("zip", ""),
                    "_record_city": s.get("city", ""),
                    "_source_signal": s,
                }
                for s in all_signals
            ]
            matched, match_meta = match_signals_to_parcels(
                enriched_signals, bcad_records,
            )
            placeholders_by_id = {p["parcel_id"]: p for p in all_parcels}
            new_parcels_by_id: dict = {}
            for enr, sig in zip(enriched_signals, all_signals):
                m = match_meta.get(enr["signal_id"], {})
                primary_pid = m.get("primary_parcel_id")
                if primary_pid and primary_pid in matched:
                    sig["parcel_id"] = primary_pid
                    sig["primary_parcel_id"] = primary_pid
                    new_parcels_by_id[primary_pid] = matched[primary_pid]
                else:
                    placeholder_pid = sig.get("parcel_id")
                    if placeholder_pid in placeholders_by_id:
                        new_parcels_by_id[placeholder_pid] = (
                            placeholders_by_id[placeholder_pid]
                        )
            all_parcels = list(new_parcels_by_id.values())

            # Owner-name-pattern signals — emit raw_event_records for parcels
            # whose owner name matches the estate / living-trust patterns.
            parcels_with_lead_signals = {
                sig.get("primary_parcel_id") or sig.get("parcel_id")
                for sig in all_signals
                if sig.get("primary_parcel_id") or sig.get("parcel_id")
            }
            emitted = emit_owner_name_signals_for_parcels(
                parcels=all_parcels,
                parcels_with_lead_signals=parcels_with_lead_signals,
                source_id="parcel_master",
            )
            adapted_owner_name = [
                _adapt_translator_signal(s, "parcel_master") for s in emitted
            ]
            all_signals.extend(adapted_owner_name)

        raw_signals = all_signals
        parcels = all_parcels
        out_dir = Path(args.out) if args.out else REPO_ROOT / "data"
        mode = "production"

        sources_used = [
            s for s, c in county_config.get("sources", {}).items()
            if c.get("enabled", True) and c.get("translator")
        ]
        if len(sources_used) < 3:
            build_label = "SOURCE_LIMITED"
            build_label_reason = (
                f"Source-limited build: only sources {sources_used} were "
                "enabled. Other sources are deferred."
            )

        print(f"[production] translated sources: {translated_sources}",
              file=sys.stderr)

    if not parcels:
        print("no parcels available; cannot proceed.", file=sys.stderr)
        return 4

    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = run_pipeline(
            mode=mode, parcels=parcels, raw_signals=raw_signals,
            county_id=county_config.get("county_id", ""),
            county_name=county_config.get("county_name", ""),
            state=county_config.get("state", ""),
            state_rule_family=county_config.get("state_rule_family", ""),
            scoring_overrides=county_config.get("scoring_overrides", {}),
            as_of=as_of,
            build_label=build_label, build_label_reason=build_label_reason,
            deployment=county_config.get("deployment") or {},
            workdir=out_dir,
            approve_needs_review=args.approve_needs_review,
        )
    except run_pipeline_staged.scoring_seam.SemanticGateBlocked as exc:
        print(f"§20 DEPLOY_BLOCKED: {exc}", file=sys.stderr)
        return 5
    except run_pipeline_staged.scoring_seam.SemanticGateNeedsReview as exc:
        print(f"§20 NEEDS_OPERATOR_REVIEW: {exc}\n"
              "  Re-run with --approve-needs-review to proceed.",
              file=sys.stderr)
        return 6

    # --- write dashboard payload + heartbeat + manifest -------------------
    payload_path = out_dir / "dashboard.json"
    payload_path.write_text(
        json.dumps(result["payload"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    heartbeat_path = out_dir / "source_heartbeat.json"
    heartbeat_path.write_text(
        json.dumps(result["heartbeat"], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest = result["manifest"]
    manifest_files = []
    for p in (payload_path, heartbeat_path,
              result["matched_leads_path"], result["scored_leads_path"],
              result["evidence_ledger_path"]):
        try:
            manifest_files.append(str(Path(p).relative_to(REPO_ROOT)))
        except ValueError:
            manifest_files.append(str(p))
    manifest["output_files"] = manifest_files

    manifest_dir = out_dir / "runs"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "latest.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8",
    )
    (manifest_dir / f"{manifest['run_id']}.manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8",
    )

    payload = result["payload"]
    print(f"Wrote {payload_path}")
    print(f"  lead_total:               {payload['lead_total']}")
    print(f"  §20 verdict:              {result['semantic_verdict']}")
    print(f"  score_tier_distribution:  {payload['score_tier_distribution']}")
    print(f"  deal_path_distribution:   {payload['deal_path_distribution']}")
    print(f"  pattern_counts:           {payload['pattern_counts']}")
    print(f"  attribute_counts:         {payload['attribute_counts']}")
    print(f"  enrichment_breakdown:     {payload['enrichment_breakdown']}")
    print(f"  matched_leads.json:       {result['matched_leads_path']}")
    print(f"  scored_leads.json:        {result['scored_leads_path']}")
    print(f"  evidence_ledger.json:     {result['evidence_ledger_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
