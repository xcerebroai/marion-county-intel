#!/usr/bin/env python3
"""v5.4.0 Session 9 unit tests — the scoring seam (matched_lead → scored_lead).

Wired into run_all.py via scaffold/tests/v5_4_0/. Verifies the Session 9
seam (Option Y):

  - the canonical_doc_type → normalized_doc_type bridge handles registry-
    aligned types (hospital_lien), broad §17 keys via fan-out
    (foreclosure_notice → NOTICE_OF_SALE), the Session-8 plural renames
    (executors_deed), AND unknowns (None);
  - stack_depth reflects matched_lead.signals[].count (G3 — duplicate
    same-pattern instruments earn additional stack bonus);
  - recent_flag fires when any group's latest_recorded_date is within 30
    days of as_of;
  - score_matched_lead emits a schema-valid scored_lead UNENRICHED and
    ENRICHED;
  - the seam never drops a lead — a REVIEW_REQUIRED matched_lead emits a
    REVIEW_REQUIRED scored_lead (review_flag seeded), still scored;
  - score_matched_leads (batch) is deterministic (sorted by lead_id) and
    re-runs to identical output.

Run: python3 scaffold/tests/v5_4_0/test_scoring_seam_units.py
Exit 0 = pass, non-zero = fail.
"""
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.pipeline import scoring_seam as seam


def _matched_lead(*, lead_id="lead_p1", parcel_id="P1",
                  owner_name="DOE, MARGARET R", owner_type="INDIVIDUAL",
                  parcel_resolution_status="RESOLVED",
                  review_reason=None,
                  enrichment_status="UNENRICHED",
                  signals=None,
                  source_ids=None, evidence_ids=None) -> dict:
    """A matched_lead skeleton — `signals` must be supplied (the schema
    requires minItems: 1, but the seam tests don't validate matched_lead
    here; we still ship at least one group so the seam produces a stack)."""
    return {
        "lead_id": lead_id,
        "primary_parcel_id": parcel_id,
        "owner_name": owner_name,
        "owner_type": owner_type,
        "filer_entity": None,
        "review_reason": review_reason,
        "parcel_resolution_status": parcel_resolution_status,
        "enrichment_status": enrichment_status,
        "signals": signals or [],
        "source_ids": source_ids or ["clerk_recordings"],
        "evidence_ids": evidence_ids or ["ev1"],
    }


