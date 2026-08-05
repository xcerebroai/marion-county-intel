# 05 — Verification and Rollback

The verification gate is the framework's single most important post-build step. Synthetic verification (Python re-derivation of counts) is necessary but insufficient — it doesn't catch bugs in the dashboard's JavaScript. Live browser verification against the deployed URL catches what synthetic tests miss.

This file is the spec for `pipeline/verify.py`.

---

## Scraper fixture requirement

**No scraper is production-ready until it passes saved-fixture tests against eight standard scenarios.** This is the gate Phase 3+ scrapers must pass before they touch a live source.

Fixtures live at `tests/fixtures/<source_id>/` and the scraper module must implement a `parse_fixture(fixture_name)` entry point that the test harness calls. The eight required fixtures per source:

1. **`empty_result.html`** (or `.json`/`.pdf`) — a search response with zero results. Scraper must return an empty array, not throw, not return `None`.
2. **`single_result.html`** — one record returned. Scraper must produce one normalized output with all required fields populated.
3. **`multiple_results.html`** — multiple records on one page. Scraper must produce one normalized output per record without dropping or duplicating.
4. **`pagination.html`** — a multi-page result set. Scraper must walk pagination (page numbers, cursors, offsets, or infinite scroll per fingerprint) and produce records from all pages.
5. **`record_detail.html`** — a single record-detail page. Scraper must populate the detail fields the list view didn't have.
6. **`document_download.pdf`** (or image, where applicable) — a downloaded document. Scraper must successfully save it, return the local path, and (if OCR is needed) extract text.
7. **`blocked_session.html`** — session-expired or CAPTCHA-challenge response. Scraper must exit cleanly with exit code 4 (session-expired signal per `engineering/04_blocked_source_strategies.md`) and emit a heartbeat update.
8. **`malformed_record.html`** — a record missing required fields, with broken HTML, or with non-UTF-8 garbage. Scraper must route the record to review with `parser_confidence < 80` rather than crashing or fabricating values.

### How fixtures are captured

During Phase 0 recon, save the response bytes from the real source for each of the eight scenarios. Re-fetching from the live site for tests is forbidden — tests must be reproducible offline.

```bash
# During recon
curl -o tests/fixtures/<source_id>/single_result.html "<source URL>"
```

### How the harness runs

`tests/test_scrapers.py` iterates every adapter module under `scrapers/`. For each adapter, it loads each fixture and calls `parse_fixture(fixture_name)`. The test asserts:

- Empty fixture → returns `[]` with no error
- Single/multiple fixtures → returns array of expected length, every record has required schema fields
- Pagination → returns sum of records across all pages
- Detail fixture → returns enriched record
- Document download → file saved, text extracted (or text-extraction-skipped flag set if scanned)
- Blocked session → exit code 4, heartbeat updated with `session_expired` status
- Malformed → record routed to review queue, parser_confidence below 80

A scraper that fails any fixture cannot be promoted past Phase 2.

### Why this matters

Without fixture coverage, scrapers tend to be written against whatever the live source returns the day they're built. The first time the source returns an empty result, a multi-page set, a malformed record, or a session-expired challenge in production, the scraper crashes or silently corrupts data. Fixtures force the scraper to handle all eight cases before going live.

---

## What synthetic verification catches

These checks run in `pipeline/build_leads.py` before write:

- Schema validation: `leads.json` matches the JSON Schema
- Two-Truths invariant: header counts match records-derived counts
- Pattern enumeration: every pattern listed in records exists in the pattern_counts header
- Subtype enumeration: every subtype is registered
- TTL enforcement: no signals older than their TTL window
- Stale-record GC: no records where every signal has expired
- Run-over-run regression: no pattern dropped > 50% from previous build

These run in milliseconds. They catch pipeline logic bugs.

---

## What synthetic verification misses

Synthetic verification re-derives the dashboard's expected counts in Python. The dashboard renders by running the same `matches()` logic in JavaScript. **A bug in the JavaScript implementation isn't caught.**

A prior county build had this exact failure mode:
- `leads.json` was valid (Two-Truths PASS in Python)
- The dashboard's `renderFilterRail()` called `Object.keys(subTotalsByPat[p])` for every pattern
- 8 of 11 patterns had no subtype data, so `subTotalsByPat[p]` was `undefined`
- `Object.keys(undefined)` threw `TypeError`
- The exception killed `load()` before `renderAll()` ran
- Page stayed on "Loading…" forever
- Synthetic verification reported "ALL 11 PASS" because none of the checks tested rendered DOM

**The fix:** verify the live deployed URL renders correctly in a real browser.

---

## The live verification gate

