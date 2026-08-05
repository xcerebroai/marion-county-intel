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

import collections
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers._common import CROSSWALK_DIR, OUT_DIR, REPO_ROOT, banner, log, read_jsonl  # noqa: E402

OUT_HTML = REPO_ROOT / "dashboard" / "marion_dashboard.html"

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


def build() -> dict:
    banner("BUILD DASHBOARD — Marion County (no scoring)")

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
            records.append({
                "t": dt,
                "lt": LEAD_TYPE_LABEL.get(dt, dt.replace("_", " ").title()),
                "g": LEAD_GROUP.get(dt, "other"),
                "s": sid,
                "sl": SOURCE_LABEL.get(sid, sid),
                "d": r.get("recorded_date") or r.get("event_date") or "",
                "p": state or "",
                "pl": p.get("parcel_id_local") or (pid if str(pid).isdigit() else ""),
                "a": (f"{p.get('situs_house_no','')} {p.get('situs_street','')}".strip()
                      or (r.get("property_refs") or {}).get("situs_address") or ""),
                "z": p.get("situs_zip") or "",
                "o": _clean_owner(p.get("owner_name")
                                  or (r.get("parties") or [{}])[0].get("name", "")),
                "av": p.get("assessed_value"),
                "amt": _amount(r),
                "inst": r.get("instrument_number") or "",
                "note": (r.get("document_body_text") or "").replace("PARCEL_STATUS: ", ""),
                "bf": bool(r.get("_is_backfill")),
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
                    or rec.get("parcel_local") or rec.get("address")
                    or rec.get("case_number") or ""),
            "detail": (rec.get("address") or rec.get("legal_summary")
                       or rec.get("style") or rec.get("note") or ""),
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
    data_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return _TEMPLATE.replace("/*__DATA__*/", data_json)


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Marion County | Distress Signal Intelligence</title>
<link rel="preconnect" href="https://fonts.googleapis.com" />
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
<style>
  :root {
    --black:      #0A0A0A;   /* Deep Black    */
    --midnight:   #0F172A;   /* Midnight Blue */
    --blue:       #3B82F6;   /* Electric Blue */
    --blue-light: #60A5FA;   /* Light Blue    */
    --gray-soft:  #E5E7EB;   /* Soft Gray     */
    --gray-dark:  #1F2937;   /* Dark Gray     */

    --surface:  #0F172A;
    --surface2: #1F2937;
    --line:     rgba(229,231,235,0.10);
    --muted:    #94A3B8;

    --amber: #F59E0B;
    --red:   #EF4444;
    --green: #10B981;

    --font: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;

    --g-foreclosure: #EF4444;
    --g-tax:         #F59E0B;
    --g-lien:        #3B82F6;
    --g-code:        #8B5CF6;
    --g-eviction:    #EC4899;
    --g-probate:     #10B981;
    --g-surplus:     #14B8A6;
    --g-other:       #94A3B8;
  }
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--black);color:var(--gray-soft);font-family:var(--font);
       font-size:14px;line-height:1.55;min-height:100vh}

  /* HEADER */
  header{position:sticky;top:0;z-index:100;background:rgba(10,10,10,.94);
    backdrop-filter:blur(12px);border-bottom:1px solid var(--line);
    padding:0 24px;display:flex;align-items:center;justify-content:space-between;height:60px}
  .logo{display:flex;align-items:center;gap:12px}
  .logo-icon{width:34px;height:34px;border-radius:8px;
    background:linear-gradient(135deg,var(--blue),var(--blue-light));
    display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff}
  .logo-text{font-size:17px;font-weight:700;letter-spacing:-.01em;color:#fff}
  .logo-sub{font-size:11px;color:var(--blue-light);letter-spacing:.08em;
    text-transform:uppercase;font-weight:500}
  .header-right{display:flex;align-items:center;gap:14px}
  .status-dot{width:8px;height:8px;border-radius:50%;background:var(--green);
    animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.45}}
  .last-updated{font-size:12px;color:var(--muted)}
  .btn{background:var(--blue);color:#fff;border:none;padding:8px 15px;border-radius:6px;
    font-family:var(--font);font-size:13px;font-weight:600;cursor:pointer;
    transition:background .15s,transform .1s}
  .btn:hover{background:var(--blue-light);transform:translateY(-1px)}
  .btn.ghost{background:transparent;border:1px solid var(--line);color:var(--gray-soft)}
  .btn.ghost:hover{border-color:var(--blue);color:var(--blue-light);background:transparent}

  /* COVERAGE BANNER */
  .coverage-banner{background:rgba(245,158,11,.10);border-bottom:1px solid rgba(245,158,11,.32);
    padding:11px 24px;display:flex;gap:12px;align-items:flex-start}
  .coverage-banner .ico{font-size:16px;line-height:1.2}
  .coverage-banner b{color:var(--amber);font-weight:600}
  .coverage-banner .txt{font-size:13px;color:#FCD9A0}
  .coverage-banner .more{background:none;border:none;color:var(--amber);
    text-decoration:underline;cursor:pointer;font-family:var(--font);font-size:12px;padding:0}

  /* TOOLBAR */
  .toolbar{display:flex;gap:8px;padding:10px 24px;background:var(--surface);
    border-bottom:1px solid var(--line);flex-wrap:wrap;align-items:center}

  /* STATS */
  .stats-bar{background:var(--surface);border-bottom:1px solid var(--line);
    padding:14px 24px;display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
  .stat-block{padding:6px 20px;border-right:1px solid var(--line)}
  .stat-block:last-child{border-right:none}
  .stat-value{font-size:28px;font-weight:700;line-height:1.1;color:var(--blue-light)}
  .stat-label{font-size:11px;color:var(--muted);letter-spacing:.07em;
    text-transform:uppercase;margin-top:2px;font-weight:500}

  .main{max-width:1680px;margin:0 auto;padding:22px 24px}

  /* TABS */
  .tabs-row{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}
  .view-tab{background:var(--surface2);border:1px solid var(--line);color:var(--muted);
    padding:9px 16px;border-radius:7px;font-family:var(--font);font-size:13px;
    font-weight:500;cursor:pointer;transition:all .15s}
  .view-tab:hover{color:var(--blue-light);border-color:var(--blue)}
  .view-tab.active{background:var(--blue);color:#fff;border-color:var(--blue)}
  .tab-badge{background:rgba(0,0,0,.28);padding:1px 7px;border-radius:10px;
    font-size:11px;margin-left:6px;font-weight:600}

  /* CONTROLS */
  .controls-row{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px;align-items:center}
  .search-wrap{flex:1;min-width:230px;position:relative}
  .search-wrap svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);
    color:var(--muted);width:15px;height:15px}
  .search-input{width:100%;background:var(--surface2);border:1px solid var(--line);
    color:var(--gray-soft);padding:9px 12px 9px 36px;border-radius:7px;
    font-family:var(--font);font-size:13px;outline:none}
  .search-input:focus{border-color:var(--blue)}
  .search-input::placeholder{color:var(--muted)}
  select.ctl,input.ctl{background:var(--surface2);border:1px solid var(--line);
    color:var(--gray-soft);padding:9px 11px;border-radius:7px;font-family:var(--font);
    font-size:13px;outline:none;cursor:pointer}
  select.ctl:focus,input.ctl:focus{border-color:var(--blue)}
  input.ctl{width:120px;cursor:text}

  /* CHIPS */
  .chips-row{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:10px}
  .chip{background:var(--surface2);border:1px solid var(--line);color:var(--muted);
    padding:6px 12px;border-radius:20px;font-size:12px;font-weight:500;cursor:pointer;
    transition:all .15s;display:inline-flex;align-items:center;gap:6px}
  .chip:hover{border-color:var(--blue);color:var(--blue-light)}
  .chip.active{background:var(--blue);color:#fff;border-color:var(--blue)}
  .chip .ct{background:rgba(0,0,0,.25);padding:0 6px;border-radius:9px;font-size:11px}
  .chip .cov{width:7px;height:7px;border-radius:50%}
  .cov-full{background:var(--green)} .cov-capped{background:var(--amber)}
  .cov-frozen{background:var(--red)} .cov-partial{background:var(--blue-light)}

  .count-line{font-size:12px;color:var(--muted);margin:10px 0}
  .count-line span{color:var(--blue-light);font-weight:600}

  /* TABLE */
  .table-wrap{background:var(--surface);border:1px solid var(--line);border-radius:9px;
    overflow-x:auto}
  table{width:100%;border-collapse:collapse;font-size:13px}
  thead th{background:var(--surface2);color:var(--muted);text-align:left;
    padding:10px 12px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;
    font-weight:600;white-space:nowrap;cursor:pointer;border-bottom:1px solid var(--line);
    position:sticky;top:0}
  thead th:hover{color:var(--blue-light)}
  tbody td{padding:10px 12px;border-bottom:1px solid rgba(229,231,235,.05);
    vertical-align:top}
  tbody tr:hover{background:rgba(59,130,246,.05)}
  .mono{font-variant-numeric:tabular-nums;font-feature-settings:"tnum"}
  .pill{display:inline-block;padding:2px 9px;border-radius:11px;font-size:11px;
    font-weight:600;white-space:nowrap}
  .src-pill{display:inline-flex;align-items:center;gap:5px;padding:2px 8px;
    border-radius:5px;font-size:11px;background:var(--surface2);color:var(--gray-soft)}
  .stack-badge{display:inline-block;background:rgba(59,130,246,.16);
    border:1px solid rgba(59,130,246,.4);color:var(--blue-light);padding:1px 8px;
    border-radius:10px;font-size:11px;font-weight:600;cursor:pointer}
  .stack-badge.hot{background:rgba(239,68,68,.16);border-color:rgba(239,68,68,.45);
    color:#FCA5A5}
  .addr-main{color:var(--gray-soft)}
  .addr-sub{font-size:11px;color:var(--muted)}
  .muted{color:var(--muted)}
  .bf-tag{font-size:10px;color:var(--red);border:1px solid rgba(239,68,68,.35);
    padding:0 5px;border-radius:4px;margin-left:5px}
  .empty{padding:48px;text-align:center;color:var(--muted)}

  /* STACK DETAIL ROWS */
  .stack-row td{background:rgba(59,130,246,.04);padding-top:0}
  .sig-line{display:flex;gap:10px;align-items:center;padding:3px 0;font-size:12px}

  /* PAGINATION */
  .pagination{display:flex;gap:5px;justify-content:center;padding:16px 0;flex-wrap:wrap}
  .page-btn{background:var(--surface2);border:1px solid var(--line);color:var(--gray-soft);
    padding:6px 11px;border-radius:6px;font-family:var(--font);font-size:12px;cursor:pointer}
  .page-btn:hover:not(:disabled){border-color:var(--blue);color:var(--blue-light)}
  .page-btn.active{background:var(--blue);color:#fff;border-color:var(--blue)}
  .page-btn:disabled{opacity:.35;cursor:not-allowed}

  /* MODAL */
  .modal-overlay{position:fixed;inset:0;background:rgba(10,10,10,.82);z-index:200;
    display:none;align-items:center;justify-content:center;padding:24px}
  .modal-overlay.open{display:flex}
  .modal-box{background:var(--surface);border:1px solid var(--line);border-radius:11px;
    padding:26px;max-width:780px;width:100%;max-height:82vh;overflow-y:auto;position:relative}
  .modal-close{position:absolute;top:14px;right:16px;background:none;border:none;
    color:var(--muted);font-size:19px;cursor:pointer}
  .modal-title{font-size:18px;font-weight:700;color:#fff;margin-bottom:16px}
  .cov-item{border-left:3px solid var(--line);padding:9px 0 9px 13px;margin-bottom:13px}
  .cov-item h4{font-size:13px;font-weight:600;color:var(--gray-soft);margin-bottom:3px}
  .cov-item p{font-size:12.5px;color:var(--muted);line-height:1.55}
  .cov-item .lvl{font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.05em}

  footer{border-top:1px solid var(--line);padding:20px 24px;display:flex;
    justify-content:space-between;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted)}
  .brand{color:var(--blue-light);font-weight:600}
</style>
</head>
<body>

<header>
  <div class="logo">
    <div class="logo-icon">M</div>
    <div>
      <div class="logo-text">MARION INTEL</div>
      <div class="logo-sub">Distress Signal Intelligence</div>
    </div>
  </div>
  <div class="header-right">
    <div class="status-dot"></div>
    <div class="last-updated" id="lastUpdated">—</div>
    <button class="btn" onclick="exportCSV()">⬇ Export CSV</button>
  </div>
</header>

<!-- COVERAGE DISCLOSURE — required, always visible -->
<div class="coverage-banner">
  <div class="ico">⚠️</div>
  <div class="txt">
    <b>Coverage is incomplete and counts are floors, not totals.</b>
    The recorder portal caps every search at <b>200 rows</b> against roughly
    <b>8,251 documents per month</b> of real volume, so all lien and deed counts here are
    <b>undercounts</b>. Code enforcement is a <b>frozen</b> extract (no records after 2024-02-27).
    Do not read any number on this dashboard as complete.
    <button class="more" onclick="openCoverage()">Per-source detail →</button>
  </div>
</div>

<div class="toolbar">
  <button class="btn ghost" onclick="exportCSV()">⬇ Signals CSV</button>
  <button class="btn ghost" onclick="exportStacked()">⬇ Stacked Parcels CSV</button>
  <button class="btn ghost" onclick="exportReview()">⬇ Review Queue CSV</button>
  <button class="btn ghost" onclick="openCoverage()">📋 Coverage</button>
  <div style="margin-left:auto;font-size:12px;color:var(--muted)">
    No scoring — raw signals only. Ranking and judgment are yours.
  </div>
</div>

<div class="stats-bar">
  <div class="stat-block"><div class="stat-value" id="sTotal">—</div><div class="stat-label">Signals</div></div>
  <div class="stat-block"><div class="stat-value" id="sParcels">—</div><div class="stat-label">Distinct Parcels</div></div>
  <div class="stat-block"><div class="stat-value" id="sStacked">—</div><div class="stat-label">Parcels w/ Stacked Signals</div></div>
  <div class="stat-block"><div class="stat-value" id="sDeepest">—</div><div class="stat-label">Deepest Stack</div></div>
  <div class="stat-block"><div class="stat-value" id="sReview">—</div><div class="stat-label">Review Queue</div></div>
</div>

<div class="main">
  <div class="tabs-row">
    <button class="view-tab active" data-view="signals" onclick="setView('signals')">Signals <span class="tab-badge" id="bSignals">0</span></button>
    <button class="view-tab" data-view="stacked" onclick="setView('stacked')">Stacked Parcels <span class="tab-badge" id="bStacked">0</span></button>
    <button class="view-tab" data-view="review" onclick="setView('review')">Review Queue <span class="tab-badge" id="bReview">0</span></button>
  </div>

  <div class="controls-row">
    <div class="search-wrap">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>
      </svg>
      <input class="search-input" id="searchInput" type="text"
             placeholder="Search owner, address, parcel, instrument…" />
    </div>
    <select class="ctl" id="sortSelect" onchange="applyFilters()">
      <option value="date_desc">Date: Newest First</option>
      <option value="date_asc">Date: Oldest First</option>
      <option value="stack_desc">Signals on Parcel: Most First</option>
      <option value="av_desc">Assessed Value: High → Low</option>
      <option value="av_asc">Assessed Value: Low → High</option>
      <option value="amt_desc">Amount: High → Low</option>
    </select>
    <input class="ctl" id="avMin" type="number" placeholder="AV min" oninput="deb()">
    <input class="ctl" id="avMax" type="number" placeholder="AV max" oninput="deb()">
    <button class="chip" id="stackOnly" onclick="toggleStackOnly()">Stacked only</button>
  </div>

  <div class="chips-row" id="typeChips"></div>
  <div class="chips-row" id="sourceChips"></div>

  <div class="count-line" id="countLine"></div>

  <div class="table-wrap">
    <table>
      <thead><tr id="tableHead"></tr></thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>
  <div class="pagination" id="pagination"></div>
</div>

<div class="modal-overlay" id="covModal">
  <div class="modal-box">
    <button class="modal-close" onclick="closeCoverage()">✕</button>
    <div class="modal-title">Data Coverage by Source</div>
    <p style="font-size:13px;color:var(--muted);margin-bottom:18px">
      Every count on this dashboard is a floor. These are the known limits of each feed.
    </p>
    <div id="covBody"></div>
  </div>
</div>

<footer>
  <div>Marion County, Indiana · Distress Signal Intelligence<br/>
    Sources: Treasurer tax sale · DBNS code enforcement · County Recorder ·
    Indiana Courts (MyCase) · Sheriff sale</div>
  <div style="text-align:right">Built by <span class="brand">XCEREBRO</span><br/>
    <span id="genAt"></span></div>
</footer>

<script>
const DATA = /*__DATA__*/;
const R = DATA.records, RV = DATA.review, COV = DATA.coverage;

let view='signals', typeFilter='', sourceFilter='', stackOnly=false, page=1;
let filtered=[], stackedRows=[], expanded=new Set();
const PER=100;

const byParcel={};
R.forEach(r=>{ if(r.p){ (byParcel[r.p]=byParcel[r.p]||[]).push(r); } });

function esc(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;')
  .replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function money(v){return (v!=null&&v!==''&&!isNaN(v))
  ? '$'+Number(v).toLocaleString('en-US',{maximumFractionDigits:0}) : '—';}
function setText(id,v){const e=document.getElementById(id); if(e) e.innerHTML=v;}

// ── INIT ────────────────────────────────────────────────────────
setText('sTotal',   DATA.stats.total.toLocaleString());
setText('sParcels', DATA.stats.parcels.toLocaleString());
setText('sStacked', DATA.stats.stacked.toLocaleString());
setText('sDeepest', DATA.stats.deepest);
setText('sReview',  DATA.stats.review.toLocaleString());
setText('bSignals', DATA.stats.total.toLocaleString());
setText('bStacked', DATA.stats.stacked.toLocaleString());
setText('bReview',  DATA.stats.review.toLocaleString());
setText('lastUpdated', DATA.generated_at);
setText('genAt', DATA.generated_at);

// stacked parcels, deepest first
stackedRows = Object.keys(byParcel).filter(p=>byParcel[p].length>1)
  .map(p=>({p, sigs:byParcel[p]})).sort((a,b)=>b.sigs.length-a.sigs.length);

// chips
(function(){
  const tc={}; R.forEach(r=>tc[r.t]=(tc[r.t]||0)+1);
  const order=Object.keys(tc).sort((a,b)=>tc[b]-tc[a]);
  let h=`<button class="chip active" data-t="" onclick="setType('')">All Types <span class="ct">${R.length.toLocaleString()}</span></button>`;
  order.forEach(t=>{ const lbl=(R.find(x=>x.t===t)||{}).lt||t;
    h+=`<button class="chip" data-t="${esc(t)}" onclick="setType('${esc(t)}')">${esc(lbl)} <span class="ct">${tc[t].toLocaleString()}</span></button>`;});
  document.getElementById('typeChips').innerHTML=h;

  const sc={}; R.forEach(r=>sc[r.s]=(sc[r.s]||0)+1);
  let s=`<button class="chip active" data-s="" onclick="setSource('')">All Sources <span class="ct">${R.length.toLocaleString()}</span></button>`;
  Object.keys(sc).sort((a,b)=>sc[b]-sc[a]).forEach(k=>{
    const c=COV[k]||{level:'partial',short:''};
    s+=`<button class="chip" data-s="${esc(k)}" onclick="setSource('${esc(k)}')" title="${esc(c.short)}">`
      +`<span class="cov cov-${c.level}"></span>${esc(DATA.source_label[k]||k)} <span class="ct">${sc[k].toLocaleString()}</span></button>`;});
  document.getElementById('sourceChips').innerHTML=s;
})();

// coverage modal
(function(){
  const col={full:'var(--green)',capped:'var(--amber)',frozen:'var(--red)',partial:'var(--blue-light)'};
  document.getElementById('covBody').innerHTML=Object.keys(COV).map(k=>{
    const c=COV[k];
    return `<div class="cov-item" style="border-left-color:${col[c.level]}">
      <div class="lvl" style="color:${col[c.level]}">${esc(c.level)}</div>
      <h4>${esc(DATA.source_label[k]||k)} — ${esc(c.short)}</h4>
      <p>${esc(c.detail)}</p></div>`;}).join('');
})();

function openCoverage(){document.getElementById('covModal').classList.add('open');}
function closeCoverage(){document.getElementById('covModal').classList.remove('open');}

function setView(v){view=v;page=1;
  document.querySelectorAll('.view-tab').forEach(b=>b.classList.toggle('active',b.dataset.view===v));
  applyFilters();}
function setType(t){typeFilter=t;page=1;
  document.querySelectorAll('#typeChips .chip').forEach(b=>b.classList.toggle('active',b.dataset.t===t));
  applyFilters();}
function setSource(s){sourceFilter=s;page=1;
  document.querySelectorAll('#sourceChips .chip').forEach(b=>b.classList.toggle('active',b.dataset.s===s));
  applyFilters();}
function toggleStackOnly(){stackOnly=!stackOnly;page=1;
  document.getElementById('stackOnly').classList.toggle('active',stackOnly);applyFilters();}
function toggleStack(p){expanded.has(p)?expanded.delete(p):expanded.add(p);renderTable();}

let t0; function deb(){clearTimeout(t0);t0=setTimeout(()=>{page=1;applyFilters();},250);}
document.getElementById('searchInput').addEventListener('input',deb);

const HEADS={
  signals:['Lead Type','Source','Date','Parcel','Situs Address','Owner','Amount','Assessed','Signals','Instrument'],
  stacked:['Parcel','Situs Address','Owner','Assessed','Signals','Lead Types',''],
  review: ['Source','Reason','Derivation','Conf.','Reference','Detail']
};

function applyFilters(){
  const q=document.getElementById('searchInput').value.toLowerCase().trim();
  const mn=parseFloat(document.getElementById('avMin').value);
  const mx=parseFloat(document.getElementById('avMax').value);

  if(view==='review'){
    filtered=RV.filter(r=>!q||[r.src,r.reason,r.ref,r.detail,r.method].join(' ').toLowerCase().includes(q));
    setText('countLine',`Showing <span>${filtered.length.toLocaleString()}</span> review items — unresolved, not dropped`);
  } else if(view==='stacked'){
    filtered=stackedRows.filter(row=>{
      const s=row.sigs[0];
      if(typeFilter && !row.sigs.some(x=>x.t===typeFilter)) return false;
      if(sourceFilter && !row.sigs.some(x=>x.s===sourceFilter)) return false;
      if(!isNaN(mn) && !(s.av>=mn)) return false;
      if(!isNaN(mx) && !(s.av<=mx)) return false;
      if(q){const h=[row.p,s.a,s.o,...row.sigs.map(x=>x.lt)].join(' ').toLowerCase();
        if(!h.includes(q))return false;}
      return true;});
    setText('countLine',`Showing <span>${filtered.length.toLocaleString()}</span> parcels carrying more than one distress signal`);
  } else {
    filtered=R.filter(r=>{
      if(typeFilter && r.t!==typeFilter) return false;
      if(sourceFilter && r.s!==sourceFilter) return false;
      if(stackOnly && r.st<2) return false;
      if(!isNaN(mn) && !(r.av>=mn)) return false;
      if(!isNaN(mx) && !(r.av<=mx)) return false;
      if(q){const h=[r.o,r.a,r.p,r.pl,r.inst,r.lt,r.sl,r.note].join(' ').toLowerCase();
        if(!h.includes(q))return false;}
      return true;});
    const sv=document.getElementById('sortSelect').value, [k,d]=sv.split('_');
    filtered.sort((a,b)=>{
      if(k==='stack') return d==='desc'?b.st-a.st:a.st-b.st;
      if(k==='av')    return d==='desc'?(b.av||0)-(a.av||0):(a.av||0)-(b.av||0);
      if(k==='amt')   return d==='desc'?(b.amt||0)-(a.amt||0):(a.amt||0)-(b.amt||0);
      const av=a.d||'',bv=b.d||'';
      return d==='asc'?(av<bv?-1:av>bv?1:0):(av<bv?1:av>bv?-1:0);});
    setText('countLine',`Showing <span>${filtered.length.toLocaleString()}</span> distress signals`);
  }
  document.getElementById('tableHead').innerHTML=HEADS[view].map(h=>`<th>${h}</th>`).join('');
  renderTable(); renderPagination();
}

function renderTable(){
  const start=(page-1)*PER, rows=filtered.slice(start,start+PER);
  const tb=document.getElementById('tableBody');
  if(!rows.length){tb.innerHTML=`<tr><td colspan="10"><div class="empty">No records match these filters</div></td></tr>`;return;}

  if(view==='review'){
    tb.innerHTML=rows.map(r=>`<tr>
      <td><span class="src-pill">${esc(r.src)}</span></td>
      <td>${esc(r.reason)}</td>
      <td class="muted">${esc(r.method||'—')}</td>
      <td class="mono">${r.conf==null?'—':r.conf}</td>
      <td class="mono">${esc(r.ref||'—')}</td>
      <td class="muted">${esc((r.detail||'').slice(0,90))}</td></tr>`).join('');
    return;
  }

  if(view==='stacked'){
    tb.innerHTML=rows.map(row=>{
      const s=row.sigs[0], open=expanded.has(row.p);
      const types=[...new Set(row.sigs.map(x=>x.lt))];
      const chips=types.map(t=>{
        const g=(row.sigs.find(x=>x.lt===t)||{}).g||'other';
        return `<span class="pill" style="background:rgba(255,255,255,.06);color:var(--g-${g})">${esc(t)}</span>`;}).join(' ');
      let h=`<tr>
        <td class="mono">${esc(row.p)}<div class="addr-sub">${esc(s.pl||'')}</div></td>
        <td><div class="addr-main">${esc(s.a||'—')}</div><div class="addr-sub">${esc(s.z||'')}</div></td>
        <td>${esc(s.o||'—')}</td>
        <td class="mono">${money(s.av)}</td>
        <td><span class="stack-badge ${row.sigs.length>=4?'hot':''}">${row.sigs.length} signals</span></td>
        <td>${chips}</td>
        <td><button class="btn ghost" style="padding:4px 9px;font-size:11px" onclick="toggleStack('${esc(row.p)}')">${open?'Hide':'Show'}</button></td></tr>`;
      if(open){
        h+=`<tr class="stack-row"><td colspan="7">`+row.sigs.map(x=>
          `<div class="sig-line">
            <span class="pill" style="background:rgba(255,255,255,.06);color:var(--g-${x.g})">${esc(x.lt)}</span>
            <span class="src-pill">${esc(x.sl)}</span>
            <span class="mono muted">${esc(x.d||'—')}</span>
            <span class="mono">${esc(x.inst||'')}</span>
            <span class="muted">${esc(x.note||'')}</span>
            ${x.amt!=null?`<span class="mono">${money(x.amt)}</span>`:''}
            ${x.bf?'<span class="bf-tag">BACKFILL</span>':''}
          </div>`).join('')+`</td></tr>`;
      }
      return h;}).join('');
    return;
  }

  tb.innerHTML=rows.map(r=>`<tr>
    <td><span class="pill" style="background:rgba(255,255,255,.06);color:var(--g-${r.g})">${esc(r.lt)}</span>${r.bf?'<span class="bf-tag">BF</span>':''}</td>
    <td><span class="src-pill"><span class="cov cov-${(COV[r.s]||{}).level||'partial'}"></span>${esc(r.sl)}</span></td>
    <td class="mono" style="white-space:nowrap">${esc(r.d||'—')}</td>
    <td class="mono" style="white-space:nowrap">${esc(r.p||'—')}<div class="addr-sub">${esc(r.pl||'')}</div></td>
    <td><div class="addr-main">${esc(r.a||'—')}</div><div class="addr-sub">${esc(r.z||'')}</div></td>
    <td>${esc((r.o||'—').slice(0,42))}</td>
    <td class="mono">${money(r.amt)}</td>
    <td class="mono">${money(r.av)}</td>
    <td>${r.st>1?`<span class="stack-badge ${r.st>=4?'hot':''}" onclick="setView('stacked')">${r.st}</span>`:'<span class="muted">1</span>'}</td>
    <td class="mono muted" style="white-space:nowrap">${esc(r.inst||'—')}</td></tr>`).join('');
}

function renderPagination(){
  const total=Math.ceil(filtered.length/PER), el=document.getElementById('pagination');
  if(total<=1){el.innerHTML='';return;}
  let h=`<button class="page-btn" onclick="goPage(${page-1})" ${page===1?'disabled':''}>‹</button>`;
  for(let p=1;p<=total;p++){
    if(total>10 && p>3 && p<total-2 && Math.abs(p-page)>1){
      if(p===4||p===total-3) h+=`<span class="page-btn" style="border:none;background:none">…</span>`;
      continue;}
    h+=`<button class="page-btn ${p===page?'active':''}" onclick="goPage(${p})">${p}</button>`;}
  h+=`<button class="page-btn" onclick="goPage(${page+1})" ${page===total?'disabled':''}>›</button>`;
  el.innerHTML=h;
}
function goPage(p){const t=Math.ceil(filtered.length/PER);
  if(p<1||p>t)return;page=p;renderTable();renderPagination();window.scrollTo({top:0,behavior:'smooth'});}

// ── CSV ─────────────────────────────────────────────────────────
function dl(rows,name){
  const csv=rows.map(r=>r.map(v=>'"'+String(v==null?'':v).replace(/"/g,'""')+'"').join(',')).join('\n');
  const b=new Blob([csv],{type:'text/csv'}),u=URL.createObjectURL(b),a=document.createElement('a');
  a.href=u;a.download=name;a.click();URL.revokeObjectURL(u);
}
const STAMP=()=>new Date().toISOString().slice(0,10);

function exportCSV(){
  const src=(view==='signals'&&filtered.length)?filtered:R;
  const rows=[['Lead Type','Source','Coverage','Date','State Parcel','Local Parcel',
    'Situs Address','Zip','Owner','Amount','Assessed Value','Signals On Parcel',
    'Instrument','Note','Backfill']];
  src.forEach(r=>rows.push([r.lt,r.sl,(COV[r.s]||{}).short||'',r.d,r.p,r.pl,r.a,r.z,r.o,
    r.amt==null?'':r.amt,r.av==null?'':r.av,r.st,r.inst,r.note,r.bf?'YES':'']));
  dl(rows,`marion_signals_${STAMP()}.csv`);
}
function exportStacked(){
  const rows=[['State Parcel','Local Parcel','Situs Address','Owner','Assessed Value',
    'Signal Count','Lead Types','Sources']];
  stackedRows.forEach(row=>{const s=row.sigs[0];
    rows.push([row.p,s.pl,s.a,s.o,s.av==null?'':s.av,row.sigs.length,
      [...new Set(row.sigs.map(x=>x.lt))].join(' | '),
      [...new Set(row.sigs.map(x=>x.sl))].join(' | ')]);});
  dl(rows,`marion_stacked_parcels_${STAMP()}.csv`);
}
function exportReview(){
  const rows=[['Source','Reason','Derivation Method','Confidence','Reference','Detail']];
  RV.forEach(r=>rows.push([r.src,r.reason,r.method,r.conf==null?'':r.conf,r.ref,r.detail]));
  dl(rows,`marion_review_queue_${STAMP()}.csv`);
}

applyFilters();
</script>
</body>
</html>
"""


if __name__ == "__main__":
    build()
