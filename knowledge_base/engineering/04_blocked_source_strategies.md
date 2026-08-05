# 04 — Blocked Source Strategies

When a county source is blocked, the framework has a defined response per blocker type. This file is the playbook. Document the access path, build the scraper, ship.

---

## Access strategy ordering

The framework follows two different rules depending on whether the operator has already declared a working strategy in the county config.

### During Phase 0 recon (no declared strategy yet)

When no strategy is known for a source, attempt the cleanest, simplest, lowest-cost paths first, then escalate. The escalation ladder:

1. **Direct HTML extraction** — `requests` + `BeautifulSoup`/`lxml` against rendered HTML
2. **Hidden API or network endpoint extraction** — discover JSON endpoints in DevTools Network tab, hit them directly with `requests` or `httpx`
3. **JavaScript-rendered extraction with Playwright** — headless browser when JS rendering is required to populate the DOM
4. **Session cookie based extraction** — copy cookies from a manual browser session, replay against the source
5. **Seeded browser session** — full session state (cookies + storage + headers) seeded from a real session, replayed
6. **Operator seeded session** — operator manually completes a browser interaction (login, CAPTCHA, MFA), framework replays the session
7. **CAPTCHA solver path** — third-party solver service for reCAPTCHA v2/v3, hCaptcha, Turnstile
8. **Stealth browser path** — `undetected-chromedriver`, `playwright-stealth`, or equivalent fingerprint masking
9. **Residential proxy path** — route through residential IP pool to bypass datacenter-IP detection
10. **Operator credentialed login path** — declared in county config with credentials managed via secrets, used when source requires authenticated access
11. **Hybrid browser-plus-API replay** — use browser to obtain tokens/cookies, switch to API for production extraction
12. **Manual operator-assisted pull** — operator extracts records manually on a defined schedule, drops them into ingest path
13. **Public-records request or bulk-records request** — see "Public-records request rule" below

Document every attempted strategy in the source heartbeat (`access_attempts` array per `architecture/10_source_heartbeat_and_cursors.md`) before escalating to the next level.

### During Phase 2+ (county config declares the working strategy)

Once the county config declares a working access strategy for a source, **follow the declared strategy. Do not re-prove every lower path.** The recon already did that work.

The county config is authoritative:

```json
{
  "sources": {
    "clerk_recordings": {
      "access_strategy": "OPERATOR_SEEDED_SESSION",
      "fingerprint_ref": "data/recon/clerk_recordings.fingerprint.json",
      "session_seed_path": ".env",
      "session_max_age_hours": 72
    }
  }
}
```

If the declared strategy fails at runtime, the framework alerts and waits for operator action. It does not silently fall back to a different strategy without operator confirmation — silent fallback is a hallucination-risk path.

### When to re-escalate

Re-escalate only when:
- The declared strategy fails repeatedly (3+ consecutive runs)
- The portal vendor changes (recon must be re-run)
- The operator explicitly requests a re-fingerprint via `--rerun-recon`

A single run failure is a transient issue, not a strategy failure. Honor the existing strategy until evidence accumulates.

---

## Public-records request rule

Public-records request and bulk-records request occupy two distinct roles in the framework:

### Role A — Final last resort (when a portal exists but is blocked)

When a real-time portal exists for the source but cannot be solved after exhausting paths 1–12 above, public-records request is the final last resort. Mark the source with:

```json
{
  "access_strategy": "FINAL_LAST_RESORT_RECORDS_REQUEST",
  "records_request_allowed": true,
  "escalation_reason": "<documented failures of paths 1-12>"
}
```

**Never default to this. Never recommend it because the portal is "difficult" or "slow" or "JavaScript-rendered." Solve the portal first.**

### Role B — Legitimate primary channel (when there is no portal, or operator has standing delivery)

Public-records request or bulk delivery is a legitimate primary configured channel when ANY of:

1. No usable portal exists for the source (the data is only available via official request)
2. The data is only delivered through official request by upstream policy
3. The operator has filed a standing public-records request with recurring delivery
4. The county delivers recurring CSV, PDF, spreadsheet, or bulk file drops on a schedule
5. The source is intentionally configured as a scheduled public-records delivery source in the county config

In Role B, mark the source with:

```json
{
  "access_strategy": "SCHEDULED_RECORDS_REQUEST",
  "records_request_allowed": true,
  "delivery_cadence": "<weekly | monthly | quarterly>",
  "delivery_format": "<CSV | XLSX | PDF | bulk_zip>",
  "ingest_path": "data/raw/<source_id>/incoming/"
}
```

In Role B, the records-request channel is NOT a fallback. It is the source. The framework treats it as a first-class data feed, not as a degraded substitute.

### Rule of thumb

- Solve the portal first **when a portal exists**.
- Do not punt to records request because the portal is difficult.
- If no portal exists, or the standing delivery is the real source, records request is the configured primary channel — not a last resort.

---

## reCAPTCHA v3 (server-enforced)

