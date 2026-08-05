"""
scrapers/mycase_sheriff_join.py — resolve MyCase MF cases to a parcel.

This closes the gap the recon flagged as the hardest problem in the build
(§1.5 / OPEN_ITEMS.md SB-2): MyCase carries no address and no parcel, so its MF
foreclosure cases cannot be joined to a property on their own.

The recon proposed an address bridge via the sheriff sale list. The list turned
out to be better than that: its "Public Sold To List" rows carry the court
CAUSE NUMBER and the LOCAL PARCEL NUMBER on the same row, so the join is a
direct key lookup — no address normalization, no fuzzy matching, no owner-name
guessing (which recon §1.5 path 3 explicitly warns against).

    MyCase MF case_number ──┐
                            ├── cause_number ──> parcel_id_local ──> parcel_id_state
    Sheriff Sold To List ───┘

Lead-time note: a case only appears on the sheriff list once it has reached
sale, months after filing. So a batch of freshly-filed MF cases will have a LOW
match rate by construction — those parcels are not knowable yet from this
bridge. That is a property of the data, not a defect, and unmatched cases stay
UNRESOLVED in the review queue rather than being force-matched.

Run:
  .venv\\Scripts\\python.exe scrapers\\mycase_sheriff_join.py
  .venv\\Scripts\\python.exe scrapers\\mycase_sheriff_join.py --backfill-from-sheriff
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    OUT_DIR, banner, log, party, raw_event, read_jsonl, stable_id, to_review,
    write_jsonl,
)
from scrapers.address_parcel_crosswalk import Crosswalk  # noqa: E402

MYCASE_PATH = OUT_DIR / "raw" / "mycase" / "mycase_mf_events.jsonl"
SHERIFF_PATH = OUT_DIR / "raw" / "sheriff_sale" / "sheriff_sale_events.jsonl"
OUT_PATH = OUT_DIR / "raw" / "mycase" / "mycase_mf_resolved.jsonl"

JOIN_CONFIDENCE = 97   # direct key match on a court-issued cause number


def _sheriff_index() -> dict[str, dict]:
    idx = {}
    for e in read_jsonl(SHERIFF_PATH):
        cause = (e.get("property_refs") or {}).get("case_number")
        if not cause:
            continue
        idx[cause.upper()] = {
            "parcel_id_local": e["property_refs"].get("parcel_id"),
            "situs_address": e["property_refs"].get("situs_address"),
            "sfn": e.get("instrument_number"),
            "status": (e.get("document_body_text") or "").replace("PARCEL_STATUS: ", ""),
            "source_url": e.get("source_url"),
        }
    return idx


def _local_to_state(xw: Crosswalk) -> dict[str, str]:
    return {p["parcel_id_local"]: sp for sp, p in xw.parcels.items()
            if p.get("parcel_id_local")}


def backfill_from_sheriff(limit: int = 40) -> list[dict]:
    """Fetch the MyCase records for MF cause numbers that appear on the sheriff
    list. Demonstrates the bridge end to end on cases that have actually reached
    sale, rather than on freshly-filed cases that cannot be on the list yet."""
    from scrapers.mycase import SEARCH_URL, REFERER, MF_CANONICAL, _parties_from_style, _iso
    from scrapers._common import http_json, write_raw

    idx = _sheriff_index()
    mf_causes = [c for c in idx if "-MF-" in c][:limit]
    log(f"MF cause numbers on the sheriff list: {len(mf_causes)} (fetching each)")

    out = []
    for i, cause in enumerate(mf_causes, 1):
        body = {
            "Mode": "ByCase", "CourtItemID": None, "CaseNum": cause, "CiteNum": None,
            "CrossRefNum": None, "First": None, "Middle": None, "Last": None,
            "Business": None, "DoBStart": None, "DoBEnd": None, "OANum": None,
            "BarNum": None, "SoundEx": False, "Categories": None, "Limits": None,
            "ActiveFlag": "All", "FileStart": None, "FileEnd": None,
            "CountyCode": "49", "Skip": 0, "Take": 10,
            "Sort": "CaseNumber ASC", "CaptchaAnswer": None,
        }
        try:
            js = http_json(SEARCH_URL, method="POST", body=body, headers={
                "X-Requested-With": "XMLHttpRequest", "Referer": REFERER})
        except Exception as exc:
            to_review(source_id="mycase_courts", reason="backfill_fetch_failed",
                      record={"cause": cause, "error": str(exc)[:200]})
            continue
        for r in (js.get("Results") or []):
            if (r.get("CaseNumber") or "").upper() != cause:
                continue
            filed = _iso(r.get("FileDate"))
            ev = raw_event(
                raw_event_id=stable_id("MC", r.get("CaseNumber")),
                source_id="mycase_courts", canonical_doc_type=MF_CANONICAL,
                raw_doc_type=r.get("CaseType"), source_url=SEARCH_URL,
                recorded_date=filed, event_date=filed,
                instrument_number=r.get("CaseNumber"),
                parties=_parties_from_style(r.get("Style") or ""),
                parcel_id=None, case_number=r.get("CaseNumber"),
                document_body_text=(r.get("Style") or ""),
                parser_name="mycase.mf.backfill", parser_confidence=95)
            ev["_source_row"] = {"Court": r.get("Court"),
                                 "CaseStatus": r.get("CaseStatus"),
                                 "IsActive": r.get("IsActive")}
            out.append(ev)
        if i % 10 == 0:
            log(f"  fetched {i}/{len(mf_causes)}")
    write_raw("mycase", "backfill_from_sheriff.json", {"causes": mf_causes})
    return out


def run(backfill: bool = False) -> dict:
    banner("MYCASE MF -> PARCEL  (bridge: sheriff Sold To List, key = cause number)")

    xw = Crosswalk()
    idx = _sheriff_index()
    l2s = _local_to_state(xw)
    log(f"sheriff rows indexed by cause number: {len(idx):,}")
    log(f"local->state parcel map             : {len(l2s):,}")

    events = read_jsonl(MYCASE_PATH)
    if backfill:
        extra = backfill_from_sheriff()
        seen = {e["instrument_number"] for e in events}
        added = [e for e in extra if e["instrument_number"] not in seen]
        log(f"backfilled {len(added)} MF cases that reached sheriff sale")
        events = events + added

    resolved, unresolved = 0, 0
    out = []
    for ev in events:
        cause = (ev.get("property_refs") or {}).get("case_number") or ev.get("instrument_number")
        hit = idx.get((cause or "").upper())
        if hit and hit.get("parcel_id_local"):
            local = hit["parcel_id_local"]
            state = l2s.get(local)
            ev["property_refs"]["parcel_id"] = state or local
            ev["property_refs"]["situs_address"] = hit.get("situs_address")
            ev["_parcel_keys"] = {
                "parcel_id_state": state,
                "parcel_id_state_n": (state or "").replace("-", "").replace(".", "") or None,
                "parcel_id_local": local,
            }
            ev["_derivation"] = {
                "method": "sheriff_cause_number_exact",
                "confidence": JOIN_CONFIDENCE if state else 85,
                "bridge_source": "sheriff_sale",
                "sheriff_sfn": hit.get("sfn"),
                "sheriff_status": hit.get("status"),
            }
            resolved += 1
        else:
            unresolved += 1
            to_review(
                source_id="mycase_courts",
                reason="mf_not_yet_on_sheriff_list",
                derivation_method="sheriff_cause_number_exact",
                confidence=0,
                record={"case_number": cause,
                        "file_date": ev.get("recorded_date"),
                        "note": "Case has not reached sheriff sale yet, so no "
                                "parcel is knowable from this bridge. Not "
                                "force-matched."},
            )
        out.append(ev)

    n = write_jsonl(OUT_PATH, out)
    pct = resolved / len(out) * 100 if out else 0
    log("")
    log(f"MF cases processed : {len(out):,}")
    log(f"resolved to parcel : {resolved:,} ({pct:.1f}%)")
    log(f"unresolved (review): {unresolved:,}")
    log(f"wrote {n:,} -> {OUT_PATH.relative_to(OUT_DIR.parent)}")
    return {"total": len(out), "resolved": resolved, "unresolved": unresolved}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill-from-sheriff", action="store_true",
                    help="also fetch MF cases that appear on the sheriff list")
    a = ap.parse_args()
    run(backfill=a.backfill_from_sheriff)
