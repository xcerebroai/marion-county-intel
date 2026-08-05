"""
semantic_verify — v5.4.0 staged pipeline, stage 5 (the §20 semantic gate).

STATUS: IMPLEMENTED in v5.4.0 Session 5. This module is the §20 semantic
verification engine — the pre-dashboard deploy gate that runs AFTER mechanical
verification (§20.G) and confirms the pipeline's output is *meaningful*, not
merely well-formed.

Contract: knowledge_base/architecture/20_semantic_verification_contract.md.

§20.C defines twelve check classes. Each check returns one of the §20.D outcome
states — VALID, INVALID, AMBIGUOUS — or SKIPPED when the check's deploy-time
inputs are not available to this pre-dashboard run. The overall verdict (§20.F):

  - DEPLOY_OK             — every executed check is VALID.
  - DEPLOY_BLOCKED        — any executed check is INVALID.
  - NEEDS_OPERATOR_REVIEW — at least one AMBIGUOUS, none INVALID.

Six checks run on the staged pipeline's own artifacts (matched_leads.json plus
the leads-base records and evidence ledger): Check 1 (debtor attribution),
Check 2 (owner-type classification), Check 4 (enrichment-decoupling integrity
and the §13.5 No-False-Dashboard row-provenance rule), Check 5 (signal
aggregation), Check 6 (cross-source aggregation), Check 12 (universal
filer-as-owner scan). Six checks need deploy-time inputs not present before the
dashboard renders — Check 3 (parcel-master join data), Check 7 (OCR confidence),
Check 8 (CSV export), Check 9 (live source-URL resolution), Check 10 (browser),
Check 11 (build report) — and report SKIPPED here; a county verifier supplies
those inputs at deploy time (§20.H).

Check 5 — count vs distinct instrument numbers: the §19 aggregator's `count` is
the number of distinct events (distinct non-null instruments PLUS each
null-instrument record), so `count` legitimately exceeds `len(instrument_numbers)`
when records carry null instruments. Per §20.D this is AMBIGUOUS — null
instruments (legitimate) or a dedup failure (a bug) — and routes to operator
review, NOT INVALID. `count < len(instrument_numbers)` is impossible and is
INVALID.

This module is universal framework code: the twelve check classes, the
three-state model, and the deploy verdicts are universal; per-county sample
sizes and the deploy-time check implementations are county-scoped (§20.J). No
county / state / vendor literal appears here.
"""

from __future__ import annotations

import json
from typing import Optional

from jsonschema import Draft202012Validator

from scaffold.pipeline.contracts import schema_path
from scaffold.pipeline.debtor_party_engine import classify_owner_type, match_known_filer

CHECK_STATES = ("VALID", "INVALID", "AMBIGUOUS", "SKIPPED")
"""§20.D outcome states, plus SKIPPED for a check whose deploy-time inputs are
absent (a reporting state — not a §20.D outcome)."""

DEPLOY_VERDICTS = ("DEPLOY_OK", "DEPLOY_BLOCKED", "NEEDS_OPERATOR_REVIEW")
"""§20.F overall deploy verdicts."""

_VALIDATOR_CACHE: dict[str, Draft202012Validator] = {}


def _matched_lead_validator() -> Draft202012Validator:
    if "v" not in _VALIDATOR_CACHE:
        schema = json.loads(
            schema_path("matched_lead_record").read_text(encoding="utf-8")
        )
        _VALIDATOR_CACHE["v"] = Draft202012Validator(schema)
    return _VALIDATOR_CACHE["v"]


def _result(check: int, name: str, status: str, detail: str,
            samples: Optional[list] = None) -> dict:
    """One §20.C check result."""
    if status not in CHECK_STATES:
        raise ValueError(f"_result: invalid status {status!r}")
    return {
        "check": check,
        "name": name,
        "status": status,
        "detail": detail,
        "samples": list(samples or []),
    }


# ---------------------------------------------------------------------------
# §20.C checks that run on the staged pipeline's own artifacts.
# ---------------------------------------------------------------------------

def _check_1_debtor_attribution(matched_leads: list, ctx: dict) -> dict:
    """Check 1 — owner_name is the debtor, never a known filer (§17 / §20.C)."""
    offenders = []
    for lead in matched_leads:
        if lead.get("parcel_resolution_status") == "REVIEW_REQUIRED":
            # owner_name is the §17.E placeholder, not a real party name.
            continue
        owner = lead.get("owner_name") or ""
        hit = match_known_filer(owner)
        if hit:
            offenders.append({
                "lead_id": lead.get("lead_id"),
                "owner_name": owner,
                "filer_pattern": hit,
            })
    if offenders:
        return _result(
            1, "Debtor attribution sampling", "INVALID",
            f"{len(offenders)} matched lead(s) carry a known filer pattern as "
            f"owner_name — a filer-as-owner inversion (§17).", offenders)
    return _result(
        1, "Debtor attribution sampling", "VALID",
        f"full scan of {len(matched_leads)} matched leads: no resolved "
        f"owner_name matches a known filer pattern.")


