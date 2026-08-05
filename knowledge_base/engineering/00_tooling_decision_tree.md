# 00 — Tooling Decision Tree

This file is the AI's quick-reference for choosing the right scraping/parsing/verification tool for a given task. The tree is structured by the question being asked, not by tool category, because what the AI needs to know is "what do I reach for when I see X."

---

## Question 0: What is the portal fingerprint?

**Fingerprint before you write code.** Vendor platforms differ but the same vendor can be deployed differently across counties — never assume a county or state based on the vendor. The fingerprint determines the adapter; the adapter determines the tool.

### 20-question fingerprint checklist

Answer these in order, observing the real portal, before writing any scraper line:

1. Is the page served as static HTML (records visible in the original HTML response)?
2. Does the page require JavaScript to load records?
3. Does the Network tab show XHR or fetch calls returning JSON?
4. Are search results posted through form-encoded requests?
5. Are hidden anti-forgery tokens (CSRF, `__RequestVerificationToken`, `viewstate`) required?
6. Are cookies required after first page load (session cookies, ASP.NET_SessionId, etc.)?
7. Is there reCAPTCHA v2, reCAPTCHA v3, hCaptcha, or Cloudflare Turnstile on submit?
8. Is there a WAF challenge (Imperva, Akamai, Cloudflare) on first hit?
9. Does pagination use page numbers, offsets, cursors, tokens, or infinite scroll?
10. Are record-detail pages on separate URLs (deep-linkable) or rendered in modals/viewers?
11. Are documents downloadable as PDF, image, or embedded in a JavaScript viewer?
12. Is OCR needed (scanned PDFs without text layer)?
13. Does the portal require operator login (SAML SSO, username/password, MFA)?
14. Can a seeded session (browser cookies copied from a real session) replay the source?
15. Is there a public bulk-delivery channel (FTP, scheduled CSV, monthly extract)?
16. Is there a documented API endpoint anywhere on the host?
17. What rate limits or anti-bot signals fire on rapid requests?
18. Is the source lead-generating (P0/P1 distress) or enrichment (P2)?
19. What scraper module pattern fits: `_html.py`, `_api.py`, `_playwright.py`, `_seeded.py`, `_captcha.py`, `_stealth.py`, `_login.py`, `_pdf.py`, `_arcgis.py`, `_socrata.py`, `_records_request.py`, `_manual_upload_csv.py`, `_manual_upload_pdf.py`, `_manual_upload_xlsx.py`, `_manual_upload_html.py`, `_manual_upload_screenshot.py`?
20. Is the discovery reproducible — can another operator follow the same trail and get the same fingerprint?

### Portal vendor families (fingerprint signals only, never assumptions)

These are recognizable platform families. Identifying the family narrows the adapter selection but **does not** guarantee behavior — the same vendor can ship different configurations per county.

- Tyler-hosted recorder portals
- Tyler iDocket / Odyssey court portals
- Tyler Eagle Recorder
- CivicPlus county websites
- Granicus public-records portals
- GovOS / govOS Tax + Recording
- Catalis-hosted portals
- Kofile recorder portals
- Landmark recorder portals
- Aumentum tax portals
- ArcGIS REST feature services
- Socrata open-data endpoints
- Accela code enforcement portals
- EnerGov permitting + code portals
- Cityworks municipal portals
- Custom county clerk / tax collector / court portals
- PDF-only publication pages

### Portal fingerprint output schema

Every Phase 0 recon must emit a fingerprint object per source. Store as `data/recon/<source_id>.fingerprint.json`:

```json
{
  "source_id": "<source_id>",
  "source_type": "<clerk_recordings | court_civil | court_probate | sheriff_sales | tax_delinquency | code_enforcement | parcel_master | ...>",
  "portal_vendor": "<vendor_family_or_UNKNOWN>",
  "portal_family": "<family_label_or_UNKNOWN>",
  "rendering_type": "<STATIC_HTML | JAVASCRIPT_RENDERED | SPA | PDF | API | UNKNOWN>",
  "access_pattern": "<OPEN_API | STATIC_HTML | SPA_WITH_API | SPA_RECAPTCHA | WAF | OPERATOR_LOGIN | PDF_ONLY | PUBLIC_RECORDS_ONLY>",
  "api_discovery_status": "<FOUND | NOT_FOUND | BLOCKED | NOT_TESTED>",
  "captcha_status": "<NONE | V2 | V3 | TURNSTILE | HCAPTCHA | UNKNOWN>",
  "session_status": "<NO_SESSION_REQUIRED | COOKIE_REQUIRED | SEEDED_SESSION_REQUIRED | LOGIN_REQUIRED>",
  "pagination_model": "<NONE | PAGE_NUMBER | OFFSET | CURSOR | INFINITE_SCROLL | UNKNOWN>",
  "record_detail_model": "<INLINE | DETAIL_PAGE | MODAL | DOCUMENT_VIEWER | PDF | UNKNOWN>",
  "download_model": "<NONE | PDF | IMAGE | CSV | BULK_FILE | UNKNOWN>",
  "source_priority": "<P0 | P1 | P2>",
  "recommended_adapter": "<scrapers/<source_id>_<adapter>.py>",
  "notes": "<recon notes>"
}
```

