# v5.4.0 Release Notes — the executable §17-§20 pipeline

**Tag:** `v5.4.0`
**Date:** 2026-05-23
**Codename:** Xcerebro County Intelligence Harness
**Previous version:** `v5.3.1`
**Release channel:** stable

---

## TL;DR

v5.4.0 ships the **executable §17-§20 pipeline engine**. v5.3.0 shipped the
§16-§20 architecture as *contract surface* — doc-presence invariants asserted
that the contracts were *present*, but the engine behind them was not built.
v5.4.0 builds, proves, and finalizes that engine, retires the v5.1.2-beta
monolith's signal→identity→aggregation core, and ships the **scoring seam
(Option Y)** that bridges the staged engine to the retained scoring /
classification / dashboard stages.

The ESC-002 escalation — "the §16-§20 contracts existed only as
documentation" — is resolved: every §16-§20 contract now has executable
behavior gated by `scaffold/tests/run_all.py`.

After v5.4.0 a county's distress-lead pipeline is:

```
translators/  +  normalize.py  +  owner_name_patterns.py
        │  (raw events, canonical_doc_type populated)
        ▼
   matcher.py  (§13.14 parcel resolution)
        ▼
   §17 debtor_party_engine        → debtor_resolved records
        ▼
   §18 leads_base_writer          → <source>_leads_base.json
        ▼
   §19 aggregator                 → matched_leads.json   ◀── immutable
        ▼
   §20 semantic_verify            → DEPLOY_OK / NEEDS_REVIEW / BLOCKED  (gate)
        ▼
   SEAM (scoring_seam — Option Y) → scored_lead records
        ▼
   score + classify + title-complexity + review (RETAINED, invoked by seam)
        ▼
   dashboard.json + manifest + heartbeat
```

`build_leads.py` is the new orchestrator; the old monolith `run_pipeline`'s
signal→identity→aggregation body is **gone**.

---

## Changes from v5.3.1

### Executable §17 — Debtor Party Engine (Session 2; extended Sessions 7-8)

`scaffold/pipeline/debtor_party_engine.py`. Resolves the debtor / lead subject
from a raw event record per `knowledge_base/architecture/17_debtor_party_rules.md`,
emitting `debtor_resolved_record` (`debtor_resolved_record.schema.json`). The
F-1 finding — "the §17 engine writes ONLY its own verdict
(`debtor_resolution_status`)" — was ratified in Session 2 and is preserved
end-to-end through cutover.

**Coverage at v5.4.0:** §17.C now covers **42 canonical doc types**:
- 17 from Session 2 (hospital_lien, code_lien, federal_tax_lien, …),
- 12 from Session 7 (the 9 operator-supplied debtor rules — `tax_deed`,
  `tax_foreclosure_notice`, `tax_sale_certificate`, `sheriff_sale_surplus`,
  `eviction_filing`, `writ_of_possession`, `divorce_filing`,
  `final_decree_of_divorce`, `marital_property_division`,
  `bankruptcy_petition`, `condemnation_notice`, `demolition_order`),
- 13 Session-8 broad-key → registry fan-out aliases (`notice_of_sale`,
  `letters_testamentary`, `judgment_lien`, etc.).

**Document-only resolution.** §17 resolves the debtor solely from parties
named on the document. The 12 Session-7 rules use the review_reason
`"owner_not_on_document"` when the owner isn't present — §17 does NOT
invoke parcel / assessor / tax-roll / GIS resolution itself (that is the
downstream §13.14 stage).

**Rule 6 — divorce multi-owner.** Both spouses go in the Session-7A
multi-owner block. If the decree clearly awards / orders sold / vests the
property in one named spouse, that spouse is `is_primary` and
`multi_owner_status` is `MULTIPLE_OWNERS_PRIMARY_CLEAR`. Otherwise both
spouses are preserved with no `is_primary`,
`multi_owner_status` is `MULTIPLE_OWNERS_PRIMARY_UNCLEAR`, and
`debtor_resolution_status` is `REVIEW_REQUIRED` — ownership priority is
never invented.

**Rule 7 — bankruptcy "no_property_connection".** When a bankruptcy
petition has no real-property hook (no parcel_id / situs_address /
legal_description), the engine routes to REVIEW_REQUIRED
`"no_property_connection"` — the lead is NOT hard-excluded. `case_number`
alone does NOT count (on a bankruptcy record it is the BK case, not a
property identifier). Contact context (signer / managing member /
registered agent / principal) is enrichment, NOT §17.

