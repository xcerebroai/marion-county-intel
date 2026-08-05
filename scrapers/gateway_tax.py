"""
scrapers/gateway_tax.py — Indiana Gateway tax bill / delinquency (recon §6.2).

Source rank 7, ENRICHMENT_SOURCE, verdict GREEN.

Recon established (do not re-probe):
  https://gateway.ifionline.org/TaxBillLookUp/Default.aspx  — DLGF, all 92
  counties, Marion = county value "49". ASP.NET WebForms postback, no CAPTCHA.
  It speaks ONLY the STATE parcel number: the punctuated form is accepted as
  input and the grid renders the digits-only form (= parcel_id_state_n). The
  LOCAL parcel number returns "No records to display."

  The parcel DETAIL page carries a "Penalty and Delinquent Taxes" block:
    Personal Property Late Penalty / Underpay Penalty
    Prior Year Delinquent Payment / Prior Year Delinquent Penalty
  plus assessed values, homestead AV (a free absentee-owner signal), tax rate,
  net liability and tax caps.

  Bulk export is UNPROVEN (OPEN_ITEMS.md SB-3) — the Export to Excel control is
  enabled but produced no download. This adapter is therefore PER_RECORD_ONLY:
  it enriches a known parcel set, it is not a discovery source.

  Stability caveat: the detail page leaks a SQL error and renders Total Credits
  blank. Treated as unknown rather than zero.

Run:
  .venv\\Scripts\\python.exe scrapers\\gateway_tax.py --parcels 49-06-05-112-029.000-600
  .venv\\Scripts\\python.exe scrapers\\gateway_tax.py --from-events --limit 5
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    OUT_DIR, banner, log, norm_state_parcel, read_jsonl, to_review,
    write_jsonl, write_raw,
)

SOURCE_ID = "indiana_gateway_tax_bills"
URL = "https://gateway.ifionline.org/TaxBillLookUp/Default.aspx"
COUNTY_VALUE = "49"

OUT_PATH = OUT_DIR / "raw" / "gateway" / "gateway_enrichment.jsonl"
PARCEL_MASTER = OUT_DIR / "raw" / "crosswalk" / "parcel_master.jsonl"

_MONEY = r"\$?-?[\d,]+\.\d{2}"

FIELDS = {
    "total_gross_assessed_value": r"Total Gross Assessed Value\s*(" + _MONEY + ")",
    "homestead_av": r"Gross AV of Homestead Property\s*(" + _MONEY + ")",
    "other_residential_av": r"Gross AV of Other Residential Property and Farmland\s*(" + _MONEY + ")",
    "total_net_assessed_value": r"Total Net Assessed Value\s*(" + _MONEY + ")",
    "local_tax_rate": r"Local Tax Rate\s*(" + _MONEY + ")",
    "gross_tax": r"Gross Tax\s*(" + _MONEY + ")",
    "net_current_liability": r"Net Current Property Tax Liability\s*(" + _MONEY + ")",
    "property_tax_cap": r"Property Tax Cap\s*(" + _MONEY + ")",
    "pp_late_penalty": r"Personal Property Late Penalty\s*(" + _MONEY + ")",
    "pp_underpay_penalty": r"Personal Property Underpay Penalty\s*(" + _MONEY + ")",
    "prior_year_delinquent_payment": r"Prior Year Delinquent Payment\s*(" + _MONEY + ")",
    "prior_year_delinquent_penalty": r"Prior Year Delinquent Penalty\s*(" + _MONEY + ")",
}


def _money(s):
    if not s:
        return None
    try:
        return float(s.replace("$", "").replace(",", ""))
    except ValueError:
        return None


def fetch_parcels(parcels: list[str], pay_year: str = "2025",
                  headless: bool = True) -> list[dict]:
    from playwright.sync_api import sync_playwright

    out = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx = browser.new_context(
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/151.0.0.0 Safari/537.36"),
            viewport={"width": 1440, "height": 1400},
        )
        page = ctx.new_page()

        for i, parcel in enumerate(parcels, 1):
            try:
                page.goto(URL, wait_until="networkidle", timeout=90000)
                page.wait_for_timeout(2000)
                page.select_option('select[name="ctl00$cph_Main$yearDdl"]', pay_year)
                page.wait_for_load_state("networkidle"); page.wait_for_timeout(2000)
                page.select_option('select[name="ctl00$cph_Main$countyDdl"]', COUNTY_VALUE)
                page.wait_for_load_state("networkidle"); page.wait_for_timeout(2500)
                page.fill('input[name="ctl00$cph_Main$parcelTxt"]', parcel)
                page.click('input[name="ctl00$cph_Main$searchBtn"]')
                page.wait_for_load_state("networkidle"); page.wait_for_timeout(3000)

                grid = page.evaluate("""() => {
                    const t = document.querySelector('#ctl00_cph_Main_rg_TaxBill_ctl00');
                    if (!t) return null;
                    return Array.from(t.querySelectorAll('tr')).map(
                        r => Array.from(r.cells).map(c => c.innerText.trim()));
                }""")
                if grid and len(grid) >= 2:
                    log(f"  [{i}/{len(parcels)}] {parcel}: grid row -> {grid[1][:4]}")
                if not grid or len(grid) < 2 or "No records" in " ".join(grid[1]):
                    log(f"  [{i}/{len(parcels)}] {parcel}: no records")
                    to_review(source_id=SOURCE_ID, reason="no_gateway_record",
                              record={"parcel_id_state": parcel, "pay_year": pay_year})
                    continue

                row = grid[1]
                # Drill into the detail page. The postback triggers a full
                # navigation, which destroys the JS execution context — so the
                # evaluate must be wrapped in an explicit navigation wait rather
                # than followed by one.
                try:
                    with page.expect_navigation(wait_until="networkidle", timeout=60000):
                        page.evaluate(
                            "() => __doPostBack("
                            "'ctl00$cph_Main$rg_TaxBill$ctl00$ctl04$parcelNumberBtn','')")
                    page.wait_for_timeout(2500)
                except Exception as nav_exc:
                    log(f"      detail postback did not navigate "
                        f"({str(nav_exc).splitlines()[0][:60]}); using grid row only")
                text = page.evaluate("() => document.body.innerText")
                write_raw("gateway", f"detail_{parcel.replace('.', '_')}.txt", text)

                rec = {
                    "source_id": SOURCE_ID,
                    "parcel_id_state": parcel,
                    "parcel_id_state_n": re.sub(r"\D", "", parcel),
                    "pay_year": pay_year,
                    "taxpayer": row[2] if len(row) > 2 else None,
                    "total_tax_bill": _money(row[3]) if len(row) > 3 else None,
                    "source_url": URL,
                }
                for key, pat in FIELDS.items():
                    m = re.search(pat, text)
                    rec[key] = _money(m.group(1)) if m else None

                rec["is_delinquent"] = any(
                    (rec.get(k) or 0) > 0 for k in
                    ("prior_year_delinquent_payment", "prior_year_delinquent_penalty",
                     "pp_late_penalty", "pp_underpay_penalty"))
                # homestead AV of 0 => no homestead deduction => non-owner-occupied
                rec["absentee_signal"] = (rec.get("homestead_av") == 0.0)
                rec["total_credits_unreliable"] = True   # recon §6.2 SQL error

                out.append(rec)
                log(f"  [{i}/{len(parcels)}] {parcel}: bill={rec['total_tax_bill']} "
                    f"delinquent={rec['is_delinquent']} absentee={rec['absentee_signal']}")
            except Exception as exc:
                log(f"  [{i}/{len(parcels)}] {parcel}: FAILED {str(exc).splitlines()[0][:90]}")
                to_review(source_id=SOURCE_ID, reason="gateway_fetch_failed",
                          record={"parcel_id_state": parcel, "error": str(exc)[:300]})

        browser.close()
    return out


def run(parcels: list[str] | None = None, from_events: bool = False,
        limit: int = 5, headless: bool = True) -> list[dict]:
    banner("INDIANA GATEWAY — per-parcel tax bill + delinquency enrichment")

    if from_events or not parcels:
        rows = read_jsonl(PARCEL_MASTER)[:limit]
        parcels = [r["parcel_id_state"] for r in rows if r.get("parcel_id_state")]
        log(f"parcel set from crosswalk parcel_master: {len(parcels)}")

    parcels = [p for p in (norm_state_parcel(x) for x in (parcels or [])) if p]
    if not parcels:
        log("no valid STATE parcel numbers supplied — Gateway speaks only that key")
        return []

    log(f"enriching {len(parcels)} parcel(s) (PER_RECORD_ONLY; bulk export unproven)")
    recs = fetch_parcels(parcels, headless=headless)
    n = write_jsonl(OUT_PATH, recs)
    log(f"wrote {n} enrichment records -> {OUT_PATH.relative_to(OUT_DIR.parent)}")
    if recs:
        log(f"delinquent: {sum(1 for r in recs if r['is_delinquent'])}/{len(recs)} | "
            f"absentee: {sum(1 for r in recs if r['absentee_signal'])}/{len(recs)}")
    return recs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--parcels", nargs="*", default=None)
    ap.add_argument("--from-events", action="store_true")
    ap.add_argument("--limit", type=int, default=5)
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    run(parcels=a.parcels, from_events=a.from_events, limit=a.limit,
        headless=not a.headed)