def _check_2_owner_type(matched_leads: list, ctx: dict) -> dict:
    """Check 2 — owner_type matches the §17.F classifier for owner_name."""
    offenders = []
    checked = 0
    for lead in matched_leads:
        if lead.get("parcel_resolution_status") == "REVIEW_REQUIRED":
            continue
        owner = lead.get("owner_name") or ""
        declared = lead.get("owner_type")
        rederived = classify_owner_type(owner)
        checked += 1
        if rederived != declared:
            offenders.append({
                "lead_id": lead.get("lead_id"),
                "owner_name": owner,
                "declared_owner_type": declared,
                "reclassified_owner_type": rederived,
            })
    if offenders:
        return _result(
            2, "Owner type classification sampling", "INVALID",
            f"{len(offenders)} matched lead(s) have an owner_type that "
            f"disagrees with the §17.F classifier (substring false positive "
            f"or misclassification).", offenders)
    return _result(
        2, "Owner type classification sampling", "VALID",
        f"full scan of {checked} resolved matched leads: owner_type agrees "
        f"with the §17.F classifier.")


def _check_3_parcel_plausibility(matched_leads: list, ctx: dict) -> dict:
    """Check 3 — parcel-resolution plausibility (deploy-time)."""
    return _result(
        3, "Parcel-resolution plausibility", "SKIPPED",
        "requires parcel-master join data and situs-address join keys — a "
        "county deploy-time check (§20.H); not present on matched_leads.json.")


def _check_4_enrichment_decoupling(matched_leads: list, ctx: dict) -> dict:
    """Check 4 — §13.14 enrichment-status decoupling + §13.5 No False Dashboard.

    (a) No invalid (parcel_resolution_status, enrichment_status) pair —
        ENRICHED requires a RESOLVED parcel (§13.14.1).
    (b) No False Dashboard: every matched lead carries at least one signal
        from a PRIMARY_EVENT_SOURCE — an enrichment-only row (no primary lead
        event) is a fabricated dashboard row (§13.5). Runs when leads-base
        source roles are available.
    """
    bad_combo = []
    for lead in matched_leads:
        prs = lead.get("parcel_resolution_status")
        ens = lead.get("enrichment_status")
        if ens == "ENRICHED" and prs != "RESOLVED":
            bad_combo.append({
                "lead_id": lead.get("lead_id"),
                "parcel_resolution_status": prs,
                "enrichment_status": ens,
            })

    enrichment_only = []
    role_by_id = ctx.get("source_role_by_id") or {}
    provenance_checked = bool(role_by_id)
    if provenance_checked:
        for lead in matched_leads:
            source_ids = lead.get("source_ids") or []
            has_primary = any(
                role_by_id.get(sid) == "PRIMARY_EVENT_SOURCE"
                for sid in source_ids
            )
            if not has_primary:
                enrichment_only.append({
                    "lead_id": lead.get("lead_id"),
                    "source_ids": list(source_ids),
                })

    offenders = bad_combo + enrichment_only
    if offenders:
        parts = []
        if bad_combo:
            parts.append(f"{len(bad_combo)} ENRICHED row(s) without a RESOLVED "
                         f"parcel (§13.14.1)")
        if enrichment_only:
            parts.append(f"{len(enrichment_only)} enrichment-only row(s) with "
                         f"no PRIMARY_EVENT_SOURCE signal (No False Dashboard, "
                         f"§13.5)")
        return _result(4, "Enrichment status decoupling integrity", "INVALID",
                       "; ".join(parts) + ".", offenders)
    detail = ("enrichment-status pairs valid (§13.14.1)")
    if provenance_checked:
        detail += "; every matched lead carries a PRIMARY_EVENT_SOURCE signal"
    else:
        detail += "; row-provenance (No False Dashboard) not checked — no "
        detail += "leads-base source roles supplied"
    return _result(4, "Enrichment status decoupling integrity", "VALID",
                   detail + ".")


