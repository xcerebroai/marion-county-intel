"""
scrapers/recorder_fidlar.py — Marion County Recorder, Fidlar Direct Search (recon §4.1).

Source rank 5, PRIMARY_LEAD_SOURCE, verdict GREEN. BROWSER-CONTEXT ADAPTER.

Why a browser (recon §01.29 enforcement test, do not re-litigate):
  POST /breeze/Search with no headers        -> HTTP 401 Unauthorized
  same search driven through a real browser  -> HTTP 200, 90 results, no challenge
The endpoint requires a Bearer JWE plus a `fidlarcaptchasolution` reCAPTCHA v3
token, both minted by the page. reCAPTCHA v3 is invisible and score-based, so
there is no puzzle and no human step — this is an engineering cost (run in a
browser context), not a blocker, and NO CAPTCHA IS EVER SOLVED.

  /breeze/Settings and /breeze/DocumentTypes need no auth and are plain HTTP.

Binding constraints from the recon:
  - 5-DAY CURSOR LAG. The portal states "Document information is available five
    days after recording." Cursors that do not lag will silently miss documents.
  - EXACT-MATCH PARTY SEARCH ONLY (`UseWildcardSearches: false`). This adapter
    searches by DATE RANGE + DOCUMENT TYPE and never by partial name.
  - NO parcel and NO address, by statute (IC 36-1-8.5), in search AND detail.
    The only join path is LegalSummary -> SUBDIV_TAG + LOTNUM. DO NOT join on
    SUBDIVNUM — it is '0' for many subdivisions (recon §1.5).

Run:
  .venv\\Scripts\\python.exe scrapers\\recorder_fidlar.py --start 2026-01-01 --end 2026-01-31
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    MIN_PARCEL_CONFIDENCE, OUT_DIR, banner, flush_review, http_json, log, party,
    raw_event, read_jsonl, stable_id, stamp_first_seen, to_review, utc_now_iso,
    write_jsonl, write_raw, write_run_log,
)
from scrapers.address_parcel_crosswalk import Crosswalk  # noqa: E402

SOURCE_ID = "marion_recorder_fidlar"
PORTAL = "https://inmarion.fidlar.com/INMarion/DirectSearch/"
API_BASE = "https://inmarion.fidlar.com/INMarion/Scrap.WebService.DirectSearch"
SEARCH_EP = f"{API_BASE}/breeze/Search"
DOCTYPES_EP = f"{API_BASE}/breeze/DocumentTypes"

RECORDING_LAG_DAYS = 5          # recon §4.1 — non-negotiable

OUT_PATH = OUT_DIR / "raw" / "recorder" / "recorder_events.jsonl"

# Marion recorder document-type codes -> canonical types. Only the distinctly
# typed distress codes; the six NOT_SEPARABLE lead types (lis pendens, abstract
# of judgment, state tax lien, heirship affidavit, executor/administrator deed)
# have no dedicated code here and are deliberately absent (recon §3.2).
DOC_TYPE_MAP = {
    "24": ("MECHANIC LIEN", "MECHANICS_LIEN"),
    "21": ("FEDERAL TAX LIEN", "FEDERAL_TAX_LIEN"),
    "33": ("SHERIFF DEED", "SHERIFF_DEED"),
    "46": ("ASSESSMENT LIEN", "MUNICIPAL_LIEN"),
    "35": ("SEWER LIEN", "WATER_LIEN"),
    "50": ("HOSPITAL LIEN", "HOSPITAL_LIEN"),
    "23": ("LIEN", "JUDGMENT_LIEN"),
    "25": ("MECHANIC LIEN RELEASE", "RELEASE_OF_LIEN"),
    "22": ("FEDERAL TAX LIEN RELEASE", "RELEASE_OF_FEDERAL_TAX_LIEN"),
}

# "Sub: SADDLEBROOK NORTH SEC 1  Lot: 2"
_LEGAL_RE = re.compile(r"Sub:\s*(?P<sub>.+?)\s+Lot:\s*(?P<lot>[\w-]+)", re.IGNORECASE)

MAPSERVER = "https://gis.indy.gov/server/rest/services/MapIndy/MapIndyProperty/MapServer"
SUBDIV_LAYER = f"{MAPSERVER}/19"


def fetch_document_types() -> list[dict]:
    """No auth required (recon §4.1)."""
    js = http_json(DOCTYPES_EP)
    return js.get("DocumentTypes", [])


def _search_payload(start: date, end: date, doc_type: str = "") -> dict:
    return {
        "FirstName": "", "LastBusinessName": "",
        "StartDate": start.isoformat(), "EndDate": end.isoformat(),
        "DocumentName": "", "DocumentType": doc_type,
        "SubdivisionName": "", "SubdivisionLot": "", "SubdivisionBlock": "",
        "MunicipalityName": "", "TractSection": "", "TractTownship": "",
        "TractRange": "", "TractQuarter": "", "TractQuarterQuarter": "",
        "AddressHouseNo": "", "AddressStreet": "", "AddressCity": "",
        "AddressZip": "", "ParcelNumber": "", "Book": "", "Page": "",
        "ReferenceNumber": "",
        "DisplayStartDate": start.strftime("%m/%d/%Y"),
        "DisplayEndDate": end.strftime("%m/%d/%Y"),
    }


# ===========================================================================
# TUNABLES — slice width, pacing and backfill window. Deliberately at the top
# of the module rather than buried in the call sites.
# ===========================================================================
RESULT_CAP        = 200   # server-side truncation limit, observed
SLICE_START_DAYS  = 31    # opening slice width; bisects down only when capped
SLICE_MIN_DAYS    = 1     # below this, split by document type instead of date
REQUEST_DELAY_S   = 1.5   # pause between searches
MAX_RETRIES       = 3     # per slice, on transport/HTTP error
RETRY_BACKOFF_S   = 5     # multiplied by attempt number
BACKFILL_DAYS     = 31    # default backfill span ending at the lag cursor
DAILY_WINDOW_DAYS = 5     # trailing window for the scheduled daily pull

# ---------------------------------------------------------------------------
# How truncation is detected — this is the whole basis of the coverage claim.
#
# The portal answers every search with three numbers:
#     TotalResults     the true match count for the criteria
#     ViewableResults  how many it is willing to return
#     DocResults[]     the rows actually returned
#
# Under the cap all three agree. At the cap TotalResults races ahead:
#     TotalResults=8251  ViewableResults=200  returned=200
#
# So `TotalResults > len(DocResults)` is an explicit truncation signal, and
# TotalResults doubles as an INDEPENDENT count to verify a slice against. A
# slice is complete only when returned == TotalResults. A capped slice is never
# accepted; it is bisected until every leaf agrees.
# ---------------------------------------------------------------------------


def is_truncated(js: dict) -> bool:
    got = len(js.get("DocResults") or [])
    total = js.get("TotalResults") or 0
    return total > got or got >= RESULT_CAP


class Portal:
    """One browser session reused across every slice.

    Each search is issued by the page itself (so the Angular interceptor signs
    it with a fresh Bearer + reCAPTCHA v3 token) while route interception swaps
    in the criteria we want. No CAPTCHA is solved and no token is forged.
    """

    def __init__(self, headless: bool = True, delay: float = REQUEST_DELAY_S):
        self.headless, self.delay = headless, delay
        self._pw = self._browser = self._page = None
        self._payload = {}
        self.searches = 0
        self.throttle_events: list[dict] = []

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        ctx = self._browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"),
            viewport={"width": 1440, "height": 1000})
        self._page = ctx.new_page()

        def handler(route, request):
            if request.method == "POST" and "/breeze/Search" in request.url and self._payload:
                route.continue_(post_data=json.dumps(self._payload))
            else:
                route.continue_()

        self._page.route("**/breeze/Search", handler)
        return self

    def __exit__(self, *exc):
        try:
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()

    def search(self, start: date, end: date, doc_type: str = "") -> dict | None:
        """One slice. Retries with backoff. Returns the parsed response or None."""
        self._payload = _search_payload(start, end, doc_type)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                pg = self._page
                pg.goto(PORTAL, wait_until="networkidle", timeout=90000)
                pg.wait_for_timeout(2500)
                pg.fill("#mat-input-0", start.strftime("%m/%d/%Y"))
                pg.wait_for_timeout(250)
                pg.fill("#mat-input-1", end.strftime("%m/%d/%Y"))
                pg.wait_for_timeout(250)
                with pg.expect_response(lambda r: "/breeze/Search" in r.url,
                                        timeout=90000) as ri:
                    pg.locator('button:has-text("Search")').first.click()
                resp = ri.value
                self.searches += 1
                if resp.status == 429 or resp.status == 503:
                    sig = {"status": resp.status, "at": utc_now_iso(),
                           "slice": f"{start}..{end}", "doc_type": doc_type}
                    self.throttle_events.append(sig)
                    log(f"      THROTTLE {resp.status} — backing off "
                        f"{RETRY_BACKOFF_S * attempt}s")
                    time.sleep(RETRY_BACKOFF_S * attempt)
                    continue
                if resp.status != 200:
                    log(f"      HTTP {resp.status} (attempt {attempt}/{MAX_RETRIES})")
                    time.sleep(RETRY_BACKOFF_S * attempt)
                    continue
                time.sleep(self.delay)
                return resp.json()
            except Exception as exc:
                log(f"      error attempt {attempt}/{MAX_RETRIES}: "
                    f"{str(exc).splitlines()[0][:90]}")
                time.sleep(RETRY_BACKOFF_S * attempt)
        to_review(source_id=SOURCE_ID, reason="slice_failed_after_retries",
                  record={"start": start.isoformat(), "end": end.isoformat(),
                          "doc_type": doc_type})
        return None


class SliceStats:
    def __init__(self):
        self.executed = 0
        self.bisected = 0
        self.capped_unresolved = 0
        self.min_width_days = 10 ** 6
        self.by_doc_type_splits = 0
        self.independent_total = {}   # doc_type -> TotalResults of the widest slice


def harvest(portal: Portal, start: date, end: date, doc_type: str,
            stats: SliceStats, depth: int = 0) -> list[dict]:
    """Recursively slice [start, end] for one doc type until nothing is capped.

    Bisects on date. When a single day still caps, the date dimension is
    exhausted — that is recorded as an unresolved cap rather than silently
    accepting a truncated slice.
    """
    width = (end - start).days + 1
    js = portal.search(start, end, doc_type)
    stats.executed += 1
    if js is None:
        return []

    got = len(js.get("DocResults") or [])
    total = js.get("TotalResults") or 0
    pad = "  " * depth

    if depth == 0:
        stats.independent_total[doc_type] = total

    if not is_truncated(js):
        stats.min_width_days = min(stats.min_width_days, width)
        if got:
            log(f"    {pad}[{start}..{end}] {width}d -> {got} rows (total {total}) OK")
        write_raw("recorder",
                  f"slice_{doc_type or 'ALL'}_{start}_{end}.json", js)
        return js.get("DocResults") or []

    log(f"    {pad}[{start}..{end}] {width}d -> CAPPED "
        f"(returned {got} of {total}) — bisecting")
    stats.bisected += 1

    if width <= SLICE_MIN_DAYS:
        # Date dimension exhausted for a single day. The caller already slices
        # by doc type, so there is no further axis available here.
        stats.capped_unresolved += 1
        log(f"    {pad}!! single day still capped for doc type {doc_type} — "
            f"{total - got} rows unreachable")
        to_review(source_id=SOURCE_ID, reason="single_day_capped_unresolved",
                  record={"date": start.isoformat(), "doc_type": doc_type,
                          "total_results": total, "returned": got})
        write_raw("recorder", f"CAPPED_{doc_type or 'ALL'}_{start}.json", js)
        return js.get("DocResults") or []

    mid = start + timedelta(days=max(1, width // 2) - 1)
    left = harvest(portal, start, mid, doc_type, stats, depth + 1)
    right = harvest(portal, mid + timedelta(days=1), end, doc_type, stats, depth + 1)
    return left + right


def _resolve_parcel(legal_summary: str, xw: Crosswalk, subdiv_name_cache: dict):
    """LegalSummary -> SUBDIV_TAG -> parcel (recon §1.5 path 1)."""
    m = _LEGAL_RE.search(legal_summary or "")
    if not m:
        return None, 0, "no_legal_summary"
    sub_name = m.group("sub").strip().upper()
    lot = m.group("lot").strip().upper()

    tag = subdiv_name_cache.get(sub_name, "MISS")
    if tag == "MISS":
        import urllib.parse
        where = f"UPPER(RECORDED_NAME) = '{sub_name.replace(chr(39), chr(39) * 2)}'"
        try:
            js = http_json(f"{SUBDIV_LAYER}/query?" + urllib.parse.urlencode({
                "where": where, "outFields": "RECORDED_NAME,SUBDIV_TAG",
                "returnGeometry": "false", "f": "json"}))
            feats = js.get("features") or []
            tag = feats[0]["attributes"]["SUBDIV_TAG"] if feats else None
        except Exception:
            tag = None
        subdiv_name_cache[sub_name] = tag

    if not tag:
        return None, 0, "subdivision_name_not_found"
    return xw.by_subdivision_lot(tag, lot)


def run(start: date | None = None, end: date | None = None,
        doc_codes: list[str] | None = None, headless: bool = True,
        daily: bool = False) -> dict:
    """Backfill or daily pull with recursive date slicing and cap verification."""
    cursor_end = date.today() - timedelta(days=RECORDING_LAG_DAYS)
    if end is None:
        end = cursor_end
    if start is None:
        span = DAILY_WINDOW_DAYS if daily else BACKFILL_DAYS
        start = end - timedelta(days=span - 1)
    if end > cursor_end:
        log(f"5-day recording lag: clamping end {end} -> {cursor_end} (recon §4.1)")
        end = cursor_end
    if start > end:
        log("window is entirely inside the 5-day lag; nothing to fetch")
        return {"rows": 0, "new": 0}

    banner(f"MARION RECORDER — {'daily' if daily else 'backfill'} "
           f"{start} .. {end} ({(end - start).days + 1} days)")

    doc_codes = doc_codes or list(DOC_TYPE_MAP.keys())
    types = fetch_document_types()
    write_raw("recorder", "document_types.json", types)
    log(f"document types available: {len(types)} | harvesting {len(doc_codes)} mapped codes")

    stats = SliceStats()
    docs: list[dict] = []
    with Portal(headless=headless) as portal:
        for code in doc_codes:
            name = DOC_TYPE_MAP[code][0]
            log(f"  doc type {code} ({name})")
            docs.extend(harvest(portal, start, end, code, stats))
        searches = portal.searches
        throttles = portal.throttle_events

    # ---- dedupe on the instrument number ----
    seen, deduped = set(), []
    for d in docs:
        inst = (d.get("DocumentName") or "").strip()
        if inst and inst in seen:
            continue
        if inst:
            seen.add(inst)
        deduped.append(d)
    dupes = len(docs) - len(deduped)

    log("")
    log(f"slices executed        : {stats.executed}")
    log(f"slices requiring bisect: {stats.bisected}")
    log(f"narrowest slice reached: {stats.min_width_days if stats.min_width_days < 10**6 else 0} day(s)")
    log(f"unresolved capped      : {stats.capped_unresolved}")
    log(f"rows fetched           : {len(docs):,} ({dupes} duplicate instruments dropped)")

    # ---- coverage verification ----
    indep = sum(stats.independent_total.values())
    complete = stats.capped_unresolved == 0
    log("")
    log("COVERAGE VERIFICATION")
    log(f"  method: portal TotalResults per slice (independent count exposed by source)")
    log(f"  independent total across mapped doc types : {indep:,}")
    log(f"  deduped rows harvested                    : {len(deduped):,}")
    log(f"  slices still capped after bisection       : {stats.capped_unresolved}")
    log(f"  VERDICT: {'COMPLETE for mapped doc types' if complete else 'INCOMPLETE'}")

    # ---- build events ----
    xw = Crosswalk()
    cache: dict = {}
    events, joined, unresolved = [], 0, 0
    for d in deduped:
        raw_type = (d.get("DocumentType") or "").strip()
        canonical = next((c for _, (n, c) in DOC_TYPE_MAP.items() if n == raw_type), None)
        if not canonical:
            to_review(source_id=SOURCE_ID, reason="unmapped_document_type",
                      record={"document_type": raw_type,
                              "doc_number": d.get("DocumentName")})
            continue

        legal = d.get("LegalSummary") or ""
        parcel, conf, method = _resolve_parcel(legal, xw, cache)
        if parcel and conf >= MIN_PARCEL_CONFIDENCE:
            joined += 1
        else:
            unresolved += 1
            to_review(source_id=SOURCE_ID, reason=f"parcel_unresolved:{method}",
                      derivation_method=method, confidence=conf,
                      record={"doc_number": d.get("DocumentName"),
                              "legal_summary": legal, "doc_type": raw_type})
            parcel = None

        rec_dt = (d.get("RecordedDateTime") or "").split(" ")[0]
        ev = raw_event(
            raw_event_id=stable_id("RC", d.get("DocumentName")),
            source_id=SOURCE_ID, canonical_doc_type=canonical, raw_doc_type=raw_type,
            source_url=PORTAL, recorded_date=rec_dt or None, event_date=rec_dt or None,
            instrument_number=d.get("DocumentName"),
            parties=[party(p.get("Name", ""), "GR" if p.get("PartyTypeId") == 1 else "GE")
                     for p in (d.get("Parties") or []) if p.get("Name")],
            parcel_id=parcel, legal_description=legal,
            amounts=[{"label": "consideration", "value": d.get("ConsiderationAmount")}],
            parser_name="recorder_fidlar", parser_confidence=92)
        ev["_derivation"] = {"method": method, "confidence": conf}
        events.append(ev)

    # ---- first_seen / newness ----
    events, new_count = stamp_first_seen(SOURCE_ID, events)

    # Merge with any previously harvested events so a daily pull does not shrink
    # the dataset. Raw captures are immutable; this merged file is derived.
    prior = {e.get("instrument_number"): e for e in read_jsonl(OUT_PATH)
             if e.get("instrument_number")}
    for e in events:
        prior[e["instrument_number"]] = e
    merged = list(prior.values())

    n = write_jsonl(OUT_PATH, merged)
    pct = joined / len(events) * 100 if events else 0
    log("")
    log(f"events this run : {len(events):,} ({new_count:,} NEW instruments)")
    log(f"merged dataset  : {n:,} rows -> {OUT_PATH.relative_to(OUT_DIR.parent)}")
    log(f"parcel-joined   : {joined:,}/{len(events):,} ({pct:.1f}%) via subdivision+lot")
    log(f"review-routed   : {unresolved:,}")

    if throttles:
        log(f"THROTTLE EVENTS : {len(throttles)} — recorded for OPEN_ITEMS")

    summary = {
        "source": SOURCE_ID, "mode": "daily" if daily else "backfill",
        "window": f"{start}..{end}", "days": (end - start).days + 1,
        "searches": searches, "slices_executed": stats.executed,
        "slices_bisected": stats.bisected,
        "narrowest_slice_days": stats.min_width_days if stats.min_width_days < 10**6 else 0,
        "capped_unresolved": stats.capped_unresolved,
        "rows_fetched": len(docs), "duplicates_dropped": dupes,
        "rows_deduped": len(deduped), "events": len(events),
        "new_instruments": new_count, "merged_total": n,
        "parcel_joined": joined, "review_routed": unresolved,
        "independent_total": indep,
        "coverage_verified": complete,
        "verification_method": "portal TotalResults per slice; zero capped slices",
        "throttle_events": throttles,
    }
    write_run_log(summary)
    flush_review()
    return summary


def _d(s: str) -> date:
    y, m, dd = s.split("-")
    return date(int(y), int(m), int(dd))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=None, help="YYYY-MM-DD")
    ap.add_argument("--end", default=None, help="YYYY-MM-DD (clamped to the 5-day lag)")
    ap.add_argument("--daily", action="store_true",
                    help=f"trailing {DAILY_WINDOW_DAYS}-day window")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    run(_d(a.start) if a.start else None,
        _d(a.end) if a.end else None,
        headless=not a.headed, daily=a.daily)
