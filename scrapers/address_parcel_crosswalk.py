"""
scrapers/address_parcel_crosswalk.py — address -> canonical parcel key (recon §1.5 path 2).

Builds the join spine that address-bearing sources need: Accela code enforcement,
the sheriff sale list, and the tax sale Surplus "Parcel Location" column.

IMPORTANT SCOPE NOTE (recon §4.3, OPEN_ITEMS.md SB-2):
MyCase court records carry NO address and NO parcel. This crosswalk cannot join
them on its own — there is no address to look up. MF cases stay UNRESOLVED until
the sheriff sale bridge (SB-1) supplies an address per case number.

Built from MapIndy (recon §4.5):
  layer 10  Parcel              STATEPARCELNUMBER + PARCEL_C + situs components
  layer 0   Unit Address Points authoritative address spine (secondary pass)

§1.4: the parcel layer is NOT row-unique — multi-polygon parcels repeat up to
30x. Every ingest dedupes on the canonical key. returnGeometry is always false.

Run:
  .venv\\Scripts\\python.exe scrapers\\address_parcel_crosswalk.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import (  # noqa: E402
    CROSSWALK_DIR, OUT_DIR, address_key, arcgis_page_all, banner, log,
    norm_address, parcel_keys, write_raw,
)

SOURCE_ID = "mapindy_parcel"
MAPSERVER = "https://gis.indy.gov/server/rest/services/MapIndy/MapIndyProperty/MapServer"
PARCEL_LAYER = f"{MAPSERVER}/10"

PARCEL_FIELDS = ("STATEPARCELNUMBER,PARCEL_C,STNUMBER,PRE_DIR,STREET_NAME,SUFFIX,"
                 "SUF_DIR,FULL_STNAME,CITY,ZIPCODE,FULLOWNERNAME,PROPERTY_CLASS,"
                 "ASSESSORYEAR_TOTALAV,STATUS,SUBDIVISION_TAG,LOTNUM,LEGAL_DESCRIPTION_")

CROSSWALK_PATH = CROSSWALK_DIR / "address_parcel.json"
PARCEL_MASTER_PATH = CROSSWALK_DIR / "parcel_master.jsonl"
SUBDIV_LOT_PATH = CROSSWALK_DIR / "subdivision_lot.json"


def build(limit: int | None = None) -> dict:
    banner("ADDRESS -> PARCEL CROSSWALK (recon §1.5 path 2)")

    where = "STATEPARCELNUMBER IS NOT NULL AND STATEPARCELNUMBER <> ''"
    log("paging MapIndy parcel layer (returnGeometry=false, maxRecordCount=1000) ...")
    rows = arcgis_page_all(PARCEL_LAYER, where=where, out_fields=PARCEL_FIELDS,
                           page_size=1000, max_records=limit,
                           order_by="STATEPARCELNUMBER")
    log(f"raw parcel rows fetched: {len(rows):,}")

    write_raw("mapindy", "parcel_layer_sample.json",
              json.dumps(rows[:50], ensure_ascii=False, indent=2))

    # ---- dedupe on the canonical key (§1.4 multi-polygon trap) ----
    by_state: dict[str, dict] = {}
    for a in rows:
        keys = parcel_keys(a.get("STATEPARCELNUMBER"), a.get("PARCEL_C"))
        sp = keys["parcel_id_state"]
        if not sp:
            continue
        if sp in by_state:
            continue                     # first row wins; geometry dupes discarded
        by_state[sp] = {
            **keys,
            "situs_house_no": (a.get("STNUMBER") or "").strip(),
            "situs_street": (a.get("FULL_STNAME") or "").strip(),
            "situs_city": (a.get("CITY") or "").strip(),
            "situs_zip": (a.get("ZIPCODE") or "").strip(),
            "owner_name": (a.get("FULLOWNERNAME") or "").strip(),
            "property_class": (a.get("PROPERTY_CLASS") or "").strip(),
            "assessed_value": a.get("ASSESSORYEAR_TOTALAV"),
            "parcel_status": (a.get("STATUS") or "").strip(),
            "subdivision_tag": a.get("SUBDIVISION_TAG"),
            "lot_number": (a.get("LOTNUM") or "").strip(),
            "legal_description": (a.get("LEGAL_DESCRIPTION_") or "").strip(),
        }

    dupes = len(rows) - len(by_state)
    log(f"deduped on parcel_id_state: {len(by_state):,} unique parcels "
        f"({dupes:,} multi-polygon rows collapsed)")

    # ---- address index ----
    addr_index: dict[str, list[str]] = {}
    no_addr = 0
    for sp, p in by_state.items():
        k = address_key(p["situs_house_no"], p["situs_street"], p["situs_zip"])
        if not k:
            no_addr += 1
            continue
        addr_index.setdefault(k, []).append(sp)

    unique_addr = sum(1 for v in addr_index.values() if len(v) == 1)
    ambiguous = {k: v for k, v in addr_index.items() if len(v) > 1}

    log(f"address keys built     : {len(addr_index):,}")
    log(f"  unambiguous (1 parcel): {unique_addr:,}")
    log(f"  ambiguous (>1 parcel) : {len(ambiguous):,}  -> resolved at match time, "
        f"never silently collapsed")
    log(f"  parcels with no usable address: {no_addr:,}")

    # ---- subdivision+lot index (recon §1.5 path 1, for the recorder) ----
    subdiv_index: dict[str, list[str]] = {}
    for sp, p in by_state.items():
        tag, lot = p.get("subdivision_tag"), p.get("lot_number")
        if tag and int(tag or 0) > 0 and lot:
            subdiv_index.setdefault(f"{int(tag)}|{lot.upper()}", []).append(sp)
    log(f"subdivision_tag|lot keys: {len(subdiv_index):,} "
        f"(recon ceiling ~114,831 parcels / 33%)")

    CROSSWALK_PATH.parent.mkdir(parents=True, exist_ok=True)
    CROSSWALK_PATH.write_text(json.dumps({
        "_built_from": "MapIndy MapServer layer 10 (Parcel)",
        "_canonical_key": "parcel_id_state (STATEPARCELNUMBER)",
        "_dedupe_rule": "first row per parcel_id_state; multi-polygon rows collapsed (recon §1.4)",
        "_address_key_format": "<house_no>|<normalized street>|<zip5>",
        "index": addr_index,
    }, ensure_ascii=False), encoding="utf-8")

    SUBDIV_LOT_PATH.write_text(json.dumps({
        "_built_from": "MapIndy layer 10 SUBDIVISION_TAG + LOTNUM",
        "_warning": "DO NOT use SUBDIVNUM — it is '0' for many subdivisions (recon §1.5)",
        "index": subdiv_index,
    }, ensure_ascii=False), encoding="utf-8")

    with PARCEL_MASTER_PATH.open("w", encoding="utf-8") as fh:
        for sp, p in by_state.items():
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")

    log(f"wrote {CROSSWALK_PATH.relative_to(OUT_DIR.parent)}")
    log(f"wrote {SUBDIV_LOT_PATH.relative_to(OUT_DIR.parent)}")
    log(f"wrote {PARCEL_MASTER_PATH.relative_to(OUT_DIR.parent)} ({len(by_state):,} parcels)")

    return {"parcels": len(by_state), "address_keys": len(addr_index),
            "ambiguous": len(ambiguous), "subdiv_keys": len(subdiv_index)}


# ---------------------------------------------------------------------------
# lookup API used by the address-bearing adapters
# ---------------------------------------------------------------------------

class Crosswalk:
    def __init__(self):
        self.addr = {}
        self.subdiv = {}
        self.parcels = {}
        if CROSSWALK_PATH.exists():
            self.addr = json.loads(CROSSWALK_PATH.read_text(encoding="utf-8"))["index"]
        if SUBDIV_LOT_PATH.exists():
            self.subdiv = json.loads(SUBDIV_LOT_PATH.read_text(encoding="utf-8"))["index"]
        if PARCEL_MASTER_PATH.exists():
            with PARCEL_MASTER_PATH.open("r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        p = json.loads(line)
                        self.parcels[p["parcel_id_state"]] = p

    def by_address(self, house_no, street, zipcode=None):
        """Return (parcel_id_state, confidence, method). None when unresolved."""
        k = address_key(house_no, street, zipcode)
        if not k:
            return None, 0, "no_address_key"
        hits = self.addr.get(k)
        if not hits:
            # retry without zip — many sources omit or mangle it
            k2 = address_key(house_no, street, None)
            loose = [v for kk, v in self.addr.items() if kk.rsplit("|", 1)[0] + "|" == k2]
            hits = [x for sub in loose for x in sub]
            if len(hits) == 1:
                return hits[0], 85, "address_no_zip"
            if len(hits) > 1:
                return None, 40, "address_ambiguous_no_zip"
            return None, 0, "address_not_found"
        if len(hits) == 1:
            return hits[0], 98, "address_exact"
        return None, 45, "address_ambiguous"

    def by_subdivision_lot(self, subdiv_tag, lot):
        if not subdiv_tag or not lot:
            return None, 0, "no_subdiv_lot"
        hits = self.subdiv.get(f"{int(subdiv_tag)}|{str(lot).upper()}")
        if not hits:
            return None, 0, "subdiv_lot_not_found"
        if len(hits) == 1:
            return hits[0], 96, "subdivision_lot_exact"
        return None, 45, "subdivision_lot_ambiguous"

    def enrich(self, parcel_id_state):
        return self.parcels.get(parcel_id_state)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None,
                    help="cap parcels fetched (small batch runs)")
    a = ap.parse_args()
    build(limit=a.limit)
