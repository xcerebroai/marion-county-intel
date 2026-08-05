# Framework v4 — How to Use This for Any County

This is the operator-facing handoff document. If you're sitting down to build a new county on this framework, start here.

The framework is universal. It is not built for any specific county. It is designed to be copied into a new private repo, pointed at a target county config, and allowed to discover the county's source landscape from recon.

---

## What this framework is

A reusable system for building autonomous county-lead-intelligence dashboards. Every county built on this framework inherits:

- Daily refresh from county clerk / court / sheriff / tax / code sources
- Source-classified, scored, deal-path-classified leads
- Strict evidence ledger attached to every field and every claim
- Source heartbeat and cursor tracking so refreshes do not duplicate or miss records
- Six client deal-path classifications (wholesale / flip / sub-to / seller-finance / partial-interest / messy-title)
- Live-browser verification with auto-rollback (broken dashboards never reach clients)
- Telegram alerts for source failures, regressions, session expiry, new high-stack leads
- Watchdog every 6 hours catching post-deploy drift
- Entity resolution for individuals, LLCs, trusts, estates, parcels, addresses, cases, and instruments
- Synthetic test harness before real county data enters the system
- STATIC_JSON_MODE / SUPABASE_MODE / HYBRID_MODE storage options

The framework codifies what was learned across earlier county builds. Every county built on it inherits those lessons by default. **Earlier county builds remain as learning artifacts and are not retrofitted.**

---

## Universal rule

**Do not hardcode a county. Do not hardcode a state. Do not carry assumptions from a previous county build into a new one.**

Every new county is discovered from its own config and its own `RECON.md`. The framework's universal files (knowledge base, schema, scaffold) do not change per county. The only file that varies per county is `config/counties/<county_id>.json`.

---

## The workflow at a glance

```
1. Pick a county (any county)
2. Create a new private GitHub repo named <county_id>-intel
3. Copy this framework into the repo
4. Copy config/counties/_template.json to config/counties/<county_id>.json
5. Open Claude Code in the repo
6. Paste MASTER_PROMPT.md as the first message, with target county set
7. Let Claude Code run Phase 0 → Phase 8 autonomously
8. Run the deployment checklist (knowledge_base/engineering/06_deployment.md)
9. County is live and refreshing daily
```

---

## Step-by-step

### Step 1: Create the new repo

```bash
cd C:\Dev\xcerebro-builds\projects
mkdir <county_id>-intel
cd <county_id>-intel
git init
gh repo create xcerebroai/<county_id>-intel --private --source=. --remote=origin
```

The repo stays private. Client access is granted by GitHub-account add or revoked by removing access. GitHub Pages serves the dashboard from this private repo.

### Step 2: Copy the framework scaffold

```bash
xcopy /E /I C:\Dev\framework_v4\knowledge_base knowledge_base
xcopy /E /I C:\Dev\framework_v4\config config
xcopy /E /I C:\Dev\framework_v4\scaffold scaffold
copy C:\Dev\framework_v4\MASTER_PROMPT.md MASTER_PROMPT.md
```

### Step 3: Copy the template config and rename

```bash
copy config\counties\_template.json config\counties\<county_id>.json
```

Edit the new file to set:
- `county_id`
- `county_name`
- `state`
- `subject_state_full`
- `fips_code`
- `timezone`
- `geography.municipalities` (full list, with codes and FIPS place codes)
- `geography.parcel_id_format` (regex)
- `dashboard.title`
- `deployment.github_repo`
- `deployment.live_url`
- `deployment.scheduled_task_name`
- `deployment.watchdog_task_name`
- `storage.mode` (default STATIC_JSON_MODE; switch to SUPABASE_MODE or HYBRID_MODE if needed)

The `sources` block can be left mostly empty at this stage. Phase 0 recon fills in URLs, access patterns, field maps, and doc-type synonyms per source.

### Step 4: Open Claude Code in the repo

```bash
cd C:\Dev\xcerebro-builds\projects\<county_id>-intel
claude
```

### Step 5: Paste the master prompt

In Claude Code, paste the contents of `MASTER_PROMPT.md` as the first message, and append:

```
Target county: <county_id>
Begin Phase 0.
```

Claude Code will:
1. Read all required-reading files + the county config
2. Summarize back what it understands
3. Run Phase 0 (combined source recon + onboarding gate — produces validated county config)
4. Run Phase 1 (synthetic data harness against fake data)
5. Run Phase 2 (first adapter — usually parcel master enrichment)
6. Run Phases 3-7 (scrapers, matching, scoring, dashboard, verification)
7. Run Phase 7 (refresh harness + alerts)
8. Run Phase 8 (build summary)