**Detection:**
- Page source contains `grecaptcha.execute(siteKey, {action: ...})`
- API responses include `"recaptcha_required": true` or similar
- Calls without a valid token return 403 / 401 / explicit error message
- Browser DevTools shows `X-RecaptchaToken` or `g-recaptcha-response` header in successful calls

**Available paths (solve the portal first):**

### 1. Seeded session

Operator clears reCAPTCHA in real Chrome once. Framework replays the resulting cookies and tokens.

**Operator setup** (one-time per session):
1. Open the source in Chrome, complete a search
2. DevTools → Application → Cookies → copy all cookies for the domain
3. DevTools → Network → find the search request → copy `X-RequestVerificationToken` (or equivalent) header
4. Paste into `.env`:
   ```
   <SOURCE>_SESSION_COOKIES=<cookie string>
   <SOURCE>_SESSION_TOKEN=<verification token>
   <SOURCE>_SESSION_SEEDED_AT=<ISO timestamp>
   ```

**Framework behavior:**
- `scrapers/<source>_seeded.py` reads env vars, replays them via `requests`
- On HTTP 401/403 or recaptcha challenge response: scraper exits with code 4
- Refresh harness detects exit 4 → Telegram alert: "Re-seed session within 24h"
- At 72-96h session age: pre-emptive Telegram alert recommends re-seed

**Tradeoffs:** Daily cadence. Periodic operator action (~30 sec). Sessions can expire faster on aggressive sources.

### 2. CAPTCHA-solving service

Programmatic CAPTCHA solving via 2Captcha or Anti-Captcha.

**Setup:**
- Account funded ($10-50 to start)
- API key in `.env`: `TWOCAPTCHA_API_KEY=...` or `ANTICAPTCHA_API_KEY=...`
- `scrapers/<source>_solved.py` calls solver per request

**Cost:** ~$1.50–3 per 1,000 reCAPTCHA v3 tokens. Daily refresh on a typical county = $5-25/month.

**Tradeoffs:** Fully autonomous. No periodic operator action. Solver tokens can return below the source's required score; build retry logic. Combine with seeded session as fallback.

### 3. Stealth browser fingerprinting

`undetected-chromedriver` or Playwright with stealth plugin presents a fingerprint indistinguishable from real Chrome. reCAPTCHA v3 scores the session as legitimate based on timing, mouse, canvas, and WebGL signals.

**Tradeoffs:** Free per-request. Detection heuristics rotate; expect to update the stealth config every 30-90 days.

### 4. Public-records request (final last resort — portal exists but unsolved after 1–3 fail)

The county is statutorily required to provide records on request. Only invoke this path after seeded session, CAPTCHA solver, and stealth browser have all failed for this source.

- File `pipeline/records_request.py --county=<id>` to generate a signature-ready PDF (the script generates the request regardless of what the target state names its records-request statute)
- Operator signs and emails to the county records custodian
- Response within the statutory window (varies by state)
- Standing 12-month order means the request only happens once per period
- Files delivered drop into `data/raw/<source>_records_request/incoming/`
- `scrapers/<source>_records_request_ingest.py` auto-ingests on next refresh

**Tradeoffs:** Slower cadence (typically monthly). Complete coverage. Low maintenance. **Reduces daily-distress cadence**, which is a real cost to the product premise. Use only when 1–3 are not viable for this source.

**Exception — primary configured channel:** if no usable portal exists at all, OR the data is only delivered through official request, OR the operator has filed a standing recurring delivery, records-request is a legitimate primary channel (not a last resort). See "Public-records request rule" Role B above.

---

## Imperva / Akamai / Cloudflare WAF

**Detection:**
- Page returns CAPTCHA challenge for any non-browser request
- "Access denied" or "Request blocked" responses on automation
- HTTP 403 with `cf-ray` (Cloudflare) or `x-iinfo` (Imperva) headers
- TLS fingerprinting active (JA3 hash analysis)
- Browser fingerprinting (canvas, WebGL, fonts)

**Available paths (solve the portal first):**

### 1. Residential proxy + stealth browser

WAF systems track IP reputation. Datacenter IPs (AWS, GCP) get blocked instantly. Residential IPs pass scrutiny.

**Vendors:** Bright Data, Oxylabs, Smartproxy.
**Cost:** $30-80/month for residential bandwidth (1-10 GB).

**Pattern:**
```python
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth_sync

with sync_playwright() as p:
    browser = p.chromium.launch()
    context = browser.new_context(
        proxy={
            "server": f"http://{os.environ['PROXY_HOST']}:{os.environ['PROXY_PORT']}",
            "username": os.environ["PROXY_USER"],
            "password": os.environ["PROXY_PASS"],
        },
        user_agent="Mozilla/5.0 ...",
    )
    stealth_sync(context)
    page = context.new_page()
    # ... scrape
```

**Tradeoffs:** Infrastructure-grade. Higher confidence against aggressive WAFs. Per-month cost.

### 2. Operator-credentialed login

When the source offers an authenticated portal that bypasses the WAF challenge for logged-in users, and operator has authorized credentials declared in `config/counties/<county>.json`. The scraper uses `_login.py` adapter to fetch records via the authenticated path.