**§17.D filer suppression.** 16 universal suppression groups now (7
Session-2 + 9 Session-7 — `tax_authority`, `auction_party`, `law_firm`,
`court_role`, `law_enforcement`, `surplus_recovery`,
`bankruptcy_official`, `code_enforcement_role`, `property_manager`).

### Executable §18 — Aggregation Key + Leads-Base Writer (Session 3)

`aggregation_key_engine.py` + `leads_base_writer.py`. The §18.B key
`(parcel_id, canonical_doc_type, signal_type)` and the §18.F anti-collapse
rule (distinct signal_type values never collapse, even on the same parcel)
both executable. Per-source `<source>_leads_base.json` files are
deterministic (stable ordering / sorted keys) so the §19.D idempotency
invariant is achievable.

### Executable §19 — Idempotent Aggregator (Session 4)

`aggregator.py`. `matched_leads.json` is re-derived deterministically from
the per-source base files on every run — the §19.D idempotency rule is
enforced by `aggregator.idempotency_self_check`. `matched_leads.json` is
the immutable output of record; no downstream stage mutates it.

### Executable §20 — Semantic Verification Gate (Session 5)

`semantic_verify.py`. Twelve §20.C check classes execute against the staged
pipeline's own artifacts; six run pre-dashboard (debtor attribution,
owner-type classification, enrichment-decoupling, signal aggregation,
cross-source aggregation, universal filer scan), six are SKIPPED here as
deploy-time-input-required. Verdict: `DEPLOY_OK` / `NEEDS_OPERATOR_REVIEW`
/ `DEPLOY_BLOCKED`. The verdict gates scoring + dashboard.

### Multi-owner contract (Session 7A)

`records.py` + the three downstream schemas (`debtor_resolved_record`,
`leads_base_record`, `matched_lead_record`) extended with the **multi-owner
block**: `owners[]` (each owner: name, role, name_type, is_primary,
confidence, source_field, resolution_status, notes), plus the scalars
`primary_owner_name`, `additional_owner_names`, `owner_count`, and
`multi_owner_status` (`SINGLE_OWNER` / `MULTIPLE_OWNERS_PRIMARY_CLEAR` /
`MULTIPLE_OWNERS_PRIMARY_UNCLEAR`). `multi_owner_status` is **descriptive**
— it never carries a review verdict; the needs-review verdict stays
`debtor_resolution_status` / `parcel_resolution_status`. The schemas'
`allOf` consistency rules make it **impossible** for the descriptive and
verdict fields to contradict — co-owners are never dropped, ownership
priority is never invented.

### Doc-type bridge — three-namespace reconciliation (Session 8)

`doc_type_bridge.py` + `knowledge_base/architecture/22_doc_type_bridge.md`.
The bridge reconciles §16's 27 Title-Case `lead_type` taxonomy with the
canonical_doc_types.json registry's 74 UPPERCASE keys and the monolith's
UPPERCASE `normalized_doc_type` output. Three layers:

1. `monolith_to_registry(UPPERCASE)` — total over normalize.py's 74
   outputs; unknown returns None (no fuzzy fallback).
2. `registry_to_lead_type(lowercased)` — exhaustive over 74 registry types
   (36 → 25 distinct §16 lead types; 38 → None with documented reasons in
   `REGISTRY_WITHOUT_LEAD_TYPE_REASONS`).
3. `lead_type_for_monolith_output` composes end-to-end.

**Documented gaps (no operator decision required):**
- `Tax Delinquency` — a tax-roll STATUS (enrichment), not a recorded
  document; closest analogue `tax_foreclosure_notice` is bridged
  separately to "Tax Lien Foreclosure".
- `Abstract of Judgment` — shares `judgment_lien` with "Civil Judgment"
  (the registry carries one instrument for both).

### Option-Y scoring seam (Session 9)

`scoring_seam.py` + `scored_lead_record.schema.json`. Per the seam-design
operator decision: scoring emits a **new `scored_lead_record`** that
REFERENCES the immutable `matched_lead` by `lead_id` — it never mutates
the §19 output of record. The seam:

- Adapts §18 aggregated SignalGroups → a stack-shaped input for the
  retained `score.compute_score` / `classify.classify_deal_paths` /
  `_title_complexity` (extracted as `scoring_seam.title_complexity`).
  §18.E legitimate-stacking preserved: one stack entry per signal-group
  `count` so duplicate same-pattern instruments earn the additional
  stack-depth bonus.
