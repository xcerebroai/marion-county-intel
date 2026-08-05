"""
scrapers/code_enforcement.py — Indianapolis DBNS/DCE code enforcement (recon §4.4).

Two paths to the same authority, and they are NOT equivalent:

  Path A  open-data extract (this adapter)
          gis.indy.gov OpenData_NonSpatial layer 1, 910,483 rows.
          FROZEN at 2024-02-27 — zero rows after 2025-01-01 — despite a 2025
          catalog "modified" stamp. RED as a live feed, GREEN for 2010-2024
          historical backfill. Carries STREET_ADDRESS but NO parcel column.

  Path B  live Accela (aca-prod.accela.com tenant INDY)
          No control enforced: 0 captcha nodes, no grecaptcha, no password
          field, public search without login. Exposes a parcel-number search
          field (txtGSParcelNo). See OPEN_ITEMS.md SB-4 — the Reports module
          (Case Research Report) is the likely bulk path and is not built.

This adapter runs Path A because it is the one that yields data today, and it
routes every row through the address crosswalk to recover the canonical parcel
key the extract omits. Rows are stamped is_backfill=true so nothing downstream
can mistake them for current.

Run:
  .venv\\Scripts\\python.exe scrapers\\code_enforcement.py [--limit 2000]
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    MIN_PARCEL_CONFIDENCE, OUT_DIR, banner, arcgis_page_all, log, party,
    raw_event, stable_id, to_review, write_jsonl, write_raw,
)
from scrapers.address_parcel_crosswalk import Crosswalk  # noqa: E402

SOURCE_ID = "opendata_code_enforcement"
LAYER = ("https://gis.indy.gov/server/rest/services/OpenData/"
         "OpenData_NonSpatial/MapServer/1")
FIELDS = ("CASE_NUMBER,CASE_TYPE,CASE_STATUS,OPEN_DATE,STREET_ADDRESS,CITY,"
          "STATE,ZIP,OWNER,TOWNSHIP,LINK")

OUT_PATH = OUT_DIR / "raw" / "code_enforcement" / "code_enforcement_events.jsonl"

# Marion CASE_TYPE -> canonical doc type. Distress types only; the rest is noise
# (High Weeds & Grass, Trash, Vehicle, Right of Way, Zoning, ...).
DISTRESS_TYPES = {
    "Enforcement/Violation/Demolition/NA": "DEMOLITION_ORDER",
    "Enforcement - Demolition": "DEMOLITION_ORDER",
    "Enforcement/Investigation/Unsafe Buildings/NA": "CONDEMNATION_NOTICE",
    "Enforcement/Violation/Vacant Board Order/NA": "CODE_VIOLATION_NOTICE",
    "Enforcement - Vacant Board Order": "CODE_VIOLATION_NOTICE",
    "Enforcement/Violation/Repair/NA": "CODE_VIOLATION_NOTICE",
    "Enforcement/Violation/Repair No Hearing/NA": "CODE_VIOLATION_NOTICE",
    "Enforcement - Repair w/no Hearing": "CODE_VIOLATION_NOTICE",
    "Enforcement/Violation/Building/NA": "CODE_VIOLATION_NOTICE",
    "Enforcement/Investigation/Building/NA": "CODE_VIOLATION_NOTICE",
    "Enforcement/Legal/NA/NA": "MUNICIPAL_LIEN",
}

_HOUSE_RE = re.compile(r"^\s*(\d+[A-Z]?)\s+(.*)$")


def _epoch_to_iso(ms) -> str | None:
    if ms in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OverflowError, OSError):
        return None


def _split_address(addr: str):
    m = _HOUSE_RE.match((addr or "").strip())
    return (m.group(1), m.group(2)) if m else (None, None)


def run(limit: int | None = 2000) -> list[dict]:
    banner("CODE ENFORCEMENT — open-data extract (BACKFILL ONLY, frozen 2024-02-27)")

    xw = Crosswalk()
    if not xw.addr:
        log("!! crosswalk is empty — run scrapers/address_parcel_crosswalk.py first")
        return []
    log(f"crosswalk loaded: {len(xw.addr):,} address keys, {len(xw.parcels):,} parcels")

    where = " OR ".join(f"CASE_TYPE='{t}'" for t in DISTRESS_TYPES)
    rows = arcgis_page_all(LAYER, where=where, out_fields=FIELDS,
                           page_size=1000, max_records=limit,
                           order_by="OPEN_DATE DESC")
    log(f"distress-type rows fetched: {len(rows):,}")
    write_raw("code_enforcement", "opendata_sample.json",
              __import__("json").dumps(rows[:50], ensure_ascii=False, indent=2))

    events, joined, unresolved = [], 0, 0
    for a in rows:
        case_no = a.get("CASE_NUMBER")
        addr = a.get("STREET_ADDRESS")
        hn, street = _split_address(addr)
        zipc = a.get("ZIP")
        if zipc not in (None, ""):
            zipc = str(int(float(zipc))) if str(zipc).replace(".", "").isdigit() else zipc

        parcel, conf, method = xw.by_address(hn, street, zipc)

        if parcel and conf >= MIN_PARCEL_CONFIDENCE:
            joined += 1
        else:
            unresolved += 1
            to_review(source_id=SOURCE_ID,
                      reason=f"parcel_unresolved:{method}",
                      derivation_method=method, confidence=conf,
                      record={"case_number": case_no, "address": addr,
                              "zip": zipc, "case_type": a.get("CASE_TYPE")})
            parcel = None

        opened = _epoch_to_iso(a.get("OPEN_DATE"))
        ev = raw_event(
            raw_event_id=stable_id("CE", case_no),
            source_id=SOURCE_ID,
            canonical_doc_type=DISTRESS_TYPES.get(a.get("CASE_TYPE"), "CODE_VIOLATION_NOTICE"),
            raw_doc_type=a.get("CASE_TYPE"),
            source_url=a.get("LINK") or LAYER,
            recorded_date=opened,
            event_date=opened,
            instrument_number=case_no,
            parties=[party(a.get("OWNER"), "TP")] if a.get("OWNER") else [],
            parcel_id=parcel,
            situs_address=addr,
            case_number=case_no,
            document_body_text=f"CASE_STATUS: {a.get('CASE_STATUS')}",
            parser_name="code_enforcement.opendata",
            parser_confidence=90,
        )
        ev["_derivation"] = {"method": method, "confidence": conf}
        ev["_is_backfill"] = True          # FROZEN source — never treat as current
        ev["_freshness"] = "FROZEN@2024-02-27"
        events.append(ev)

    n = write_jsonl(OUT_PATH, events)
    log(f"wrote {n:,} raw_event records -> {OUT_PATH.relative_to(OUT_DIR.parent)}")
    pct = joined / len(events) * 100 if events else 0
    log(f"parcel-joined via address crosswalk: {joined:,}/{len(events):,} ({pct:.1f}%)")
    log(f"routed to review (unresolved)      : {unresolved:,}")
    return events


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000)
    a = ap.parse_args()
    run(limit=a.limit)
