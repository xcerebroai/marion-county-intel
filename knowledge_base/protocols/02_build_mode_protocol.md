# 02. Build Mode Protocol (v5.3.0+)

The Build Mode Protocol is the deterministic procedure that connects recon outputs to a
deployed lead dashboard. It governs when a county build proceeds, partially proceeds, or
stops; the pipeline contract from translator through deploy; the deploy-gate sequencing;
and the halt and escalation conditions during a build.

This is the second document in the `knowledge_base/protocols/` family, after §01 County
Recon Protocol. It is county-agnostic throughout.

---

## 02.0 Purpose

The Build Mode Protocol connects recon outputs — the §16 Source of Record Matrix and the
§01 upgraded County Recon Protocol — to a deployed dashboard.

The protocol governs:

- when a build proceeds, partially proceeds, defers, or stops;
- the pipeline contract from translator through deploy;
- the deploy-gate sequencing (mechanical verification, then semantic verification);
- the halt, rollback, and escalation conditions encountered during a build.

This protocol **absorbs the concepts** of the v5.2.0-era Build Eligibility Gate (parked
in `stash@{0}`) without applying that stash. §02.12 records the absorption.

---

## 02.1 Build Mode entry preconditions

Build Mode does not begin until ALL of the following hold:

- the §16 Source of Record Matrix exists and validates against the
  `sourceOfRecordMatrix` schema in `config/counties/_schema.json`;
- all required SoR-matrix artifacts are present: the matrix JSON, the coverage map, the
  API discovery report, the build eligibility report, and the per-source fingerprints;
- the matrix's `county_build_status` is `READY_TO_BUILD` or `PARTIAL_BUILD_READY`;
- at least one `lead_type` has a per-lead-type status of `LIVE_SOURCE_FOUND`;
- every primary event source has completed PDF/sample-document inspection per §01;
- every primary event source has a bulk-availability classification per §01;
- every source has a documented-API discovery report per §01.

If any precondition fails, Build Mode does not begin — the recon phase must complete or
escalate first.

**Halt conditions on `county_build_status`:**

- `RECON_ONLY` → stop; ship the recon outputs to the operator; no build phase.
- `WAITING_ON_ACCESS` → halt; the operator must resolve the access issue before a build.
- `NOT_BUILDABLE_YET` → stop; document the blockers; no build.

---

## 02.2 Build mode classifications

Once the entry preconditions pass, the build is classified as one of:

- **`FULL_BUILD`** — `county_build_status = READY_TO_BUILD` and all primary event
  sources are `LIVE_SOURCE_FOUND`. Build all sources concurrently.
- **`PARTIAL_BUILD`** — `county_build_status = PARTIAL_BUILD_READY`; at least one primary
  event source is `LIVE_SOURCE_FOUND` and others are `SOURCE_FOUND_BLOCKED` /
  `SOURCE_FOUND_NEEDS_LOGIN` / `SOURCE_FOUND_PAID` / `SOURCE_FOUND_CAPTCHA` /
  `NEEDS_OPERATOR_REVIEW`. Build the live sources; document the blocked sources in the
  build report; surface them for the operator.
- **`DEFERRED_BUILD`** — `county_build_status` is `READY_TO_BUILD` or
  `PARTIAL_BUILD_READY` but the operator has flagged the county for a delayed build.
  Build Mode is entered, but no work begins; the deferred-build queue captures the county
  for later.

Build mode classification is the operational analog of the Build Eligibility Gate
concept from `stash@{0}` (Patch 2) — absorbed here without applying the stash. The stash
itself remains parked; the concepts are integrated, and the mechanics are independently
rewritten in the context of v5.3.0's complete picture (Gaps 1–8, the §13.14
enrichment-decoupling amendment, and semantic verification).

---

## 02.3 The pipeline contract

