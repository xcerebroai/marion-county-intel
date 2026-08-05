# 02 — Scraping Libraries

Reference for the scraping tools the framework uses, with version-specific quirks and patterns.

---

## requests (HTTP, no browser)

**Version:** 2.32.3

**Use for:** JSON APIs, static HTML, replaying SPA APIs after seeded session.

**Default session pattern:**

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

def make_session():
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=1.0,  # 1s, 2s, 4s, 8s, 16s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"],
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 ...",
    })
    return s
```

**Timeout:** Always set `timeout=30` (or longer for known-slow sources). Never use unbounded timeouts — the scheduled task will hang forever on a stuck connection.

**Cookies:** `requests.Session` handles cookie persistence automatically. For seeded-session replay, set the cookie jar manually:

```python
import http.cookiejar
import os

cookie_string = os.environ["CLERK_SESSION_COOKIES"]
jar = requests.cookies.RequestsCookieJar()
for pair in cookie_string.split(";"):
    name, _, value = pair.strip().partition("=")
    jar.set(name, value, domain=".source-domain.com", path="/")
s.cookies = jar
```

---

## httpx (modern HTTP, async-capable)

**Version:** 0.27.2

**Use when:**
- You need `async/await` (rare in this framework, but useful for parallel scraping of independent sources)
- HTTP/2 is required (some modern APIs benefit)
- The cleaner API is preferred over `requests`

**Pattern:**

```python
import httpx

with httpx.Client(timeout=30, http2=True) as client:
    r = client.get(url)
    r.raise_for_status()
    data = r.json()
```

**Async pattern (for parallel pulls):**

```python
import asyncio
import httpx

async def fetch_all(urls):
    async with httpx.AsyncClient(timeout=30) as client:
        tasks = [client.get(u) for u in urls]
        return await asyncio.gather(*tasks)

results = asyncio.run(fetch_all(url_list))
```

**Note:** Most framework scrapers use `requests` because the cognitive overhead of async isn't worth it for sequential scraping. Reach for `httpx` only when you have a specific reason.

---

## Playwright (real browser)

**Version:** 1.49.0

**Browser:** Chromium (installed via `playwright install chromium`).

**Why Chromium specifically:** best fingerprint compatibility for sites that check, smallest install footprint vs WebKit/Firefox, most reliable selector behavior. Don't use Firefox or WebKit unless you have a specific reason.

**Sync API pattern (for build scripts):**

```python
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        user_agent="Mozilla/5.0 ...",
        viewport={"width": 1920, "height": 1080},
        accept_downloads=True,
    )
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_selector(".results", timeout=15_000)
    rows = page.locator(".results tr").all()
    browser.close()
```

**Async API:** available but rarely used in this framework. `sync_playwright` is sufficient for sequential pulls and the verifier.

**Headless mode:** default `True` for production builds. Switch to `False` when debugging (`headless=False, slow_mo=100`) so you can watch the browser do the work.

---

### Playwright quirks worth knowing

**1. `wait_until` strategies**

- `"domcontentloaded"` — DOM is parsed, fastest, use for SPAs that render after this
- `"networkidle"` — no network activity for 500ms, good for "everything finished"
- `"load"` — DOM + all subresources, slower, rarely needed

For most SPAs, use `"domcontentloaded"` then `wait_for_selector` on a known-rendered element.

**2. Wait for selector vs. wait for timeout**

Always wait for a selector, not a timeout:

```python
# WRONG — fragile
page.goto(url)
page.wait_for_timeout(5000)
rows = page.locator(".results tr").all()

# RIGHT — robust
page.goto(url, wait_until="domcontentloaded")
page.wait_for_selector(".results tr", timeout=15_000)
rows = page.locator(".results tr").all()
```

**3. Console error capture**

For the live verification gate, capture all console errors:

```python
console_errors = []
page.on("console", lambda msg: console_errors.append(msg.text) if msg.type == "error" else None)
page.on("pageerror", lambda exc: console_errors.append(f"pageerror: {exc}"))
```

**4. Download capture**

For verifying CSV exports:

```python
with page.expect_download(timeout=8000) as dl_info:
    page.locator("#export-csv").click()
download = dl_info.value
download.save_as(temp_path)
```

**5. Stealth (when reCAPTCHA scoring matters)**

Install `playwright-stealth`:
```
pip install playwright-stealth==2.0.0
```

Apply at context creation:
```python
from playwright_stealth import stealth_sync
context = browser.new_context(...)
stealth_sync(context)
```

Stealth defeats common automation-detection signals (navigator.webdriver, missing plugins, etc.). Reduces but doesn't eliminate reCAPTCHA scoring issues. Combine with realistic mouse movement for harder targets.

---

## undetected-chromedriver (Selenium-based stealth alternative)

**Version:** 3.5.5

**Use when:** Playwright stealth isn't enough for a particular site. Some sites detect Playwright specifically.

**Pattern:**

```python
import undetected_chromedriver as uc

