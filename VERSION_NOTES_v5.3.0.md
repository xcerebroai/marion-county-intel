# VERSION NOTES — v5.3.0

**Release date:** 2026-05-18
**Type:** Minor release (additive — framework gap closure + recon/build contracts)
**Predecessor:** v5.2.0
**Successor:** v5.3.1 (planned — see Known Issues)

---

## Summary

v5.3.0 closes eight framework gaps identified after the v5.2.0 line, plus an
enrichment-decoupling amendment. The gaps clustered into three areas: recon
completeness (Gaps 1–3), lead/build semantics (Gaps 5, 6, 8 and §13.14), and
verification + build sequencing (Gaps 4, 7).

The release is **additive and county-agnostic**. It adds five architecture
documents, one protocol document, one reference template, ten per-gap
invariants, and a Source of Record Matrix schema. It amends the recon protocol,
the lead origination contract, the county-config schema, the master prompt, and
the onboarding doc. No locked rule was changed; no existing contract was broken.

Every universal file added or amended in this cycle passes the county-agnostic
regression scanner. The framework runs county-agnostic or v5.3.0 is wrong.

---

## Closed gaps

| Gap | Title | Universal artifact | Invariant |
|-----|-------|--------------------|-----------|
| 1 | PDF / sample-document inspection in recon | §01.20–§01.26 (`01_county_recon.md`) | `test_recon_requires_pdf_inspection.py` |
| 2 | Documented-API discovery in recon | §01.20–§01.26 (`01_county_recon.md`) | `test_recon_requires_api_discovery.py` |
| 3 | Bulk-availability classification in recon | §01.20–§01.26 (`01_county_recon.md`) | `test_recon_requires_bulk_classification.py` |
| 4 | Semantic verification contract | §20 (`20_semantic_verification_contract.md`) + `semantic_verify_template.py` | `test_semantic_verification_contract_present.py` |
| 5 | Debtor party rules | §17 (`17_debtor_party_rules.md`) | `test_debtor_party_rules_present.py` |
| 6 | Signal aggregation contract | §18 (`18_signal_aggregation_contract.md`) | `test_signal_aggregation_contract_present.py` |
| 7 | Build Mode Protocol | §02 (`02_build_mode_protocol.md`) + MASTER_PROMPT §4.34 | `test_build_mode_protocol_present.py` |
| 8 | Aggregator idempotency rule | §19 (`19_aggregator_idempotency_rule.md`) | `test_aggregator_idempotency_rule_present.py` |
| — | §13.14 enrichment-decoupling amendment | §13.14 (`13_lead_origination_contract.md`) | `test_enrichment_status_decoupled.py` |

The Source of Record Matrix (§16) underpins Gaps 1–3 and the Build Mode entry
preconditions; its schema invariant is `test_schema_source_of_record_matrix.py`.

---

## New universal files

- `docs/v5.3.0_patch_plan.md` — the cycle plan of record.
- `knowledge_base/architecture/16_source_of_record_matrix.md` — the SoR matrix
  contract bridging recon outputs to Build Mode.
- `knowledge_base/architecture/17_debtor_party_rules.md` — doc-type-specific
  debtor `name_type` extraction, filer-suppression patterns, `owner_type`
  classification.
- `knowledge_base/architecture/18_signal_aggregation_contract.md` — the
  universal aggregation key `(parcel_id, canonical_doc_type, signal_type)` and
  the anti-collapse rule.
- `knowledge_base/architecture/19_aggregator_idempotency_rule.md` — the
  run-twice / compare-byte-for-byte / refuse-to-deploy-on-mismatch rule.
- `knowledge_base/architecture/20_semantic_verification_contract.md` — twelve
  check classes, the three-state outcome model, deploy verdicts.
- `knowledge_base/protocols/02_build_mode_protocol.md` — the deterministic
  recon→deploy procedure; second document in the `protocols/` family.
- `scaffold/ops/semantic_verify_template.py` — a documentation-grade,
  county-agnostic reference template for the §20 contract.
- `scaffold/tests/v5_3_0/` — ten per-gap invariants (one per row above).

---

## Amended universal files

- `knowledge_base/protocols/01_county_recon.md` — §01.20–§01.26 added (PDF
  inspection, API discovery, bulk classification, SoR matrix production).
- `knowledge_base/architecture/13_lead_origination_contract.md` — §13.14
  enrichment-decoupling amendment (`parcel_resolution_status` is decoupled from
  `enrichment_status`; a lead is never dropped because enrichment failed).
- `config/counties/_schema.json` / `_schema.md` / `_template.json` — four
  nullable top-level properties and six `$defs` added for the Source of Record
  Matrix and its sub-objects.
- `MASTER_PROMPT.md` — §4.34–§4.39 added (Build Mode Protocol pointer and the
  §16–§20 contract pointers); the §4.34 reserved-gap placeholder is now filled,
  making the §4.33→§4.39 sequence contiguous.
- `START_HERE.md` — onboarding updated for the upgraded recon protocol.
- `scaffold/bootstrap_county.py` — recon-output expectations updated.
- `scaffold/tests/test_county_agnostic_regression.py` — see Precondition fixes.
- `README.md`, `scaffold/ops/verify_live.py`, `scaffold/ops/watchdog.py` — see
  Stub honesty disclosure.
- `FRAMEWORK_VERSION.json` — `framework_version` → `v5.3.0`,
  `previous_version` → `v5.2.0`, `locked_at` → `2026-05-18`. All locked rules
  preserved.

---

## Stub honesty disclosure

`scaffold/ops/verify_live.py` and `scaffold/ops/watchdog.py` shipped as CLI
stubs whose docstrings claimed the full implementation would land "in v5.2.0".
v5.2.0 shipped without it. v5.3.0 corrects the record:

- Both module docstrings now state plainly that v5.3.0 ships **no** production
  self-verifier or watchdog, that the earlier "v5.2.0" claim was not honored,
  and that production implementation is deferred to a future harness release.
- The stub return logic is unchanged — `verify_live.py` still returns
  `PRODUCTION_VERIFICATION_BLOCKED` (exit 3) and `watchdog.py` still returns
  `WATCHDOG_STUB_MODE` (exit 3), so no caller mistakes a stub for a pass.
- `README.md` no longer claims "live-browser verification with auto-rollback"
  as a shipped capability. The Infrastructure bullet now states that the
  verification *contract* is defined in v5.3.0 (§20) while the production
  implementation is deferred, and that production verifier/watchdog
  infrastructure is a per-county responsibility until universal production
  tooling lands. The Phase 6 line in the build workflow is hedged identically.

What v5.3.0 *does* ship for verification: the §20 contract surface and the
`semantic_verify_template.py` reference template — documentation-grade, not a
production verifier.

---

## Precondition fixes

The county-agnostic regression scanner was broken at baseline: it walked
`.venv/` and flagged strings inside vendored third-party packages, producing
174 false positives and making the gate unusable. v5.3.0 fixed it before any
gap work began:

- Added `EXCLUDED_DIR_COMPONENTS` (`.venv`, `venv`, `site-packages`,
  `node_modules`, `.git`, `__pycache__`, `.pytest_cache`, `.mypy_cache`,
  `dist`, `build`, `.tox`, `.eggs`) — a path is exempt if any component matches.
- Broadened the test-file exemption from `scaffold/tests/fixtures/` to all of
  `scaffold/tests/` (test `.py` files legitimately carry county-shaped input).
- Exempted `scaffold/pipeline/matcher.py` (carries an all-US-states code set as
  universal validation data).

The scanner now passes as a real gate with zero violations.

---

## Patch 2 status

Patch 2 (the v5.2.0-era "Build Eligibility Gate") remains parked in
`git stash@{0}`. It was **never applied**. Its concepts — build-mode entry
preconditions, build classifications, escalation patterns — were absorbed by
re-derivation into §02 Build Mode Protocol, rewritten in the full v5.3.0
context (Gaps 1–8, §13.14, semantic verification). §02.12 records the
absorption. The stash stays parked as historical reference and should not be
applied; it may be retired in a future cleanup pass.

---

## Verification — 14/14 green

- **4 gate suites** (`scaffold/tests/run_all.py`): Golden path, County-agnostic
  regression, Atomic county config writer, Translator registry — all PASS.
- **10 v5.3.0 invariants** (`scaffold/tests/v5_3_0/`) — all PASS.

The county-agnostic regression scanner is green: no county name, state name,
vendor name, or portal URL in any universal framework file it scans.

---

## Out of scope

- Production `verify_live.py` / `watchdog.py` implementations — deferred to a
  future harness release (see Stub honesty disclosure).
- Output-contract de-vendoring — see Known Issues below.

---

## Known Issues — Deferred to v5.3.1

The universality scanner has known blind spots that surfaced during the v5.3.0 release finalization:

1. **`_state`-suffix slug pattern blind spot.** The scanner word-boundary-matches county name tokens but does not detect `<county>_<state>` slug forms (e.g. `bexar_tx`, `el_paso_tx`) when they appear as code identifiers, default parameter values, or in docstrings. Hardcoded county slugs in `scaffold/ops/verify_live.py`, `scaffold/ops/write_county_config.py`, and other ops files are not currently caught by the scanner. Pre-existing as of v5.2.0; not introduced by v5.3.0.

2. **Output-contract vendor contamination.** Certain output enum values and translator identifiers carry vendor-derived names (e.g. `bcad_*` status values in `scaffold/pipeline/build_leads.py`, `publicsearch`/`tyler_odyssey` translator enums in the schema). These are not pure county-name leaks but are vendor-specific identifiers that should be county-agnostic per the universality contract. Pre-existing as of v5.2.0; touches output contracts consumed by downstream pipelines, so de-vendoring requires a coordinated migration with output-contract version bump.

v5.3.1 patch cycle will address both classes with appropriate anchor cases, per-gap invariants, and output-contract migration discipline. v5.3.0 ships with the scanner enforcing what it has historically enforced; no new enforcement claims with hidden carve-outs.

---

## Distribution

v5.3.0 is cut as `dist/framework_v5_3_0.zip` with a companion
`dist/framework_v5_3_0.zip.sha256` checksum. The zip is produced by
`git archive` from the `v5.3.0` tag — it contains only committed, tracked
content, and county-scoped tracked paths are stripped from the archive before
it is finalized.

---

## Working tree state at v5.3.0 cut

At release finalization the canonical harness working tree carried four
untracked items, none of which are v5.3.0 framework changes:

- `.claude/` — operator-side Claude Code settings.
- `config/counties/el_paso_tx.json` — a separate (El Paso) county build's
  config.
- `data/el_paso_tx/` — that build's data.
- `runs/el_paso_tx/` — that build's run folder.

These were untracked in both `sync/v5.3.0-source-of-record` and `main`. The
v5.3.0 commit set itself was complete and had no modified or staged tracked
files. Because the release zip is cut with `git archive` from the `v5.3.0`
tag, **none of these untracked items entered the release** — they are excluded
by construction.

Full strict-clean working-tree discipline is deferred to v5.3.1, specifically:

- `.gitignore` additions for `.claude/`;
- per-county-scoped artifact path conventions so a separate county build's
  config, data, and run artifacts cannot accumulate untracked in the canonical
  harness working tree.

---

**Tag:** `v5.3.0`
**Commit message:** `v5.3.0 release notes: VERSION_NOTES_v5.3.0.md`