Each phase reports completion. If a phase fails, Claude Code stops and writes `BUILD_BROKEN.md`. The operator investigates, fixes, restarts.

### Step 6: Enable GitHub Pages

After the first commit lands:

1. Go to `https://github.com/xcerebroai/<county_id>-intel/settings/pages`
2. Source: Deploy from a branch
3. Branch: `main`, folder `/` (root)
4. Save

Pages flushes in 1-3 minutes. The repo stays private; Pages serves through GitHub's auth.

### Step 7: First live verification

```bash
py -3.12 pipeline\verify.py
```

If it passes: `LIVE_VERIFIED.txt` is committed. The dashboard is live.

If it fails: `BUILD_BROKEN.md` is written and HEAD reverts. Read the broken file, fix the issue, re-run.

### Step 8: Register scheduled tasks

```powershell
schtasks /create /xml scripts\daily_refresh.xml /tn "<county_id>-intel-refresh" /ru <COMPUTERNAME>\<USER> /rp <password> /f
schtasks /create /xml scripts\watchdog.xml /tn "<county_id>-intel-watchdog" /ru <COMPUTERNAME>\<USER> /rp <password> /f
```

The framework writes the XML files; the operator provides the password (the autonomous build cannot acquire it).

### Step 9: Configure Telegram

Add to `.env`:

```
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_CHAT_ID=<from getUpdates after bot creation>
```

Smoke-test:
```bash
py -3.12 -c "from pipeline.alerts import telegram_send; telegram_send('test from <county_id>-intel')"
```

### Step 10: Smoke-test the daily refresh

```powershell
schtasks /run /tn "<county_id>-intel-refresh"
```

Wait 5-10 minutes. Confirm:
- The task ran (Task Scheduler history)
- A new commit landed
- The dashboard refreshed

If yes: the county is autonomous.

---

## What the operator does ongoing per county

**Weekly:**
- Re-seed any seeded-session sources (~30 sec each in Chrome → copy cookies → paste to `.env`)

**Monthly:**
- Sign and email any standing public-records requests

**As-needed (driven by Telegram alerts):**
- "Re-seed clerk session within 24h" → re-seed within 24h
- "Source layout changed for X" → look at scrape log, fix parser
- "Build auto-rolled back" → read `BUILD_BROKEN.md`, fix forward

That's the ongoing operator workload per county. Otherwise autonomous.

---

## Client access model

GitHub Pages hosts the dashboard from the private repo. The client gets:
- A bookmark to `https://xcerebroai.github.io/<county_id>-intel/`
- Read access to the repo (or no repo access — Pages can be served to clients without granting repo access via GitHub auth)

**Revocation paths** when a client stops paying or otherwise needs to lose access:
1. Disable Pages on the repo
2. Remove client's GitHub access
3. Replace `data/leads.json` with a placeholder
4. Disable the daily refresh scheduled task (dashboard goes stale)

The framework's hosting model assumes paid client access. Revocation paths are part of the product.

---

## What the framework refuses to do

(From `domain/06_hallucination_controls.md` and `MASTER_PROMPT.md`)

- Skip the live verification gate
- Ship leads without prime-directive labels (Confirmed / Estimated / Possible / Unknown)
- Declare a build done without `BUILD_SUMMARY.md` passing all checks
- Back-fill empty buckets with derived noise
- Generate leads from parcel-master metadata alone
- Mix synthetic data with real data in production `leads.json`
- Auto-merge entities when evidence is weak (always route to review)

---

## How to extend the framework

Three ways the framework can grow:

### A. Add a new pattern or subtype

Edit `domain/01_lead_types.md` (add pattern + subtypes + deal-path mapping), `domain/03_scoring_and_stacking.md` (base scores), `domain/04_deal_path_classifier.md` (rules), `scaffold/data/synthetic_signals.jsonl` (test coverage), `scaffold/data/synthetic_expectations.json` (expected counts). Run Phase 1 against synthetic data to confirm.

### B. Add a new source type

Edit `domain/02_signals_and_sources.md` (classification), `engineering/00_tooling_decision_tree.md` (access pattern), `config/counties/_schema.json` (subtype enum). Each county adds the source to its config.

### C. Add a new client persona / deal path

Edit `domain/00_client_business_model.md` (persona), `domain/04_deal_path_classifier.md` (rules), `domain/01_lead_types.md` (pattern matrix), `scaffold/data/synthetic_expectations.json` (path distribution).

---

## Versioning

This is **v5.1.2-beta-r3**.