driver = uc.Chrome(headless=True, version_main=130)  # Pin Chrome major version
driver.get(url)
elements = driver.find_elements("css selector", ".results tr")
driver.quit()
```

**Tradeoffs vs Playwright:** slower API, less ergonomic, but better at evading certain bot detection heuristics. Selenium 4.x with manager works similarly but lacks the auto-undetect features.

**Decision rule:** start with Playwright. Switch to undetected-chromedriver only if Playwright + stealth still fails on a specific source.

---

## CAPTCHA-solving service integration (2Captcha)

**When to use:** operator has explicitly opted in.

**Library:** `2captcha-python==1.5.1`

**Pattern for reCAPTCHA v3:**

```python
from twocaptcha import TwoCaptcha
import os

solver = TwoCaptcha(os.environ["TWOCAPTCHA_API_KEY"])
result = solver.recaptcha(
    sitekey="<site_key from page source>",
    url="<page_url>",
    version="v3",
    enterprise=0,  # 1 if reCAPTCHA Enterprise
    action="<action from page JS>",
    score=0.7,  # minimum acceptable score
)
token = result["code"]
```

Then attach `token` to the request to the source's API endpoint, typically as a hidden form field or header named `g-recaptcha-response` or similar.

**Cost:** ~$1.50–3 per 1,000 v3 tokens. Budget accordingly.

**Failure handling:** solver can fail (low-score result, timeout). Always wrap in try/except and fall back to public-records path or seeded session.

---

## Residential proxy integration

**When to use:** operator has opted in, source enforces IP-rate-limits aggressively.

**Library:** none specific — proxies are configured at the request session level.

**Pattern for `requests`:**

```python
import os

proxies = {
    "http": f"http://{os.environ['PROXY_USER']}:{os.environ['PROXY_PASS']}@{os.environ['PROXY_HOST']}:{os.environ['PROXY_PORT']}",
    "https": f"http://{os.environ['PROXY_USER']}:{os.environ['PROXY_PASS']}@{os.environ['PROXY_HOST']}:{os.environ['PROXY_PORT']}",
}
r = session.get(url, proxies=proxies)
```

**Pattern for Playwright:**

```python
context = browser.new_context(
    proxy={
        "server": f"http://{os.environ['PROXY_HOST']}:{os.environ['PROXY_PORT']}",
        "username": os.environ["PROXY_USER"],
        "password": os.environ["PROXY_PASS"],
    }
)
```

**Vendors:** Bright Data, Oxylabs, Smartproxy. Costs $30-80/month for residential bandwidth. Datacenter proxies are cheaper but more often blocked.

---

## ArcGIS REST endpoints (a special case)

Many state and county government data layers expose ArcGIS REST endpoints. These are JSON APIs, no auth, no rate limiting in most cases.

**Standard query pattern:**

```python
import requests

base = "https://maps.example.gov/arcgis/rest/services/<service>/MapServer/<layer>/query"
params = {
    "where": "COUNTY='<TARGET_COUNTY_NAME_UPPERCASE>'",
    "outFields": "*",
    "returnGeometry": "false",
    "resultOffset": 0,
    "resultRecordCount": 2000,
    "f": "json",
}
r = requests.get(base, params=params, timeout=60)
data = r.json()
```

**Pagination:** ArcGIS pages with `resultOffset` and `resultRecordCount`. Default max page size varies (500 for older services, 2000 for newer). Loop until `data["exceededTransferLimit"]` is false.

**Field discovery:** GET the layer URL itself (without `/query`) to see all available fields:

```python
r = requests.get("https://maps.example.gov/arcgis/rest/services/<service>/MapServer/<layer>?f=json")
fields = r.json()["fields"]
```

Use this to discover field names during recon, then filter explicitly in production scrapes.

---

## Selector strategy

When extracting from HTML or rendered DOM:

**1. Prefer ARIA labels and stable attributes** when present:
```python
page.locator('[aria-label="Search results"]')
page.locator('[data-test="lead-row"]')
```

**2. Otherwise, use CSS classes** — but only stable, semantic ones:
```python
page.locator(".lead-row")
page.locator(".search-results table tr")
```

**3. Avoid:** XPath unless you have no alternative. Avoid index-based selectors (`tr:nth-child(3)`) — they break when the source changes layout.

**4. Always verify** the selector returns expected count before extracting:
```python
expected = 80
actual = page.locator(".lead-row").count()
if actual < expected * 0.9:
    raise ValueError(f"Selector returned {actual} rows, expected {expected}+")
```

This is the parser-confidence check from `domain/05_review_queue_rules.md` made concrete.

---

## What to log from every scraper

Every scraper writes to `data/raw/<source>.scrape.log`:

```
[2026-05-05T18:32:36Z] start url=<url> params=<params>
[2026-05-05T18:32:38Z] status=200 records_in_response=80
[2026-05-05T18:32:39Z] parsed=80 valid=78 invalid=2
[2026-05-05T18:32:39Z] wrote data/raw/<source>.jsonl (78 records)
[2026-05-05T18:32:39Z] parser_confidence=0.975
[2026-05-05T18:32:39Z] done elapsed=3.2s
```

This log is consumed by `pipeline/refresh.py` for the heartbeat metric and by `pipeline/build_leads.py` for parser-confidence-based review-queue routing.
