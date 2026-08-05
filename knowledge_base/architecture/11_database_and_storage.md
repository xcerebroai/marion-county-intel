# 11 — Database and Storage

The framework supports three storage modes:

```
STATIC_JSON_MODE
SUPABASE_MODE
HYBRID_MODE
```

GitHub Pages remains the dashboard host in all three modes. The repo stays private. Access is revocable by disabling Pages, removing client access, rotating the repo, or replacing the data payload.

---

## STATIC_JSON_MODE

Use this for first-pass deployments, lower-volume counties, demos, and any build where the dashboard reads its data from a single JSON file.

**GitHub stores:**
- Dashboard files (`index.html`, `methodology.html`, CSS, JS)
- `data/leads.json` — the dashboard's primary input
- `data/quality_metrics.json` — per-build metric snapshot
- `data/source_heartbeat.json` — heartbeat per source
- `data/source_cursors.json` — cursor per source
- Committed build summaries (`BUILD_SUMMARY.md`, `BUILD_BROKEN.md`)
- Committed verification artifacts (`LIVE_VERIFIED.txt`)

**Gitignored:**
- Raw scraper outputs (`data/raw/`)
- records-request-delivered files (except templates)
- Logs

**Pros:** No external dependencies. Fast. Cheap. The dashboard is just a static site reading JSON. Auto-rollback is `git revert`.

**Cons:** Doesn't scale beyond ~10K leads per county (JSON file gets big, browser load gets slow). No server-side filtering. No multi-user review workflow without extra plumbing.

---

## SUPABASE_MODE

Use this when:
- Lead volume per county exceeds ~10K
- Multiple users need to interact with the data (operator + clients viewing different slices)
- You want server-side filtering, search, and review workflow
- You want longer history than git-committed JSON snapshots provide
- You want richer evidence tracking and audit history

**Required tables:**

```
sources                  -- one row per configured source per county
source_runs              -- append-only run log
source_heartbeat         -- current heartbeat per source
source_cursors           -- current cursor per source
raw_records              -- raw scraper output
normalized_signals       -- parsed signals
parcels                  -- parcel master data
entities                 -- resolved owner entities
entity_aliases           -- alternate names for entities
matched_leads            -- the join output
evidence                 -- the evidence ledger
review_queue             -- records held for review
exports                  -- export job history
dashboard_snapshots      -- materialized dashboard views
audit_log                -- mutation history
```

**Every table needs:**
- `id` (UUID primary key)
- `created_at`
- `updated_at`
- `source_id` (where applicable)
- `run_id` (where applicable)
- `status` (where applicable)

**Every lead row needs:**
- `lead_id`
- `parcel_id`
- `entity_id`
- `score`
- `deal_paths`
- `match_confidence`
- `parser_confidence`
- `export_status`
- `evidence_summary`

**Pros:** Scales. Server-side filtering. Real-time updates. Multi-user workflows.

**Cons:** Adds an external dependency. Adds RLS policy work. Adds key management.

---

## HYBRID_MODE

Use this when the dashboard stays on GitHub Pages but data lives in Supabase.

**GitHub stores:**
- Dashboard shell (`index.html`, JS, CSS)
- Static assets (icons, branding)
- Deployment history
- Verification artifacts

**Supabase stores:**
- Records (raw, signals, parcels, leads)
- Evidence
- Review queue
- Heartbeat and cursors
- Audit history

The dashboard either:
1. Fetches Supabase directly using the anon key with RLS policies that filter to the appropriate dataset, OR
2. Loads a `leads.json` snapshot generated nightly from Supabase and committed to the repo

Option 2 is the simpler migration path from STATIC_JSON_MODE — the dashboard doesn't change, but the data origin does.

---

## Mode selection

The county config declares which mode applies:

```json
{
  "storage": {
    "mode": "STATIC_JSON_MODE",
    "supabase_enabled": false,
    "dashboard_payload": "data/leads.json",
    "retain_raw_records_days": -1,
    "retain_source_runs_days": 365
  }
}
```

`retain_raw_records_days: -1` means raw records are **never deleted**. This is the framework default per the raw-data-preservation rule below. Operators may set a positive integer only with explicit justification (storage cost limits, GDPR-style request) and the change is logged to the audit trail.

---

## Raw data preservation rule

Raw scraped records are immutable and append-only. The framework guarantees:

1. **Every scrape writes a new raw record.** Re-scraping the same source URL on a different day produces a new `raw_record_id`, never an in-place update.
2. **Raw records are never overwritten.** Field corrections, parser fixes, and downstream normalization changes flow into derived records (signals, leads), never into the raw record.
3. **Raw records are never deleted by default.** The `retain_raw_records_days: -1` default keeps them permanently. Any non-default retention setting is logged to the audit trail with operator name and reason.
4. **Raw payload contents are preserved verbatim.** `raw_payload` and `raw_text` capture exactly what the source returned. The framework does not normalize, clean, or "fix" raw fields before storing.
5. **Source URLs in raw records are recorded as-fetched.** If a source URL changes shape over time, the historical raw record still carries the URL that was used at fetch time.
6. **Raw records survive entity merges.** Merging two parcels or two owner entities does NOT delete or alter the raw records that fed them. Both raw records remain attached to the merged entity.
7. **Audit trail captures every read and every export of raw records** in SUPABASE_MODE and HYBRID_MODE. STATIC_JSON_MODE captures access via git history of the data files.

This rule exists because the framework's evidence ledger (`architecture/08_evidence_ledger.md`) is only as strong as its source-of-truth backing. If raw records can be modified or lost, every claim in the framework loses its foundation.

Allowed `mode` values:
- `STATIC_JSON_MODE`
- `SUPABASE_MODE`
- `HYBRID_MODE`

`dashboard_payload` is the path the dashboard fetches. In static and hybrid mode this is `data/leads.json`. In Supabase mode it can be a Supabase REST URL.

**Mode migration is not a config change.** Switching from STATIC to SUPABASE means rebuilding the dashboard's data layer (fetch calls, auth, pagination, filtering). The mode flag tells the framework which pipeline to run; it does not magically transform the dashboard.

---

## Secrets management

Do not commit secrets. Use `.env` for:

```
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
TWOCAPTCHA_API_KEY=
ANTICAPTCHA_API_KEY=
PROXY_USERNAME=
PROXY_PASSWORD=
PROXY_ENDPOINT=
CLERK_SESSION_COOKIES=
CLERK_SESSION_TOKEN=
CLERK_SESSION_SEEDED_AT=
```

**Service role key boundary:** The Supabase service role key bypasses RLS and has full database access. It belongs only on the operator's build server / refresh-task host. **It never goes anywhere a client touches.** Client-facing dashboards use the anon key with RLS policies that restrict the client to their own slice of data.

The anon key is safe to ship to a browser. The service role key is not. The framework's `.env.example` template marks them differently for this reason.

---

## Audit rule

Every export, merge, review-queue decision, source-cursor change, and dashboard publish creates an audit log entry. In static mode this is a JSONL append. In Supabase mode it's an `audit_log` table row.

Audit log fields:
- `audit_id`
- `actor` (system / operator / scheduled-task / watchdog)
- `action` (export / merge / review_decision / cursor_advance / publish)
- `target_id` (lead_id, review_id, source_id, etc.)
- `before_state` (snapshot of relevant fields)
- `after_state`
- `created_at`

The audit log is what lets the operator answer "why did this lead change?" three weeks later.

---

## GitHub Pages access control

The repo stays private throughout. GitHub Pages serves the dashboard from a private repo with proper access control.

### Dashboard access modes

The dashboard renders one of five modes based on the client's status. The mode is read from the client access control config (below) at every page load.

| Mode | What renders | Use case |
|---|---|---|
| `FULL_ACCESS` | All leads, all fields, all features, no banners | Operator's own view; primary client during paid period |
| `CLIENT_VIEW` | All leads but with operator-internal fields hidden (run IDs, parser confidence, evidence ledger drawer collapsed) | Paying client default view |
| `DEMO_VIEW` | Sample subset of leads (capped at 10), watermarked, no CSV export, no detail drawer | Sales demos to prospects |
| `PAUSED_FOR_NONPAYMENT` | Dashboard loads; lead count tile shows actual count; row detail is replaced with `"Payment required to unlock current lead details"`; CSV export disabled; banner explains how to restore access | Client behind on payment but not yet terminated |
| `REDACTED_VIEW` | Dashboard loads; counts and aggregates visible; owner names, addresses, and any contact-relevant fields show as `[redacted]`; CSV export disabled | Legal hold, dispute, or operator decision to limit visibility temporarily |

