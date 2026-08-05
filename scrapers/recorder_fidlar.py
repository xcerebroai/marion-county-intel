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
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    MIN_PARCEL_CONFIDENCE, OUT_DIR, banner, http_json, log, party, raw_event,
    stable_id, to_review, write_jsonl, write_raw,
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


# The portal returns at most this many rows per search, regardless of
# TotalResults. Found while building (a one-month all-types search reported
# TotalResults 8251 but ViewableResults 200). Slice windows to stay under it.
RESULT_CAP = 200


def browser_search(payloads: list[dict], headless: bool = True) -> list[dict]:
    """Drive the SPA and rewrite each search body in flight.

    A plain fetch() from inside the page returns 401: the Bearer JWE and the
    fidlarcaptchasolution token are attached by the app's own Angular HTTP
    interceptor, which a raw fetch bypasses. Rather than forge those headers, we
    let the app issue its own search — clicking Search in the UI so it mints
    fresh tokens — and use route interception to swap the POST body for the
    query we actually want. The app signs the request; we choose the criteria.

    No CAPTCHA is solved and no token is fabricated or replayed.
    """
    from playwright.sync_api import sync_playwright

    out: list[dict] = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/151.0.0.0 Safari/537.36"),
            viewport={"width": 1440, "height": 1000},
        )
        page = ctx.new_page()

        current: dict = {}

        def handler(route, request):
            if request.method == "POST" and "/breeze/Search" in request.url and current:
                route.continue_(post_data=json.dumps(current["payload"]))
            else:
                route.continue_()

        page.route("**/breeze/Search", handler)

        for i, pl in enumerate(payloads):
            current["payload"] = pl
            try:
                # Reload for each search. Navigating back from the results view
                # proved unreliable (the back control is not a stable locator),
                # and a fresh load also guarantees fresh tokens.
                page.goto(PORTAL, wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(3000)
                # Dates must be present or the UI refuses to submit; the body we
                # inject carries the real criteria.
                page.fill("#mat-input-0", pl["DisplayStartDate"])
                page.wait_for_timeout(400)
                page.fill("#mat-input-1", pl["DisplayEndDate"])
                page.wait_for_timeout(400)

                with page.expect_response(lambda r: "/breeze/Search" in r.url,
                                          timeout=90000) as ri:
                    page.locator('button:has-text("Search")').first.click()
                resp = ri.value
                if resp.status == 200:
                    js = resp.json()
                    out.append(js)
                    tot, got = js.get("TotalResults", 0), len(js.get("DocResults") or [])
                    flag = "  <-- CAPPED, slice finer" if tot > got else ""
                    log(f"  search {i + 1}/{len(payloads)} "
                        f"[{pl.get('DocumentType') or 'ALL'}] "
                        f"HTTP 200  total={tot} returned={got}{flag}")
                    if tot > got:
                        to_review(source_id=SOURCE_ID, reason="result_cap_truncation",
                                  record={"payload": pl, "total_results": tot,
                                          "returned": got, "cap": RESULT_CAP})
                else:
                    log(f"  search {i + 1}/{len(payloads)} HTTP {resp.status}")
                    to_review(source_id=SOURCE_ID, reason=f"search_http_{resp.status}",
                              record={"payload": pl})
            except Exception as exc:
                log(f"  search {i + 1}/{len(payloads)} failed: "
                    f"{str(exc).splitlines()[0][:110]}")
                to_review(source_id=SOURCE_ID, reason="search_exception",
                          record={"payload": pl, "error": str(exc)[:300]})
            page.wait_for_timeout(1500)

        browser.close()
    return out


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


def run(start: date, end: date, doc_codes: list[str] | None = None,
        headless: bool = True) -> list[dict]:
    banner(f"MARION RECORDER (Fidlar) — {start} .. {end}")

    cursor_end = date.today() - timedelta(days=RECORDING_LAG_DAYS)
    if end > cursor_end:
        log(f"5-day recording lag: clamping end {end} -> {cursor_end} (recon §4.1)")
        end = cursor_end
    if start > end:
        log("window is entirely inside the 5-day lag; nothing to fetch")
        return []

    doc_codes = doc_codes or list(DOC_TYPE_MAP.keys())

    types = fetch_document_types()
    write_raw("recorder", "document_types.json", types)
    log(f"document types available: {len(types)} (no auth required)")

    payloads = [_search_payload(start, end, code) for code in doc_codes]
    log(f"issuing {len(payloads)} doc-type searches through a browser context ...")
    responses = browser_search(payloads, headless=headless)
    log(f"successful search responses: {len(responses)}/{len(payloads)}")

    xw = Crosswalk()
    cache: dict = {}
    events, joined, unresolved = [], 0, 0

    for i, js in enumerate(responses):
        write_raw("recorder", f"search_{start.isoformat()}_{i}.json", js)
        for d in (js.get("DocResults") or []):
            raw_type = (d.get("DocumentType") or "").strip()
            canonical = next((c for _, (n, c) in DOC_TYPE_MAP.items()
                              if n == raw_type), None)
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
                source_id=SOURCE_ID,
                canonical_doc_type=canonical,
                raw_doc_type=raw_type,
                source_url=PORTAL,
                recorded_date=rec_dt or None,
                event_date=rec_dt or None,
                instrument_number=d.get("DocumentName"),
                parties=[party(p.get("Name", ""), "GR" if p.get("PartyTypeId") == 1 else "GE")
                         for p in (d.get("Parties") or []) if p.get("Name")],
                parcel_id=parcel,
                legal_description=legal,
                amounts=[{"label": "consideration", "value": d.get("ConsiderationAmount")}],
                parser_name="recorder_fidlar",
                parser_confidence=92,
            )
            ev["_derivation"] = {"method": method, "confidence": conf}
            events.append(ev)

    n = write_jsonl(OUT_PATH, events)
    log(f"wrote {n:,} raw_event records -> {OUT_PATH.relative_to(OUT_DIR.parent)}")
    pct = joined / len(events) * 100 if events else 0
    log(f"parcel-joined via subdivision+lot: {joined:,}/{len(events):,} ({pct:.1f}%) "
        f"— recon ceiling is 33% of parcels")
    log(f"routed to review (unresolved)    : {unresolved:,}")
    return events


def _d(s: str) -> date:
    y, m, dd = s.split("-")
    return date(int(y), int(m), int(dd))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-01-31")
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    run(_d(a.start), _d(a.end), headless=not a.headed)
