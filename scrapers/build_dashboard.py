"""
scrapers/build_dashboard.py — generate the Marion County intelligence dashboard.

Structurally mirrors the Harris intel dashboard (header / stats bar / view tabs /
controls row / filter chips with live counts / sortable table / pagination /
CSV export). Deviations are only where Marion's data differs:

  - NO SCORING. No composite score, no score band, no ranking by score. Harris
    removed scoring for the same reason ("the client decides what's a lead by
    filtering, not by our score"). Marion never had one and does not get one.
    Raw signals are surfaced; the operator draws the conclusion.
  - Marion's lead types and sources.
  - A COVERAGE DISCLOSURE that Harris has no need for: the recorder adapter is
    capped at 200 rows per search against ~8,251 documents/month of real volume,
    so every lien count on this dashboard is a floor, not a total. This is shown
    as a persistent banner AND a per-source badge — never only in a comment.
  - Review queue is a first-class view, not hidden.

Brand: Xcerebro palette + Inter. Deep Black #0A0A0A, Midnight Blue #0F172A,
Electric Blue #3B82F6, Light Blue #60A5FA, Soft Gray #E5E7EB, Dark Gray #1F2937.

OUTPUT CONTAINS PII (owner names, situs addresses) and is therefore written
under dashboard/ but gitignored. This generator is what gets committed; the
rendered HTML is rebuilt locally on demand.

Run:
  .venv\\Scripts\\python.exe scrapers\\build_dashboard.py
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import CROSSWALK_DIR, OUT_DIR, REPO_ROOT, banner, log, read_jsonl  # noqa: E402

# dashboard/index.html — mirrors harris-intel. GitHub Pages uploads dashboard/
# as the artifact root (build_type: workflow), so index.html serves at the site
# root: https://xcerebroai.github.io/marion-county-intel/
OUT_HTML = REPO_ROOT / "dashboard" / "index.html"
TEMPLATE_PATH = Path(__file__).resolve().parent / "dashboard_template.html"

FEEDS = {
    "tax_sale_lists_indygov":    OUT_DIR / "raw" / "tax_sale" / "tax_sale_events.jsonl",
    "opendata_code_enforcement": OUT_DIR / "raw" / "code_enforcement" / "code_enforcement_events.jsonl",
    "marion_recorder_fidlar":    OUT_DIR / "raw" / "recorder" / "recorder_events.jsonl",
    "mycase_courts":             OUT_DIR / "raw" / "mycase" / "mycase_mf_resolved.jsonl",
    "sheriff_sale":              OUT_DIR / "raw" / "sheriff_sale" / "sheriff_sale_events.jsonl",
}

SOURCE_LABEL = {
    "tax_sale_lists_indygov":    "Tax Sale",
    "opendata_code_enforcement": "Code Enf",
    "marion_recorder_fidlar":    "Recorder",
    "mycase_courts":             "Courts",
    "sheriff_sale":              "Sheriff",
}

# Per-source coverage disclosure. `level` drives the badge colour.
#   full     — believed complete for the window pulled
#   capped   — server-side result cap; counts are FLOORS
#   frozen   — upstream stopped delivering; historical only
#   partial  — window-limited or bridge-limited
SOURCE_COVERAGE = {
    "tax_sale_lists_indygov": {
        "level": "full",
        "short": "Complete for 2025 sale",
        "detail": "Full 2025 Parcel Status + Surplus lists. 100% pre-keyed on the "
                  "local parcel number. Annual publication — not a daily feed.",
    },
    "opendata_code_enforcement": {
        "level": "frozen",
        "short": "FROZEN at 2024-02-27",
        "detail": "The open-data extract stopped receiving records on 2024-02-27 "
                  "despite a 2025 catalog 'modified' stamp. Historical backfill "
                  "only — this is NOT current code enforcement. Live Accela is a "
                  "separate, unbuilt path.",
    },
    "marion_recorder_fidlar": {
        "level": "capped",
        "short": "CAPPED 200/search — counts are FLOORS",
        "detail": "The recorder portal returns at most 200 rows per search. A "
                  "one-month all-types search reports 8,251 total results and "
                  "returns 200. Every lien and deed count from this source is an "
                  "UNDERCOUNT, not a total. Additionally the portal publishes on "
                  "a 5-day lag, and six lead types (lis pendens, abstract of "
                  "judgment, state tax lien, heirship affidavit, executor and "
                  "administrator deeds) have no dedicated document code in Marion "
                  "County and cannot be separated from generic buckets at all.",
    },
    "mycase_courts": {
        "level": "partial",
        "short": "5-day sample; MF parcel join needs sheriff list",
        "detail": "Court filings for the sampled window only. A foreclosure case "
                  "gets a parcel only once it reaches sheriff sale, so recently "
                  "filed MF cases show no parcel and sit in the review queue.",
    },
    "sheriff_sale": {
        "level": "partial",
        "short": "Published sale lists only",
        "detail": "Only the sale lists currently published on the auction portal. "
                  "Discovery depends on scraping links off that page; there is no "
                  "stable index endpoint.",
    },
}

LEAD_TYPE_LABEL = {
    "LIS_PENDENS":               "Foreclosure (MF)",
    "SHERIFF_SALE":              "Sheriff Sale",
    "SHERIFF_DEED":              "Sheriff Deed",
    "SHERIFF_SALE_SURPLUS":      "Surplus",
    "TAX_SALE_CERTIFICATE":      "Tax Sale Certificate",
    "TAX_FORECLOSURE_NOTICE":    "Tax Delinquency",
    "TAX_DEED":                  "Tax Deed",
    "MECHANICS_LIEN":            "Mechanic Lien",
    "JUDGMENT_LIEN":             "Judgment Lien",
    "HOSPITAL_LIEN":             "Hospital Lien",
    "MUNICIPAL_LIEN":            "Assessment Lien",
    "WATER_LIEN":                "Sewer Lien",
    "FEDERAL_TAX_LIEN":          "Federal Tax Lien",
    "CODE_VIOLATION_NOTICE":     "Code Violation",
    "DEMOLITION_ORDER":          "Demolition",
    "CONDEMNATION_NOTICE":       "Condemnation",
    "EVICTION_FILING":           "Eviction",
    "LETTERS_OF_ADMINISTRATION": "Probate",
    "RELEASE_OF_LIEN":           "Lien Release",
}

# Grouping for the filter chips (Harris uses cat/cat_label the same way).
LEAD_GROUP = {
    "LIS_PENDENS": "foreclosure", "SHERIFF_SALE": "foreclosure",
    "SHERIFF_DEED": "foreclosure", "SHERIFF_SALE_SURPLUS": "surplus",
    "TAX_SALE_CERTIFICATE": "tax", "TAX_FORECLOSURE_NOTICE": "tax",
    "TAX_DEED": "tax", "FEDERAL_TAX_LIEN": "tax",
    "MECHANICS_LIEN": "lien", "JUDGMENT_LIEN": "lien",
    "HOSPITAL_LIEN": "lien", "MUNICIPAL_LIEN": "lien", "WATER_LIEN": "lien",
    "RELEASE_OF_LIEN": "lien",
    "CODE_VIOLATION_NOTICE": "code", "DEMOLITION_ORDER": "code",
    "CONDEMNATION_NOTICE": "code",
    "EVICTION_FILING": "eviction", "LETTERS_OF_ADMINISTRATION": "probate",
}


def _load_crosswalk():
    parcels, local_to_state = {}, {}
    p = CROSSWALK_DIR / "parcel_master.jsonl"
    if not p.exists():
        return parcels, local_to_state
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            sp = r.get("parcel_id_state")
            if not sp:
                continue
            parcels[sp] = r
            if r.get("parcel_id_local"):
                local_to_state[r["parcel_id_local"]] = sp
    return parcels, local_to_state


def _clean_owner(name: str) -> str:
    """The assessor's FULLOWNERNAME is a fixed 4-field concatenation, so unused
    slots arrive as trailing commas ("SMITH, JOHN, , , "). Strip them."""
    if not name:
        return ""
    parts = [p.strip() for p in str(name).split(",")]
    parts = [p for p in parts if p]
    return ", ".join(parts)


def _amount(rec):
    for a in rec.get("amounts") or []:
        if a.get("value") not in (None, ""):
            try:
                return float(a["value"])
            except (TypeError, ValueError):
                pass
    return None


def _redact_owner(name: str) -> str:
    """Owner name -> non-identifying form for a publicly served build.

    Entities (LLC, INC, TRUST, BANK, ...) are business records and stay intact.
    Natural persons are reduced to a surname initial, which preserves the
    ability to eyeball-group a stack without naming the individual.
    """
    if not name:
        return ""
    if re.search(r"\b(LLC|L\.L\.C|INC|CORP|TRUST|BANK|COMPANY|CO|LP|LLP|PLC|"
                 r"ASSOCIATION|AUTHORITY|CHURCH|MINISTRIES|HOLDINGS|PROPERTIES|"
                 r"INVESTMENTS|GROUP|PARTNERS|FUND|REALTY|HOMES|CAPITAL)\b",
                 name.upper()):
        return name
    first = name.split(",")[0].strip()
    return (first[:1].upper() + "█████") if first else "█████"


def _redact_addr(addr: str) -> str:
    """Situs address -> block-level. '2615 WHITE AVE' -> '2600 BLOCK WHITE AVE'."""
    if not addr:
        return ""
    m = re.match(r"^\s*(\d+)\s+(.*)$", addr.strip())
    if not m:
        return addr
    n = int(m.group(1))
    return f"{(n // 100) * 100} BLOCK {m.group(2)}"


def build(redact: bool = False) -> dict:
    banner(f"BUILD DASHBOARD — Marion County (no scoring"
           f"{', REDACTED for public serving' if redact else ''})")

    parcels, l2s = _load_crosswalk()
    log(f"crosswalk: {len(parcels):,} parcels, {len(l2s):,} local->state keys")

    records, unjoined = [], 0
    for sid, path in FEEDS.items():
        rows = read_jsonl(path)
        log(f"{SOURCE_LABEL.get(sid, sid):<10} {len(rows):>6,}")
        for r in rows:
            pid = (r.get("property_refs") or {}).get("parcel_id")
            # Normalize every parcel reference to the canonical STATE key.
            # tax sale and sheriff arrive keyed on the LOCAL number; without this
            # the same parcel appears twice and stacking is undercounted.
            state = pid if pid in parcels else l2s.get(pid or "")
            if not pid:
                unjoined += 1
                continue
            p = parcels.get(state or "", {})
            dt = r.get("canonical_doc_type") or ""
            addr = (f"{p.get('situs_house_no','')} {p.get('situs_street','')}".strip()
                    or (r.get("property_refs") or {}).get("situs_address") or "")
            owner = _clean_owner(p.get("owner_name")
                                 or (r.get("parties") or [{}])[0].get("name", ""))
            records.append({
                "t": dt,
                "lt": LEAD_TYPE_LABEL.get(dt, dt.replace("_", " ").title()),
                "g": LEAD_GROUP.get(dt, "other"),
                "s": sid,
                "sl": SOURCE_LABEL.get(sid, sid),
                "d": r.get("recorded_date") or r.get("event_date") or "",
                "p": state or "",
                "pl": p.get("parcel_id_local") or (pid if str(pid).isdigit() else ""),
                "a": (_redact_addr(addr) if redact else addr),
                "z": p.get("situs_zip") or "",
                "o": (_redact_owner(owner) if redact else owner),
                "av": p.get("assessed_value"),
                "amt": _amount(r),
                "inst": r.get("instrument_number") or "",
                "note": (r.get("document_body_text") or "").replace("PARCEL_STATUS: ", ""),
                "bf": bool(r.get("_is_backfill")),
                # secondary fields — surfaced in the details drawer only, never
                # as permanent table columns
                "rid": r.get("raw_event_id") or "",
                "rt": r.get("raw_doc_type") or "",
                "dm": (r.get("_derivation") or {}).get("method") or "direct_key",
                "dc": (r.get("_derivation") or {}).get("confidence"),
                "url": r.get("source_url") or "",
                "role": r.get("source_role") or "",
            })

    # ---- stacking on the canonical key ----
    stack = collections.Counter(r["p"] for r in records if r["p"])
    for r in records:
        r["st"] = stack.get(r["p"], 1) if r["p"] else 1

    stacked_parcels = {k: v for k, v in stack.items() if v > 1}
    log("")
    log(f"records on dashboard    : {len(records):,}")
    log(f"distinct parcels        : {len(stack):,}")
    log(f"parcels with >1 signal  : {len(stacked_parcels):,}")
    log(f"deepest stack           : {max(stack.values()) if stack else 0} signals")

    # ---- review queue ----
    review = []
    for r in read_jsonl(OUT_DIR / "raw" / "review_queue.jsonl"):
        rec = r.get("record") or {}
        review.append({
            "src": SOURCE_LABEL.get(r.get("source_id"), r.get("source_id") or ""),
            "reason": r.get("reason") or "",
            "method": r.get("derivation_method") or "",
            "conf": r.get("confidence"),
            "ref": (rec.get("case_number") or rec.get("doc_number")
                    or rec.get("parcel_local") or rec.get("address") or ""),
            "cand": rec.get("parcel_local") or rec.get("candidate_parcel") or "",
            "date": (rec.get("file_date") or rec.get("open_date")
                     or (r.get("queued_at") or "")[:10]),
            "detail": (rec.get("address") or rec.get("legal_summary")
                       or rec.get("style") or rec.get("note")
                       or rec.get("raw_status") or ""),
        })
    log(f"review queue            : {len(review):,}")

    by_type = collections.Counter(r["t"] for r in records)
    by_source = collections.Counter(r["s"] for r in records)

    payload = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "records": records,
        "review": review,
        "coverage": SOURCE_COVERAGE,
        "source_label": SOURCE_LABEL,
        "stats": {
            "total": len(records),
            "parcels": len(stack),
            "stacked": len(stacked_parcels),
            "deepest": max(stack.values()) if stack else 0,
            "review": len(review),
            "unjoined": unjoined,
        },
    }

    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(_html(payload), encoding="utf-8")
    log("")
    log(f"wrote {OUT_HTML.relative_to(REPO_ROOT)} "
        f"({OUT_HTML.stat().st_size / 1024 / 1024:.2f} MB, single file)")

    return {"records": len(records), "by_type": by_type, "by_source": by_source,
            "parcels": len(stack), "stacked": len(stacked_parcels),
            "deepest": max(stack.values()) if stack else 0,
            "review": len(review), "path": OUT_HTML}


def _html(payload: dict) -> str:
    """Inject the data payload into the UI template.

    The template lives in scrapers/dashboard_template.html rather than inline
    here: it is ~700 lines of HTML/CSS/JS and keeping it as a Python string made
    UI work needlessly painful. The generator remains the source of truth — the
    template is data-less until this function fills it.
    """
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tpl = TEMPLATE_PATH.read_text(encoding="utf-8")
    if "/*__DATA__*/" not in tpl:
        raise RuntimeError(f"{TEMPLATE_PATH} is missing the /*__DATA__*/ placeholder")
    return tpl.replace("/*__DATA__*/", data_json)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--redact", action="store_true",
                    help="omit individual owner names and reduce situs addresses to "
                         "block level. Not used by the deploy path.")
    a = ap.parse_args()
    build(redact=a.redact)
