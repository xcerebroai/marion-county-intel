"""
test_golden_path.py — the framework's single end-to-end gate test.

v5.4.0 Session 10 — REWRITTEN FOR THE STAGED PIPELINE. Through v5.3.x the
golden-path test inlined a self-contained re-implementation of every
framework layer, asserting that the architecture's contracts were
*satisfiable*. v5.4.0 ships those layers as executable engines, and the
v5.4.0 cutover replaces the monolith's signal→identity→aggregation core
with the staged engine + the Option-Y scoring seam. The golden path is
rewritten to drive the REAL modules end-to-end, layer by layer, without
losing coverage of any layer.

The 9 layers, mapped to the v5.4.0 staged architecture:

  1. raw source record           → raw_event_record contract (Session 1)
  2. normalize + debtor identity → normalize.normalize_doc_type (RETAINED)
                                    + §17 debtor_party_engine (NEW)
  3. parcel match                → matcher.match_signals_to_parcels (RETAINED)
  4. stacked lead + scoring      → §18 leads_base_writer + §19 aggregator
                                    + the Option-Y seam (scoring_seam) +
                                    retained score.compute_score /
                                    classify.classify_deal_paths /
                                    title-complexity → scored_lead_record
  5. evidence ledger             → evidence_ledger.build_evidence_ledger
                                    + verify_evidence_traceability
  6. review queue                → review.evaluate_review_queue (RETAINED;
                                    invoked by the seam)
  7. dashboard output            → run_pipeline_staged.project_scored_lead /
                                    build_dashboard_payload (RETAINED-shape)
  8. run manifest                → manifest.build_run_manifest (RETAINED)
  9. source heartbeat update     → manifest.build_heartbeat (RETAINED)

Per F-8 / §09 reconciliation (Session 6 seam design): lead `signals` is the
§18 rich aggregated-group shape, not the §09 `signal_id`-string shape.
This test pins the new shape and the rewritten §09 description (see §09
Session-10 amendment).

R3(iii) — enrichment is OPTIONAL: the test exercises BOTH paths. The
ENRICHED path proves dashboard display fields are populated from
parcel-master enrichment; the UNENRICHED path proves a lead is still
scored, still review-evaluated, still reaches the dashboard when no
parcel-master row is available — the §13.14 enrichment-optional rule.

The framework is NOT shippable unless this test passes.

Rules enforced:
- No county-specific data. Synthtown placeholders only.
- No real names. TEST_OWNER_* placeholders only.
- No real addresses. 100 Synthetic Lane style.
- No real portals. Sources are synthetic://... URLs.

Run with: python3 scaffold/tests/test_golden_path.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from jsonschema import Draft202012Validator  # noqa: E402

from scaffold.pipeline import evidence_ledger as evidence_ledger_mod  # noqa: E402
from scaffold.pipeline import manifest as manifest_mod  # noqa: E402
from scaffold.pipeline import matcher  # noqa: E402
from scaffold.pipeline import normalize  # noqa: E402
from scaffold.pipeline import run_pipeline_staged  # noqa: E402
from scaffold.pipeline.contracts import schema_path  # noqa: E402

REGISTRY_PATH = (
    REPO_ROOT / "knowledge_base" / "domain" / "canonical_doc_types.json"
)
REGISTRY = json.loads(REGISTRY_PATH.read_text())
CANONICAL = REGISTRY["canonical_types"]


# ---------------------------------------------------------------------------
# Synthetic fixtures — Synthtown A, one affidavit_of_heirship on SYN-001.
# ---------------------------------------------------------------------------

GOLDEN_RAW_DOC_TYPE = "AOH"  # raw subtype label the source emits
GOLDEN_RECORDED_DATE = "2026-05-07"
GOLDEN_AS_OF = date(2026, 5, 14)

GOLDEN_RAW_EVENT_ID = "raw_golden_001"
GOLDEN_EVIDENCE_ID = "ev_golden_001"
GOLDEN_PARCEL_ID = "SYN-001"
GOLDEN_INSTRUMENT_NUMBER = "SYN-2026-0001"


def make_raw_payload() -> dict:
    """The pre-translator payload — what a county scraper would fetch."""
    return {
        "source_id": "synth_clerk_recordings",
        "source_url": "synthetic://clerk/SYN-test-001",
        "fetched_at": "2026-05-07T12:00:00Z",
        "raw_doc_type": GOLDEN_RAW_DOC_TYPE,
        "instrument_number": GOLDEN_INSTRUMENT_NUMBER,
        "recording_date": GOLDEN_RECORDED_DATE,
        "grantor": "TEST_OWNER_001 (DECEASED)",
        "grantee": "TEST_HEIR_001",
        "parcel_ref": GOLDEN_PARCEL_ID,
        "legal_description": "Lot 1, Block 1, Synthtown A Subdivision",
        "parser_confidence": 95,
    }


def make_parcel_master_row() -> dict:
    """The parcel-master enrichment row.

    Carries BOTH `address`/`city`/`zip` (what `matcher.match_signals_to_parcels`
    indexes on per architecture/12_entity_resolution.md tier 1) AND
    `situs_*` keys (what the dashboard's parcel_display block consumes via
    the seam). The translator-shaped row also carries `owner_name` /
    `owner_mailing_*` / `assessed_value` / `last_sale_*` / `year_built` —
    the §13.14 enrichment surface."""
    return {
        "parcel_id": GOLDEN_PARCEL_ID,
        # Matcher-shaped fields (architecture/12).
        "address": "100 Synthetic Lane",
        "city": "Synthtown A",
        "zip": "00001",
        # Dashboard-shaped fields (seam → parcel_display).
        "situs_address": "100 Synthetic Lane",
        "situs_city": "Synthtown A",
        "situs_state": "ZZ",
        "situs_zip": "00001",
        "owner_name": "TEST_OWNER_001",
        "owner_mailing_addr1": "100 Synthetic Lane",
        "owner_mailing_address": "100 Synthetic Lane",
        "owner_mailing_city": "Synthtown A",
        "owner_mailing_state": "ZZ",
        "owner_mailing_zip": "00001",
        "assessed_value": 340000,
        "last_sale_price": 185000,
        "last_sale_date": "2002-03-12",
        "year_built": 1978,
        "_synthetic": True,
    }


def make_raw_event(canonical_doc_type: str) -> dict:
    """Build a raw_event_record (raw_event_record.schema.json) — the
    stage-1 input the staged engine consumes. The translator step (which
    builds this record in production) is exercised separately by
    test_translator_registry.py; the golden path materializes one
    representative raw_event directly so the §17→§20 contract is exercised
    end-to-end on the canonical synthetic case."""
    payload = make_raw_payload()
    # §17 extracts the decedent from the document body for
    # affidavit_of_heirship (DOCUMENT_BODY rule). Use the canonical label
    # the §17 body extractor recognises.
    body_text = (
        "AFFIDAVIT OF HEIRSHIP\n"
        f"DECEDENT: {payload['grantor']}\n"
        f"HEIR: {payload['grantee']}\n"
    )
    return {
        "raw_event_id": GOLDEN_RAW_EVENT_ID,
        "source_id": payload["source_id"],
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": canonical_doc_type,
        "raw_doc_type": payload["raw_doc_type"],
        "instrument_number": payload["instrument_number"],
        "recorded_date": payload["recording_date"],
        "event_date": None,
        "source_url": payload["source_url"],
        "parties": [
            {"name": payload["grantor"], "name_type": "GR",
             "raw_role": "DECEDENT"},
            {"name": payload["grantee"], "name_type": "GE", "raw_role": "HEIR"},
        ],
        "document_body_text": body_text,
        "property_refs": {
            "parcel_id": payload["parcel_ref"],
            "situs_address": None,
            "legal_description": payload["legal_description"],
            "case_number": None,
        },
        "amounts": [],
        "evidence_ids": [GOLDEN_EVIDENCE_ID],
        "parser_name": "golden_path_synthetic",
        "parser_version": "1.0.0",
        "parser_confidence": payload["parser_confidence"],
        "captured_at": payload["fetched_at"],
    }


def make_evidence_entry() -> dict:
    payload = make_raw_payload()
    return {
        "evidence_id": GOLDEN_EVIDENCE_ID,
        "record_id": GOLDEN_RAW_EVENT_ID,
        "field": "owner_name",
        "value": payload["grantor"],
        "status": "Confirmed",
        "source_id": payload["source_id"],
        "source_reliability_grade": "A",
        "source_url": payload["source_url"],
        "captured_at": payload["fetched_at"],
    }


# ---------------------------------------------------------------------------
# Test runner.
# ---------------------------------------------------------------------------

def run_golden_path() -> bool:
    assertions: list = []

    def assert_(label: str, condition: bool, detail=None) -> None:
        assertions.append(
            ("PASS", label) if condition else ("FAIL", label, detail)
        )

    # =====================================================================
    # LAYER 2 — RETAINED normalize.py (run early so it sets canonical_doc_type).
    # The synthetic raw payload's doc_type "AOH" normalizes to the registry
    # entry AFFIDAVIT_OF_HEIRSHIP. The staged engine consumes the lowercased
    # form; the doc_type_bridge (Session 8) guarantees lowercased(UPPERCASE) is
    # always a registry-aligned canonical_doc_type the §17 rule table accepts.
    # =====================================================================
    norm = normalize.normalize_doc_type(GOLDEN_RAW_DOC_TYPE)
    assert_("Layer 2 (normalize): doc_type 'AOH' normalizes to "
            "AFFIDAVIT_OF_HEIRSHIP", norm["normalized_doc_type"]
            == "AFFIDAVIT_OF_HEIRSHIP", f"got {norm['normalized_doc_type']!r}")
    assert_("Layer 2 (normalize): confidence is 100 (exact-match path)",
            norm["confidence"] == 100, f"got {norm['confidence']}")
    assert_("Layer 2 (normalize): review_required is False",
            norm["review_required"] is False)
    canonical_doc_type = (norm["normalized_doc_type"] or "").lower()
    canonical_entry = CANONICAL.get(norm["normalized_doc_type"] or "", {})
    assert_("Layer 2 (normalize): canonical lead_pattern is 'estate'",
            canonical_entry.get("lead_pattern") == "estate")
    assert_("Layer 2 (normalize): canonical source_class is lead_generating",
            canonical_entry.get("source_class") == "lead_generating")

    # =====================================================================
    # LAYER 1 — raw_event_record (the staged stage-1 input).
    # =====================================================================
    raw_event = make_raw_event(canonical_doc_type)
    assert_("Layer 1 (raw_event): raw_event_id present",
            bool(raw_event["raw_event_id"]))
    assert_("Layer 1 (raw_event): source_role is PRIMARY_EVENT_SOURCE "
            "(only PRIMARY_EVENT_SOURCE originates leads — §13 / §16.E)",
            raw_event["source_role"] == "PRIMARY_EVENT_SOURCE")
    assert_("Layer 1 (raw_event): canonical_doc_type populated by normalize",
            raw_event["canonical_doc_type"] == "affidavit_of_heirship")
    assert_("Layer 1 (raw_event): parser_confidence >= 80",
            raw_event["parser_confidence"] >= 80)
    assert_("Layer 1 (raw_event): instrument_number preserved verbatim",
            raw_event["instrument_number"] == GOLDEN_INSTRUMENT_NUMBER)
    assert_("Layer 1 (raw_event): document_body_text carries the §17 "
            "DECEDENT: label so the body extractor can resolve the decedent",
            "DECEDENT:" in (raw_event["document_body_text"] or ""))

    # =====================================================================
    # LAYER 3 — RETAINED matcher.match_signals_to_parcels (parcel resolution).
    # The synthetic fixture pre-resolves parcel_id on the raw_event; this
    # block additionally exercises the real matcher against the same parcel-
    # master row so the §13.14 parcel-resolution stage is covered.
    # =====================================================================
    parcel_master = make_parcel_master_row()
    matcher_input = [{
        "signal_id": "golden_match_001",
        "_record_address": parcel_master["situs_address"],
        "_record_city": parcel_master["situs_city"],
        "_record_zip": parcel_master["situs_zip"],
    }]
    matched, match_meta = matcher.match_signals_to_parcels(
        matcher_input, [parcel_master]
    )
    match_result = match_meta.get("golden_match_001", {})
    assert_("Layer 3 (matcher): real matcher resolves the synthetic parcel "
            "from the parcel-master row",
            match_result.get("primary_parcel_id") == GOLDEN_PARCEL_ID,
            f"got {match_result!r}")
    assert_("Layer 3 (matcher): match_confidence >= 80",
            match_result.get("match_confidence", 0) >= 80)

    # =====================================================================
    # LAYERS 4 + 5 + 6 + 7 — staged §17→§18→§19→§20 → seam → scoring →
    # review → dashboard. Driven through the real run_pipeline_staged
    # orchestrator with an enrichment_provider (R3(iii) — also re-exercised
    # UNENRICHED below for the §13.14 enrichment-optional gate).
    # =====================================================================
    def enrichment_provider(parcel_id):
        return make_parcel_master_row() if parcel_id == GOLDEN_PARCEL_ID else None

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        result = run_pipeline_staged.run_staged_pipeline(
            [raw_event],
            evidence_entries=[make_evidence_entry()],
            signal_type_labels={"affidavit_of_heirship": "Affidavit of Heirship"},
            workdir=workdir / "enriched",
            as_of=GOLDEN_AS_OF,
            enrichment_provider=enrichment_provider,
        )

        # --- LAYER 2 continued — §17 resolves the debtor (NOT the heir) -----
        debtor_resolved = result["debtor_resolved"]
        assert_("Layer 2 (§17 debtor party engine): one debtor-resolved record",
                len(debtor_resolved) == 1)
        drr = debtor_resolved[0]
        assert_("Layer 2 (§17): debtor_resolution_status RESOLVED",
                drr["debtor_resolution_status"] == "RESOLVED")
        owner_name_upper = (drr.get("owner_name") or "").upper()
        assert_("Layer 2 (§17): owner_name is the decedent TEST_OWNER_001 "
                "(extracted from the document body — §17.C "
                "affidavit_of_heirship lead is the decedent)",
                "TEST_OWNER_001" in owner_name_upper,
                f"owner_name={drr.get('owner_name')!r}")
        assert_("Layer 2 (§17): owner_type classified (ESTATE, INDIVIDUAL, "
                "or ENTITY — not UNKNOWN for a resolved debtor)",
                drr.get("owner_type") in ("ESTATE", "INDIVIDUAL", "ENTITY"))
        assert_("Layer 2 (§17): filer_entity is not the owner (the §17.D "
                "filer-as-owner inversion guarantee — §20 Check 12)",
                (drr.get("filer_entity") or "") != drr.get("owner_name"))

        # --- LAYER 4 part 1 — §18 leads_base + §19 aggregator -----------------
        matched_leads = result["matched_leads"]
        assert_("Layer 4 (§19 aggregator): one matched_lead emitted",
                len(matched_leads) == 1, f"got {len(matched_leads)}")
        matched_lead = matched_leads[0]
        assert_("Layer 4 (§19): matched_lead primary_parcel_id is SYN-001",
                matched_lead.get("primary_parcel_id") == GOLDEN_PARCEL_ID)
        assert_("Layer 4 (§19): matched_lead has at least one §18 aggregated "
                "signal group (F-8: signals is the §18 rich shape, NOT the "
                "§09 signal_id-string shape)",
                len(matched_lead.get("signals") or []) >= 1)
        sig_group = matched_lead["signals"][0]
        assert_("Layer 4 (§19): signal group carries the §18 aggregation_key "
                "tuple (parcel_id, canonical_doc_type, signal_type)",
                set(sig_group.get("aggregation_key", {}).keys())
                == {"parcel_id", "canonical_doc_type", "signal_type"})
        assert_("Layer 4 (§19): signal group canonical_doc_type matches the "
                "lowercased registry key",
                sig_group.get("canonical_doc_type") == canonical_doc_type)
        assert_("Layer 4 (§19): signal group count >= 1 (legitimate "
                "stacking per §18.E)",
                sig_group.get("count", 0) >= 1)

        # --- LAYER 4 part 2 — §20 semantic gate ------------------------------
        assert_("Layer 4 (§20 semantic gate): verdict DEPLOY_OK on the "
                "golden synthetic dataset (no filer-as-owner, no aggregation "
                "violations, no missing evidence)",
                result["semantic_verdict"] == "DEPLOY_OK",
                f"verdict={result['semantic_verdict']!r}; "
                f"report={result['semantic_report'].get('verdict')}")

        # --- LAYER 4 part 3 — seam → scored_lead -----------------------------
        scored_leads = result["scored_leads"]
        assert_("Layer 4 (seam / scored_lead): exactly one scored_lead "
                "produced (Option Y — one scored_lead per matched_lead)",
                len(scored_leads) == 1)
        scored_lead = scored_leads[0]
        assert_("Layer 4 (seam): scored_lead.lead_id references the "
                "matched_lead by id (Option Y — scored_lead REFERENCES, "
                "matched_lead is immutable)",
                scored_lead.get("lead_id") == matched_lead.get("lead_id"))
        assert_("Layer 4 (scoring): score is in [0, 100]",
                0 <= scored_lead.get("score", -1) <= 100,
                f"score={scored_lead.get('score')!r}")
        assert_("Layer 4 (scoring): score > 0 on the golden lead "
                "(AOH base score plus enrichment attribute bonus)",
                scored_lead.get("score", 0) > 0)
        assert_("Layer 4 (scoring): tier is one of the 5 SCORE_TIERS",
                scored_lead.get("tier") in
                ("Hot", "Strong", "Workable", "Low", "Archive"))
        assert_("Layer 4 (scoring): score_reasons present and non-empty",
                len(scored_lead.get("score_reasons") or []) > 0)
        assert_("Layer 4 (classify): at least one deal_path with a rationale",
                len(scored_lead.get("deal_paths") or []) >= 1
                and all(dp.get("rationale")
                        for dp in scored_lead.get("deal_paths") or []))
        assert_("Layer 4 (title-complexity): contributors present when "
                "title_complexity_score > 0",
                scored_lead.get("title_complexity_score", 0) == 0
                or len(scored_lead.get("title_complexity_contributors") or [])
                > 0)
        assert_("Layer 4 (seam): pattern_set carries the 'estate' pattern "
                "(seam derives it from canonical_doc_type via "
                "doc_type_bridge + the registry's lead_pattern)",
                "estate" in (scored_lead.get("pattern_set") or []))

        # --- LAYER 5 — evidence ledger + traceability -----------------------
        evidence_ledger_path = result["evidence_ledger_path"]
        assert_("Layer 5 (evidence_ledger): evidence_ledger.json written",
                evidence_ledger_path.exists())
        ledger_entries = json.loads(evidence_ledger_path.read_text())
        ledger = evidence_ledger_mod.build_evidence_ledger(ledger_entries)
        trace = evidence_ledger_mod.verify_evidence_traceability(
            matched_leads, ledger
        )
        assert_("Layer 5 (evidence): every matched-lead claim traces to a "
                "real evidence entry (§08 — every claim must source)",
                trace.get("traceable") is True,
                f"trace={trace!r}")
        ev_entry = ledger.get(GOLDEN_EVIDENCE_ID) or {}
        assert_("Layer 5 (evidence): the golden evidence entry's reliability "
                "grade is A-E",
                ev_entry.get("source_reliability_grade")
                in ("A", "B", "C", "D", "E"))
        assert_("Layer 5 (evidence): the evidence is back-referenced to the "
                "raw_event_record (record_id)",
                ev_entry.get("record_id") == GOLDEN_RAW_EVENT_ID)
        assert_("Layer 5 (evidence): the matched_lead's evidence_ids carry "
                "the golden entry",
                GOLDEN_EVIDENCE_ID in (matched_lead.get("evidence_ids") or []))

        # --- LAYER 6 — review queue (invoked by the seam) -------------------
        assert_("Layer 6 (review): review_flags evaluated (the seam invokes "
                "review.evaluate_review_queue per scored_lead)",
                isinstance(scored_lead.get("review_flags"), list))
        assert_("Layer 6 (review): golden-path scored_lead is "
                "APPROVED_FOR_DASHBOARD (no flags on a clean fixture)",
                scored_lead.get("lead_status") == "APPROVED_FOR_DASHBOARD",
                f"flags={scored_lead.get('review_flags')!r}; "
                f"status={scored_lead.get('lead_status')!r}")

        # --- LAYER 7 — dashboard projection ---------------------------------
        # ENRICHED scored_lead → dashboard row carries the parcel-master
        # display fields.
        assert_("Layer 7 (dashboard): scored_lead is ENRICHED — "
                "parcel_display populated with synthetic parcel-master row",
                scored_lead.get("enrichment_status") == "ENRICHED"
                and scored_lead.get("parcel_display") is not None)
        payload = run_pipeline_staged.build_dashboard_payload(
            scored_leads, semantic_verdict=result["semantic_verdict"],
            county="<synthetic>", state="ZZ", mode="synthetic",
        )
        assert_("Layer 7 (dashboard): payload lead_total == 1",
                payload["lead_total"] == 1)
        assert_("Layer 7 (dashboard): semantic_verdict surfaces on the "
                "payload (operator visibility of the §20 gate)",
                payload.get("semantic_verdict") == "DEPLOY_OK")
        row = payload["records"][0]
        assert_("Layer 7 (dashboard): row carries scored_lead_id and "
                "lead_id (back-reference to the immutable matched_lead)",
                row.get("lead_id") == matched_lead.get("lead_id")
                and row.get("scored_lead_id") == scored_lead.get(
                    "scored_lead_id"))
        assert_("Layer 7 (dashboard): display_address populated from the "
                "parcel_display block — '100 Synthetic Lane, Synthtown A, ZZ'",
                "100 Synthetic Lane" in (row.get("display_address") or "")
                and "ZZ" in (row.get("display_address") or ""))
        assert_("Layer 7 (dashboard): display_owner is the §17 debtor "
                "(decedent), not a filer (the F-8 / §20 Check 12 guarantee)",
                "TEST_OWNER" in (row.get("display_owner") or ""))
        assert_("Layer 7 (dashboard): display_score == scored_lead.score",
                row.get("display_score") == scored_lead.get("score"))
        assert_("Layer 7 (dashboard): display_deal_paths re-derives from "
                "scored_lead.deal_paths (no invented fields)",
                row.get("display_deal_paths")
                == [dp["path"] for dp in scored_lead.get("deal_paths") or []])
        assert_("Layer 7 (dashboard): payload enrichment_breakdown shows "
                "1 ENRICHED + 0 UNENRICHED",
                payload["enrichment_breakdown"]["ENRICHED"] == 1
                and payload["enrichment_breakdown"]["UNENRICHED"] == 0)

        # --- LAYER 4 / 7 — scored_lead schema validation --------------------
        scored_lead_validator = Draft202012Validator(
            json.loads(schema_path("scored_lead_record").read_text())
        )
        assert_("Layer 4 (contract): scored_lead validates against "
                "scored_lead_record.schema.json",
                not list(scored_lead_validator.iter_errors(scored_lead)))

    # =====================================================================
    # R3(iii) — re-run UNENRICHED to prove enrichment is OPTIONAL. The
    # §13.14 enrichment-optional rule says a lead is never dropped /
    # blocked / held for missing enrichment.
    # =====================================================================
    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        result_un = run_pipeline_staged.run_staged_pipeline(
            [raw_event],
            evidence_entries=[make_evidence_entry()],
            signal_type_labels={"affidavit_of_heirship": "Affidavit of Heirship"},
            workdir=workdir / "unenriched",
            as_of=GOLDEN_AS_OF,
        )
        assert_("R3(iii) UNENRICHED: §20 verdict still DEPLOY_OK without "
                "enrichment",
                result_un["semantic_verdict"] == "DEPLOY_OK")
        unen = result_un["scored_leads"][0]
        assert_("R3(iii) UNENRICHED: scored_lead.enrichment_status is "
                "UNENRICHED",
                unen["enrichment_status"] == "UNENRICHED"
                and unen["parcel_display"] is None)
        assert_("R3(iii) UNENRICHED: lead is still scored (score >= 0) and "
                "reaches APPROVED_FOR_DASHBOARD (a lead is never dropped, "
                "blocked, or held for missing enrichment per §13.14)",
                unen["score"] >= 0
                and unen["lead_status"] == "APPROVED_FOR_DASHBOARD")

    # =====================================================================
    # LAYER 8 — RETAINED manifest.build_run_manifest.
    # =====================================================================
    run_manifest = manifest_mod.build_run_manifest(
        county="<synthetic>", state="ZZ",
        started_at="2026-05-07T12:00:00Z",
        sources_attempted=1, records_collected=1,
        records_normalized=1, leads_created=1, review_required=0,
        output_files=["data/matched_leads.json", "data/scored_leads.json",
                       "data/evidence_ledger.json"],
    )
    assert_("Layer 8 (manifest): run_id present",
            bool(run_manifest.get("run_id")))
    assert_("Layer 8 (manifest): counts add up — 1 raw → 1 normalized → "
            "1 lead — no leaks across stages",
            run_manifest["records_collected"]
            == run_manifest["records_normalized"]
            == run_manifest["leads_created"] == 1)
    assert_("Layer 8 (manifest): errors empty on the golden path",
            run_manifest.get("errors") == [])
    assert_("Layer 8 (manifest): output_files lists the staged-pipeline "
            "artifacts (matched_leads, scored_leads, evidence_ledger)",
            "matched_leads.json" in " ".join(run_manifest["output_files"])
            and "scored_leads.json" in " ".join(run_manifest["output_files"])
            and "evidence_ledger.json" in " ".join(run_manifest["output_files"]))

    # =====================================================================
    # LAYER 9 — RETAINED manifest.build_heartbeat.
    # =====================================================================
    heartbeat = manifest_mod.build_heartbeat(
        source_id="synth_clerk_recordings",
        source_name="Synthetic Clerk Recordings (test fixture)",
        source_class="lead_generating",
        source_priority="P0",
        source_reliability_grade="A",
        build_priority="mvp_required",
        access_pattern="open_api",
        records_seen=1, records_new=1,
        parser_confidence_avg=95,
        strategy="synthetic_jsonl_fixture",
        strategy_reason="Phase 1 synthetic harness",
    )
    assert_("Layer 9 (heartbeat): status is healthy",
            heartbeat["status"] == "healthy")
    assert_("Layer 9 (heartbeat): source_priority P0",
            heartbeat["source_priority"] == "P0")
    assert_("Layer 9 (heartbeat): source_reliability_grade in A-E",
            heartbeat["source_reliability_grade"]
            in ("A", "B", "C", "D", "E"))
    assert_("Layer 9 (heartbeat): access_attempts logged",
            len(heartbeat.get("access_attempts") or []) >= 1)
    assert_("Layer 9 (heartbeat): final_access_strategy set",
            bool(heartbeat.get("final_access_strategy")))

    # =====================================================================
    # CROSS-LAYER linkage + universality guard.
    # =====================================================================
    payload = make_raw_payload()
    parcel = make_parcel_master_row()
    assert_("Cross-layer: synthetic Synthtown placeholder city",
            "Synth" in parcel["situs_city"] and parcel["situs_state"] == "ZZ")
    assert_("Cross-layer: TEST_OWNER_* placeholder owner",
            parcel["owner_name"].startswith("TEST_OWNER"))
    assert_("Cross-layer: synthetic:// portal URL (no real vendor)",
            payload["source_url"].startswith("synthetic://"))

    # --- Report -----------------------------------------------------------
    passed = sum(1 for a in assertions if a[0] == "PASS")
    failed = sum(1 for a in assertions if a[0] == "FAIL")
    print("=" * 72)
    print("GOLDEN PATH — one synthetic lead through the v5.4.0 staged + seam "
          "pipeline (9 layers; rewritten in Session 10)")
    print("=" * 72)
    for a in assertions:
        marker = "PASS" if a[0] == "PASS" else "FAIL"
        print(f"  [{marker}] {a[1]}")
        if a[0] == "FAIL" and len(a) > 2 and a[2]:
            print(f"         detail: {a[2]}")
    print()
    print(f"RESULT: {passed} pass, {failed} fail")
    print("=" * 72)
    return failed == 0


if __name__ == "__main__":
    ok = run_golden_path()
    sys.exit(0 if ok else 1)
