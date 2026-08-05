# 10 — Source Heartbeat and Cursors

Every source needs a heartbeat. Every source with pagination, dates, record IDs, document IDs, pages, or sessions needs a cursor.

This file specs both. Without them, the framework can re-scrape the same records (waste, source rate-limit risk), miss new records (silent freshness failure), or stop refreshing without alerting (the dashboard goes stale and nobody notices).

---

## Why this exists

A scraper without a cursor and heartbeat can:
- Scrape the same records on every run (wasted bandwidth, source-side rate-limit triggers)
- Miss new records that posted late
- Silently stop refreshing when a session expires or layout changes
- Fail without alerting
- Lose track of session health
- Over-count leads when the dedupe step hides the duplication
- Under-count source regressions because you can't compare run-over-run without a baseline

Heartbeat fixes the visibility problem. Cursors fix the freshness problem.

---

## Heartbeat schema

One heartbeat record per source, updated on every run (success or failure).

```json
{
  "source_id": "clerk_recordings",
  "source_name": "County Clerk Recorded Instruments",
  "source_class": "lead_generating",
  "source_priority": "P0",
  "source_reliability_grade": "A",
  "build_priority": "mvp_required",
  "access_pattern": "seeded_session",
  "status": "healthy",
  "last_attempted_at": "2026-05-07T15:00:00Z",
  "last_successful_at": "2026-05-07T15:04:00Z",
  "last_failed_at": null,
  "last_failure": {
    "classification": null,
    "message": null,
    "timestamp": null
  },
  "records_seen_current_run": 0,
  "records_new_current_run": 0,
  "records_seen_previous_run": 0,
  "records_new_previous_run": 0,
  "parser_confidence_avg": 0,
  "error_count_current_run": 0,
  "consecutive_failures": 0,
  "session_status": "valid",
  "session_expires_at": null,
  "next_retry_at": null,
  "next_scheduled_run_at": "2026-05-08T06:00:00Z",

  "access_attempts": [
    {
      "attempt_order": 1,
      "strategy": "HIDDEN_API_DISCOVERY",
      "status": "FAILED",
      "reason": "No stable JSON endpoint found in DevTools Network tab",
      "timestamp": "2026-05-07T14:00:00Z"
    },
    {
      "attempt_order": 2,
      "strategy": "PLAYWRIGHT_RENDERED_EXTRACTION",
      "status": "FAILED",
      "reason": "reCAPTCHA v3 server-enforced, headless browser score insufficient",
      "timestamp": "2026-05-07T14:15:00Z"
    },
    {
      "attempt_order": 3,
      "strategy": "OPERATOR_SEEDED_SESSION",
      "status": "SUCCESS",
      "reason": "Manual browser session seeded by operator, replay confirmed",
      "timestamp": "2026-05-07T14:30:00Z"
    }
  ],
  "final_access_strategy": "OPERATOR_SEEDED_SESSION",
  "records_request_allowed": false
}
```

**Field meanings:**
- `status` — one of `healthy`, `degraded`, `blocked`, `session_expired`, `layout_changed`, `empty_return`, `manual_action_required`, `disabled`
- `source_priority` — one of `P0` (daily-refresh distress), `P1` (weekly-refresh distress), `P2` (enrichment); per `domain/02_signals_and_sources.md` Source priority tiers section
- `access_pattern` — matches the value from `config/counties/<county>.json` source entry
- `consecutive_failures` — increments on each failed run, resets on success
- `last_failure.classification` — controlled enum: `NO_RESULTS`, `PARSER_CHANGED`, `CAPTCHA_REQUIRED`, `SESSION_EXPIRED`, `WAF_BLOCKED`, `RATE_LIMITED`, `LOGIN_REQUIRED`, `SOURCE_DOWN`, `LAYOUT_CHANGED`, `TIMEOUT`, `UNKNOWN_ERROR`. See `architecture/09_output_schemas.md` Schema 11 "Source failure classification" for the full table. Free-form failure strings are rejected at validation.
- `session_status` — `valid`, `expiring_soon` (within 24h), `expired`, `not_applicable`
- `next_retry_at` — when the next retry will fire (after exponential backoff)
- `access_attempts` — append-only log of every access strategy tried during Phase 0 recon for this source. Each entry records strategy name, success/failure status, reason, and timestamp. The log is the audit trail that proves the framework attempted technical paths before escalating to records-request. Per `engineering/04_blocked_source_strategies.md` "Access strategy ordering."
- `final_access_strategy` — the strategy currently in production use. After Phase 0 recon, this is the one the framework uses on every run. Mirrors the value in `config/counties/<county>.json` for this source.
- `records_request_allowed` — boolean. True only when (a) `final_access_strategy` is `FINAL_LAST_RESORT_RECORDS_REQUEST` after exhausting technical paths, or (b) `final_access_strategy` is `SCHEDULED_RECORDS_REQUEST` because the source has no usable portal and bulk delivery is the configured primary channel. See `engineering/04_blocked_source_strategies.md` "Public-records request rule" for the two valid roles.