### Adapter selection from fingerprint

The `rendering_type` + `access_pattern` combination maps to an adapter module name:

| Fingerprint | Adapter module | Tooling answer in Question 1 |
|---|---|---|
| `STATIC_HTML` + `STATIC_HTML` | `_html.py` | Branch C |
| `API` + `OPEN_API` | `_api.py` | Branch A or B |
| `SPA` + `SPA_WITH_API` | `_api.py` (prefer over browser) | Branch D + A |
| `SPA` + `SPA_RECAPTCHA` | `_seeded.py` or `_captcha.py` or `_stealth.py` | Branch E |
| `JAVASCRIPT_RENDERED` + `STATIC_HTML` | `_playwright.py` | Branch D |
| any + `WAF` | `_stealth.py` (residential proxy + stealth browser) | Branch F |
| any + `OPERATOR_LOGIN` | `_login.py` (with credentials declared in county config) | new — see `04_blocked_source_strategies.md` |
| `PDF` + `PDF_ONLY` | `_pdf.py` | Branch G |
| `API` + ArcGIS REST host | `_arcgis.py` | Branch A |
| `API` + Socrata host | `_socrata.py` | Branch A |
| any + `PUBLIC_RECORDS_ONLY` | `_records_request.py` (legitimate primary channel when no portal exists) | new — see `04_blocked_source_strategies.md` |
| manual upload (CSV from operator) | `_manual_upload_csv.py` | new — operator-assisted extraction |
| manual upload (PDF from operator) | `_manual_upload_pdf.py` | new — operator-assisted extraction |
| manual upload (XLSX from operator) | `_manual_upload_xlsx.py` | new — operator-assisted extraction |
| manual upload (HTML save from operator) | `_manual_upload_html.py` | new — operator-assisted extraction |
| manual upload (screenshot from operator) | `_manual_upload_screenshot.py` | new — operator-assisted extraction; uses OCR |

**Manual upload adapters** are NOT a public-records-request fallback. They are a distinct path: the operator opens a portal, performs the search manually, exports/saves the result, and drops the file into `data/raw/<source_id>/manual_uploads/incoming/`. The adapter watches that directory and ingests new files on the next pipeline run. Use cases:

- Portal works but is not yet automatable (operator can extract while automation is being built)
- Source has a small daily volume that doesn't justify automation cost
- Source returns data the operator needs to filter or curate before ingestion
- One-off historical backfill the operator performs once

Manual uploads are first-class data and produce normalized signals identical to automated scrapers. The evidence ledger records `source_reliability_grade` per the original source — a CSV the operator exported from the official clerk portal is grade A, not grade D, because the upload path doesn't degrade the underlying source's authority.

**Rule:** prefer API over browser when an API exists and is stable. Browsers are slower, flakier, and easier to detect.

### Universality rule

The core pipeline must not contain vendor-specific logic. Vendor-specific quirks live in the adapter module. The pipeline reads the adapter's normalized output. The fingerprint is the contract between county config (declares the source) and adapter (handles the source).

---

## Question 1: How is this source served?

### A. JSON API (REST or GraphQL) with no auth

**Examples:** ArcGIS REST endpoints, statewide parcel layers, county appraisal-district APIs.

**Tool:** `requests` (with retries) or `httpx`. Pure HTTP, no browser.

**Pattern:**
```python
import requests
from requests.adapters import HTTPAdapter, Retry

s = requests.Session()
s.mount("https://", HTTPAdapter(max_retries=Retry(
    total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504]
)))
r = s.get(url, params=params, timeout=30)
r.raise_for_status()
data = r.json()
```

**Why:** Fastest, most reliable, no rendering overhead. Always try this first.

---

### B. JSON API with auth token / API key

**Examples:** PACER (after login), some state portals.

**Tool:** Same as A, but read credential from `.env`. Never hardcode.

**Pattern:**
```python
import os
from dotenv import load_dotenv
load_dotenv()
headers = {"Authorization": f"Bearer {os.environ['SOURCE_API_KEY']}"}
```