- Bridges the canonical_doc_type → normalized_doc_type namespace via
  `doc_type_bridge` (handles registry-aligned keys, Session-8 broad-key
  fan-out, and Session-8 plural renames).
- Runs `review.evaluate_review_queue` against the synthesized lead-shaped
  transient so the review-flag / lead_status transitions stay identical
  to the monolith's behavior.
- Gates on the §20 verdict — `gate_on_semantic_verdict` raises
  `SemanticGateBlocked` (DEPLOY_BLOCKED) or `SemanticGateNeedsReview`
  (NEEDS_OPERATOR_REVIEW without `approve_needs_review=True`).

### R3(iii) — enrichment-optional property (§13.14 enforced)

Enrichment is **OPTIONAL** by design. The seam accepts an optional
`enrichment_provider`; when supplied, attributes are derived via
`normalize.derive_attributes` and `parcel_display` is stamped on the
scored_lead. When absent / returning None / raising, scoring degrades to
UNENRICHED — the lead is **still scored, still review-evaluated, still
reaches the dashboard**. A lead is never dropped, blocked, or held for
missing enrichment. The schema's `allOf` enforces:
`parcel_display` non-null **iff** `enrichment_status == "ENRICHED"`.

### Monolith core retirement (Session 10)

The monolith's signal → identity → aggregation orchestration is **gone**.
What was retired:

- `build_leads.py`'s `run_pipeline` body (the inline normalize → stack →
  lead-assembly loop), `normalize_signal`, `derive_synthetic_signals`,
  `_signals_by_parcel`, `build_lead_from_stack`, `_title_complexity` (now
  in `scoring_seam`), and the `stack.stack_signals` integration.
- `stack.stack_signals` itself (replaced by §17 + §18.B + §19). `stack.py`
  retains only `detect_multi_property_owners`.
- `evidence.py` (replaced by `evidence_ledger.py`).

What was **RETAINED** (and is reachable from the new staged path):

- `normalize.normalize_doc_type` — feeds the staged engine via
  `build_leads`'s signal → raw_event adapter.
- `translators/` — per-source raw-record → signal adapters.
- `matcher.match_signals_to_parcels` — §13.14 parcel resolution.
- `owner_name_patterns.emit_owner_name_signals_for_parcels` — parcel-
  master-derived raw events.
- `score` / `classify` / `review` / `dashboard.assert_two_truths` —
  invoked by the seam and the orchestrator.
- `manifest.build_run_manifest` / `manifest.build_heartbeat` — run
  manifest + per-source heartbeat.

`build_leads.py` is now the v5.4.0 staged orchestrator: translators →
normalize → matcher → §17→§18→§19→§20 → seam → scored_leads → dashboard
+ manifest + heartbeat. The CLI shape (`--synthetic`, `--county-config`,
`--out`) is preserved; `--approve-needs-review` is added for the §20
NEEDS_OPERATOR_REVIEW path. The output artifact set is:

- `data/<run>/matched_leads.json`        — the §19 immutable output
- `data/<run>/scored_leads.json`         — the seam's output
- `data/<run>/evidence_ledger.json`      — the §08 ledger
- `data/<run>/dashboard.json`            — the dashboard payload (Two-
                                            Truths invariant enforced)
- `data/<run>/source_heartbeat.json`     — per-source heartbeat
- `data/<run>/runs/<run_id>.manifest.json` — run manifest

### Rewritten golden path (Session 10)