**Rule:** never delete the dashboard to revoke access. Set the mode. The dashboard URL stays the same; the content visible at it changes.

### Client access control config

Every county's deployment includes a `config/client_access.json` file declaring who has access and at what level. Sample:

```json
{
  "client_id": "<client_id>",
  "client_name": "<client name>",
  "client_status": "ACTIVE",
  "dashboard_access": "FULL_ACCESS",
  "repo_access": "PRIVATE",
  "github_pages_status": "ENABLED",
  "supabase_row_level_security": true,
  "last_payment_verified_at": "<ISO 8601 timestamp>",
  "access_notes": "free-form internal notes"
}
```

**Field meanings:**

- `client_id` — internal identifier for the client (matches CRM if integrated)
- `client_status` — one of `ACTIVE`, `TRIAL`, `PAUSED`, `TERMINATED`, `INTERNAL`
- `dashboard_access` — one of the five modes above
- `repo_access` — `PRIVATE` (default), `RESTRICTED` (specific GitHub user list), `PUBLIC` (rare; used only for demo deployments)
- `github_pages_status` — `ENABLED`, `DISABLED`
- `supabase_row_level_security` — only relevant in SUPABASE_MODE or HYBRID_MODE; when true, the client's view enforces RLS to limit which rows the client can see
- `last_payment_verified_at` — set by operator after confirming payment; used by automation to flip status if too stale
- `access_notes` — internal-only commentary

### Revocation paths

When a client stops paying or otherwise needs to lose access, change `dashboard_access` and (optionally) `client_status`. The dashboard reads the change on next page load. Specific paths:

1. **Move to `PAUSED_FOR_NONPAYMENT`** — dashboard still loads, lead details locked behind a payment-required banner. Client can see they have leads waiting; this is gentler than a 404 and tends to recover faster.
2. **Move to `REDACTED_VIEW`** — for legal-hold or dispute scenarios; counts visible, PII redacted.
3. **Move to `DEMO_VIEW`** — for downgrades to a non-paying viewer.
4. **Set `github_pages_status = DISABLED`** — turn Pages off entirely (404). Use only as last resort or for terminated clients.
5. **Remove client's read access to the repo** — if client was a collaborator on the private repo, revoke. (Pages access does not require repo membership, but a collaborator can read the JSON directly.)
6. **Rotate the repo URL** — for severe cases (intellectual property concerns); requires client to update their bookmark.

The framework's hosting model assumes paid client access. The revocation paths above are part of the product, not a manual afterthought. Every state transition is logged to the audit trail.

---

## Dashboard data contract

The dashboard is a **read-only projection** of the approved schema (per `architecture/09_output_schemas.md` §6 Dashboard record). It is not an inference layer.

**Rules:**

- **The dashboard may only display fields from the approved dashboard schema.** If a field exists in `architecture/09_output_schemas.md` §6, the dashboard may render it. If a field does not exist in that schema, the dashboard may not invent it.
- **If an approved field is missing or null, display `Unknown`.** The dashboard does not fall back to "Not available," "N/A," empty string, dash, or its own substitute label. The single string `Unknown` is the contract.
- **The dashboard may not infer, guess, enrich, rename, transform, or derive new fields inside the dashboard layer.** All inference happens upstream in normalization (`domain/08_document_normalization.md`), entity resolution (`architecture/12_entity_resolution.md`), or scoring (`domain/03_scoring_and_stacking.md`).
- **The dashboard may not re-fetch source data.** It reads the projected output once at page load and renders it. If the data is stale, the refresh pipeline upstream is the layer responsible, not the dashboard.
- **The dashboard may not compute scores, fire patterns, set lifecycle stages, or write evidence.** It displays what the pipeline produced.
- **Display-only transformations are allowed**: number formatting (`$340,000`), date formatting (`May 7, 2026`), capitalization of canonical type labels for readability (`AFFIDAVIT_OF_HEIRSHIP` → `Affidavit of Heirship`), and unit conversions for display. These are presentation, not inference. Anything that changes the *meaning* of a field is forbidden in the dashboard layer.
- **Access mode controls visibility, not content.** A `REDACTED_VIEW` shows `[redacted]` for PII fields but does not invent the redaction logic — the dashboard reads `access_mode` from `config/client_access.json` and applies the visibility rules in this section's table. The pipeline output is unchanged.