**Why:** Same speed/reliability. Auth-token APIs are still HTTP, no browser needed.

---

### C. Static HTML, no JavaScript required to render

**Examples:** Older county clerk search pages, some sheriff sale listings, simple court dockets.

**Tool:** `requests` + `BeautifulSoup` (lxml parser).

**Pattern:**
```python
import requests
from bs4 import BeautifulSoup

r = requests.get(url, timeout=30)
soup = BeautifulSoup(r.text, "lxml")
rows = soup.select("table.results tr")
```

**Why:** No JS execution overhead. lxml parser is faster than Python's html.parser.

---

### D. JavaScript-rendered SPA without server-side rendering

**Examples:** Many county clerk SPAs, Tyler iDocket modern interfaces, vendor portals.

**Tool:** Playwright (Chromium).

**Pattern:**
```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto(url)
    page.wait_for_selector(".results-table")
    rows = page.locator(".results-table tr").all()
```

**Why:** Real browser executes the SPA's JS. Playwright is more modern and faster than Selenium for new builds. Chromium has the best fingerprint compatibility for sites that check.

**Subcase D1: SPA with API behind it (preferred when discoverable)**

Most SPAs call internal JSON APIs. If you can identify the API call (Network tab → look for XHR / fetch requests), skip the browser entirely and call the API directly with `requests`. This is 100x faster and more reliable.

The browser is only needed when:
- The API requires browser-set headers (like `X-RequestVerificationToken`)
- The API requires browser-acquired cookies (session-bound)
- The API uses encrypted client-side payloads (rare but exists)

---

### E. JavaScript SPA with reCAPTCHA v3 (server-enforced)

**Examples:** Many modern county clerk portals.

**Tools, in order of preference (solve the portal first):**

**E1. Seeded session (preferred for daily freshness)**
- Operator clears reCAPTCHA in real Chrome once (~30 sec)
- Operator copies cookies + tokens into `.env`
- Scraper replays them via `requests` for 24-72 hours
- Implementation in `scrapers/<source>_seeded.py`
- Re-seed weekly when session expires

**E2. CAPTCHA-solving service**
- 2Captcha, Anti-Captcha (~$1.50–3 per 1,000 v3 tokens)
- Fully autonomous, no operator action
- Implementation calls solver API for token, attaches as header

**E3. Stealth browser fingerprinting**
- `playwright-stealth` plugin or `undetected-chromedriver`
- Defeats reCAPTCHA v3 scoring without solver service
- Free, no per-request cost
- Detection heuristics rotate; expect to update stealth config every 30-90 days

**E4. Public-records request (final last resort — portal exists but unsolved)**
- File a statutory records request for the underlying data only after E1–E3 have failed
- Generated by `pipeline/records_request.py`
- Slower cadence, complete coverage, lowest maintenance
- **When a real-time portal exists, the framework must solve portal access first.** E4 is only invoked after E1–E3 and the additional steps in `engineering/04_blocked_source_strategies.md` "Access strategy ordering" have been exhausted.
- **Exception — primary configured channel:** if no usable portal exists at all, OR the data is only delivered through official request, OR the operator has filed a standing recurring delivery, records-request is a legitimate primary channel (not a last resort). Mark with `SCHEDULED_RECORDS_REQUEST` per `engineering/04_blocked_source_strategies.md`.

The framework's default is E1. E2 and E3 are configured per source based on freshness requirements and cost preference. E4 is the final last resort when E1–E3 fail.

---

### F. Imperva / Akamai / Cloudflare WAF-protected

**Examples:** State unified court portals, some state-level government sites.

**Tools, in order of preference (solve the portal first):**

**F1. Residential-proxy + stealth browser**
- Bright Data, Oxylabs, Smartproxy (~$30-80/month)
- Rotates IPs to defeat WAF rate limits
- Stealth browser to defeat fingerprinting
- Infrastructure-grade, the way commercial scrapers operate
- Configure per source based on cost preference

**F2. Operator-credentialed login** — when the source offers an authenticated portal that bypasses the WAF challenge for logged-in users, and operator has authorized credentials declared in county config.

**F3. Manual operator pull** — for low-volume needs, operator fetches via browser, drops files into ingest folder via the `manual_upload_*` adapters (per `engineering/00_tooling_decision_tree.md` adapter table).

**F4. Public-records request (final last resort — portal exists but unsolved)**
- Same as E4 above. Only invoke when F1–F3 have been exhausted.
- **When a real-time portal exists, the framework must solve portal access first.** Records request is the final last resort, not a default.
- **Exception — primary configured channel:** records-request is a legitimate primary channel when no usable portal exists at all, the data is only delivered through official request, or the operator has standing recurring delivery.