`scaffold/tests/test_golden_path.py` — REWRITTEN to drive the staged + seam
pipeline. All 9 framework layers covered; 66 assertions. Same county-
agnostic discipline (Synthtown / ZZ / TEST_OWNER_* / synthetic:// only).
The R3(iii) enrichment-optional path is exercised twice (ENRICHED +
UNENRICHED) — both produce schema-valid scored_leads that reach
APPROVED_FOR_DASHBOARD. F-8 reconciled: lead `signals` is the §18 rich
aggregated-group shape, not the §09 `signal_id`-string shape.

### Run_all.py gate — 30 tests

Final gate count: **30 tests** (was 4 in v5.3.1):

| Bucket | Count | What |
|---|---|---|
| Monolith | 4 | Golden path (rewritten), county-agnostic regression, atomic config writer, translator registry. |
| v5.3.0 invariants | 10 | §02 build-mode, §17/§18/§19/§20 contract presence, §13.14 enrichment decoupling, recon API/PDF/bulk discovery, source-of-record matrix. |
| v5.4.0 contract-shape | 16 | Contract schemas, §17 debtor engine + units + behavior + filer suppression, multi-owner contract, §18 key engine + aggregator + units + behavior, §20 semantic verify + idempotent behavior + units, doc-type bridge, scored_lead contract, scoring seam units, staged + staged-with-scoring end-to-end. |

County-agnostic regression clean (no county / state / vendor literal in
universal framework files). All 9 framework layers gated end-to-end via
the rewritten `test_golden_path.py`.

### Documentation updates

- `knowledge_base/architecture/17_debtor_party_rules.md` §17.K — F-1 / F-5
  / F-6 reconciliations + Session 7A (multi-owner) + Session 7 (the 9
  deferred rules) + Session 8 (plural-key fixes + 7-key reconciliation).
- `knowledge_base/architecture/22_doc_type_bridge.md` — NEW. The
  three-namespace bridge design note.
- `docs/v5.4.0_session6_seam_design.md` — the Option-Y seam design that
  guided Sessions 7-10.
- `scaffold/pipeline/__init__.py` — module map updated for the post-
  cutover architecture.

---

## Breaking changes

- **`build_leads.py` orchestration body REPLACED.** `run_pipeline(...)` is
  preserved as the public entry point but its signature kwargs and return
  shape are unchanged; its body now routes through the staged engine. The
  old `normalize_signal`, `derive_synthetic_signals`,
  `_apply_parcel_master_matching`, `build_lead_from_stack`,
  `_title_complexity`, `_signals_by_parcel` symbols are **gone**.
- **`stack.stack_signals` removed.** `stack.py` retains only
  `detect_multi_property_owners`.
- **`evidence.py` removed.** Replaced by `evidence_ledger.py`.
- **Output artifact set CHANGED.** The monolith's `data/leads.json` /
  `data/leads_synthetic.json` (single payload file) is replaced by the
  staged artifact set under `data/<run>/`: `matched_leads.json`,
  `scored_leads.json`, `evidence_ledger.json`, `dashboard.json`,
  `source_heartbeat.json`, plus `runs/<run_id>.manifest.json`.
- **Non-gate tests stubbed.** `test_owner_name_signal_integration.py` and
  `verify_synthetic_harness.py` are reduced to documentation stubs that
  redirect to the new staged-pipeline gate tests; their original
  monolith-shaped assertions are superseded by the rewritten golden path
  and the v5.4.0 contract-shape tests.

### Migration — operator checklist

1. Re-run `python3 scaffold/pipeline/build_leads.py --synthetic` to see the
   new artifact set. The §20 NEEDS_OPERATOR_REVIEW verdict on synthetic
   data is expected — add `--approve-needs-review` to proceed.
2. Adapt any downstream consumer that reads `data/leads.json` to read the
   new `data/<run>/scored_leads.json` (per-lead) or `data/<run>/dashboard.json`
   (rendered payload).
3. The `scored_lead_record` schema is the new per-lead contract for
   downstream scoring / CRM / dashboard consumers — see
   `scaffold/pipeline/contracts/scored_lead_record.schema.json`.

---

## ESC-002 resolution

ESC-002 — "the §16-§20 contracts shipped as documentation, with passing
doc-presence tests, while the executable pipeline behind them was never
built" — is **resolved** by v5.4.0. Every §16-§20 contract now has
executable behavior:

| Contract | Executable engine | Gated by |
|---|---|---|
| §16 Source of Record Matrix | bridge to `lead_type` taxonomy | `test_doc_type_bridge.py` |
| §17 Debtor Party Rules | `debtor_party_engine.py` (29 doc types + 13 fan-out) | `test_debtor_party_engine_units.py` + behavior + filer-suppression + multi-owner contract + golden path |
| §18 Aggregation Key | `aggregation_key_engine.py` + `leads_base_writer.py` | `test_aggregation_key_engine_units.py` + behavior + aggregator units |
| §19 Idempotent Aggregator | `aggregator.py` | `test_aggregator_units.py` + idempotent behavior + staged end-to-end |
| §20 Semantic Verification | `semantic_verify.py` | `test_semantic_verify_units.py` + staged end-to-end |

The v5.3.0 doc-presence tests (`scaffold/tests/v5_3_0/test_*_present.py`)
remain wired — they continue to assert the contract *documentation* is
present alongside the executable engine. No previous contract was
weakened; every previous gate stays green.

---

## Tag

`v5.4.0` is tagged on the merge commit `feat/v5.4.0-pipeline-engine` →
`main` (`--no-ff`). The branch is preserved.