def _check_5_signal_aggregation(matched_leads: list, ctx: dict) -> dict:
    """Check 5 — signal count vs distinct instrument numbers (§18.E)."""
    invalid, ambiguous = [], []
    signal_count = 0
    for lead in matched_leads:
        for sig in lead.get("signals") or []:
            signal_count += 1
            count = sig.get("count")
            n_instruments = len(sig.get("instrument_numbers") or [])
            sample = {
                "lead_id": lead.get("lead_id"),
                "signal_type": sig.get("signal_type"),
                "count": count,
                "distinct_instrument_numbers": n_instruments,
            }
            if not isinstance(count, int) or count < n_instruments:
                invalid.append(sample)
            elif count > n_instruments:
                ambiguous.append(sample)
    if invalid:
        return _result(
            5, "Signal aggregation integrity", "INVALID",
            f"{len(invalid)} signal(s) have count below the distinct "
            f"instrument-number count — impossible; an aggregation bug.",
            invalid)
    if ambiguous:
        return _result(
            5, "Signal aggregation integrity", "AMBIGUOUS",
            f"{len(ambiguous)} signal(s) have count above the distinct "
            f"instrument-number count — null-instrument records (legitimate "
            f"§18.E) or a dedup failure (a bug); routed to operator review.",
            ambiguous)
    return _result(
        5, "Signal aggregation integrity", "VALID",
        f"full scan of {signal_count} signal(s): count equals the distinct "
        f"instrument-number count (clean §18.E stacking).")


def _check_6_cross_source(matched_leads: list, ctx: dict) -> dict:
    """Check 6 — cross-source aggregation and §18.F anti-collapse integrity."""
    offenders = []
    signal_count = 0
    for lead in matched_leads:
        seen_keys = set()
        for sig in lead.get("signals") or []:
            signal_count += 1
            key = sig.get("aggregation_key") or {}
            tup = (key.get("parcel_id"), key.get("canonical_doc_type"),
                   key.get("signal_type"))
            if tup in seen_keys:
                offenders.append({
                    "lead_id": lead.get("lead_id"),
                    "issue": "two signals share one aggregation key (under-merge)",
                    "aggregation_key": key,
                })
            seen_keys.add(tup)
            if (sig.get("canonical_doc_type") != key.get("canonical_doc_type")
                    or sig.get("signal_type") != key.get("signal_type")):
                offenders.append({
                    "lead_id": lead.get("lead_id"),
                    "issue": "signal fields disagree with its aggregation key",
                    "aggregation_key": key,
                    "signal_type": sig.get("signal_type"),
                    "canonical_doc_type": sig.get("canonical_doc_type"),
                })
    if offenders:
        return _result(
            6, "Cross-source aggregation integrity", "INVALID",
            f"{len(offenders)} signal-grouping inconsistency(ies) — an "
            f"under-merge or a key/signal mismatch (§18.D / §18.F).", offenders)
    return _result(
        6, "Cross-source aggregation integrity", "VALID",
        f"full scan of {signal_count} signal(s): every signal has a distinct, "
        f"self-consistent aggregation key (§18.F anti-collapse holds).")


def _check_7_ocr_routing(matched_leads: list, ctx: dict) -> dict:
    """Check 7 — OCR confidence routing (source-ingestion-time)."""
    return _result(
        7, "OCR confidence routing", "SKIPPED",
        "requires per-record OCR confidence scores — source-ingestion-time "
        "data not carried on matched_leads.json (§20.H).")


def _check_8_csv_schema(matched_leads: list, ctx: dict) -> dict:
    """Check 8 — CSV output schema validation (deploy-time)."""
    return _result(
        8, "CSV output schema validation", "SKIPPED",
        "requires the operator-facing CSV export — a deploy-time artifact "
        "(§20.H).")


def _check_9_source_links(matched_leads: list, ctx: dict) -> dict:
    """Check 9 — source proof link validation (deploy-time)."""
    return _result(
        9, "Source proof link validation", "SKIPPED",
        "requires live source-URL resolution (HTTP / offline-path checks) — a "
        "deploy-time check (§20.H).")


def _check_10_dashboard_rows(matched_leads: list, ctx: dict) -> dict:
    """Check 10 — dashboard row integrity (deploy-time, browser)."""
    return _result(
        10, "Dashboard row integrity", "SKIPPED",
        "requires browser automation against the rendered dashboard — a "
        "deploy-time check (§20.H).")


def _check_11_methodology(matched_leads: list, ctx: dict) -> dict:
    """Check 11 — methodology consistency (deploy-time)."""
    return _result(
        11, "Methodology consistency", "SKIPPED",
        "requires the build report — a deploy-time artifact (§20.H).")