### 3. Manual operator pull

For low-volume needs (< 100 records/month), operator fetches via real browser and drops files into `data/raw/<source>_manual/incoming/`. Framework runs `scrapers/<source>_manual_ingest.py` on the dropped file. This uses the `manual_upload_*` adapters from `engineering/00_tooling_decision_tree.md`.

### 4. Public-records request (final last resort — portal exists but unsolved after 1–3 fail)

The statutory channel doesn't care what the WAF does. Only invoke after residential proxy + stealth, operator login, and manual pull have all failed for this source.

- File via `pipeline/records_request.py` to generate signature-ready PDF
- Standing 12-month order means single request per period

**Tradeoffs:** **Reduces daily-distress cadence**, which is a real cost to the product premise. Use only when 1–3 are not viable.

**Exception — primary configured channel:** if no usable portal exists at all, OR the data is only delivered through official request, OR the operator has filed a standing recurring delivery, records-request is a legitimate primary channel (not a last resort). See "Public-records request rule" Role B above.

---

## Paywalls (PACER, etc.)

**Detection:**
- Source explicitly requires payment to access records
- PACER (federal courts), some state title-search systems

**Available paths:**

### 1. Authenticated scraper after account funding

Operator creates an account, funds it. Framework authenticates and pulls.

PACER specifically: $0.10/page, capped quarterly. Framework uses authenticated API access via `pacer-fastrack` (commercial) or scrapes after login via Playwright.

**Cost:** PACER averages $100-500/month for an active operator pulling bankruptcy records county-wide.

### 2. Alternative source signals

Most paywalled records duplicate at the county clerk for property-affecting events (lis pendens, judgments, lien filings). The framework prefers clerk records when both exist for the same data.

For bankruptcy specifically: sheriff sale status fields often note "BANKRUPTCY" when a stay is filed. Some states record bankruptcy notices at the county clerk. These are alternative paths when the operator hasn't funded a PACER account.

---

## Login walls (SAML SSO, etc.)

**Detection:**
- Source redirects to `/saml/login` or shows "Sign in with..." screens
- Examples: state-level court systems restricted to attorneys, law enforcement, or agency users

**Available paths:**

### 1. Operator-credentialed access

When the operator holds appropriate credentials, the framework authenticates and pulls. Use a session-replay scraper similar to seeded-session pattern.

### 2. Public-records request (when credentials unavailable)

Most login-walled court records are still public records by statute, just not exposed publicly online. Records request to the court records custodian still works.

**Important:** records-request here is invoked only when operator credentials are unavailable (path 1 cannot be used). If the operator has credentials, path 1 is the right answer and records-request is not the default. **When a real-time portal exists and operator credentials exist for it, the framework must solve portal access first.**

### 3. Clerk-recording duplicates

Most foreclosure-related records (lis pendens, judgments, liens) are recorded at the county clerk in addition to court systems. The framework prefers clerk records when both exist for the same data.

---

## Sealed records

**Detection:**
- Source explicitly notes "sealed by default" or "court order required"
- Examples: family court divorce filings, juvenile court records

**Available paths:**

### 1. Indirect signals

Even when the underlying filing is sealed, downstream property-affecting orders are often recorded at the county clerk:
- Marital settlement deeds
- Quitclaim deeds from one spouse to another
- Court-ordered sale orders that get recorded

The framework detects these indirect signals at the clerk layer instead of attempting the sealed source.

---

## Soft blocks — rate limits, IP bans, transient challenges

**Detection:**
- HTTP 429 (rate limited)
- Cloudflare 5-second challenge that passes with normal retry
- IP ban (HTTP 403 with retry-after)

**Available paths:**

### 1. Honor rate limits explicitly

```python
import time
for record in records:
    process(record)
    time.sleep(0.5)  # 2 req/sec is conservative
```

### 2. Exponential backoff on 429

Already in the standard `requests` retry config (`engineering/02_scraping_libraries.md`).

### 3. Proxy rotation

For sources that rate-limit by IP, residential proxy rotation handles the pressure. Configure as in the WAF section above.

---

## Documentation requirements

When recon identifies a blocked source, the framework writes to `RECON.md`:

```
## <source name>

**Status:** Blocked
**Block type:** reCAPTCHA v3 (server-enforced)
**Detection:** API returns `enableServerRecaptcha=1` flag; calls without valid token return 403
**Available paths:**
- Path A — `pipeline/records_request.py --county=<id>` (statutory request)
- Path B — `scrapers/<source>_seeded.py` (seeded session)
- Path C — `scrapers/<source>_solved.py` (CAPTCHA solver)
- Path D — `scrapers/<source>_stealth.py` (stealth browser)
**Operator actions required per path:** sign+email request / re-seed weekly / fund solver account / none
**Estimated time to first data per path:** 7+ business days / 1 day / immediate / immediate
```

This entry becomes the source's section in `methodology.html` so the operator's client sees exactly what paths are active and what the data freshness implications are.
