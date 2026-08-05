"""
Framework-canonical lead pipeline package.

This package contains UNIVERSAL pipeline logic that runs for any county.
County-specific logic lives in:

  - config/counties/<slug>.json      (county configuration)
  - scrapers/<source>.py             (county source adapters)
  - runs/<slug>/                     (county run artifacts)
  - data/                            (county output data)

The universality contract (MASTER_PROMPT §4.31, added in v5.1.2-beta) is:

  1. No county name, city, statute, vendor, or portal hostname appears
     literally in any file under scaffold/pipeline/.
  2. No state-specific date arithmetic, doc-type list, or municipality
     list is hardcoded in scaffold/pipeline/. State and county rules
     enter the pipeline ONLY through config and the translator registry.
  3. Source-specific translators register against a generic protocol
     (scaffold/pipeline/translators/__init__.py). The orchestrator
     dispatches by string name from county config; it never branches
     on source IDs.
  4. Synthetic fixture logic stays in scaffold/data/ and is consumed
     only when --synthetic is passed. Production code paths never
     read synthetic fixtures.

Modules (v5.4.0 post-cutover):

  ── Staged engine (v5.4.0 §17 → §18 → §19 → §20) ────────────────────────
    contracts/                 Inter-stage data contracts — JSON Schemas +
                               frozen dataclass mirrors (raw_event_record,
                               debtor_resolved_record, leads_base_record,
                               matched_lead_record, scored_lead_record,
                               evidence_ledger_entry).
    debtor_party_engine        §17 — debtor party engine. Resolves the lead
                               subject from raw_event_record per §17.C.
    aggregation_key_engine     §18 — (parcel_id, canonical_doc_type,
                               signal_type) key + signal_type resolution.
    leads_base_writer          §18 — writes <source>_leads_base.json.
    aggregator                 §19 — idempotent matched_leads.json builder.
    semantic_verify            §20 — semantic verification gate
                               (DEPLOY_OK / DEPLOY_BLOCKED / NEEDS_REVIEW).
    evidence_ledger            §08 — evidence_ledger.json builder +
                               traceability check.
    doc_type_bridge            Session 8 — three-namespace doc-type bridge
                               (monolith UPPERCASE ↔ registry lowercased ↔
                               §16 Title-Case lead_type).

  ── Option-Y scoring seam (v5.4.0 Session 9) ────────────────────────────
    scoring_seam               Adapter from matched_lead → score input;
                               R3(iii) enrichment-optional path; §20 gate.
    run_pipeline_staged        Drives §17→§18→§19→§20 + seam end-to-end.

  ── RETAINED upstream / downstream stages ───────────────────────────────
    normalize                  Doc-type normalization (canonical + per-
                               source synonyms). Feeds the staged engine
                               via build_leads' signal → raw_event adapter.
    translators                Per-source raw-record → signal adapters.
                               Hybrid framework + county pattern.
    matcher                    Parcel-master matcher (§13.14 parcel-
                               resolution stage). Runs before §17.
    owner_name_patterns        Regex signal emitter for parcel-master
                               owner-name strings (estate / living_trust).
    score                      Base + stack + recency + attribute scoring;
                               invoked by scoring_seam.
    classify                   Deal-path classifier; invoked by scoring_seam.
    review                     Review-queue rule engine; invoked by
                               scoring_seam.
    dashboard                  Dashboard projection + Two-Truths invariant
                               (assert_two_truths invoked by build_leads).
    manifest                   Run manifest + per-source heartbeat.
    stack                      multi-property-owner detection helper.
                               (Note: `stack.stack_signals` — the monolith's
                               per-parcel TTL / lifecycle / collapse stacker
                               — was retired in Session 10. The §17→§19
                               staged engine replaces its role.)
    sale_date_rules            State-statute rule registry for
                               expected_sale_date derivation.

  ── Orchestrator ────────────────────────────────────────────────────────
    build_leads                v5.4.0 staged-pipeline orchestrator (CLI).
                               Reads county config, dispatches translators,
                               adapts signals → raw_event_records, runs the
                               staged engine + seam, writes matched_leads /
                               scored_leads / evidence_ledger /
                               dashboard.json + manifest + heartbeat.

v5.1.2-beta CRITICAL CHANGES from earlier in-county Phase 1-4 work
(captured during the May 2026 universality audit):
  - Translator dispatch is config-driven, not hardcoded.
  - Geography rules (accepted_municipalities, sale_date_rule,
    cross_county_policy) come from config.
  - Doc-type synonyms come from per-source config blocks, not from
    in-code maps.
  - Parcel ID prefixes come from per-source config, not from in-code
    string constants.
  - Appraisal-district / county-specific literals scrubbed from all
    universal files.
"""