WAF defeat is harder than CAPTCHA defeat, but solving it preserves the daily-refresh thesis. Records-request fallback (F4) reduces cadence from daily to whatever the records custodian publishes — usually weekly to monthly — which is a real cost to the product premise. Use F1–F3 first.

---

### G. PDF document

**Examples:** Sheriff sale lists, records-request-delivered bulk extracts (sometimes).

**Tools:**

**G1. `pdfplumber`** — for text extraction from text-based PDFs. Best for tabular data, preserves column structure.

```python
import pdfplumber
with pdfplumber.open(path) as pdf:
    for page in pdf.pages:
        rows = page.extract_table()
```

**G2. `PyMuPDF` (`fitz`)** — for fast text extraction and image extraction. Good when `pdfplumber` is too slow on large PDFs.

```python
import fitz
doc = fitz.open(path)
for page in doc:
    text = page.get_text()
```

**G3. `pypdf`** — modern fork of PyPDF2. Reasonable for simple text extraction. Avoid for tables.

**G4. OCR (`pytesseract` + `pdf2image`)** — for scanned PDFs without OCR layer.

```python
from pdf2image import convert_from_path
import pytesseract
images = convert_from_path(path)
text = "\n".join(pytesseract.image_to_string(img) for img in images)
```

**Decision rule:**
- Text-based PDF with tables → `pdfplumber`
- Text-based PDF without tables → `PyMuPDF`
- Scanned PDF → OCR via `pytesseract`
- Forms with fillable fields → `pypdf` (form extraction)

---

### H. Excel / CSV file

**Examples:** records-request-delivered bulk extracts (most common), bulk downloads from county data portals.

**Tools:**

**H1. CSV** → `csv` module (stdlib) for simple cases, `pandas` for analytical work.

**H2. XLSX / XLSM** → `openpyxl` for read/write, `pandas.read_excel()` for read-only DataFrame work.

**H3. XLS (legacy)** → `xlrd` (older versions) — but most modern sources don't ship legacy .xls; require .xlsx.

**Decision rule:**
- One-off ingest, normalize to JSONL → `csv` module + manual loop
- Aggregate analysis → `pandas`
- Need to write back to Excel → `openpyxl`

---

### I. Word document (DOCX)

**Examples:** records-request response letters, occasional source documents.

**Tool:** `python-docx` for read/write. `mammoth` for converting docx → HTML/text.

**Decision rule:** Most source ingest is CSV / Excel / PDF. DOCX is rare for source data; the framework's docx work is mostly about generating output (records-request PDFs are PDF, not DOCX).

---

### J. HTML scraping in JavaScript context (browser extension)

**Examples:** Operator-driven authenticated search portals where the source mandates the operator's own credentials (county-clerk title-search portals, etc.).

**Tool:** Browser extension manifest v3, `chrome.runtime.sendMessage`, fetch from extension to API endpoint.

**When to use:** When the source requires the operator to be logged in with their personal credentials, and an extension is the cleanest way to capture data while operator browses. Extension pushes captured data to a webhook the framework consumes.

**Decision rule:** This is an operator-tooling pattern, not a daily-refresh pattern. Use only when source mandates personal authenticated access.

---

## Question 2: How do I verify the scraper actually worked?

### Synthetic verification (cheap, runs in build pipeline)

- Schema validation: scraper output matches expected JSONL schema
- Field completeness: required fields populated above threshold
- Dedup check: no duplicate `_key` values
- Date range check: records fall within expected window

Tools: `jsonschema`, manual assertions in scraper test mode.

### Live verification (the gate)

- Playwright Chromium against deployed URL
- Asserts DOM rendered
- Captures console errors
- Validates rendered counts match `leads.json` header
- Tests interactive elements

Tools: `playwright.sync_api`, see `engineering/05_verification_and_rollback.md`.

**The rule:** Synthetic verification catches structural bugs before deploy. Live verification catches rendering bugs that don't appear in headless test mode. Both are required.

---

## Question 3: How do I handle rate limits and retries?

**Default retry strategy** for all HTTP calls:
- 5 attempts maximum
- Exponential backoff: 1s, 2s, 4s, 8s, 16s
- Retry on: 429 (rate limit), 500/502/503/504 (server errors), connection errors
- Do NOT retry on: 401 (auth failure), 403 (forbidden), 404 (not found), 422 (validation)

**Implementation:** `requests.adapters.HTTPAdapter` with `Retry` from `urllib3.util.retry`.

