"""
Adapter test for scrapers/foreclosure_notices_map.py.

Per engineering/05_verification_and_rollback.md "Scraper fixture
requirement", every adapter must ship with at least 8 fixtures
covering the realistic branches of the source. The injected
`fetch_fn` returns the appropriate fixture based on the request URL
+ params, so the adapter is exercised end-to-end without touching
the network.

This test runs as part of `scaffold/tests/run_all.py`.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.scrapers._arcgis_featureserver import (  # noqa: E402
    ArcGISFeatureServer,
    ArcGISServerError,
)
from scrapers import foreclosure_notices_map as fnm  # noqa: E402


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "foreclosure_notices_map"


def _load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------
# Reusable fake fetcher
# ---------------------------------------------------------------------

class FakeFetch:
    """Injectable fetch_fn that maps (url, params) -> fixture payload."""

    def __init__(self, routes: dict):
        # routes is dict[(layer_id_str, kind)] -> fixture name or list of
        # fixtures (for pagination scenarios where multiple offsets need
        # different payloads).
        self.routes = routes
        self.calls = []

    def __call__(self, url: str, params: dict) -> dict:
        self.calls.append({"url": url, "params": dict(params)})

        if "returnCountOnly" in params and params.get("returnCountOnly") == "true":
            return _load("count_only.json")

        # Per-layer fixture (URL ends with /<layer_id>/query).
        parts = url.rstrip("/").split("/")
        layer_id = parts[-2]  # e.g. ".../MapServer/0/query"

        kind = self.routes.get((layer_id, "query"))
        if kind is None:
            # Fallback: empty layer.
            return _load("empty_layer.json")

        if isinstance(kind, list):
            # Pagination: the offset determines which fixture to return.
            offset = int(params.get("resultOffset", 0))
            page_idx = min(offset // max(1, int(params.get("resultRecordCount", 1000))),
                           len(kind) - 1)
            return _load(kind[page_idx])

        return _load(kind)


def _assert(label, cond, detail=""):
    if cond:
        print(f"  [PASS] {label}")
        return True
    print(f"  [FAIL] {label}  --  {detail}")
    return False


# ---------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------

def test_happy_path_two_layers() -> int:
    fake = FakeFetch({
        ("0", "query"): "mortgage_typical.json",
        ("1", "query"): "tax_typical.json",
    })
    server = ArcGISFeatureServer(
        "https://maps.bexar.org/arcgis/rest/services/CC/ForeclosuresProd/MapServer",
        fetch_fn=fake,
    )
    records = list(fnm.fetch_all(server))

    ok = True
    ok &= _assert("happy: 3 records pulled across two layers", len(records) == 3,
                  f"got {len(records)}")
    ok &= _assert("happy: every record carries source_id",
                  all(r["source_id"] == "foreclosure_notices_map" for r in records))
    ok &= _assert("happy: every record carries raw_record_id",
                  all(r["raw_record_id"].startswith("raw_") for r in records))
    mortgage_records = [r for r in records if r["raw_payload"]["layer_id"] == 0]
    tax_records = [r for r in records if r["raw_payload"]["layer_id"] == 1]
    ok &= _assert("happy: 2 mortgage records", len(mortgage_records) == 2)
    ok &= _assert("happy: 1 tax record", len(tax_records) == 1)
    ok &= _assert("happy: event_date derived from year+month",
                  all(r["raw_payload"]["recording_event_date"] == "2026-05-01" for r in records))
    ok &= _assert("happy: parser_confidence high for full records",
                  all(r["parser_confidence"] == 95 for r in records))
    return 0 if ok else 1


def test_empty_layer() -> int:
    fake = FakeFetch({
        ("0", "query"): "empty_layer.json",
        ("1", "query"): "empty_layer.json",
    })
    server = ArcGISFeatureServer(
        "https://example/MapServer",
        fetch_fn=fake,
    )
    records = list(fnm.fetch_all(server))
    return 0 if _assert("empty layer yields 0 records", len(records) == 0) else 1


def test_pagination_completes() -> int:
    fake = FakeFetch({
        ("0", "query"): ["pagination_first_page.json", "pagination_second_page.json"],
        ("1", "query"): "empty_layer.json",
    })
    server = ArcGISFeatureServer(
        "https://example/MapServer",
        fetch_fn=fake,
        page_size=1000,
    )
    records = list(fnm.fetch_all(server))
    return 0 if _assert(
        "pagination: 1000 + 200 = 1200 records",
        len(records) == 1200,
        f"got {len(records)}",
    ) else 1


def test_missing_doc_number_lowers_confidence() -> int:
    fake = FakeFetch({
        ("0", "query"): "missing_doc_number.json",
        ("1", "query"): "empty_layer.json",
    })
    server = ArcGISFeatureServer(
        "https://example/MapServer",
        fetch_fn=fake,
    )
    records = list(fnm.fetch_all(server))
    ok = True
    ok &= _assert("missing doc#: still produces 1 record", len(records) == 1)
    ok &= _assert("missing doc#: parser_confidence drops to 70",
                  records[0]["parser_confidence"] == 70)
    return 0 if ok else 1


def test_malformed_year_month_no_event_date() -> int:
    fake = FakeFetch({
        ("0", "query"): "malformed_year_month.json",
        ("1", "query"): "empty_layer.json",
    })
    server = ArcGISFeatureServer(
        "https://example/MapServer",
        fetch_fn=fake,
    )
    records = list(fnm.fetch_all(server))
    return 0 if _assert(
        "null year/month yields recording_event_date=None",
        records[0]["raw_payload"]["recording_event_date"] is None,
    ) else 1


def test_arcgis_error_envelope_raises() -> int:
    fake = FakeFetch({
        ("0", "query"): "arcgis_error_envelope.json",
    })
    server = ArcGISFeatureServer(
        "https://example/MapServer",
        fetch_fn=fake,
    )
    try:
        list(server.iter_features(layer_id=0))
    except ArcGISServerError as e:
        return 0 if _assert(
            "ArcGIS error envelope raises ArcGISServerError",
            e.code == 400 and "Invalid where clause" in e.message,
        ) else 1
    _assert("ArcGIS error envelope raises ArcGISServerError", False,
            "expected exception, got success")
    return 1


def test_count_only() -> int:
    fake = FakeFetch({})
    server = ArcGISFeatureServer(
        "https://example/MapServer",
        fetch_fn=fake,
    )
    n = server.count_features(layer_id=0)
    return 0 if _assert("count_only returns int 482", n == 482) else 1


def test_run_writes_jsonl_and_marks_change_status() -> int:
    fake = FakeFetch({
        ("0", "query"): "mortgage_typical.json",
        ("1", "query"): "tax_typical.json",
    })
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "foreclosure_notices_map.jsonl"

        # First run — everything is NEW_RECORD.
        stats1 = fnm.run(output_path=out, fetch_fn=fake)
        ok = True
        ok &= _assert("run #1: stats.total_after_merge == 3",
                      stats1["total_after_merge"] == 3)
        ok &= _assert("run #1: stats.new_record_count == 3",
                      stats1["new_record_count"] == 3)
        ok &= _assert("run #1: jsonl file written",
                      out.exists() and out.stat().st_size > 0)

        # Second run on identical data — SAME records.
        fake2 = FakeFetch({
            ("0", "query"): "mortgage_typical.json",
            ("1", "query"): "tax_typical.json",
        })
        stats2 = fnm.run(output_path=out, fetch_fn=fake2)
        ok &= _assert("run #2: same data -> all SAME",
                      stats2["same_record_count"] == 3,
                      f"got new={stats2['new_record_count']} same={stats2['same_record_count']}")
        ok &= _assert("run #2: no NEW_RECORD on rerun",
                      stats2["new_record_count"] == 0)
        ok &= _assert("run #2: total still 3",
                      stats2["total_after_merge"] == 3)

        return 0 if ok else 1


def test_run_marks_disappeared_records() -> int:
    fake_full = FakeFetch({
        ("0", "query"): "mortgage_typical.json",
        ("1", "query"): "tax_typical.json",
    })
    fake_subset = FakeFetch({
        ("0", "query"): "tax_typical.json",  # only 1 tax record this run
        ("1", "query"): "empty_layer.json",
    })
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "foreclosure_notices_map.jsonl"
        fnm.run(output_path=out, fetch_fn=fake_full)
        stats2 = fnm.run(output_path=out, fetch_fn=fake_subset)
        return 0 if _assert(
            "disappeared records flagged",
            stats2["disappeared_record_count"] >= 2,
            f"got {stats2['disappeared_record_count']}",
        ) else 1


def main() -> int:
    print("[adapter test] scrapers/foreclosure_notices_map.py")
    rcs = [
        test_happy_path_two_layers(),
        test_empty_layer(),
        test_pagination_completes(),
        test_missing_doc_number_lowers_confidence(),
        test_malformed_year_month_no_event_date(),
        test_arcgis_error_envelope_raises(),
        test_count_only(),
        test_run_writes_jsonl_and_marks_change_status(),
        test_run_marks_disappeared_records(),
    ]
    failures = sum(1 for rc in rcs if rc != 0)
    print(f"\nfailures: {failures} of {len(rcs)}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