def _signal(*, canonical_doc_type, signal_type=None, count=1,
            instrument_numbers=None, latest="2026-05-10",
            earliest=None, source_urls=None, evidence_ids=None) -> dict:
    return {
        "aggregation_key": {
            "parcel_id": "P1", "canonical_doc_type": canonical_doc_type,
            "signal_type": signal_type or canonical_doc_type,
        },
        "signal_type": signal_type or canonical_doc_type,
        "canonical_doc_type": canonical_doc_type,
        "count": count,
        "instrument_numbers": instrument_numbers or [f"I-{canonical_doc_type}"],
        "source_urls": source_urls or [
            f"https://example.test/{canonical_doc_type}"
        ],
        "evidence_ids": evidence_ids or [f"ev-{canonical_doc_type}"],
        "source_ids": ["clerk_recordings"],
        "earliest_recorded_date": earliest or latest,
        "latest_recorded_date": latest,
        "recorded_date_range": [earliest or latest, latest],
    }


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    # =======================================================================
    # Part 1 — the canonical_doc_type → normalized_doc_type bridge.
    # =======================================================================
    cdt = seam.canonical_doc_type_to_normalized
    check("bridge: registry-aligned hospital_lien → HOSPITAL_LIEN",
          cdt("hospital_lien") == "HOSPITAL_LIEN")
    check("bridge: registry-aligned eviction_filing → EVICTION_FILING",
          cdt("eviction_filing") == "EVICTION_FILING")
    check("bridge: Session-8 plural rename executors_deed → EXECUTORS_DEED",
          cdt("executors_deed") == "EXECUTORS_DEED")
    check("bridge: broad §17 key `foreclosure_notice` fans out via Session-8 "
          "BROAD_KEY_REGISTRY_ALIASES to NOTICE_OF_SALE (first fan-out alias)",
          cdt("foreclosure_notice") == "NOTICE_OF_SALE")
    check("bridge: broad §17 key `code_lien` fans out to CODE_VIOLATION_NOTICE",
          cdt("code_lien") == "CODE_VIOLATION_NOTICE")
    check("bridge: broad §17 key with empty fan-out (administrative_lien) "
          "returns None (broad bucket — children carry their own rules)",
          cdt("administrative_lien") is None)
    check("bridge: unknown canonical_doc_type returns None (no fabrication)",
          cdt("not_a_real_type") is None)
    check("bridge: None / empty input returns None",
          cdt(None) is None and cdt("") is None)

    # Pattern lookup
    check("pattern: hospital_lien → lien",
          seam.pattern_for_canonical_doc_type("hospital_lien") == "lien")
    check("pattern: foreclosure_notice (broad-key fan-out) → foreclosure",
          seam.pattern_for_canonical_doc_type("foreclosure_notice")
          == "foreclosure")
    check("pattern: unknown → None",
          seam.pattern_for_canonical_doc_type("not_a_real_type") is None)

    # =======================================================================
    # Part 2 — adapt_matched_lead_to_stack.
    # =======================================================================
    # G3 — count contributes to stack_depth.
    matched = _matched_lead(signals=[
        _signal(canonical_doc_type="hospital_lien", count=2,
                instrument_numbers=["I1", "I2"], latest="2026-05-10"),
        _signal(canonical_doc_type="notice_of_sale", count=1,
                instrument_numbers=["I3"], latest="2026-05-12"),
    ])
    stack = seam.adapt_matched_lead_to_stack(matched, as_of=date(2026, 5, 14))
    check("seam adapter: 2 hospital_lien + 1 notice_of_sale → stack_depth 3 "
          "(§18.E count contributes to stack)",
          stack["stack_depth"] == 3 and len(stack["active_signals"]) == 3)
    check("seam adapter: distinct patterns = {lien, foreclosure}",
          set(stack["pattern_set"]) == {"lien", "foreclosure"})
    check("seam adapter: recent_flag True when latest_recorded_date within "
          "30 days of as_of (2026-05-12 vs 2026-05-14)",
          stack["recent_flag"] is True)

    # recent_flag False when all dates are older than 30 days.
    matched_old = _matched_lead(signals=[
        _signal(canonical_doc_type="hospital_lien", count=1, latest="2026-01-01"),
    ])
    stack_old = seam.adapt_matched_lead_to_stack(matched_old,
                                                  as_of=date(2026, 5, 14))
    check("seam adapter: recent_flag False when all dates older than 30 days",
          stack_old["recent_flag"] is False)

    # Unknown canonical_doc_type → no pattern, doesn't contribute to depth.
    matched_unknown = _matched_lead(signals=[
        _signal(canonical_doc_type="not_a_real_type", count=1),
    ])
    stack_unknown = seam.adapt_matched_lead_to_stack(matched_unknown,
                                                     as_of=date(2026, 5, 14))
    check("seam adapter: unknown canonical_doc_type contributes no pattern, "
          "no stack_depth (fails to score rather than guess)",
          stack_unknown["stack_depth"] == 0
          and stack_unknown["pattern_set"] == [])

    # =======================================================================
    # Part 3 — score_matched_lead (UNENRICHED and ENRICHED).
    # =======================================================================
    matched = _matched_lead(signals=[
        _signal(canonical_doc_type="hospital_lien", count=2,
                instrument_numbers=["I1", "I2"], latest="2026-05-10"),
        _signal(canonical_doc_type="notice_of_sale", count=1,
                instrument_numbers=["I3"], latest="2026-05-12"),
    ])

    sl_un = seam.score_matched_lead(matched, as_of=date(2026, 5, 14))
    check("score (UNENRICHED): emits valid scored_lead with score in [0,100]",
          isinstance(sl_un.get("score"), int)
          and 0 <= sl_un["score"] <= 100)
    check("score (UNENRICHED): enrichment_status = UNENRICHED",
          sl_un["enrichment_status"] == "UNENRICHED")
    check("score (UNENRICHED): parcel_display is None",
          sl_un["parcel_display"] is None)
    check("score (UNENRICHED): attributes is empty list "
          "(R3-iii — scoring runs without enrichment)",
          sl_un["attributes"] == [])
    check("score (UNENRICHED): lead_id back-reference equals the matched "
          "lead's lead_id",
          sl_un["lead_id"] == matched["lead_id"])
    check("score (UNENRICHED): scored_lead_id is a non-empty deterministic "
          "string",
          isinstance(sl_un["scored_lead_id"], str)
          and sl_un["scored_lead_id"].startswith("scored_"))

    def provider(pid):
        return {
            "parcel_id": pid,
            "situs_address": "100 EXAMPLE WAY",
            "situs_state": "ZZ",
            "owner_mailing_state": "ZZ",
            "owner_mailing_address": "100 EXAMPLE WAY",
            "owner_mailing_city": "EXAMPLECITY",
            "owner_mailing_zip": "00000",
            "assessed_value": 200000,
            "last_sale_price": 80000,
            "last_sale_date": "2009-04-15",
            "year_built": 1975,
        }

    sl_en = seam.score_matched_lead(matched, as_of=date(2026, 5, 14),
                                    enrichment_provider=provider)
    check("score (ENRICHED): enrichment_status = ENRICHED",
          sl_en["enrichment_status"] == "ENRICHED")
    check("score (ENRICHED): parcel_display non-null with situs_address "
          "from the provider",
          sl_en["parcel_display"] is not None
          and sl_en["parcel_display"]["situs_address"] == "100 EXAMPLE WAY")
    check("score (ENRICHED): attributes derived from enrichment includes "
          "long_term_owned (last_sale 2009 vs as_of 2026 — >= 15y default)",
          "long_term_owned" in sl_en["attributes"])
    check("score (ENRICHED): score >= UNENRICHED score "
          "(attribute_bonus is non-negative)",
          sl_en["score"] >= sl_un["score"])

    # =======================================================================
    # Part 4 — provider exception does NOT block scoring (R3-iii).
    # =======================================================================
    def failing_provider(pid):
        raise RuntimeError("simulated enrichment outage")

    sl_fail = seam.score_matched_lead(matched, as_of=date(2026, 5, 14),
                                      enrichment_provider=failing_provider)
    check("score (R3-iii): a failing enrichment provider degrades to "
          "UNENRICHED rather than blocking the lead",
          sl_fail["enrichment_status"] == "UNENRICHED"
          and sl_fail["parcel_display"] is None)

    # =======================================================================
    # Part 5 — REVIEW_REQUIRED matched_lead → REVIEW_REQUIRED scored_lead.
    # =======================================================================
    matched_rr = _matched_lead(
        parcel_resolution_status="REVIEW_REQUIRED",
        review_reason="owner_not_on_document",
        owner_name="eviction_filing against unidentified party",
        owner_type="UNKNOWN",
        signals=[
            _signal(canonical_doc_type="eviction_filing", count=1,
                    latest="2026-05-10"),
        ],
    )
    sl_rr = seam.score_matched_lead(matched_rr, as_of=date(2026, 5, 14))
    check("seam: REVIEW_REQUIRED matched_lead → REVIEW_REQUIRED scored_lead "
          "(the lead is NEVER dropped)",
          sl_rr["lead_status"] == "REVIEW_REQUIRED")
    check("seam: REVIEW_REQUIRED scored_lead carries the matched-lead's "
          "review reason as a review_flag",
          any("owner_not_on_document" in f for f in sl_rr["review_flags"]))

    # =======================================================================
    # Part 6 — batch helper score_matched_leads is deterministic.
    # =======================================================================
    matched_a = _matched_lead(lead_id="lead_A", signals=[
        _signal(canonical_doc_type="hospital_lien", count=1, latest="2026-05-10"),
    ])
    matched_b = _matched_lead(lead_id="lead_B", signals=[
        _signal(canonical_doc_type="notice_of_sale", count=1, latest="2026-05-12"),
    ])
    batch1 = seam.score_matched_leads([matched_b, matched_a],
                                      as_of=date(2026, 5, 14))
    batch2 = seam.score_matched_leads([matched_a, matched_b],
                                      as_of=date(2026, 5, 14))
    check("batch: score_matched_leads orders by lead_id (deterministic)",
          [s["lead_id"] for s in batch1] == ["lead_A", "lead_B"]
          and [s["lead_id"] for s in batch2] == ["lead_A", "lead_B"])
    check("batch: two runs over the same inputs produce identical scored leads",
          json.dumps(batch1, sort_keys=True) == json.dumps(batch2, sort_keys=True))

    # =======================================================================
    # Part 7 — §20 gate behavior.
    # =======================================================================
    deploy_ok = {"verdict": "DEPLOY_OK"}
    deploy_blocked = {"verdict": "DEPLOY_BLOCKED"}
    needs_review = {"verdict": "NEEDS_OPERATOR_REVIEW"}

    check("gate: DEPLOY_OK returns the verdict (no raise)",
          seam.gate_on_semantic_verdict(deploy_ok) == "DEPLOY_OK")
    raised = False
    try:
        seam.gate_on_semantic_verdict(deploy_blocked)
    except seam.SemanticGateBlocked:
        raised = True
    check("gate: DEPLOY_BLOCKED raises SemanticGateBlocked", raised)

    raised = False
    try:
        seam.gate_on_semantic_verdict(needs_review)
    except seam.SemanticGateNeedsReview:
        raised = True
    check("gate: NEEDS_OPERATOR_REVIEW without approval raises "
          "SemanticGateNeedsReview", raised)

    check("gate: NEEDS_OPERATOR_REVIEW with approve_needs_review=True "
          "returns the verdict",
          seam.gate_on_semantic_verdict(needs_review, approve_needs_review=True)
          == "NEEDS_OPERATOR_REVIEW")

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")
    if failed:
        print(f"FAIL: scoring seam — {len(failed)} of {len(checks)} "
              f"checks failed")
        return 1
    print(f"PASS: scoring seam (v5.4.0 Session 9) — all {len(checks)} "
          f"checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
