"""
scrapers/_common.py — shared foundation for Marion County, Indiana source adapters.

Everything here is county-specific by design; the universal pipeline lives in
scaffold/ and must not learn about Marion. See MASTER_PROMPT.md §4.31.

Responsibilities:
  - immutable raw capture         data/raw/<source>/ , never overwritten
  - canonical parcel key contract recon/marion-in-recon.md §1.6
  - raw_event_record emission     scaffold/pipeline/contracts/raw_event_record.schema.json
  - review queue                  unknowns are routed, never dropped
  - polite HTTP                   recon observed no rate limiting; we throttle anyway

Copyright (c) 2026 Xcerebro LLC. Proprietary VIP license.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw"
OUT_DIR = REPO_ROOT / "data"

# Every adapter artifact lives under data/raw/. That is deliberate and load
# bearing, not cosmetic:
#   - .gitignore already excludes data/raw/, so none of it can reach history;
#   - the framework PII guard (scaffold/tests/test_no_pii_in_operator_code.py)
#     excludes any path with a "raw" component, so the gate does not scan
#     hundreds of MB of owner names — and does not fail on them.
# The crosswalk, review queue and run report all carry real owner names and
# situs addresses, so they belong here with the rest of the raw material.
REVIEW_PATH = RAW_DIR / "review_queue.jsonl"
CROSSWALK_DIR = RAW_DIR / "crosswalk"
REPORT_PATH = RAW_DIR / "pipeline_report.json"

COUNTY_SLUG = "marion_in"
STATE_PARCEL_PREFIX = "49-"          # §1.6: constant for Marion County
MIN_PARCEL_CONFIDENCE = 80           # below this a derived parcel goes to review

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
)

# Politeness. Recon observed no throttling on any source; we still pace requests.
DEFAULT_DELAY_S = 1.2


# ---------------------------------------------------------------------------
# time / ids
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def stable_id(prefix: str, *parts: Any) -> str:
    key = "|".join("" if p is None else str(p) for p in parts)
    h = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}-{h}"


# ---------------------------------------------------------------------------
# immutable raw capture
# ---------------------------------------------------------------------------

def write_raw(source: str, name: str, payload: Any, *, binary: bool = False) -> Path:
    """Write a raw source response. NEVER overwrites.

    Raw data is immutable (FRAMEWORK_VERSION.json locked rule raw_data_immutable).
    If the target exists, a run-stamped sibling is written instead so the original
    capture is preserved verbatim.
    """
    d = RAW_DIR / source
    d.mkdir(parents=True, exist_ok=True)
    path = d / name
    if path.exists():
        path = d / f"{path.stem}__{run_stamp()}{path.suffix}"
    if binary:
        path.write_bytes(payload)
    else:
        text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False, indent=2)
        path.write_text(text, encoding="utf-8")
    return path


def write_jsonl(path: Path, records: Iterable[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def http_json(url: str, *, method: str = "GET", body: Optional[dict] = None,
              headers: Optional[dict] = None, timeout: int = 90,
              delay: float = DEFAULT_DELAY_S) -> Any:
    """Polite JSON request. Raises on transport error; caller decides policy."""
    time.sleep(delay)
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json; charset=utf-8")
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_bytes(url: str, *, timeout: int = 120, delay: float = DEFAULT_DELAY_S) -> bytes:
    time.sleep(delay)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def arcgis_query(layer_url: str, *, where: str = "1=1", out_fields: str = "*",
                 result_offset: int = 0, result_record_count: int = 1000,
                 order_by: str = "", extra: Optional[dict] = None) -> dict:
    """One ArcGIS REST /query call. returnGeometry is always false — §1.4 says
    geometry is what makes the parcel layer non-row-unique."""
    params = {
        "where": where,
        "outFields": out_fields,
        "returnGeometry": "false",
        "f": "json",
        "resultOffset": str(result_offset),
        "resultRecordCount": str(result_record_count),
    }
    if order_by:
        params["orderByFields"] = order_by
    if extra:
        params.update(extra)
    url = f"{layer_url}/query?{urllib.parse.urlencode(params)}"
    return http_json(url)


def arcgis_page_all(layer_url: str, *, where: str = "1=1", out_fields: str = "*",
                    page_size: int = 1000, max_records: Optional[int] = None,
                    order_by: str = "") -> list[dict]:
    """Page an ArcGIS layer. maxRecordCount on MapIndy is 1000 (recon §4.5)."""
    out: list[dict] = []
    offset = 0
    while True:
        js = arcgis_query(layer_url, where=where, out_fields=out_fields,
                          result_offset=offset, result_record_count=page_size,
                          order_by=order_by)
        feats = js.get("features") or []
        out.extend(f.get("attributes", {}) for f in feats)
        if len(feats) < page_size:
            break
        offset += page_size
        if max_records and len(out) >= max_records:
            break
    return out[:max_records] if max_records else out


# ---------------------------------------------------------------------------
# canonical parcel key — recon §1.6
# ---------------------------------------------------------------------------

_STATE_PARCEL_RE = re.compile(r"^\d{2}-\d{2}-\d{2}-\d{3}-\d{3}\.\d{3}-\d{3}$")


def norm_state_parcel(value: Any) -> Optional[str]:
    """parcel_id_state — verbatim, punctuation preserved, uppercase, trimmed.

    §1.6: never re-derive from segments, never zero-strip the .000 suffix, and a
    number that does not begin '49-' is not a Marion parcel.
    """
    if value is None:
        return None
    s = str(value).strip().upper()
    if not s:
        return None
    if not s.startswith(STATE_PARCEL_PREFIX):
        return None
    if not _STATE_PARCEL_RE.match(s):
        return None
    return s


def norm_state_parcel_digits(value: Any) -> Optional[str]:
    """parcel_id_state_n — digits only, fixed width 18."""
    s = norm_state_parcel(value)
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    return digits if len(digits) == 18 else None


def norm_local_parcel(value: Any) -> Optional[str]:
    """parcel_id_local — PARCEL_C as a zero-padded 7-character string."""
    if value is None:
        return None
    s = re.sub(r"\D", "", str(value).strip())
    if not s:
        return None
    return s.zfill(7)


def parcel_keys(state_parcel: Any = None, local_parcel: Any = None) -> dict:
    """Build the three-key block every parcel-bearing record must carry (§1.6)."""
    return {
        "parcel_id_state": norm_state_parcel(state_parcel),
        "parcel_id_state_n": norm_state_parcel_digits(state_parcel),
        "parcel_id_local": norm_local_parcel(local_parcel),
    }


# ---------------------------------------------------------------------------
# address normalization — for the crosswalk
# ---------------------------------------------------------------------------

_DIR = {"N": "N", "S": "S", "E": "E", "W": "W", "NE": "NE", "NW": "NW",
        "SE": "SE", "SW": "SW", "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W"}

_SUFFIX = {
    "STREET": "ST", "ST": "ST", "AVENUE": "AVE", "AVE": "AVE", "AV": "AVE",
    "ROAD": "RD", "RD": "RD", "DRIVE": "DR", "DR": "DR", "LANE": "LN", "LN": "LN",
    "COURT": "CT", "CT": "CT", "CIRCLE": "CIR", "CIR": "CIR", "BOULEVARD": "BLVD",
    "BLVD": "BLVD", "PLACE": "PL", "PL": "PL", "TERRACE": "TER", "TER": "TER",
    "PARKWAY": "PKWY", "PKWY": "PKWY", "TRAIL": "TRL", "TRL": "TRL",
    "WAY": "WAY", "PIKE": "PIKE", "RUN": "RUN", "PASS": "PASS", "CROSSING": "XING",
}

_NOISE_RE = re.compile(r"\b(APT|UNIT|STE|SUITE|#|FL|FLOOR|BLDG|BUILDING|RM|ROOM)\b.*$",
                       re.IGNORECASE)


def norm_address(raw: Any) -> Optional[str]:
    """Normalize a street address to a comparable key.

    Deliberately conservative: uppercase, strip unit designators, canonicalize
    direction and street-type tokens, collapse whitespace. Deterministic before
    semantic — no fuzzy matching here.
    """
    if raw is None:
        return None
    s = str(raw).upper().strip()
    if not s:
        return None
    s = s.split(",")[0]                    # drop ", INDIANAPOLIS, IN 46218"
    s = _NOISE_RE.sub("", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    toks = [t for t in s.split() if t]
    if not toks:
        return None
    out = []
    for i, t in enumerate(toks):
        if i > 0 and t in _DIR and i < len(toks) - 1:
            out.append(_DIR[t])
        elif t in _SUFFIX:
            out.append(_SUFFIX[t])
        else:
            out.append(t)
    return " ".join(out).strip() or None


def address_key(house_no: Any, street: Any, zipcode: Any = None) -> Optional[str]:
    """Composite crosswalk key: '<houseno>|<normalized street>|<zip5>'."""
    hn = re.sub(r"\D", "", str(house_no or "")).lstrip("0")
    st = norm_address(street)
    if not hn or not st:
        return None
    z = re.sub(r"\D", "", str(zipcode or ""))[:5]
    return f"{hn}|{st}|{z}" if z else f"{hn}|{st}|"


# ---------------------------------------------------------------------------
# raw_event_record emission
# ---------------------------------------------------------------------------

def raw_event(*, raw_event_id: str, source_id: str, canonical_doc_type: str,
              source_url: str, recorded_date: Optional[str],
              instrument_number: Optional[str], parties: list[dict],
              parcel_id: Optional[str] = None, situs_address: Optional[str] = None,
              legal_description: Optional[str] = None, case_number: Optional[str] = None,
              raw_doc_type: Optional[str] = None, event_date: Optional[str] = None,
              amounts: Optional[list[dict]] = None, document_body_text: str = "",
              parser_name: str = "", parser_version: str = "1.0",
              parser_confidence: int = 90,
              source_role: str = "PRIMARY_EVENT_SOURCE") -> dict:
    """Build a contract-shaped raw_event_record.

    parcel_id may be null — 13_lead_origination_contract.md §13.14 emits the lead
    UNRESOLVED rather than dropping it. That is the correct home for a court
    record with no address (recon §1.5).
    """
    prop: dict[str, Any] = {
        "parcel_id": parcel_id,
        "situs_address": situs_address,
        "legal_description": legal_description,
    }
    if case_number is not None:
        prop["case_number"] = case_number
    return {
        "raw_event_id": raw_event_id,
        "source_id": source_id,
        "source_role": source_role,
        "raw_doc_type": raw_doc_type,
        "canonical_doc_type": canonical_doc_type,
        "instrument_number": instrument_number,
        "recorded_date": recorded_date,
        "event_date": event_date,
        "source_url": source_url,
        "parties": parties,
        "document_body_text": document_body_text,
        "property_refs": prop,
        "amounts": amounts or [],
        "evidence_ids": [],
        "parser_name": parser_name or source_id,
        "parser_version": parser_version,
        "parser_confidence": parser_confidence,
        "captured_at": utc_now_iso(),
    }


def party(name: str, name_type: str) -> dict:
    """name_type ∈ TP | DF | GR | GE | PL | OTHER (contract enum)."""
    return {"name": (name or "").strip(), "name_type": name_type}


# ---------------------------------------------------------------------------
# review queue — unknowns are routed, never dropped
# ---------------------------------------------------------------------------

_REVIEW_BUF: list[dict] = []


def to_review(*, source_id: str, reason: str, record: dict,
              derivation_method: Optional[str] = None,
              confidence: Optional[int] = None) -> None:
    """Route a record that could not be resolved. Never silently drop."""
    _REVIEW_BUF.append({
        "review_id": stable_id("RVW", source_id, reason, json.dumps(record, sort_keys=True)[:400]),
        "source_id": source_id,
        "reason": reason,
        "derivation_method": derivation_method,
        "confidence": confidence,
        "queued_at": utc_now_iso(),
        "record": record,
    })


def flush_review() -> int:
    """Append the buffered review items to data/review_queue.jsonl."""
    if not _REVIEW_BUF:
        return 0
    REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REVIEW_PATH.open("a", encoding="utf-8") as fh:
        for r in _REVIEW_BUF:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(_REVIEW_BUF)
    _REVIEW_BUF.clear()
    return n


def review_count() -> int:
    return len(read_jsonl(REVIEW_PATH))


# Any adapter run standalone must still persist its review items. Without this,
# to_review() buffers in-process and the queue is silently lost on exit — which
# would turn "routed to review" into exactly the silent drop the framework
# forbids.
import atexit  # noqa: E402

atexit.register(flush_review)


# ---------------------------------------------------------------------------
# console
# ---------------------------------------------------------------------------

def banner(title: str) -> None:
    print()
    print("=" * 72)
    print(f"  {title}")
    print("=" * 72)


def log(msg: str) -> None:
    print(f"  {msg}")