Implementation: `pipeline/verify.py` (replaces v2's verifier).

### Steps

**1. Wait for Pages CDN to flush**

Poll the live `data/leads.json` URL until the served `generated_at` matches the local build's `generated_at`. Up to 180 seconds. CloudFront / GitHub Pages CDN can lag 30-90 seconds after push.

```python
def wait_for_pages_flush(local_generated_at, deadline_s=180):
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        r = requests.get(LEADS_URL, headers={"Cache-Control": "no-cache"}, timeout=20)
        served = r.json()
        if served["generated_at"] == local_generated_at:
            return True
        time.sleep(8)
    return False
```

If CDN doesn't converge: build fails with `cdn_flush_timeout`.

**2. Launch Playwright Chromium**

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(accept_downloads=True)
    page = context.new_page()
    
    console_errors = []
    page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
    page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
    
    page.goto(LIVE_URL, wait_until="domcontentloaded", timeout=30_000)
```

**3. Wait for ready marker**

The dashboard's `index.html` sets `document.body.dataset.ready = "1"` only after `renderAll()` completes successfully. The verifier waits for this marker.

```python
try:
    page.wait_for_selector('body[data-ready="1"]', timeout=15_000)
except TimeoutError:
    fail("Ready marker", "body[data-ready=1] never appeared in 15s — load() never completed")
```

**This is the single most important check.** If the dashboard JavaScript can't reach the end of `load()`, the page is broken.

**4. Capture console errors**

Any `console.error` or `pageerror` event during load = fail.

```python
if console_errors:
    fail("Console errors", f"{len(console_errors)} JS errors during load: {console_errors[:5]}")
```

This catches the silent-throw pattern where dashboard JS fails partially but doesn't show a visible error.

**5. Assert lead-row count**

```python
expected_min_rows = min(local_leads["lead_total"], 800)
row_count = page.locator(".lead-row[data-idx]").count()
if row_count < expected_min_rows:
    fail("Row count", f"{row_count} rows rendered, expected >= {expected_min_rows}")
```

The 800 cap matches the dashboard's display ceiling.

**6. Assert Total stat-tile matches lead_total**

```python
total_text = page.locator(".stat-tile.total .value").first.text_content() or ""
total_n = int(total_text.replace(",", "").strip())
if total_n != local_leads["lead_total"]:
    fail("Two-Truths in browser", f"DOM Total tile = {total_n}, leads.json lead_total = {local_leads['lead_total']}")
```

This is Two-Truths verification at the rendered-DOM layer, not just the data layer.

**7. Test pre-canned view interaction**

```python
page.locator('button[data-precanned="<view-id>"]').click(timeout=5000)
page.wait_for_timeout(300)  # let re-render settle
after_count = page.locator(".lead-row[data-idx]").count()
if after_count < 1:
    fail("Pre-canned view", "view rendered 0 rows after click; expected >= 1")
```

Tests the interactive layer. Catches bugs where filtering breaks even when initial render works.

**8. Test CSV export**

```python
with page.expect_download(timeout=8000) as dl_info:
    page.locator("#export-csv").click()
download = dl_info.value
csv_path = ROOT / "data" / "raw" / f"_verify_{int(time.time())}.csv"
download.save_as(str(csv_path))

content = csv_path.read_text(encoding="utf-8")
csv_path.unlink()

reader = csv.reader(io.StringIO(content))
header = next(reader, [])
if header != EXPECTED_CSV_COLS:
    fail("CSV header", f"header mismatch: got {header}")
```

Validates the export path the operator's client uses to push leads to their CRM.

---

## On failure: auto-rollback

When any check fails, the verifier reverts HEAD to the previous commit and force-pushes.

```python
def revert_and_blame(failures, console_errors, stdout_log):
    subprocess.run(["git", "revert", "--no-edit", "HEAD"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)
    
    # Write BUILD_BROKEN.md to the now-reverted state
    write_broken_md(failures, console_errors, stdout_log)
    subprocess.run(["git", "add", "BUILD_BROKEN.md"], cwd=ROOT, check=True)
    subprocess.run(["git", "commit", "-m", "ops: BUILD_BROKEN.md - auto-rollback"], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=True)
    
    telegram_send(f"<b>[<county>-intel]</b> BUILD AUTO-ROLLED BACK\n{summarize(failures)}")
```

The dashboard reverts to the previous known-good build. The operator's client never sees a broken dashboard.

`BUILD_BROKEN.md` documents:
- What checks failed
- Console errors captured
- Verifier log
- Link to the reverted commit

The operator can investigate and either fix forward or accept the rollback.

---

## On success: verified marker

```python
def write_live_verified(local_leads):
    text = f"""Live verification PASS at {datetime.now(timezone.utc).isoformat()}

Live URL: {LIVE_URL}
Schema: v{local_leads['schema_version']}
Source commit: {local_leads['source_commit']}

Lead totals:
  total leads: {local_leads['lead_total']}
  total signals: {local_leads['total_signals']}
  most stacked: {local_leads['most_stacked_count']}

Pattern counts:
{format_pattern_counts(local_leads)}

Clerk ingest status:
{format_ingest_status(local_leads)}
"""
    Path("LIVE_VERIFIED.txt").write_text(text)
```

This file is committed and serves as the audit trail. When the next build runs, it can compare against the previous `LIVE_VERIFIED.txt` to detect drift.

---

## The watchdog (continuous verification)

The build-time verifier runs once per refresh. The watchdog runs every N hours independently.

`watchdog.py` (separate scheduled task, every 6 hours):

```python
def run_watchdog():
    failures = run_browser_checks_against_live()
    if failures:
        # Live URL is broken since last build
        last_good_commit = find_last_commit_with_live_verified_txt()
        revert_to(last_good_commit)
        force_push()
        telegram_send("Watchdog detected broken dashboard, rolled back")
        sys.exit(1)
```

The watchdog catches breakage that happens AFTER a successful build — most commonly, source data changes that exercise dashboard code paths the build's verification didn't cover. By detecting and rolling back, the watchdog keeps the live dashboard working continuously.

---

## What the verifier does NOT do

- It does not fix bugs. It detects and rolls back. Fixes are the operator's job.
- It does not validate semantic correctness of leads. A lead with `pattern: "wholesale_candidate"` is "correct" to the verifier as long as it renders. Lead-quality verification is a separate concern handled by `domain/07_fallback_metrics.md`.
- It does not test every interactive element. It tests the critical paths (load, filter, click, export). Comprehensive UI testing is out of scope.

The verifier's job is binary: live URL renders correctly, or it doesn't. Pass or revert.

---

## Why this matters

The framework's fundamental promise to the operator's client is "fresh leads daily." That promise is only kept if the dashboard works every day. The verifier makes that guarantee mechanical instead of hopeful.

Every county built on this framework inherits the verifier and the auto-rollback. The framework cannot ship a broken dashboard to production, ever, by construction.