**Per-source limits:** When source documents a rate limit (e.g., "no more than 60 requests per minute"), enforce client-side via `time.sleep()` between calls, even when the source isn't enforcing it server-side. Being a good citizen prevents the source from rate-limiting all clients harder.

---

## Question 4: How do I handle long-running scrapes?

For pulls that take more than 60 seconds:

- Stream output to JSONL incrementally — don't accumulate in memory
- Log progress every 100 records
- Save scraper state (cursor, last-record-id) for resume after failure
- Set process timeout via `subprocess.run(timeout=N)` — kill hung scrapers

**Pattern:**
```python
import json
from pathlib import Path

out = Path("data/raw/source.jsonl")
with out.open("w") as f:
    for i, record in enumerate(scrape_iter()):
        f.write(json.dumps(record) + "\n")
        f.flush()
        if i % 100 == 0:
            print(f"  [{i}] processed", flush=True)
```

`flush=True` on prints and `f.flush()` on file writes ensure progress is visible during long runs and survives process kills.

---

## Question 5: When do I use Playwright vs. requests?

**Default to `requests`.** Only use Playwright when:

1. The site is a SPA whose API isn't discoverable
2. The site requires browser-set headers that can't be replicated
3. The site uses fingerprint-based bot detection that requires real browser
4. The verification step requires real DOM rendering (live verification gate)

Playwright is 50-100x slower than `requests`. Don't reach for it until you've confirmed the simpler tool won't work.

---

## Quick reference table

| Source type | First choice | Fallback |
|---|---|---|
| Open JSON API | `requests` | `httpx` |
| Static HTML | `requests` + BeautifulSoup | — |
| SPA with discoverable API | `requests` (replay API) | Playwright |
| SPA with hidden API | Playwright | — |
| Behind reCAPTCHA v3 | Seeded session | CAPTCHA solver / stealth browser; records-request only as final last resort |
| Behind WAF | Residential proxy + stealth | Operator-credentialed login / manual operator pull; records-request only as final last resort |
| PDF (text, tabular) | `pdfplumber` | `PyMuPDF` |
| PDF (scanned) | `pytesseract` + `pdf2image` | — |
| CSV | `csv` module | `pandas` |
| Excel | `openpyxl` | `pandas.read_excel` |
| DOCX | `python-docx` | `mammoth` |
| Live verification | Playwright Chromium | — |

---

## Access strategy ladder (v5.0.0+)

The v5.0.0 schema introduces `next_access_strategy` on every source's proof packet (MASTER_PROMPT Section 4.7 / 4.8). This field documents the unblock plan for a `BLOCKED_SOURCE` and signals which technique to attempt during Phase 2 adapter build.

Allowed `next_access_strategy` values, ordered roughly cheapest-to-most-expensive:

1. `try_open_public_portal` — the portal might already be accessible to a plain HTTP fetch; verify before climbing the ladder
2. `find_official_vendor_link` — the data lives behind an officially-linked vendor (Tyler, GovOS, BiS); locate the vendor index page
3. `discover_hidden_api` — view-source / Network tab inspection to find an XHR endpoint not advertised on the public page
4. `use_playwright` — JS-rendered page requiring a real browser
5. `use_seeded_session` — operator logs in once, framework replays cookies
6. `use_captcha_solver` — 2Captcha, Anti-Captcha, etc. when reCAPTCHA/hCaptcha blocks automation
7. `use_stealth_browser` — anti-detect Playwright/undetected-chromedriver for fingerprinting WAFs
8. `use_residential_proxy` — when datacenter IPs are blocked but residential IPs work
9. `use_operator_login` — when the source requires per-user authenticated credentials operator must provide
10. `request_free_account` — when a free-tier account suffices but the framework needs to create or use one
11. `use_paid_subscription_if_operator_provides` — when access requires a paid subscription the operator already has
12. `manual_operator_assisted_pull` — when no automated approach works but a human operator can periodically pull the data
13. `standing_records_delivery` — when the county delivers data on a recurring schedule via email/SFTP
14. `public_records_request_last_resort` — formal records request to the clerk's office; last resort because of latency
15. `not_available` — the data does not exist online and no offline access path is viable

**Public records request is not the default.** It is a last resort when a real portal exists but remains unsolved after technical access attempts. Public records request or standing records delivery can be primary ONLY when no usable portal exists or when official recurring delivery is the configured source.

The Build Eligibility Gate (MASTER_PROMPT Section 4.10) treats `BLOCKED_SOURCE` with a clear `next_access_strategy` as eligible for `READY_WITH_BLOCKERS` or `WAITING_ON_ACCESS` verdicts. A `BLOCKED_SOURCE` without a `next_access_strategy` fails the Build Eligibility Gate.