Stored at `data/source_heartbeat.json` (single file, all sources keyed by `source_id`).

---

## Cursor schema

One cursor record per source, updated on every successful run.

```json
{
  "source_id": "clerk_recordings",
  "cursor_type": "date_and_document_number",
  "cursor_value": {
    "last_event_date": "2026-05-07",
    "last_document_number": "DOC123456",
    "last_page": 12,
    "last_row_hash": "abc123"
  },
  "updated_at": "2026-05-07T15:04:00Z",
  "safe_rewind_value": {
    "last_event_date": "2026-05-01"
  }
}
```

`cursor_value` is the high-water mark — where the scraper finished last time. `safe_rewind_value` is where it should restart from on the next run, deliberately set behind the high-water mark to catch late-posted or corrected records.

Stored at `data/source_cursors.json`.

---

## Cursor types

The framework supports these cursor strategies. The right choice depends on how the source paginates and orders records.

| Cursor type | When to use |
|---|---|
| `date` | Source orders by date, you pull "since X" |
| `date_and_document_number` | Source orders by date but multiple docs per day; need document number to disambiguate |
| `case_number` | Court dockets that increment case numbers monotonically |
| `instrument_number` | Clerk recordings ordered by instrument number |
| `page_number` | Paginated UIs without a stable ordering field |
| `offset` | Numeric offset (ArcGIS REST `resultOffset`) |
| `file_hash` | Source publishes a single file (PDF, CSV) per period — track which files have been ingested by hash |
| `row_hash` | Bulk extract where you need to dedupe at row level |
| `manual_batch_id` | records-request fulfillment — operator drops file labeled with batch ID |
| `none` | Source has no notion of incremental — pull full snapshot every time (rare, expensive) |

---

## Safe rewind rule

Every scraper using a date-based or sequence-based cursor must use a rewind window. The cursor's `safe_rewind_value` should be set behind `cursor_value` by a margin that exceeds typical late-posting and correction lag.

Defaults:
- Clerk recordings: rewind 7 days
- Court dockets: rewind 14 days
- Sheriff sales: rewind 30 days (sales get adjourned/cancelled and re-listed)
- Tax delinquency: rewind 30 days (payments and corrections post late)

The pipeline dedupes at write time using `source_id + source_document_id`, so re-pulling old records is safe. Missing records is not.

---

## Source status values

The heartbeat's `status` field uses these values:

| Status | Meaning |
|---|---|
| `healthy` | Last run succeeded, parser confidence within range |
| `degraded` | Last run succeeded but with reduced confidence or partial data |
| `blocked` | Source unreachable (CAPTCHA hard-blocked, WAF-blocked) |
| `session_expired` | Seeded-session cookies are invalid; operator action required |
| `layout_changed` | Parser confidence dropped >10 points; source likely redesigned |
| `empty_return` | Source returned zero records when previous runs had records |
| `manual_action_required` | Operator must do something (re-seed, sign records request, etc.) |
| `disabled` | Source intentionally turned off in county config |
| `paused` | Source temporarily paused via kill switch; see "Source kill switch" below |

---

## Source kill switch

When a single source is producing bad data, broken parses, or upstream errors that would corrupt the lead pool if scraped further, the operator can pause that one source without taking down the whole pipeline.

The kill switch lives in `config/counties/<county>.json` per source. Fields:

| Field | Type | Meaning |
|---|---|---|
| `enabled` | boolean | `true` = source runs on schedule; `false` = source is skipped this run and every run until set back to `true`. Default `true`. |
| `paused_reason` | string | Human-readable reason for the pause. Required when `enabled: false`. Surfaces in the heartbeat and in operator alerts. |
| `pause_until` | string | ISO 8601 timestamp. When set, the framework auto-resumes the source at this time (sets `enabled: true` and clears `paused_reason`). Empty string means "paused until operator manually re-enables." |
| `allowed_to_export` | boolean | `true` = records previously scraped from this source remain visible in the dashboard and exportable to CRM; `false` = previously-scraped records are hidden from dashboard and excluded from export until `allowed_to_export` flips back to `true`. Default `true`. Use `false` only when data already in the pool is suspect, not just when new pulls should pause. |

**Behavior on pause:**

- The refresh harness skips the source entirely (no HTTP calls, no Playwright, no fixture parsing).
- The heartbeat `status` is set to `paused` and `last_attempted_at` is NOT advanced (so freshness alerts continue firing — paused sources should not look healthy).
- An operator alert fires once when the pause begins and once when `pause_until` is reached and the source auto-resumes.
- Existing records remain in the lead pool if `allowed_to_export: true`. They are removed from dashboard projection if `allowed_to_export: false`.

**Use the kill switch for:**

- Portal layout changed and parser now writes garbage — pause until parser is fixed.
- Source is delivering test data, sandbox data, or known-bad records that would corrupt scoring.
- Vendor change announced; pause while operator runs a fresh fingerprint pass.
- Legal hold or operator decision to suspend a single feed.

**Do not use the kill switch for:**

- Transient failures (use the existing failure-classification + retry logic in `engineering/04_blocked_source_strategies.md`).
- Source being slow (use rate-limit handling).
- Operator just wants to "try without it" (set `build_priority: optional` instead — the kill switch is for known-bad, not exploratory).

The kill switch is one-source granularity. The rest of the pipeline continues running. P0 sources that are paused do not satisfy the P0 gate for ongoing builds; if all P0 sources are paused simultaneously, the framework alerts and treats the build as functionally halted.

---

## Alert triggers

Send a Telegram alert when:
- Source fails all retries (5 attempts)
- Source has 3 consecutive failures across runs
- Source returns zero records when previous runs had records
- Parser confidence drops more than 10 points from previous run
- Record count drops more than 50% from previous run (run-over-run regression)
- Session expires within 24 hours
- Heartbeat is older than 36 hours
- Cursor cannot advance (high-water mark unchanged across 3 runs)
- Cursor jumps backward unexpectedly (data integrity issue)
- Source layout changes (parser confidence flag)

Alerts go to `@<your_telegram_bot>` per `engineering/06_deployment.md`. Alert format includes the county prefix and the source ID so the operator knows immediately which county and which source.

---

## Storage

**Static mode:**
- `data/source_heartbeat.json` — current heartbeat per source
- `data/source_cursors.json` — current cursor per source
- `data/source_runs.jsonl` — append-only run log

**Supabase mode:** Tables `source_heartbeat`, `source_cursors`, `source_runs` per `11_database_and_storage.md`.

---

## Recovery rules

If a source fails on a run:
1. Retry with exponential backoff (5 attempts: 1s, 2s, 4s, 8s, 16s)
2. Update heartbeat with `status` and `last_failure_reason`
3. **Preserve the previous cursor** — do not advance on failure
4. Mark source `degraded` after first failure, `blocked` after consecutive failures
5. Continue with other sources in the refresh pipeline (one source's failure does not halt others)
6. Alert operator per the trigger rules above
7. Do not fabricate records to mask the failure

The framework's behavior on partial-source-failure is: ship what we got, mark what we missed, alert. Never fake completeness.

---

## Cursor advancement rules

A cursor advances only when:
- The run completed successfully (no errors above the partial-success threshold)
- Records were validated against the schema
- Records were written to the appropriate JSONL file
- Heartbeat was updated

If any of those fail, the cursor stays at its previous value. The next run re-pulls from the same starting point.

This means it is impossible to "lose" a record because the cursor advanced past it. The cost is occasional re-fetching of records the framework has already seen, which is what the dedupe step at write time is designed to handle.