**The contract in one line:** the dashboard renders what the schema specifies, says `Unknown` when a field is missing, and never invents what isn't there. Front-end hallucination is a bug, not a feature.

---

## CRM export contract

CRM export (`architecture/09_output_schemas.md` §7 CRM export record) is a **downstream-only** transformation. It reads approved lead and dashboard fields and writes them in the format the target CRM (GoHighLevel, Just Jarvis, HubSpot, etc.) expects.

**Rules:**

- **CRM export may not alter source records, raw payloads, normalized signals, or evidence objects.** Those upstream artifacts are immutable per `domain/06_hallucination_controls.md` and `architecture/08_evidence_ledger.md`.
- **CRM export may not alter lead scores, score reasons, pattern firings, attribute lists, or deal-path classifications.** Scoring is upstream. Export carries the values forward; it does not recompute them.
- **CRM export may not alter entity resolution, parcel matches, or owner-entity links.** Resolution is upstream.
- **CRM export may not alter review status or `lead_status`.** A lead in `REVIEW_REQUIRED` does not become `APPROVED_FOR_DASHBOARD` by virtue of being exported — those status transitions only happen in the review queue or operator action layer.
- **CRM export may only transform approved dashboard or lead fields into the target CRM column format.** Allowed transformations: rename columns to match CRM's expected names (`primary_parcel_id` → `Property ID`), concatenate display strings (`situs_address + ", " + situs_city` → `Address`), serialize array fields as comma-joined strings, format dates and numbers per CRM convention, drop fields the CRM doesn't accept.
- **When the export writes a record to the CRM, it logs the transition.** The lead's `lead_status_history` gets a new `EXPORTED_TO_CRM` entry with timestamp and CRM-side record ID where available. This is the only state mutation the export layer is allowed to make, and it is mutation of the lead's audit trail, not of the lead's substantive fields.

**The contract in one line:** the CRM export is a translator, not an editor. It carries upstream truth into the CRM's vocabulary without rewriting it.

---

## Secrets handling

The framework uses seeded sessions, operator-credentialed logins, CAPTCHA solver API keys, residential proxy credentials, Telegram bot tokens, and Supabase service-role keys. None of these may live in code or in any repo-committed artifact.

**Rules:**

- **No secrets in code.** No hardcoded API keys, tokens, cookies, passwords, or service-role keys anywhere in `.py`, `.js`, `.ts`, `.html`, or any other source file.
- **No secrets in GitHub Pages output.** The `index.html` and any JSON the dashboard reads must contain zero credentials. Pages content is publicly fetchable by anyone with the URL.
- **No secrets in dashboard files.** `data/leads.json`, `data/source_heartbeat.json`, and any other dashboard-served file must be free of cookies, tokens, proxy URLs containing auth strings, or session identifiers.
- **No secrets in committed JSON.** `config/counties/<county>.json`, `config/client_access.json`, and any other config file in the repo must reference secrets by environment variable name only (e.g. `"session_seed_env_var": "CLERK_SESSION_COOKIES"`), never by value.
- **No cookies committed to repo.** Seeded session cookies live in `.env` locally and in GitHub Secrets / hosted-runtime environment variables in production. The `.env` file is in `.gitignore`. Cookies never appear in commit history.
- **No proxy credentials committed to repo.** Residential proxy username/password and proxy endpoint URLs containing auth live in `.env` and secret stores only.
- **No CAPTCHA solver keys committed to repo.** 2Captcha, Anti-Captcha, or equivalent service API keys live in `.env` and secret stores only.
- **No Supabase service-role key committed to repo.** Service-role keys grant full database access and must never appear in the repo. The dashboard, if it reads Supabase, uses the anon key (read-only on the leads table) configured via Pages-build environment variables — never the service-role key.

**Operational pattern:**

- **Local development:** secrets live in `.env` at project root. `.env` is in `.gitignore`. The Python pipeline reads via `os.environ`.
- **GitHub Actions:** secrets live in repo Settings → Secrets and variables → Actions. Workflow YAML references `${{ secrets.NAME }}`.
- **Hosted services (Railway, Render, Supabase, etc.):** secrets live in the host's environment variable UI.
- **Secret rotation:** when a session expires, an operator re-seeds and updates `.env` and the GitHub Secret. The repo never sees the value.

This is engineering safety, not a compliance workflow. The rules above prevent the most common ways a credentials leak happens to a small operator team.

