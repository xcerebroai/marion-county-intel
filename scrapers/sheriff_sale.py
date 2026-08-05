"""
scrapers/sheriff_sale.py — Marion County Sheriff sale list (recon §5.1).

Source rank 9, SUPPORTING_LEAD_SOURCE, verdict YELLOW.

Why this source matters more than its rank suggests: it is the ONLY source that
carries both a case number and a property address. MyCase MF cases have neither
an address nor a parcel (recon §4.3), so this list is the bridge that resolves
the foreclosure pipeline to a parcel. See OPEN_ITEMS.md SB-1 / SB-2.

RESOLVED IN THIS BUILD (updates OPEN_ITEMS.md SB-1): the registration page does
not contain the list, but it links to "Public Sold To List" PDFs under
/uploads/ and /ftp/IN/Marion/. Those PDFs carry, per row:

    SFN #           sale number
    Cause #         THE COURT CASE NUMBER, e.g. 49D33-2508-MF-039989
    Parcel Number   the LOCAL parcel number (PARCEL_C), e.g. 1057424
    Parcel Address  situs address
    Parcel Status   Sold / Removed / Sold To Third Party / Sold To Plaintiff

That is better than the recon predicted. The bridge does not need address
matching at all: the list joins MyCase MF cases to a parcel key DIRECTLY on the
cause number. See scrapers/mycase_sheriff_join.py.

Run:
  .venv\\Scripts\\python.exe scrapers\\sheriff_sale.py
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    OUT_DIR, banner, http_bytes, log, parcel_keys, raw_event, stable_id,
    to_review, write_jsonl, write_raw,
)

SOURCE_ID = "sheriff_sale"
LIST_URL = ("https://liveauctions.govease.com/PublicPortal/"
            "RegistrationDetail?AuctionID=1375&Edit=False")
INFO_PAGE = "https://www.indy.gov/activity/sheriff-real-estate-sales"

OUT_PATH = OUT_DIR / "raw" / "sheriff_sale" / "sheriff_sale_events.jsonl"

# Marion case numbers look like 49D33-2606-MF-030447
_CASE_RE = re.compile(r"\b49[A-Z]\d{2}-\d{4}-[A-Z]{2}-\d{5,6}\b")
_ADDR_RE = re.compile(r"\b\d{1,6}\s+[NSEW]?\s?[A-Z0-9][A-Z0-9 ]{2,30}"
                      r"(?:ST|AVE|AV|RD|DR|LN|CT|CIR|BLVD|PL|TER|PKWY|TRL|WAY)\b")


def fetch(headless: bool = True) -> dict:
    """Render the GovEase portal and archive what comes back."""
    from playwright.sync_api import sync_playwright

    result = {"status": None, "html": "", "text": "", "url": LIST_URL}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/151.0.0.0 Safari/537.36"),
            viewport={"width": 1440, "height": 1200},
        )
        page = ctx.new_page()
        try:
            resp = page.goto(LIST_URL, wait_until="networkidle", timeout=90000)
            result["status"] = resp.status if resp else None
            page.wait_for_timeout(6000)
            result["html"] = page.content()
            result["text"] = page.evaluate("document.body.innerText")
            result["url"] = page.url
        except Exception as exc:
            log(f"portal fetch failed: {str(exc).splitlines()[0][:140]}")
            to_review(source_id=SOURCE_ID, reason="portal_fetch_failed",
                      record={"url": LIST_URL, "error": str(exc)[:300]})
        finally:
            browser.close()
    return result


GOVEASE_ROOT = "https://liveauctions.govease.com"
_LIST_LINK_RE = re.compile(
    r'href="([^"]*(?:uploads|ftp/IN/Marion)[^"]*(?:List|SoldTo|Results)[^"]*\.pdf)"',
    re.IGNORECASE)

# Rows survive kerning noise if whitespace is stripped before matching.
_CAUSE_RE = re.compile(r"49[A-Z]\d{2}-\d{4}-[A-Z]{2}-\d{5,6}")
_SFN_RE = re.compile(r"^\d{2}\.\d{2}\.\d{4}\.\d{3}$")


def _dekern(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def discover_list_pdfs(html: str) -> list[str]:
    urls = []
    for m in _LIST_LINK_RE.findall(html or ""):
        u = m if m.startswith("http") else GOVEASE_ROOT + ("" if m.startswith("/") else "/") + m
        u = u.replace(" ", "%20")
        if u not in urls:
            urls.append(u)
    return urls


def parse_sold_to_list(text: str, source_url: str) -> list[dict]:
    """Parse a 'Public Sold To List' PDF.

    Columns: SFN # | Cause # | Parcel Number | Parcel Address | (Parcel Status)
    Addresses wrap across lines, so a row is assembled from the line carrying
    the cause number plus trailing address fragments.
    """
    rows: list[dict] = []
    lines = [l for l in (text or "").splitlines() if l.strip()]
    for i, line in enumerate(lines):
        flat = _dekern(line)
        m = _CAUSE_RE.search(flat)
        if not m:
            continue
        cause = m.group(0)

        cols = [re.sub(r"\s+", " ", c).strip()
                for c in re.split(r"\s{3,}", line.strip()) if c.strip()]
        sfn = next((_dekern(c) for c in cols if _SFN_RE.match(_dekern(c))), None)

        # parcel number: a 6-8 digit run that is not part of the cause number
        parcel = None
        for c in cols:
            d = _dekern(c)
            if re.fullmatch(r"\d{6,8}", d):
                parcel = d
                break

        # address: longest column containing a letter and a digit that is not
        # the cause or the parcel
        addr_parts = []
        for c in cols:
            d = _dekern(c)
            if d in (cause, parcel, sfn):
                continue
            if re.search(r"[A-Za-z]", c) and re.search(r"\d", c):
                addr_parts.append(c)
        # the address often wraps onto the previous/next line
        for j in (i - 1, i + 1):
            if 0 <= j < len(lines) and not _CAUSE_RE.search(_dekern(lines[j])):
                frag = re.sub(r"\s+", " ", lines[j]).strip()
                if re.search(r"(?i)indianapolis|,\s*IN\b|\b46\d{3}\b", frag):
                    addr_parts.append(frag)

        address = re.sub(r"\s+", " ", " ".join(addr_parts)).strip() or None
        status = next((c for c in cols if re.fullmatch(
            r"(?i)(sold|removed|sold to third part\w*|sold to plaintiff|"
            r"cancell?ed|withdrawn)", c.strip())), None)

        rows.append({"sfn": sfn, "cause_number": cause, "parcel_local": parcel,
                     "parcel_address": address, "parcel_status": status,
                     "source_url": source_url})
    return rows


def run(headless: bool = True) -> list[dict]:
    banner("SHERIFF SALE (GovEase) — Public Sold To List")
    log("registration page (free, no registration per recon §5.1):")
    log(f"  {LIST_URL}")

    res = fetch(headless=headless)
    log(f"HTTP {res['status']} | final url: {res['url']}")
    if not res["html"]:
        write_jsonl(OUT_PATH, [])
        return []

    html_path = write_raw("sheriff_sale", "govease_portal.html", res["html"])
    write_raw("sheriff_sale", "govease_portal.txt", res["text"])
    log(f"archived portal -> {html_path.name} ({len(res['html']):,} bytes)")

    pdf_urls = discover_list_pdfs(res["html"])
    log(f"list PDFs discovered on the page: {len(pdf_urls)}")
    for u in pdf_urls:
        log(f"  {u}")

    if not pdf_urls:
        to_review(source_id=SOURCE_ID, reason="no_list_pdfs_found_on_portal",
                  record={"url": LIST_URL, "archived_html": str(html_path)})
        write_jsonl(OUT_PATH, [])
        return []

    from pypdf import PdfReader
    import io

    events: list[dict] = []
    for u in pdf_urls:
        try:
            blob = http_bytes(u)
        except Exception as exc:
            log(f"  fetch failed {u}: {str(exc)[:90]}")
            to_review(source_id=SOURCE_ID, reason="list_pdf_fetch_failed",
                      record={"url": u, "error": str(exc)[:300]})
            continue
        name = u.rsplit("/", 1)[-1].replace("%20", "_")
        write_raw("sheriff_sale", name, blob, binary=True)

        reader = PdfReader(io.BytesIO(blob))
        text = "\n".join((p.extract_text(extraction_mode="layout") or "")
                         for p in reader.pages)
        write_raw("sheriff_sale", name + ".txt", text)

        rows = parse_sold_to_list(text, u)
        keyed = sum(1 for r in rows if r["parcel_local"])
        log(f"  {name}: {len(rows)} rows, {keyed} with a parcel number")

        for r in rows:
            keys = parcel_keys(local_parcel=r["parcel_local"])
            pid = keys["parcel_id_local"]
            if not pid:
                to_review(source_id=SOURCE_ID, reason="no_parcel_on_sheriff_row",
                          record=r)
            ev = raw_event(
                raw_event_id=stable_id("SS", r["cause_number"], r["sfn"] or ""),
                source_id=SOURCE_ID,
                source_role="SUPPORTING_EVENT_SOURCE",
                canonical_doc_type="SHERIFF_SALE",
                raw_doc_type=f"SheriffSale:{r['parcel_status'] or 'listed'}",
                source_url=u,
                recorded_date=None,
                event_date=None,
                instrument_number=r["sfn"] or r["cause_number"],
                parties=[],
                parcel_id=pid,
                situs_address=r["parcel_address"],
                case_number=r["cause_number"],
                document_body_text=f"PARCEL_STATUS: {r['parcel_status']}",
                parser_name="sheriff_sale.sold_to_list",
                parser_confidence=90,
            )
            ev["_parcel_keys"] = keys
            ev["_source_row"] = r
            events.append(ev)

    n = write_jsonl(OUT_PATH, events)
    keyed = sum(1 for e in events if e["property_refs"]["parcel_id"])
    log(f"wrote {n:,} raw_event records -> {OUT_PATH.relative_to(OUT_DIR.parent)}")
    log(f"parcel-keyed directly: {keyed:,}/{n:,} "
        f"({(keyed / n * 100 if n else 0):.1f}%) — no address matching required")
    log("this list is the MyCase MF bridge: it carries the court cause number "
        "AND the parcel key on the same row")
    return events


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    run(headless=not a.headed)