For each primary event source:

    raw scrape
        -> raw_records/<source>/*.json
    doc-type normalization (§17 canonical_doc_type taxonomy)
        -> normalized_records/<source>/*.json
    translator (§17 debtor party rules + §18 signal aggregation key)
        -> <source>_leads_base.json          (STABLE per-source output)

After every source is translated:

    aggregator (§18 cross-source aggregation + §19 idempotency)
        -> matched_leads.json                (volatile aggregate, idempotent)
    dashboard build
        -> dashboard/data.json + index.html
    mechanical verification  (count > 0, schema valid, renders, no console errors)
    semantic verification (§20 — twelve check classes)
        -> semantic_verification_report.md
    deploy   (only if DEPLOY_OK; halt if DEPLOY_BLOCKED;
              operator approval if NEEDS_OPERATOR_REVIEW)

Pipeline rules (universal):

- aggregators read only from `*_leads_base.json` files, NEVER from their own output
  (§19);
- translators emit to `*_leads_base.json` and never modify another source's base file;
- the dashboard build reads only `matched_leads.json` and never reaches back to
  `raw_records`;
- every pipeline stage has an idempotency requirement — the same inputs produce the same
  outputs.

---

## 02.4 Translator obligations

Every translator MUST:

- apply the §17 debtor party rules (doc-type-specific debtor `name_type` extraction);
- apply the §17 filer-suppression patterns (the universal filer list; route to
  `REVIEW_REQUIRED` on a match);
- apply the §17 `owner_type` classification (word-boundary and position rules);
- apply the §18 signal aggregation key `(parcel_id, canonical_doc_type, signal_type)`;
- decouple `parcel_resolution_status` from `enrichment_status` per §13.14;
- never drop a lead because enrichment failed;
- emit to `<source>_leads_base.json` — the stable per-source output;
- include `source_url`, `instrument_number`, `recorded_date`, and `evidence_ids` on
  every lead.

A translator that does not implement these obligations cannot deploy.

---

## 02.5 Aggregator obligations

The aggregator MUST:

- read only from `*_leads_base.json` files;
- apply the §18 cross-source aggregation using the universal aggregation key;
- apply the §18 anti-collapse rule (distinct `signal_type` values never merge);
- apply the §19 idempotency self-check — run twice, compare byte-for-byte, refuse to
  deploy on mismatch;
- emit `matched_leads.json`;
- never read from its own output.

---

## 02.6 Mechanical verification (entry gate to semantic verification)

After the dashboard build, mechanical verification checks:

- `matched_leads.json` validates against its schema;
- the lead count is > 0 (or a stated empty state is intentional and documented);
- `dashboard/data.json` validates against its schema;
- the dashboard renders without console errors;
- all sources are represented in the build report.

If mechanical verification fails, HALT the build, document the failure, and do NOT
proceed to semantic verification.

---

## 02.7 Semantic verification (deploy gate)

After mechanical verification passes, semantic verification per §20 runs all twelve
check classes. The outcomes:

- **`DEPLOY_OK`** — proceed to deploy.
- **`DEPLOY_BLOCKED`** — HALT, document, surface for the operator.
- **`NEEDS_OPERATOR_REVIEW`** — pause for operator approval; deploy only after explicit
  operator sign-off.

The semantic verification report is committed to
`runs/<county_slug>/build/semantic_verification_report.md` regardless of the verdict.

---

## 02.8 Deploy phase

The deploy phase activates only after semantic verification passes — or after the
operator approves a `NEEDS_OPERATOR_REVIEW` verdict. Deploy:

- pushes `dashboard/data.json` and `index.html` to the hosting target;
- updates the live URL;
- records the deploy SHA, timestamp, and semantic verdict in
  `runs/<county_slug>/build/deploy_log.md`.

If deploy fails (an HTTP error, the hosting target unreachable), HALT, retry once, and
escalate if the failure persists.

---

## 02.9 Halt conditions during build

A build halts — a full halt with a work-in-progress commit, not merely a per-stage
failure — on:

- recon preconditions invalidated mid-build (e.g. the SoR matrix mutated unexpectedly);
- an aggregator idempotency self-check failure;
- a §17 or §18 contract violation detected mid-pipeline;
- a mechanical verification failure;
- a semantic verification `DEPLOY_BLOCKED` verdict;
- a deploy failure that persists after one retry.

**Halt protocol:**

- commit the current work-in-progress with an accurate WIP message;
- write the halt reason to `runs/<county_slug>/build/halt_log.md`;
- surface the halt to the operator;
- do not auto-resume — the operator decides the next action.

---

## 02.10 Build-mode escalation patterns

Some failures require an operator decision rather than an auto-halt:

- a previously-`LIVE` source goes down mid-build (its access state changed);
- semantic verification returns `NEEDS_OPERATOR_REVIEW` with `AMBIGUOUS` rows;
- a new source surfaces mid-build (operator-verified) that was not in the original SoR
  matrix;
- the build duration exceeds the per-county budget defined in
  `config/counties/<county_slug>.json`.

Each escalation pattern routes through `runs/<county_slug>/build/escalations/` as a
markdown file carrying the context, the recommended action, and an operator-decision
field.

---

## 02.11 Cross-references

- §13 Lead Origination Contract (`13_lead_origination_contract.md`).
- §16 Source of Record Matrix (`16_source_of_record_matrix.md`).
- §17 Debtor Party Rules (`17_debtor_party_rules.md`).
- §18 Signal Aggregation Contract (`18_signal_aggregation_contract.md`).
- §19 Aggregator Idempotency Rule (`19_aggregator_idempotency_rule.md`).
- §20 Semantic Verification Contract (`20_semantic_verification_contract.md`).
- §01 County Recon Protocol — upgraded (`01_county_recon.md`).

---

## 02.12 Patch 2 absorption note (transparency)

Patch 2 (parked in `stash@{0}`, v5.2.0 era) defined a Build Eligibility Gate concept — a
recon→build transition gate. This protocol absorbs the underlying concept (build-mode
entry preconditions, build classifications, escalation patterns) without applying the
stash itself.

Patch 2 was written before the broader v5.3.0 picture emerged — Gaps 1–8, the §13.14
enrichment-decoupling amendment, and semantic verification. The mechanics in this
protocol are rewritten in the v5.3.0 context and integrated with the new architecture
files (§16–§20).
The stash itself remains parked in the repository as historical reference; it should NOT
be applied. After v5.3.0 tags and ships, the stash may be retired in a future cleanup
pass.

---

## 02.13 Universal versus county-specific separation

- **Universal** — the pipeline contract, the build-mode classifications, the gate
  sequencing, and the halt conditions. They live in this file.
- **County-specific** — the per-county pipeline runners, scraper implementations, and
  dashboard configurations live under `runs/<county_slug>/build/` and in
  `config/counties/<county_slug>.json`. Per-county build budgets and escalation
  thresholds live in `config/counties/<county_slug>.json` under `build_mode`.

This file contains no county name, no state name, no portal URL, and no county-specific
example. The county-agnostic regression scanner enforces this.
