"""
scrapers/tax_sale.py — Marion County tax sale lists (recon §4.2).

Source rank 3, PRIMARY_LEAD_SOURCE, verdict GREEN.

This is the only distress source in the county that arrives PRE-KEYED: the
"Parcel #" column is the LOCAL parcel number (PARCEL_C), so it joins straight to
the parcel layer with no address bridge and no crosswalk.

Documents (annual, text-extractable PDF, no OCR required):
  Parcel Status List   every parcel that reached tax-sale eligibility, with status
  Surplus Details      overbid/surplus owed, carries parcel AND situs address
  Purchase Details     sold parcels with final bid

Asset URLs come from the recon; indy.gov itself is a client-rendered SPA and is
not re-probed here (recon is complete).

Run:
  .venv\\Scripts\\python.exe scrapers\\tax_sale.py [--year 2025] [--limit N]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    OUT_DIR, RAW_DIR, banner, http_bytes, log, parcel_keys, party, raw_event,
    stable_id, to_review, write_jsonl, write_raw,
)

SOURCE_ID = "tax_sale_lists_indygov"
CDN = "https://us-east-1-indy.graphassets.com/ActDBC5rvRWeCZlNNnLrDz"
LANDING = "https://www.indy.gov/activity/tax-sale-reports"

# Recon-captured asset ids (§4.2). indy.gov is a JS SPA; these were recovered by
# rendering it during the headless-browser pass and are treated as known-good.
ASSETS = {
    2025: {
        "status":   "cmirh1egw3f1q06lpezlzfy5c",   # Parcel Status List
        "surplus":  "cmirh3o9i3ft606jx338y4yte",   # Surplus Details
        "purchase": "cmirh2pbc3fno06jxr7cdsm6c",   # Purchase Details (sold)
    },
}

OUT_PATH = OUT_DIR / "raw" / "tax_sale" / "tax_sale_events.jsonl"

# "A1  1000182 OWNER NAME" — sequence, 6-8 digit local parcel, then the rest.
_ROW_RE = re.compile(r"^\s*(?P<seq>[A-Z]?\d+)\s+(?P<parcel>\d{6,8})\s+(?P<rest>.+?)\s*$")
_MONEY_RE = re.compile(r"^-?[\d,]+\.\d{2}$")


def _pdf_text(pdf_bytes: bytes) -> str:
    """Layout-preserving extraction.

    Default pypdf extraction collapses these tables onto a single line with no
    delimiters. layout mode preserves the column geometry, which is what makes
    the rows parseable at all.

    Caveat: the source PDFs carry odd kerning, so extracted text contains stray
    spaces INSIDE words ("INDIANAP O LIS", "KNIGHT , RO Y ST O N"). Numeric
    fields survive this cleanly because whitespace is stripped before parsing;
    owner and address text does not. Tax sale is pre-keyed on the parcel number,
    so the noisy address is never used for joining. See OPEN_ITEMS.md CN-1.
    """
    from pypdf import PdfReader
    import io
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join((p.extract_text(extraction_mode="layout") or "") for p in reader.pages)


def _cols(line: str) -> list[str]:
    """Split a layout-mode row into columns.

    Columns are separated by long space runs; kerning noise inside a field is
    1-2 spaces. Splitting on 3+ spaces separates columns without shredding
    names.
    """
    return [re.sub(r"\s+", " ", c).strip() for c in re.split(r"\s{3,}", line.strip()) if c.strip()]


def _clean_num(tok: str) -> str:
    return re.sub(r"\s+", "", tok or "")


def _money(tok: str):
    tok = (tok or "").strip()
    if tok in ("", "-"):
        return None
    if not _MONEY_RE.match(tok):
        return None
    try:
        return float(tok.replace(",", ""))
    except ValueError:
        return None


def _row_base(line: str):
    """Return (seq, parcel_local, remaining_columns) or None if not a data row."""
    cols = _cols(line)
    if len(cols) < 3:
        return None
    seq = cols[0]
    if not re.fullmatch(r"[A-Z]?\d+", _clean_num(seq)):
        return None
    parcel = _clean_num(cols[1])
    if not re.fullmatch(r"\d{6,8}", parcel):
        return None
    return seq, parcel, cols[2:]


def _money_cols(cols: list[str]) -> list[float | None]:
    out = []
    for c in cols:
        c2 = _clean_num(c)
        if c2 == "-":
            out.append(None)
        elif _MONEY_RE.match(c2):
            out.append(_money(c2))
    return out


def parse_status_list(text: str) -> list[dict]:
    """Parcel Status List: seq | parcel | owner | status | face | overbid | purchase | updated."""
    rows = []
    for line in text.splitlines():
        base = _row_base(line)
        if not base:
            continue
        seq, parcel, rest = base
        # non-numeric leading columns are owner then status
        text_cols = [c for c in rest if not _MONEY_RE.match(_clean_num(c)) and _clean_num(c) != "-"]
        money = _money_cols(rest)
        rows.append({
            "seq": seq,
            "parcel_local": parcel,
            "owner_name": text_cols[0] if text_cols else None,
            "parcel_status": text_cols[1] if len(text_cols) > 1 else None,
            "face_value": money[0] if len(money) > 0 else None,
            "overbid": money[1] if len(money) > 1 else None,
            "purchase_amount": money[2] if len(money) > 2 else None,
            "_text_noisy": True,
            "_raw_line": line.strip()[:400],
        })
    return rows


def parse_surplus(text: str) -> list[dict]:
    """Surplus Details: bidder | parcel | owner | LOCATION (situs) | face | overbid | purchase."""
    rows = []
    for line in text.splitlines():
        base = _row_base(line)
        if not base:
            continue
        seq, parcel, rest = base
        text_cols = [c for c in rest if not _MONEY_RE.match(_clean_num(c)) and _clean_num(c) != "-"]
        money = _money_cols(rest)
        rows.append({
            "seq": seq,
            "parcel_local": parcel,
            "owner_name": text_cols[0] if text_cols else None,
            "situs_address": text_cols[1] if len(text_cols) > 1 else None,
            "face_value": money[0] if len(money) > 0 else None,
            "overbid_amount": money[1] if len(money) > 1 else None,
            "purchase_amount": money[2] if len(money) > 2 else None,
            "_text_noisy": True,
            "_raw_line": line.strip()[:400],
        })
    return rows


# Status vocabulary observed in the 2025 list (recon §4.2). Extraction kerning
# splits words ("Enc roa c hme nt Is s ue"), so matching is done on the
# alpha-only reduction of both sides rather than the raw string.
KNOWN_STATUSES = [
    # observed in the recon sample (§4.2)
    "Sold", "Paid", "Owner Redeemed", "Payment Plan", "Bankruptcy",
    "Encroachment Issues", "Removed - Miscellaneous",
    # additional statuses found when parsing the full 2025 list in this build —
    # the recon sampled only the first page, so these were not in its list
    "Removed - Treasurer", "County Lien", "Invalid Sale",
]
_ALPHA_RE = re.compile(r"[^A-Z]")


def _alpha(s: str | None) -> str:
    return _ALPHA_RE.sub("", (s or "").upper())


def canonical_status(raw_status: str | None) -> str | None:
    """De-kern a status string back to its canonical spelling, or None."""
    a = _alpha(raw_status)
    if not a:
        return None
    for known in KNOWN_STATUSES:
        ka = _alpha(known)
        if a == ka or a.startswith(ka) or ka.startswith(a):
            return known
    return None


# Marion status -> canonical doc type. See OPEN_ITEMS.md FG-1: the framework has
# no canonical type for "delinquent but not yet sold", so everything that reached
# the sale but did not sell maps to TAX_FORECLOSURE_NOTICE and the true status is
# preserved verbatim on the record.
def _canonical_for_status(status: str | None) -> str:
    if canonical_status(status) == "Sold":
        return "TAX_SALE_CERTIFICATE"
    return "TAX_FORECLOSURE_NOTICE"


def _events_from_status(rows: list[dict], year: int, url: str) -> list[dict]:
    out = []
    for r in rows:
        keys = parcel_keys(local_parcel=r["parcel_local"])
        if not keys["parcel_id_local"]:
            to_review(source_id=SOURCE_ID, reason="unparseable_local_parcel", record=r)
            continue
        status = canonical_status(r["parcel_status"])
        if status is None and r["parcel_status"]:
            to_review(source_id=SOURCE_ID, reason="unrecognized_parcel_status",
                      record={"parcel_local": r["parcel_local"],
                              "raw_status": r["parcel_status"]})
        r["parcel_status_canonical"] = status
        out.append(raw_event(
            raw_event_id=stable_id("TS", year, r["parcel_local"], r["seq"]),
            source_id=SOURCE_ID,
            canonical_doc_type=_canonical_for_status(r["parcel_status"]),
            raw_doc_type=f"TaxSaleStatus:{status or r['parcel_status']}",
            source_url=url,
            recorded_date=f"{year}-12-31",
            event_date=f"{year}-12-31",
            instrument_number=f"TAXSALE-{year}-{r['seq']}",
            parties=[party(r["owner_name"], "TP")] if r["owner_name"] else [],
            parcel_id=keys["parcel_id_local"],
            amounts=[
                {"label": "face_value", "value": r["face_value"]},
                {"label": "overbid", "value": r["overbid"]},
                {"label": "purchase_amount", "value": r["purchase_amount"]},
            ],
            document_body_text=f"PARCEL_STATUS: {status or r['parcel_status']}",
            parser_name="tax_sale.status_list",
            parser_confidence=95,
        ) | {"_parcel_keys": keys, "_source_row": r})
    return out


def _events_from_surplus(rows: list[dict], year: int, url: str) -> list[dict]:
    out = []
    for r in rows:
        keys = parcel_keys(local_parcel=r["parcel_local"])
        if not keys["parcel_id_local"]:
            to_review(source_id=SOURCE_ID, reason="unparseable_local_parcel", record=r)
            continue
        out.append(raw_event(
            raw_event_id=stable_id("TSS", year, r["parcel_local"], r["seq"]),
            source_id=SOURCE_ID,
            canonical_doc_type="SHERIFF_SALE_SURPLUS",   # OPEN_ITEMS FG-2
            raw_doc_type="TaxSaleSurplus",
            source_url=url,
            recorded_date=f"{year}-12-31",
            event_date=f"{year}-12-31",
            instrument_number=f"TAXSURPLUS-{year}-{r['seq']}",
            parties=[party(r["owner_name"], "TP")] if r["owner_name"] else [],
            parcel_id=keys["parcel_id_local"],
            situs_address=r["situs_address"],
            amounts=[
                {"label": "face_value", "value": r["face_value"]},
                {"label": "overbid_amount", "value": r["overbid_amount"]},
                {"label": "purchase_amount", "value": r["purchase_amount"]},
            ],
            parser_name="tax_sale.surplus",
            parser_confidence=95,
        ) | {"_parcel_keys": keys, "_source_row": r})
    return out


def run(year: int = 2025, limit: int | None = None) -> list[dict]:
    banner(f"TAX SALE LISTS — {year} (source rank 3, pre-keyed)")
    assets = ASSETS.get(year)
    if not assets:
        log(f"no recon-captured asset ids for {year}; known years: {sorted(ASSETS)}")
        return []

    events: list[dict] = []

    for kind in ("status", "surplus"):
        asset_id = assets.get(kind)
        if not asset_id:
            continue
        url = f"{CDN}/{asset_id}"
        log(f"fetching {kind} list ...")
        try:
            blob = http_bytes(url)
        except Exception as exc:
            log(f"  FETCH FAILED ({kind}): {exc}")
            to_review(source_id=SOURCE_ID, reason=f"fetch_failed_{kind}",
                      record={"url": url, "error": str(exc)})
            continue

        raw_path = write_raw("tax_sale", f"{year}_{kind}.pdf", blob, binary=True)
        log(f"  raw -> {raw_path.relative_to(RAW_DIR.parent.parent)} ({len(blob):,} bytes)")

        text = _pdf_text(blob)
        write_raw("tax_sale", f"{year}_{kind}.txt", text)

        if kind == "status":
            rows = parse_status_list(text)
            log(f"  parsed {len(rows):,} status rows")
            events.extend(_events_from_status(rows, year, url))
        else:
            rows = parse_surplus(text)
            log(f"  parsed {len(rows):,} surplus rows")
            events.extend(_events_from_surplus(rows, year, url))

    if limit:
        events = events[:limit]

    n = write_jsonl(OUT_PATH, events)
    log(f"wrote {n:,} raw_event records -> {OUT_PATH.relative_to(OUT_DIR.parent)}")

    keyed = sum(1 for e in events if e["property_refs"]["parcel_id"])
    log(f"parcel-keyed: {keyed:,}/{len(events):,} "
        f"({(keyed / len(events) * 100 if events else 0):.1f}%) — no crosswalk needed")
    return events


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()
    run(year=a.year, limit=a.limit)