def _check_12_universal_filer_scan(matched_leads: list, ctx: dict) -> dict:
    """Check 12 — universal filer-as-owner scan of matched_leads.json."""
    offenders = []
    for lead in matched_leads:
        owner = lead.get("owner_name") or ""
        hit = match_known_filer(owner)
        if hit:
            offenders.append({
                "lead_id": lead.get("lead_id"),
                "owner_name": owner,
                "filer_pattern": hit,
                "parcel_resolution_status": lead.get("parcel_resolution_status"),
            })
    if offenders:
        return _result(
            12, "Filer-as-owner spot check (universal patterns)", "INVALID",
            f"{len(offenders)} matched lead(s) emit a universal filer pattern "
            f"(government / IRS / hospital / mortgage / federal agency) as "
            f"owner_name — it may appear only as filer_entity.", offenders)
    return _result(
        12, "Filer-as-owner spot check (universal patterns)", "VALID",
        f"full scan of {len(matched_leads)} matched leads: no universal filer "
        f"pattern appears as owner_name.")


_CHECKS = (
    _check_1_debtor_attribution,
    _check_2_owner_type,
    _check_3_parcel_plausibility,
    _check_4_enrichment_decoupling,
    _check_5_signal_aggregation,
    _check_6_cross_source,
    _check_7_ocr_routing,
    _check_8_csv_schema,
    _check_9_source_links,
    _check_10_dashboard_rows,
    _check_11_methodology,
    _check_12_universal_filer_scan,
)


def _deploy_verdict(check_results: list) -> str:
    """Compute the §20.F deploy verdict over the executed checks."""
    executed = [r for r in check_results if r["status"] != "SKIPPED"]
    if any(r["status"] == "INVALID" for r in executed):
        return "DEPLOY_BLOCKED"
    if any(r["status"] == "AMBIGUOUS" for r in executed):
        return "NEEDS_OPERATOR_REVIEW"
    return "DEPLOY_OK"


def run_semantic_verification(
    matched_leads: list,
    *,
    leads_base_records: Optional[list] = None,
    evidence_ledger: Optional[dict] = None,
) -> dict:
    """Run the §20 semantic verification gate over matched_leads.json.

    §20.G: semantic verification runs AFTER mechanical verification. This
    function first mechanically validates every matched lead against
    matched_lead_record.schema.json; a mechanical failure blocks the semantic
    checks and yields DEPLOY_BLOCKED. It then runs the twelve §20.C checks and
    computes the §20.F deploy verdict.

    Args:
        matched_leads: The aggregator's matched-lead records (matched_leads.json).
        leads_base_records: The leads-base records behind those matched leads.
            Supplies source roles for the §13.5 No-False-Dashboard check (Check
            4). Optional — Check 4's row-provenance part is skipped without it.
        evidence_ledger: Optional evidence-ledger index (evidence_id -> entry).
            Reserved for evidence-trace reporting.

    Returns:
        A report dict — `verdict`, `checks` (twelve §20.C results), the run /
        skipped / invalid / ambiguous tallies, and `mechanical_ok`.
    """
    # §20.G — mechanical verification first.
    validator = _matched_lead_validator()
    mechanical_failures = []
    for lead in matched_leads:
        errors = sorted(validator.iter_errors(lead), key=lambda e: list(e.path))
        if errors:
            mechanical_failures.append({
                "lead_id": lead.get("lead_id"),
                "errors": [e.message for e in errors[:5]],
            })
    if mechanical_failures:
        return {
            "verdict": "DEPLOY_BLOCKED",
            "mechanical_ok": False,
            "mechanical_failures": mechanical_failures,
            "checks": [],
            "detail": (
                f"§20.G: mechanical verification failed for "
                f"{len(mechanical_failures)} matched lead(s) — semantic "
                f"verification did not run."
            ),
        }

    role_by_id: dict[str, str] = {}
    for record in leads_base_records or []:
        sid = record.get("source_id")
        role = record.get("source_role")
        if sid and role:
            role_by_id[sid] = role
    ctx = {
        "source_role_by_id": role_by_id,
        "evidence_ledger": evidence_ledger or {},
    }

    results = [check(matched_leads, ctx) for check in _CHECKS]
    verdict = _deploy_verdict(results)

    return {
        "verdict": verdict,
        "mechanical_ok": True,
        "checks": results,
        "checks_run": sum(1 for r in results if r["status"] != "SKIPPED"),
        "checks_skipped": sum(1 for r in results if r["status"] == "SKIPPED"),
        "invalid_checks": [r["check"] for r in results
                           if r["status"] == "INVALID"],
        "ambiguous_checks": [r["check"] for r in results
                             if r["status"] == "AMBIGUOUS"],
        "skipped_checks": [r["check"] for r in results
                           if r["status"] == "SKIPPED"],
        "detail": (
            f"verdict {verdict} over "
            f"{sum(1 for r in results if r['status'] != 'SKIPPED')} executed "
            f"check(s); {sum(1 for r in results if r['status'] == 'SKIPPED')} "
            f"check(s) require deploy-time inputs and were skipped (§20.H)."
        ),
    }
