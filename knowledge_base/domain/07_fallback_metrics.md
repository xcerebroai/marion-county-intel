# 07 — Fallback Metrics

Fallback metrics are the framework's quality gates. They run on every build. When any metric falls below threshold, the framework either downgrades affected records (medium failures) or halts the build (critical failures).

This is the file that prevents the operator's client from receiving a dashboard that looks fine but is fundamentally broken.

---

## The metrics

### 1. Source Verification Rate

**Formula:** `verified_sources / total_sources_attempted`

**Threshold:** 100% before production scraping

**Verified means:** scraper successfully fetched and parsed at least one record matching expected schema in the current refresh cycle.

**On failure:**
- Log the failed source(s) to `HEARTBEAT.json` with `last_failure` timestamp
- Retry with exponential backoff (5 attempts, 1s/2s/4s/8s/16s)
- After all retries fail: mark source as `Blocked`, do not generate leads from it
- If failed source was the only lead source: build does NOT halt (empty buckets are honest), but Telegram alert fires

---

### 2. Field Completeness Rate

**Formula:** `records_with_all_required_fields / total_records`

Required fields:
- `pid` (parcel ID)
- `situs_address`
- `mun_name`
- `pattern` or `attribute` (at least one signal)
- `source` (origin scraper name)
- `source_url`

**Threshold:** 85% for export-ready leads

**On failure:**
- Records missing required fields route to review queue
- Build does not halt
- If field-completeness drops > 10% from previous build, Telegram alert fires (parser may be broken)

---

### 3. Property Match Confidence

**Formula:** computed per record by matcher (see `05_review_queue_rules.md`)

**Threshold:** 80 for auto-export

**On failure:**
- Records below 80 confidence route to review queue
- Build does not halt
- If average match confidence drops > 10 points from previous build, Telegram alert fires

---

### 4. Parser Confidence

**Formula:** parser self-reports per record. Each scraper emits a `parser_confidence` field (0-100) based on how many expected fields it successfully extracted.

**Threshold:** 80% for export-ready leads

**On failure:**
- Records below threshold route to review queue with reason `parser_confidence_low`
- If aggregate parser confidence for a source drops > 10% from previous build, Telegram alert fires (source layout may have changed)

---

### 5. Source URL Coverage

**Formula:** `records_with_source_url / total_records`

**Threshold:** 95%

**On failure:**
- Records without source URL route to review queue
- This metric should rarely fail for properly-built scrapers; failure indicates a scraper bug

---

### 6. Dedupe Completion Rate

**Formula:** `records_after_dedupe / records_before_dedupe`

This is a sanity check that dedupe ran. The pipeline runs dedupe before write; if dedupe count equals raw count, dedupe didn't run.

**Threshold:** dedupe must run on every build (binary check)

**On failure:**
- Build halts (`BUILD_BROKEN.md`)
- This is a critical failure — exporting un-deduped data creates phantom leads

---

### 7. Unsupported Claim Count

**Formula:** count of fields with status label `Unsupported`

**Threshold:** 0 (zero tolerance)

**On failure:**
- Each unsupported field is re-labeled to `Unknown` or `Needs Review`
- The Guardian (see `06_hallucination_controls.md`) logs and re-labels automatically
- If 5+ unsupported claims appear in one build, Telegram alert fires

---

### 8. Review Queue Ratio

**Formula:** `review_queue_count / (review_queue_count + lead_total)`

**Healthy range:** 5–40%

**On failure (>50%):**
- Build does not halt
- Telegram alert fires: `Review queue at <pct>% — parser or matcher likely needs maintenance`
- Operator action recommended

---

### 9. Hallucination Risk Score (aggregate)

**Formula:** average risk score across all records (see `06_hallucination_controls.md` for per-record formula)

**Thresholds:**
- 0–20: Low — proceed
- 21–49: Medium — surface in build summary, do not halt
- 50–79: High — Telegram alert + extended review queue routing
- 80+: Critical — build halts (`BUILD_BROKEN.md`)

---

### 10. Run-over-run Regression

**Formula:** for each pattern: `(current_count - previous_count) / previous_count`

**Threshold:** -50% drop on any single pattern

**On failure:**
- Build does not halt
- Telegram alert fires: `Run-over-run regression: <pattern> dropped <prev> → <current> (<pct>%)`
- This catches scraper breakage where source returns empty but doesn't error

**Note:** intentional regressions (like the v2.1 reset that dropped `transfer` from 6,921 to 0) require a `--no-fail-on-regression` flag to acknowledge the change is expected.

---

### 11. Heartbeat Staleness

**Formula:** `now - last_successful_refresh`

**Threshold:** 36 hours

**On failure:**
- Telegram alert fires: `Heartbeat stale: last successful refresh <X> hours ago`
- Refresh harness attempts recovery on next scheduled run

---

### 12. Live Browser Verification (the hardest gate)

**Formula:** binary — Playwright Chromium against live URL passes all checks (see `engineering/05_verification_and_rollback.md` for full check list)

**Threshold:** binary pass

**On failure:**
- HEAD reverts to previous commit
- Force-pushed
- `BUILD_BROKEN.md` written
- Telegram alert fires
- Build exits non-zero

This is the gate that prevents broken dashboards from reaching the operator's client.

---

## Metric reporting

Every build writes `data/quality_metrics.json` with the current value of every metric:

```json
{
  "build_timestamp": "2026-05-05T18:32:36Z",
  "source_verification_rate": 0.83,
  "field_completeness_rate": 0.94,
  "match_confidence_avg": 87.2,
  "parser_confidence_avg": 91.5,
  "source_url_coverage": 1.0,
  "dedupe_ran": true,
  "unsupported_claim_count": 0,
  "review_queue_ratio": 0.18,
  "hallucination_risk_avg": 12,
  "regression_alerts": [],
  "live_verification_passed": true,
  "thresholds_violated": ["source_verification_rate"]
}
```

`thresholds_violated` is the actionable field — it lists every metric that fell below threshold this build. If empty, the build is fully healthy.

---

## How metrics interact with the build pipeline

The pipeline order:

1. Scrapers run → emit raw records to `data/raw/<source>.jsonl`
2. Parser confidence computed per record
3. Build script runs → joins, scores, classifies, dedupes
4. Field completeness, match confidence, dedupe metrics computed
5. Hallucination risk computed per record
6. Aggregate metrics written to `data/quality_metrics.json`
7. Threshold check: any critical failure → `BUILD_BROKEN.md`, exit
8. Push to GitHub Pages
9. Live browser verification runs
10. Final metric: `live_verification_passed`
11. If passed: write `LIVE_VERIFIED.txt`, exit 0
12. If failed: revert HEAD, write `BUILD_BROKEN.md`, exit non-zero

---

## What's actionable for the operator

`BUILD_SUMMARY.md` always includes a "Quality Metrics" section that surfaces:
- All metrics with their current values
- All thresholds violated
- All Telegram alerts that fired
- Recommended operator actions per violation

This is the section the operator reads first after a build completes. It tells them whether the dashboard is shipping clean data or whether the build needs attention before clients see it.