**v5.1.2-beta-r3 changes from v5.1.2-beta-r2** (field_map bridge for non-canonical scraper field names — no breaking changes):

This revision activates the `field_map` bridge in both canonical translators. v5.1.2-beta added `sources.<id>.field_map` to the schema but the v5.1.2-beta-r2 translators did not actually read it — they assumed scrapers emit framework-canonical field names directly. The first parcel_master migration (Bexar) discovered that pre-existing scrapers commonly normalize to source-specific conventions (`situs_address`, `owner_mailing_addr1`, `property_class`) rather than canonical (`address`, `owner_mailing_address`, `property_use`).

`field_map` is the universal bridge. The translator resolves canonical field names through `field_map` (if present) before reading from `raw_payload`. Canonical fields absent from `field_map` are read directly (identity mapping). No county-side shim required. No re-scrape required.

Key changes:

- **`foreclosure_notices` translator** now reads `source_config.field_map` and resolves all 7 canonical fields (`address`, `doc_number`, `recording_year`, `recording_month`, `city`, `zip`, `layer_id`) through it. Partial maps (only some keys mapped) work correctly; unlisted keys default to identity.
- **`parcel_master` translator** now reads `source_config.field_map` and resolves all canonical parcel fields through it (`parcel_id`, `address`, `owner_name`, `owner_mailing_*`, `city`, `zip`, `assessed_value`, `land_value`, `improvement_value`, `year_built`, `property_use`, `acres`, `legal_description`, `exemptions`). Exemption booleans (`exempt_homestead` etc.) are explicitly NOT field-mapped — they are framework-canonical semantics, not source nomenclature.
- **MASTER_PROMPT.md §4.32** updated with explicit `field_map` documentation, including the limitation that exemption keys are not field-mapped.
- **test_translator_registry.py** extended from 39 → 55 tests. New cases: field_map full mapping (both translators), partial field_map, identity fallback for non-mapped keys.
- **FRAMEWORK_VERSION.json** bumped to `v5.1.2-beta-r3`.
- **scaffold/bootstrap_county.py** FRAMEWORK_VERSION constant bumped.
- **All 4 gate tests PASS:** golden path (46/46), county-agnostic regression (zero violations), atomic config writer (18/18), translator registry (60/60).

**No schema changes.** `sources.<id>.field_map` was already in `_schema.json` from v5.1.2-beta. r3 just makes translators honor it. r2 county configs work unchanged on r3 (field_map is optional).

**No breaking changes.** Translators in r2 read canonical names directly. Translators in r3 do the same UNLESS `field_map` is present. Existing configs continue to work.

**Bexar migration path with r3:**

After overlaying r3 canonical into the Bexar repo, `bexar_tx.json` adds a `field_map` to the parcel_master source:

```json
"parcel_master": {
  "translator": "parcel_master",
  "parcel_id_prefix": "BCAD-",
  "field_map": {
    "address": "situs_address",
    "city": "situs_city",
    "zip": "situs_zip",
    "owner_mailing_address": "owner_mailing_addr1",
    "property_use": "property_class"
  }
}
```

The wrap script from r2 still applies (deterministic flat → wrapped transform of `data/raw/parcel_master.jsonl`). No changes to scrapers, no re-scrape. The 287-lead baseline is preserved because the underlying data is bit-identical inside the wrapper, and `field_map` bridges the field names at translator-read time.

**Deferred to v5.1.2-beta-final:**

- `scaffold/data/canonical_record_fields.json` — the canonical-field-name registry. v5.1.2-beta-r3 ships the bridge mechanism; v5.1.2-beta-final will publish the canonical vocabulary so new scrapers can avoid needing `field_map` at all.

**v5.1.2-beta-r2 features preserved:** §4.32 Scraper-to-translator data contract, renamed translators, wrapped raw_payload contract, csv_static_list unchanged.

---

This is **v5.1.2-beta-r2**.

**v5.1.2-beta-r2 changes from v5.1.2-beta** (translator data-contract correction — minor breaking change for `translator` config string):

This revision corrects a data-contract ambiguity discovered during the Bexar in-place migration of v5.1.2-beta. The original v5.1.2-beta canonical translators assumed scrapers were pass-through wrappers around raw vendor protocol output. Bexar's scrapers (and likely all pre-v5.1.2-beta scrapers) instead normalize fields at scrape time before persisting. v5.1.2-beta-r2 reverses the assumption and locks the framework around **Path 1: scrapers normalize, translators consume normalized output**.

Key corrections:

- **MASTER_PROMPT.md §4.32 Scraper-to-Translator Data Contract.** New section. Declares the canonical wrapped raw-record shape that scrapers must produce and translators must consume:
  ```json
  {
    "raw_record_id": "...",
    "source_id": "...",
    "source_url": "...",
    "source_fetched_at": "...",
    "raw_payload": {<lowercase framework-canonical field names>}
  }
  ```
  Scrapers normalize source fields. Translators read normalized `raw_payload`. Translators are protocol-agnostic and never know whether the data came from a REST API, public-records portal, court e-portal, or static CSV. Portal protocol knowledge lives in the scraper or in `scaffold/scrapers/` protocol clients.
- **Translator rename.** Vendor-protocol prefix dropped:
  - `arcgis_foreclosure_notices` → `foreclosure_notices`
  - `arcgis_parcel_master` → `parcel_master`
  - `csv_static_list` unchanged (CSV isn't a vendor-specific protocol).
  - Translator files renamed in `scaffold/pipeline/translators/`.
  - Schema enum (`config/counties/_schema.json` `sources.<id>.translator`) updated to reflect new names; old names removed.
  - This is a SMALL breaking change. County configs declaring `translator: "arcgis_foreclosure_notices"` must update to `translator: "foreclosure_notices"`. No code-side migration required because the v5.1.2-beta canonical translators were not in production use (only Bexar had v5.1.2-beta and Bexar was mid-migration).
- **Translator implementations rewritten.** `foreclosure_notices` reads lowercase normalized fields (`address`, `doc_number`, `recording_year`, `recording_month`, `city`, `zip`, `layer_id` — no underscore) from `raw_payload`. `parcel_master` reads framework-canonical fields (`parcel_id`, `address`, `owner_name`, etc.) from `raw_payload` and prefers pre-parsed `exempt_*` boolean fields; legacy compatibility path parses raw `exemptions` string via `translator_config.exemption_codes` if booleans absent.
- **`test_translator_registry.py` rewritten.** 39 tests covering the new contract: builtin registration under new names, normalized-payload consumption, cross-county-leak policy with lowercase city keys, sale_date_rule dispatch from normalized year/month, parcel_master boolean-exemption fast path, parcel_master legacy-string fallback, empty-parcel_id skip behavior. Old test cases referencing UPPERCASE ArcGIS attrs removed.
- **`docs/v5.1.2-beta_bexar_migration_playbook.md`** updated to reflect new translator names + lowercase normalized translator_config field references + one-time `data/raw/parcel_master.jsonl` shape transform step (flat → wrapped).
- **`FRAMEWORK_VERSION.json`** bumped to `v5.1.2-beta-r2`, `locked_at: 2026-05-15`.
- **All 4 gate tests PASS:** golden path (46/46), county-agnostic regression (zero violations), atomic config writer (18/18), translator registry (39/39).

**Why this is r2, not v5.1.3.** v5.1.2-beta was tagged on 2026-05-14 and pushed to canonical, but it had not propagated to any production county before Bexar's mid-migration exposed the data-contract ambiguity. r2 corrects the beta release in-place under the same minor version. The original v5.1.2-beta tag is preserved on the canonical repo for audit-trail purposes; v5.1.2-beta-r2 is the recommended version for any new county build or any in-progress migration.

**Bexar migration impact.** Bexar's in-place migration paused at Step 5 of the v5.1.2-beta playbook when the contract ambiguity surfaced. With v5.1.2-beta-r2 canonical translators, Bexar resumes migration with:
1. A one-time deterministic shape transform of `data/raw/parcel_master.jsonl` from flat to wrapped shape (no data drift; baseline reproducibility preserved).
2. `bexar_tx.json` translator names updated (`foreclosure_notices` / `parcel_master`).
3. `bexar_tx.json` `translator_config` field-name references updated from UPPERCASE ArcGIS attrs to lowercase normalized names.
4. Resume Step 5 of the playbook with corrected translators.

**v5.1.2-beta features preserved:** Universality Contract §4.31, schema additions, translator registry mechanics, sale_date_rules, owner_name_patterns defensive guard, upgraded regression test, scaffold/data/synthetic_attribute_overrides.json.

---

This is **v5.1.2-beta**.

**v5.1.2-beta changes from v5.1.1-beta** (universality contract enforcement — schema additions, no breaking schema changes for existing configs):

This release closes the universality drift identified by the May 2026 audit of a v5.1.1-beta-seeded Phase 1-4 county build. The audit found 11 specific county-specific leaks in `scaffold/pipeline/` and 4 in `dashboard/`: a hardcoded municipality frozenset, a state-specific sale-date helper, hardcoded source-id dispatch in the orchestrator, in-code doc-type aliases, county-mnemonic parcel ID prefixes baked into code, vendor-named comments, and a single-county translator module. The framework code knew it was running for a specific county. v5.1.2-beta locks the universality contract.

Key additions:

- **MASTER_PROMPT.md §4.31 Universality Contract.** Ten locked rules. No county name, city, statute, vendor, or portal hostname in `scaffold/pipeline/`. Cross-county portability. State rules via `sale_date_rules` registry. Doc-type synonyms from config. Field maps from config. Parcel-ID prefixes from config. Synthetic-fixture overrides isolated to `scaffold/data/synthetic_attribute_overrides.json`. Owner-name signal emitter requires the defensive guard (parcels not already linked to a lead-generating signal cannot produce a signal). Translator registry is the only source-dispatch path. County-specific comments are scrubbed.
- **Schema additions** (`config/counties/_schema.json`):
  - `geography.accepted_municipalities[]` — superset of municipalities including unincorporated communities, spelling variants, neighboring overlaps. Replaces hardcoded city frozensets in universal code.
  - `geography.cross_county_policy` — `unknown_city_action` (drop | flag_for_review | accept_with_warning) plus optional `neighboring_county_municipalities`.
  - `geography.sale_date_rule` — `rule_name` selects from the framework registry (`first_tuesday_of_month`, `first_monday_of_month`, `first_business_day_of_month`, `first_of_month`, etc.); `holiday_shift` parameterizes date-shift logic; `statute_reference` for operator-readable provenance.
  - `state_rule_family` at config root — reserved for future per-state defaults.
  - `sources.<id>.translator` — name of a registered translator (enum). Replaces hardcoded source dispatch.
  - `sources.<id>.translator_config` — per-translator config (layer maps, field maps, etc.).
  - `sources.<id>.field_map` — raw-field-name → canonical-field-name mapping. Replaces in-code source-specific field literals.
  - `sources.<id>.parcel_id_prefix` — county-mnemonic prefix for synthetic parcel IDs. Replaces hardcoded prefixes.
  - `sources.<id>.doc_type_synonyms` — per-source doc-type label → canonical-type mapping. Replaces in-code synonym tables.
- **canonical_doc_types.json additions:** 71 → 74 types.
  - `ESTATE_OWNER_NAME_PATTERN` (lead_pattern: estate, default_confidence: 75). Promotes owner-name-pattern signal class from synthetic-only to canonical.
  - `LIVING_TRUST_OWNER_NAME_PATTERN` (lead_pattern: transfer, default_confidence: 70).
  - `SHERIFF_SALE_SURPLUS` (lead_pattern: surplus_owed, default_confidence: 80). Promotes from synthetic-only to canonical.
- **New framework modules** (county-agnostic; verified by upgraded regression test):
  - `scaffold/pipeline/__init__.py` — package contract.
  - `scaffold/pipeline/translators/__init__.py` — translator registry. `register(name, force=False)`, `lookup(name)`, `registered_names()`, `unregister(name)`, `clear()`. Raises `TranslatorAlreadyRegistered` on duplicate, `TranslatorNotFound` on missing.
  - `scaffold/pipeline/translators/arcgis_foreclosure_notices.py` — built-in. Reads `translator_config.layer_doc_type_map`, honors `geography.accepted_municipalities`, `geography.cross_county_policy`, `geography.sale_date_rule`, `sources.<id>.parcel_id_prefix`.
  - `scaffold/pipeline/translators/arcgis_parcel_master.py` — built-in. Reads `sources.<id>.field_map` and `translator_config.exemption_codes`. Returns parcels (no signals — parcel_master is enrichment).
  - `scaffold/pipeline/translators/csv_static_list.py` — built-in. Per-source `doc_type_synonyms` for label → canonical mapping. Skips records with unmapped doc-types (never guesses).
  - `scaffold/pipeline/sale_date_rules.py` — built-in rule registry (`first_tuesday_of_month`, `first_monday_of_month`, `first_business_day_of_month`, `first_of_month`) with configurable holiday_shift. County rules are NAMED, not encoded.
  - `scaffold/pipeline/owner_name_patterns.py` — universal regex emitter. **Defensive guard**: `emit_owner_name_signals_for_parcel()` requires `parcels_with_lead_signals: set[str]` and refuses to emit for parcels not in that set. Closes audit Q9 fragility — standalone enrichment-only parcels cannot create lead rows.
- **scaffold/data/synthetic_attribute_overrides.json** — placeholder isolating synthetic-fixture-only attribute overrides per §4.31.7. Production runs MUST NOT read this file.
- **Upgraded `scaffold/tests/test_county_agnostic_regression.py`:** Now scans 15+ phrase patterns including vendor names (BCAD, HCAD, MCAD, etc.), portal hostnames (publicsearch.us, tylertech.cloud, etc.), state statute references (Tex. Prop. Code, Cal. Civ. Code, etc.). Exempts `data/`, `.claude/`, `dashboard/`, `scrapers/`, `scaffold/tests/fixtures/`, `scaffold/data/`, `sale_date_rules.py`, `MASTER_PROMPT.md`, `MIGRATION.md`, `LICENSE.md`, `START_HERE.md`, `README.md`, `bootstrap_county.py`, vendor portal library. PASSES on framework.
- **New `scaffold/tests/test_translator_registry.py`:** 26 tests covering builtin registration, lookup, force-override semantics, duplicate-refusal, cross-county-leak policy (drop/flag), sale_date_rule dispatch, parcel_master field_map parsing, csv_static_list per-source doc_type_synonyms, unknown-doc-type skip behavior.
- **`scaffold/tests/run_all.py`** wired in the translator registry test (4 tests in gate suite now).
- **`README.md`** autonomy-boundaries section updated with the universality contract as the third boundary.
- **`scaffold/bootstrap_county.py`** FRAMEWORK_VERSION stamp bumped to `v5.1.2-beta`.
- **`FRAMEWORK_VERSION.json`** bumped to `v5.1.2-beta`, `locked_at: 2026-05-14`.

**This is NOT a breaking schema change for existing configs.** A v5.1.1-beta county config validates against the v5.1.2-beta schema without modification — all new fields are optional. v5.1.1-beta counties continue to work; they just don't gain the universality-contract benefits until they migrate sources to use the translator field and pull municipality lists out of in-code constants.

**v5.1.2-beta universal pipeline runtime modules are NOT in canonical yet.** The framework's `normalize.py`, `stack.py`, `score.py`, `classify.py`, `evidence.py`, `review.py`, `dashboard.py`, `manifest.py`, `matcher.py`, and `build_leads.py` still live as contaminated code inside the Bexar repo from the v5.1.1-beta-seeded build. v5.1.2-beta provides the architectural scaffolding (schema + contract + registry + sale_date_rules + owner_name_patterns + regression) plus a Bexar in-place migration playbook (`docs/v5.1.2-beta_bexar_migration_playbook.md`). The Bexar repo refactors its pipeline in-place against the new framework primitives, regression-tests against current Bexar output (287 leads, parcel_master coverage 79%), and the cleaned pipeline modules are then promoted back to canonical as **v5.1.2-beta-final**. Until then, the canonical framework runs the synthetic harness only.

**v5.1.1-beta features preserved:** execution reliability, `write_county_config.py`, atomic config writer, Phase 0 + Phase 0.5 rules, Build Mode Approval Gate, Source Verification Gate, No False Dashboard rule, Evidence First Dashboard contract, Manual Assisted Pull Mode, operator override audit, vendor portal library, all tests already passing (golden path, county-agnostic regression, atomic config writer 18/18).

**v5.1.0-beta features preserved:** Phase 0.5 Auto-Resolve Blockers, Build Mode Approval Gate, Partial Build Contract, Evidence-First Dashboard Row Contract, Lead lifecycle and suppression, Source freshness contract, Source kill switch and quarantine, production self-verification stubs, Manual Assisted Pull Mode, Vendor portal library, Cost guardrails, VIP-friendly failure messages, v5.2.0 deferred catalog.

---

**v5.1.1-beta changes from v5.1.0-beta** (execution reliability patch — no schema changes, no breaking changes):

- Added MASTER_PROMPT.md Section 4.28 (Execution Reliability — county config write strategy). Locks in six rules: writer module is the only legitimate path for populated county configs; never stream large JSON via Write tool; schema validation is optional and graceful; structured repair is exactly one attempt; atomic move semantics; overwrite is explicit.
- Added MASTER_PROMPT.md Section 4.29 (Phase Label Enforcement). Locks in exact phase-boundary phrases Claude Code must emit: `PHASE 0 STARTING`, `PHASE 0 STEP 1 — INSPECT`, `PHASE 0 STEP 2 — RECON`, `PHASE 0 STEP 3 — VERIFICATION GATE`, `PHASE 0 COMPLETE`, `PHASE 0.5 STARTING — AUTO-RESOLVE BLOCKERS` (or `PHASE 0.5 SKIPPED — NO BLOCKERS`), `PHASE 0.5 COMPLETE`, `PHASE 0 STEP 4 — WRITE CONFIG, VERDICT, MANIFEST`, `BUILD MODE APPROVAL GATE`. Phase 0.5 is a labeled boundary, never inline with Step 3.
- Added MASTER_PROMPT.md Section 4.30 (Operator Knowledge Capture). Two channels with clean separation: `operator_override_audit` for schema-level overrides that change framework behavior; `runs/<county_slug>/operator_notes.md` for casual contextual knowledge. No schema change. Claude Code MUST capture operator-volunteered knowledge to the appropriate channel, never treat it as conversational chat.
- Patched MASTER_PROMPT.md Section 4.5 (Autonomous First-Run Rule) Step 5–8 to reference the new writer module, the phase labels, and the operator notes file.
- Patched MASTER_PROMPT.md Section 6 Phase 0 Step 3–4 to mandate the writer module and clarify the graceful schema-validation path.
- New file: `scaffold/ops/write_county_config.py` — the atomic county config writer. Builds dict → json.dump to temp file → JSON syntax validation → optional schema validation (graceful skip if jsonschema missing) → atomic move. Returns a structured `WriteResult` with status, schema_validation, bytes_written, top_level_key_count, source_names, build_verdict, operator_override_count, errors, notes.
- New file: `scaffold/tests/test_write_county_config.py` — gate test for the writer. 18 assertions across happy path, overwrite guard, non-dict input rejection, missing-schema graceful skip, jsonschema validation branch, and structural impossibility of duplicate keys.
- Updated `scaffold/tests/run_all.py` to include the new writer test in the gate suite.
- Updated `scaffold/bootstrap_county.py`:
  - Framework version stamp bumped to `v5.1.1-beta`
  - Now creates `runs/<slug>/operator_notes.md` template when bootstrapping
  - Launch file template now embeds the v5.1.1-beta writer rule, phase label enforcement, and operator knowledge capture sections
- Updated `START_HERE.md` with an autonomy-boundaries section explaining what "autonomous" means in v5.1.1-beta: one sentence, one approval, but Claude Code may stop on `CONFIG_WRITE_FAILED` and `jsonschema` is not auto-installed.
- Updated `README.md` with a parallel autonomy-boundaries section in the Quick Start.
- Bumped `FRAMEWORK_VERSION.json` to `v5.1.1-beta`, `locked_at` to `2026-05-14`.

**This is NOT a schema change.** `_schema.json` and `_template.json` are unchanged. A v5.1.0-beta county config validates against the v5.1.1-beta schema without modification. Re-running Phase 0 on a v5.1.0-beta county now uses the atomic writer; the old config is preserved unless `overwrite=True` is passed explicitly.

**v5.1.0-beta features preserved:** Phase 0.5 Auto-Resolve Blockers, Build Mode Approval Gate, Partial Build Contract, Evidence-First Dashboard Row Contract, Lead lifecycle and suppression, Source freshness contract, Source kill switch and quarantine, production self-verification stubs, `operator_override_audit`, Manual Assisted Pull Mode, Vendor portal library, Cost guardrails, VIP-friendly failure messages, v5.2.0 deferred catalog.

**v5.0.0 changes from v4.1.0** (breaking schema change — v4.x configs need Phase 0 re-recon):

- Added five-layer Source Verification Gate to MASTER_PROMPT.md (Sections 4.6–4.13)
- Added 26 new source-level proof packet fields to `config/counties/_schema.json`
- Added 3 new top-level fields: `build_verdict`, `build_verdict_reason`, `build_verdict_at`
- Added 7 new enum types: `access_method` (17 values), `public_access_status` (12 values), `document_access_status` (7 values), `source_role` (6 values), `verification_confidence` (5 values), `verification_method` (8 values), `next_access_strategy` (15 values). Plus widened `official_status` to a 5-way `OFFICIAL_*` split.
- Added Build Eligibility Gate semantics — Phase 0 produces a build verdict
- Added Do Not Proceed Matrix — 11 conditions that halt Phase 0
- Added No False Dashboard rule — dashboard rows must come from lead events
- Added Source Hierarchy — Tier 1 primary lead / Tier 2 supporting / Tier 3 enrichment
- Added Recon Mode vs Build Mode distinction
- Added VIP-friendly verdict message format
- Added Operator-readable lead names rule
- Updated `scaffold/bootstrap_county.py` launch file template to reference v5.0.0 gates (bootstrap script logic unchanged)
- Bumped `FRAMEWORK_VERSION.json` to `v5.0.0`

**This is a breaking schema change.** A v4.x county config does not validate against the v5.0.0 schema until the proof packet fields are populated. Empty defaults in `_template.json` are accepted during recon; Phase 0 populates them through the verification gate.

**v4.1.0 features preserved:** the one-sentence install flow, `scaffold/bootstrap_county.py`, `START_HERE.md`, autonomous first-run rule (MASTER_PROMPT Section 4.5), and the `runs/<slug>/` directory convention.

- Patch (4.1.1) for clarifications, doc fixes
- Minor (4.2.0) for new patterns, sources, deal paths, architecture additions
- Major (5.0.0) for breaking changes that require migration of existing county builds

Each county's `BUILD_SUMMARY.md` records which framework version it was built against.

---

## Files in this framework

**Beginner entry point (v4.1.0+):**
- `START_HERE.md` — first-time-user walkthrough. Read this before anything else on your first run.

**Master entry point:**
- `MASTER_PROMPT.md` — the framework contract Claude Code reads on every build. Section 4.5 documents the autonomous first-run rule.

**Domain knowledge base** (the *what*):
- `knowledge_base/domain/00_client_business_model.md`
- `knowledge_base/domain/01_lead_types.md`
- `knowledge_base/domain/02_signals_and_sources.md`
- `knowledge_base/domain/03_scoring_and_stacking.md`
- `knowledge_base/domain/04_deal_path_classifier.md`
- `knowledge_base/domain/05_review_queue_rules.md`
- `knowledge_base/domain/06_hallucination_controls.md`
- `knowledge_base/domain/07_fallback_metrics.md`

**Architecture knowledge base** (the *contracts*):
- `knowledge_base/architecture/08_evidence_ledger.md`
- `knowledge_base/architecture/09_output_schemas.md`
- `knowledge_base/architecture/10_source_heartbeat_and_cursors.md`
- `knowledge_base/architecture/11_database_and_storage.md`
- `knowledge_base/architecture/12_entity_resolution.md`

**Engineering knowledge base** (the *how*):
- `knowledge_base/engineering/00_tooling_decision_tree.md`
- `knowledge_base/engineering/01_python_environment.md`
- `knowledge_base/engineering/02_scraping_libraries.md`
- `knowledge_base/engineering/03_document_readers.md`
- `knowledge_base/engineering/04_blocked_source_strategies.md`
- `knowledge_base/engineering/05_verification_and_rollback.md`
- `knowledge_base/engineering/06_deployment.md`

**Config:**
- `config/counties/_schema.md` — schema reference (human-readable)
- `config/counties/_schema.json` — JSON Schema (validates configs)
- `config/counties/_template.json` — empty config to copy for new counties

**Bootstrap and tests (scaffold):**
- `scaffold/bootstrap_county.py` — v4.1.0+ bounded bootstrap script. Creates `runs/<slug>/` and the launch file. Claude Code is authorized to run this automatically on first contact per `MASTER_PROMPT.md` Section 4.5.
- `scaffold/tests/run_all.py` — runs both gate tests
- `scaffold/tests/test_golden_path.py` — happy-path build gate
- `scaffold/tests/test_county_agnostic_regression.py` — enforces no hardcoded county names outside config/counties/ and LICENSE.md

**Synthetic test harness:**
- `scaffold/data/synthetic_parcels.jsonl` — 12 parcels covering every scenario
- `scaffold/data/synthetic_signals.jsonl` — 24 signals across all 11 patterns
- `scaffold/data/synthetic_expectations.json` — what the build should produce
- `scaffold/data/README.md` — how the harness works

**Per-county artifacts (v4.1.0+ convention):**

The framework distinguishes two locations for county-specific files:

- **Canonical config:** `config/counties/<county_slug>.json` — the single source-of-truth source map for the county. Produced by Phase 0 recon. Validated against `_schema.json`. Committed to the repo.

- **Run artifacts:** `runs/<county_slug>/` — county-specific launch files, run manifests, temporary logs, ad-hoc operator notes, and anything else that's county-specific but NOT part of the canonical config. The bootstrap script creates this folder. Phase manifests and operator notes accumulate here over time.

Examples of what goes where:

| File | Location |
|---|---|
| The verified source map | `config/counties/bexar_tx.json` |
| Phase 0 launch instructions | `runs/bexar_tx/LAUNCH_BEXAR_TX.md` |
| Phase 0 change manifest | `runs/bexar_tx/PHASE0_MANIFEST.md` |
| Notes from a recon session | `runs/bexar_tx/notes.md` |
| Build-specific logs (not committed) | `runs/bexar_tx/logs/` (add to `.gitignore`) |

**Why the separation:** the canonical config is what every later phase reads from. It must stay clean and validate-able. Run-folder content is operator scratchpad — useful, county-specific, but never part of the framework's data contract.

**This file:**
- `MIGRATION.md` — operator-facing instructions

