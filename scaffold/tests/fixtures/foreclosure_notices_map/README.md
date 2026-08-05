# foreclosure_notices_map fixtures

Each `*.json` file in this directory is a captured (or hand-built) ArcGIS
REST `/query` response that exercises one branch of the
`scrapers/foreclosure_notices_map.py` adapter. The framework's adapter
test (`scaffold/tests/test_foreclosure_notices_map.py`) injects a fake
`fetch_fn` that returns the appropriate fixture per request URL, then
asserts the adapter's emitted JSONL matches the expectation embedded in
the fixture filename.

Fixture inventory:

  - `mortgage_typical.json`        — happy path: 2 mortgage NSTS records
  - `tax_typical.json`             — happy path: 1 tax foreclosure record
  - `empty_layer.json`             — no features (current month not yet posted)
  - `pagination_first_page.json`   — full page of 1000 records
  - `pagination_second_page.json`  — final partial page
  - `missing_doc_number.json`      — record with empty DOC_NUMBER (low parser_confidence)
  - `malformed_year_month.json`    — record with null year/month (no event_date)
  - `arcgis_error_envelope.json`   — ArcGIS-style error response
  - `count_only.json`              — returnCountOnly response

All fixtures carry the verified 2026-05-14 schema:
`OBJECTID, ADDRESS, DOC_NUMBER, YEAR, MONTH, SCHOOL_DIST, TYPE, CITY,
ZIP, Shape`.

Data is synthetic — addresses use the `XXX SYNTHETIC LN` pattern and
doc numbers use a `FIX-YYYY-NNNNNN` shape so the framework cannot
mistake them for real records.
