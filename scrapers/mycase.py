"""
scrapers/mycase.py — Indiana Courts MyCase, Marion County MF filings (recon §4.3).

Source rank 1, PRIMARY_LEAD_SOURCE, P0, verdict GREEN. This is the county's P0
distress source and the one that satisfies the build gate.

Recon established (do not re-probe):
  POST https://public.courts.in.gov/mycase/Search/SearchCases  -> HTTP 200 JSON
  no auth, no cookie, no enforced CAPTCHA, no observed rate limiting
  CountyCode "49" = Marion; Categories ["CV"] = civil
  TotalResults saturates at 1001 and at most 500 rows return per call, so the
  harvest slices ONE DAY AT A TIME and stays well under the cap.

MF - Mortgage Foreclosure is the canonical foreclosure ORIGINATION event in
Indiana (judicial-only state). The sheriff sale is a downstream stage. Filings
concentrate in court 49D33.

Search-constraint note: the recon's "exact-match party search only, no wildcards"
constraint belongs to the RECORDER (§4.1 `UseWildcardSearches: false`). This
adapter does no name search at all — it enumerates by filing date, which avoids
the question entirely.

robots.txt: /mycase/Search/SearchCases is NOT disallowed and is used here.
/mycase/Case/* (case detail) IS disallowed and is NOT fetched.

Run:
  .venv\\Scripts\\python.exe scrapers\\mycase.py --start 2026-06-01 --end 2026-06-05
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    OUT_DIR, banner, http_json, log, party, raw_event, stable_id, to_review,
    write_jsonl, write_raw,
)

SOURCE_ID = "mycase_courts"
SEARCH_URL = "https://public.courts.in.gov/mycase/Search/SearchCases"
REFERER = "https://public.courts.in.gov/mycase/"
COUNTY_CODE = "49"

# Indiana judicial foreclosure complaint. See OPEN_ITEMS.md FG-4: the framework
# registry has no FORECLOSURE_COMPLAINT canonical, so MF maps to LIS_PENDENS,
# whose lead_pattern is by_state_profile and resolves through
# state_rule_family: IN_judicial_foreclosure.
MF_CANONICAL = "LIS_PENDENS"

# Marion court case-type prefix -> canonical doc type. Case types confirmed by
# the recon's empirical sweep (§3.1, §4.3).
CASE_TYPE_CANONICAL = {
    "MF": MF_CANONICAL,                    # Mortgage Foreclosure
    "EV": "EVICTION_FILING",               # Evictions (two dockets)
    "TP": "TAX_DEED",                      # Verified Petition for Tax Deed
    "EU": "LETTERS_OF_ADMINISTRATION",     # Estate, Unsupervised
    "ES": "LETTERS_OF_ADMINISTRATION",     # Estate, Supervised
    "EM": "LETTERS_OF_ADMINISTRATION",     # Estate, Miscellaneous
}

# Which search Categories to request for a given case-type prefix. Probate types
# live under the PR category, everything else here under CV.
CATEGORY_FOR = {"EU": "PR", "ES": "PR", "EM": "PR"}

OUT_PATH = OUT_DIR / "raw" / "mycase" / "mycase_mf_events.jsonl"

_STYLE_SPLIT = re.compile(r"\s+(?:v\.?|vs\.?)\s+", re.IGNORECASE)


def _payload(day: date, take: int = 500, category: str = "CV") -> dict:
    d = day.strftime("%m/%d/%Y")
    return {
        "Mode": "ByCase", "CourtItemID": None, "CaseNum": None, "CiteNum": None,
        "CrossRefNum": None, "First": None, "Middle": None, "Last": None,
        "Business": None, "DoBStart": None, "DoBEnd": None, "OANum": None,
        "BarNum": None, "SoundEx": False,
        "Categories": [category], "Limits": None, "ActiveFlag": "All",
        "FileStart": d, "FileEnd": d, "CountyCode": COUNTY_CODE,
        "Skip": 0, "Take": take, "Sort": "CaseNumber ASC",
        "CaptchaAnswer": None,
    }


def _parties_from_style(style: str) -> list[dict]:
    """Style reads '<plaintiff/lender> v. <defendant(s)/borrower>' (recon §3.1)."""
    if not style:
        return []
    parts = _STYLE_SPLIT.split(style, maxsplit=1)
    out = []
    if parts and parts[0].strip():
        out.append(party(parts[0].strip(), "PL"))
    if len(parts) > 1 and parts[1].strip():
        # first individual defendant is the distressed owner; keep the whole
        # string as one DF party rather than guessing at comma boundaries
        out.append(party(parts[1].strip(), "DF"))
    return out


def _iso(mdy: str) -> str | None:
    """MM/DD/YYYY -> YYYY-MM-DD."""
    if not mdy:
        return None
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", mdy.strip())
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else None


def fetch_day(day: date, category: str = "CV") -> dict:
    return http_json(SEARCH_URL, method="POST", body=_payload(day, category=category),
                     headers={
                         "X-Requested-With": "XMLHttpRequest",
                         "Referer": REFERER,
                     })


def run(start: date, end: date, case_types: str | list[str] = "MF") -> list[dict]:
    if isinstance(case_types, str):
        case_types = [case_types]
    cats = sorted({CATEGORY_FOR.get(ct, "CV") for ct in case_types})
    banner(f"MYCASE — Marion County {'/'.join(case_types)} filings "
           f"{start.isoformat()} .. {end.isoformat()}")

    events: list[dict] = []
    total_scanned = 0
    day = start
    while day <= end:
        for category in cats:
            wanted = [ct for ct in case_types if CATEGORY_FOR.get(ct, "CV") == category]
            try:
                js = fetch_day(day, category)
            except Exception as exc:
                log(f"{day} [{category}]: FETCH FAILED {exc}")
                to_review(source_id=SOURCE_ID, reason="fetch_failed",
                          record={"date": day.isoformat(), "category": category,
                                  "error": str(exc)})
                continue

            write_raw("mycase", f"searchcases_{category}_{day.isoformat()}.json", js)
            results = js.get("Results") or []
            total_scanned += len(results)

            if js.get("TotalResults", 0) >= 1001:
                log(f"{day} [{category}]: RESULT CAP HIT ({js['TotalResults']}) — "
                    f"slice finer")
                to_review(source_id=SOURCE_ID, reason="result_cap_hit",
                          record={"date": day.isoformat(), "category": category,
                                  "total_results": js.get("TotalResults")})

            matched = [r for r in results
                       if any((r.get("CaseType") or "").startswith(ct) for ct in wanted)]
            log(f"{day} [{category}]: {len(results):>4} cases, "
                f"{len(matched):>3} matching {'/'.join(wanted)}")
            _emit(matched, events)
        day += timedelta(days=1)

    n = write_jsonl(OUT_PATH, events)
    log("")
    log(f"cases scanned    : {total_scanned:,}")
    log(f"cases captured   : {len(events):,}")
    log(f"wrote {n:,} raw_event records -> {OUT_PATH.relative_to(OUT_DIR.parent)}")
    log("parcel-keyed: 0 at ingest — MyCase carries no address or parcel "
        "(recon §4.3). MF rows are resolved afterwards by "
        "scrapers/mycase_sheriff_join.py; other case types stay UNRESOLVED.")
    return events


def _emit(matched: list[dict], events: list[dict]) -> None:
        for r in matched:
            case_no = r.get("CaseNumber")
            filed = _iso(r.get("FileDate"))
            prefix = (r.get("CaseType") or "")[:2]
            canonical = CASE_TYPE_CANONICAL.get(prefix, MF_CANONICAL)
            ev = raw_event(
                raw_event_id=stable_id("MC", case_no),
                source_id=SOURCE_ID,
                canonical_doc_type=canonical,
                raw_doc_type=r.get("CaseType"),
                source_url=SEARCH_URL,
                recorded_date=filed,
                event_date=filed,
                instrument_number=case_no,
                parties=_parties_from_style(r.get("Style") or ""),
                # recon §4.3 / §1.5: MyCase carries NO address and NO parcel.
                # Emitted UNRESOLVED per 13_lead_origination_contract §13.14.
                parcel_id=None,
                situs_address=None,
                case_number=case_no,
                document_body_text=(r.get("Style") or ""),
                parser_name="mycase.mf",
                parser_confidence=95,
            )
            ev["_source_row"] = {
                "CaseID": r.get("CaseID"), "CaseToken": r.get("CaseToken"),
                "Court": r.get("Court"), "CourtCode": r.get("CourtCode"),
                "CaseStatus": r.get("CaseStatus"),
                "CaseStatusDate": r.get("CaseStatusDate"),
                "IsActive": r.get("IsActive"), "Parties": r.get("Parties"),
                "Attorneys": r.get("Attorneys"),
            }
            events.append(ev)

            # SB-2: no address => cannot resolve a parcel. Route, never drop.
            to_review(
                source_id=SOURCE_ID,
                reason="no_address_in_source_cannot_resolve_parcel",
                derivation_method="none_available",
                confidence=0,
                record={"case_number": case_no, "case_type": r.get("CaseType"),
                        "file_date": r.get("FileDate"), "court": r.get("Court"),
                        "style": r.get("Style")},
            )


def _d(s: str) -> date:
    y, m, dd = s.split("-")
    return date(int(y), int(m), int(dd))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-06-01")
    ap.add_argument("--end", default="2026-06-05")
    ap.add_argument("--case-types", nargs="*", default=["MF"],
                    help="case-type prefixes, e.g. MF EV TP EU ES EM")
    a = ap.parse_args()
    run(_d(a.start), _d(a.end), a.case_types)
