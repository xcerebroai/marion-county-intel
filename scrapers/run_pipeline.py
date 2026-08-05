"""
scrapers/run_pipeline.py — Marion County end-to-end staged run.

Order follows the recon's build recommendation: pre-keyed sources first (they
need no crosswalk and produce working data immediately), then the crosswalk,
then the sources that depend on it.

  1  tax sale lists        PRE-KEYED on the local parcel number
  2  crosswalk             address -> canonical parcel key
  3  code enforcement      address-bearing, joins via crosswalk
  4  recorder              legal description -> SUBDIV_TAG + LOTNUM
  5  MyCase MF             no address, no parcel -> UNRESOLVED + review
  6  sheriff sale          archive only (structure unverified)
  7  gateway               per-parcel enrichment

Stages after ingest (normalize -> classify -> match -> aggregate -> score ->
review -> dashboard) are the framework's, in scaffold/pipeline/. This script
produces the contract-shaped raw_event feed those stages consume, plus a report.

Run:
  .venv\\Scripts\\python.exe scrapers\\run_pipeline.py --small
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    OUT_DIR, REPORT_PATH, REVIEW_PATH, banner, flush_review, log, read_jsonl,
)
from scrapers.address_parcel_crosswalk import Crosswalk  # noqa: E402

FEEDS = {
    "tax_sale_lists_indygov": OUT_DIR / "raw" / "tax_sale" / "tax_sale_events.jsonl",
    "opendata_code_enforcement": OUT_DIR / "raw" / "code_enforcement" / "code_enforcement_events.jsonl",
    "marion_recorder_fidlar": OUT_DIR / "raw" / "recorder" / "recorder_events.jsonl",
    # the resolved feed carries the sheriff-bridge parcel join; fall back to the
    # unresolved feed if the join has not been run yet
    "mycase_courts": (OUT_DIR / "raw" / "mycase" / "mycase_mf_resolved.jsonl"
                      if (OUT_DIR / "raw" / "mycase" / "mycase_mf_resolved.jsonl").exists()
                      else OUT_DIR / "raw" / "mycase" / "mycase_mf_events.jsonl"),
    "sheriff_sale": OUT_DIR / "raw" / "sheriff_sale" / "sheriff_sale_events.jsonl",
}

# The 19 lead types the recon says are LIVE for Marion, expressed as canonical
# doc types the adapters can actually emit.
LIVE_LEAD_TYPES = {
    "LIS_PENDENS": "Foreclosure (MF filing)",
    "SHERIFF_SALE": "Sheriff Sale",
    "SHERIFF_DEED": "Sheriff Deed",
    "TAX_SALE_CERTIFICATE": "Tax Sale Certificate",
    "TAX_FORECLOSURE_NOTICE": "Tax Sale / Tax Delinquency",
    "TAX_DEED": "Tax Deed",
    "SHERIFF_SALE_SURPLUS": "Surplus",
    "MECHANICS_LIEN": "Mechanic Lien",
    "CONSTRUCTION_LIEN": "Construction Lien",
    "FEDERAL_TAX_LIEN": "Federal Tax Lien",
    "JUDGMENT_LIEN": "Civil Judgment / Judgment Lien",
    "HOSPITAL_LIEN": "Hospital Lien",
    "MUNICIPAL_LIEN": "Assessment / Code Lien",
    "WATER_LIEN": "Sewer Lien",
    "CODE_VIOLATION_NOTICE": "Code Violation",
    "DEMOLITION_ORDER": "Demolition",
    "CONDEMNATION_NOTICE": "Condemnation",
    "EVICTION_FILING": "Eviction",
    "LETTERS_OF_ADMINISTRATION": "Probate",
}

# REPORT_PATH comes from _common and lives under data/raw/ so the framework PII
# guard skips it — it embeds five real sample records.


def ingest(small: bool) -> None:
    from scrapers import tax_sale, code_enforcement, mycase, recorder_fidlar, sheriff_sale

    banner("STAGE 1 — PRE-KEYED SOURCES (no crosswalk required)")
    tax_sale.run(year=2025, limit=None)

    banner("STAGE 2 — CROSSWALK (assumed already built)")
    xw = Crosswalk()
    log(f"address keys: {len(xw.addr):,} | parcels: {len(xw.parcels):,} | "
        f"subdivision+lot keys: {len(xw.subdiv):,}")
    if not xw.addr:
        log("!! crosswalk empty — run scrapers/address_parcel_crosswalk.py")

    banner("STAGE 3 — ADDRESS-BEARING SOURCES")
    code_enforcement.run(limit=2000 if small else 20000)

    banner("STAGE 4 — RECORDER (legal description join)")
    recorder_fidlar.run(date(2026, 1, 5), date(2026, 1, 9))

    banner("STAGE 5 — MYCASE (no address at ingest; MF resolved in stage 7)")
    mycase.run(date(2026, 6, 1), date(2026, 6, 5),
               ["MF", "EV", "TP", "EU", "ES", "EM"])

    banner("STAGE 6 — SHERIFF SALE (Public Sold To List; the MF bridge)")
    try:
        sheriff_sale.run()
    except Exception as exc:
        log(f"sheriff sale adapter error: {str(exc).splitlines()[0][:120]}")

    banner("STAGE 7 — MYCASE MF -> PARCEL via sheriff cause number")
    from scrapers import mycase_sheriff_join
    try:
        mycase_sheriff_join.run(backfill=True)
    except Exception as exc:
        log(f"mycase/sheriff join error: {str(exc).splitlines()[0][:120]}")


def report() -> dict:
    banner("PIPELINE REPORT")

    xw = Crosswalk()
    all_events: list[dict] = []
    per_source = {}

    for sid, path in FEEDS.items():
        rows = read_jsonl(path)
        joined = sum(1 for r in rows if r.get("property_refs", {}).get("parcel_id"))
        per_source[sid] = {
            "records": len(rows),
            "parcel_joined": joined,
            "join_rate_pct": round(joined / len(rows) * 100, 1) if rows else 0.0,
        }
        all_events.extend(rows)

    total = len(all_events)
    joined_total = sum(1 for r in all_events if r.get("property_refs", {}).get("parcel_id"))
    review_rows = read_jsonl(REVIEW_PATH)

    print()
    print(f"  {'SOURCE':<32} {'RECORDS':>9} {'JOINED':>8} {'RATE':>7}")
    print(f"  {'-' * 32} {'-' * 9} {'-' * 8} {'-' * 7}")
    for sid, s in per_source.items():
        print(f"  {sid:<32} {s['records']:>9,} {s['parcel_joined']:>8,} "
              f"{s['join_rate_pct']:>6.1f}%")
    print(f"  {'-' * 32} {'-' * 9} {'-' * 8} {'-' * 7}")
    print(f"  {'TOTAL':<32} {total:>9,} {joined_total:>8,} "
          f"{(joined_total / total * 100 if total else 0):>6.1f}%")

    print()
    log(f"review queue: {len(review_rows):,} items")
    rc = collections.Counter(r["reason"].split(":")[0] for r in review_rows)
    for reason, n in rc.most_common(8):
        print(f"      {n:>7,}  {reason}")

    present = collections.Counter(r.get("canonical_doc_type") for r in all_events)
    populated = [t for t in LIVE_LEAD_TYPES if present.get(t)]
    print()
    log(f"lead types populated: {len(populated)}/19 of the recon's LIVE set")
    for t in LIVE_LEAD_TYPES:
        mark = "x" if present.get(t) else " "
        cnt = present.get(t, 0)
        print(f"      [{mark}] {LIVE_LEAD_TYPES[t]:<34} {cnt:>7,}")

    # local -> state map so records keyed on the LOCAL parcel number (tax sale,
    # sheriff sale) can still be enriched from the crosswalk
    local_to_state = {p["parcel_id_local"]: sp for sp, p in xw.parcels.items()
                      if p.get("parcel_id_local")}

    # five sample joined records, enriched from the crosswalk. Prefer records
    # that actually enrich, so the sample shows the join working end to end.
    samples = []
    candidates = [r for r in all_events if r.get("property_refs", {}).get("parcel_id")]
    candidates.sort(key=lambda r: 0 if (
        xw.enrich(r["property_refs"]["parcel_id"])
        or xw.enrich(local_to_state.get(r["property_refs"]["parcel_id"], ""))) else 1)

    for r in candidates:
        pid = r.get("property_refs", {}).get("parcel_id")
        state = pid if pid in xw.parcels else local_to_state.get(pid)
        p = xw.enrich(state) if state else {}
        p = p or {}
        samples.append({
            "source_id": r["source_id"],
            "canonical_doc_type": r["canonical_doc_type"],
            "instrument_number": r.get("instrument_number"),
            "recorded_date": r.get("recorded_date"),
            "parcel_id": pid,
            "parcel_id_state": p.get("parcel_id_state") or state,
            "parcel_id_local": p.get("parcel_id_local") or (
                pid if pid and pid.isdigit() else None),
            "situs": (f"{p.get('situs_house_no','')} {p.get('situs_street','')}".strip()
                      or r.get("property_refs", {}).get("situs_address")),
            "owner": p.get("owner_name"),
            "assessed_value": p.get("assessed_value"),
            "derivation": r.get("_derivation", {}).get("method", "direct_key"),
        })
        if len(samples) >= 5:
            break

    print()
    log("five sample joined records:")
    for s in samples:
        print(f"      {s['canonical_doc_type']:<24} {s['instrument_number']}")
        print(f"        parcel {s['parcel_id_state'] or s['parcel_id']}  "
              f"local {s['parcel_id_local']}  via {s['derivation']}")
        print(f"        situs  {s['situs']}   AV {s['assessed_value']}")

    rep = {
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "county_slug": "marion_in",
        "total_records": total,
        "parcel_joined": joined_total,
        "join_rate_pct": round(joined_total / total * 100, 1) if total else 0.0,
        "review_queue": len(review_rows),
        "lead_types_populated": len(populated),
        "lead_types_live_total": 19,
        "per_source": per_source,
        "samples": samples,
    }
    REPORT_PATH.write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"wrote {REPORT_PATH.relative_to(OUT_DIR.parent)}")
    return rep


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--small", action="store_true", help="small-batch run")
    ap.add_argument("--report-only", action="store_true")
    a = ap.parse_args()
    if not a.report_only:
        ingest(small=a.small)
        n = flush_review()
        log(f"flushed {n:,} review items")
    report()
