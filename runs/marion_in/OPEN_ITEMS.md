# OPEN ITEMS — marion_in

Framework gaps, blockers, and deferred work found while building source adapters.
Nothing here modifies the framework repo; this file is the county-side record so
the build keeps moving. Framework changes are a separate, later decision.

Opened 2026-08-05 during the scraper build session.

---

## FRAMEWORK GAPS (do not fix here — record only)

### FG-1 — No canonical doc type for tax delinquency
`knowledge_base/domain/canonical_doc_types.json` has 74 canonical types. The tax
family is `FEDERAL_TAX_LIEN`, `STATE_TAX_LIEN`, `TAX_SALE_CERTIFICATE`,
`TAX_FORECLOSURE_NOTICE`, `TAX_DEED`. There is **no** type for "parcel carries an
unpaid balance but has not yet been sold" — the single largest tax-distress
population and the one §01.31 calls `DELINQUENCY_LIST`.

Interim decision in this build: Marion's Tax Sale Parcel Status List maps to
`TAX_FORECLOSURE_NOTICE` for every status except `Sold`, which maps to
`TAX_SALE_CERTIFICATE`. The true status string is preserved on the raw record so
nothing is lost, but two materially different distress states currently share
one canonical type.

### FG-2 — No canonical type for tax-sale surplus, only sheriff-sale surplus
Marion publishes a "Tax Sale Surplus Details" list. The only surplus canonical is
`SHERIFF_SALE_SURPLUS` (`lead_pattern: surplus_owed`). Tax-sale surplus is mapped
to it here. Different origin, same pattern — acceptable but imprecise.

### FG-3 — `EVICT` / `EVICTION_FILING` duplication
Both appear in the canonical registry. Unclear which is authoritative. Not used
in this session (MyCase scope is MF only) but will matter when evictions are
built — Marion has two eviction dockets and very high volume.

### FG-4 — No canonical type for a judicial-foreclosure COMPLAINT
Indiana is judicial-only. The court filing (`MF - Mortgage Foreclosure`) is the
originating event, but the registry's foreclosure family is built around
non-judicial artifacts (`NOTICE_OF_DEFAULT`, `NOTICE_OF_SALE`,
`TRUSTEES_DEED_UPON_SALE`) plus `FINAL_JUDGMENT_OF_FORECLOSURE`, which is the
judgment, not the filing.

Interim decision: MF maps to `LIS_PENDENS`, whose `lead_pattern` is
`by_state_profile` and therefore resolves through `state_rule_family:
IN_judicial_foreclosure`. This is the closest correct fit, but a
`FORECLOSURE_COMPLAINT` canonical would be more honest.

### FG-5 — PII guard vs §01.22 samples (already filed upstream)
Tracked as xcerebroai/xcerebro-county-intel#6 (semantic_verify `samples` field).
No action here.

---

## SOURCE BLOCKERS

### SB-1 — Sheriff sale list — RESOLVED IN THIS BUILD
Recon §5.1 recovered the registration URL but never rendered the portal, so the
list structure was unverified.

Resolved: the registration page does not itself contain the list, but it links
to "Public Sold To List" PDFs under `/uploads/` and `/ftp/IN/Marion/`. Three
were found and parsed (225 rows, 99.1% carrying a parcel number). Each row has:

    SFN #  |  Cause #  |  Parcel Number  |  Parcel Address  |  Parcel Status

The **Cause #** is the MyCase court case number and the **Parcel Number** is the
LOCAL parcel key — on the same row. The bridge is a direct key join, not the
address match the recon anticipated. See `scrapers/sheriff_sale.py` and
`scrapers/mycase_sheriff_join.py`.

Remaining: the PDF list URLs are discovered by scraping links off the
registration page each run. If GovEase changes that page's markup, discovery
breaks. There is no stable index endpoint.

### SB-2 — MyCase carries no address — RESOLVED via SB-1, with a caveat
MyCase genuinely has no address and no parcel (recon §4.3, re-confirmed). But
the sheriff list join (SB-1) resolves MF cases to a parcel by cause number with
no address involved, so the address crosswalk is not needed for MyCase after all.

Caveat that is a property of the data, not a defect: a case appears on the
sheriff list only once it has reached sale, months after filing. Freshly-filed
MF cases therefore have NO knowable parcel yet and stay UNRESOLVED in the review
queue. Measured on a live batch: 40/73 resolved (54.8%); the 33 unresolved were
all June-2026 filings that have not reached sale.

Owner-name matching remains unused, per recon §1.5 path 3.

### SB-6 — RESOLVED 2026-08-05 by recursive date slicing
The adapter now slices by document type and recursively bisects the date range
whenever the portal truncates, and never accepts a capped slice as complete.

Truncation signal and verification path (the portal hands us both):

    TotalResults     true match count for the criteria
    ViewableResults  how many it will return
    DocResults[]     rows actually returned

Under the cap all three agree; at the cap TotalResults races ahead. So
`TotalResults > len(DocResults)` is an explicit truncation flag AND TotalResults
is an independent count to verify each slice against. A harvest is complete only
when every slice satisfies `returned == TotalResults` and zero slices remain
capped.

July 2026 backfill: 9 slices, 0 bisections needed, 445 rows, independent total
445, zero capped — VERIFIED COMPLETE for the 9 mapped doc types.

Bisection proved separately by forcing RESULT_CAP to 40 and re-harvesting
HOSPITAL LIEN (141 rows): 15 slices, 7 bisections, narrowed to 1-day, union
reconciled to exactly 141 unique instruments with zero unresolved caps.

IMPORTANT SCOPE NOTE — the "~8,251 filings/month, 2.4% coverage" framing mixes
two denominators. 8,251 is ALL 50 document types for a month, most of which are
ordinary mortgages, deeds and assignments that are not distress signals. The
adapter deliberately harvests 9 mapped distress types. For those types coverage
is now verified complete, not 2.4%. A genuine all-type harvest would need the
doc-type dimension across all 50 codes and is a different (much larger) job.

Residual: for ALL types combined, even a single day exceeds 200, so date
bisection alone cannot reach full all-type coverage — the doc-type axis is
required, which is what the adapter already uses.

### SB-6-orig — Recorder returns at most 200 rows per search (original finding)
Not recorded by the recon, which only ever ran a name search returning 90 rows.
A one-month all-types search reports `TotalResults: 8251` but
`ViewableResults: 200` and returns 200 rows.

Consequence: date windows must be sliced fine enough to stay under 200 PER
DOCUMENT TYPE. The adapter logs a `result_cap_truncation` review item whenever
`TotalResults > returned` so silent truncation cannot happen unnoticed.

### SB-7 — Recorder search cannot be driven by a plain HTTP client (NEW detail)
Confirmed the recon's 401 finding and found why: the Bearer JWE and
`fidlarcaptchasolution` headers are attached by the app's Angular HTTP
interceptor. A `fetch()` issued from inside the page bypasses the interceptor
and also gets 401.

Working approach: Playwright route interception rewrites the POST body of the
search the app issues itself, so the app signs the request and the adapter
chooses the criteria. No CAPTCHA is solved and no token is forged or replayed.
Navigating back from the results view proved unreliable, so the adapter reloads
the portal per search.

### SB-3 — Indiana Gateway bulk export unproven
Recon §6.2: the "Export to Excel" control is present and enabled but produced no
download event in headless Chromium. Gateway is therefore treated as
`PER_RECORD_ONLY` — queried per parcel, not bulk. Fine for enrichment of a known
parcel set; not a discovery source.

### SB-4 — Accela Reports module not exercised
Recon §4.4: a "Case Research Report" / "Case Summary" exists per module and is
the likely bulk path. Not exercised. The adapter uses the public search form,
which is `PER_RECORD_ONLY`-ish and slower.

### SB-5 — Recorder requires a browser context
Recon §4.1: `POST /breeze/Search` returns 401 without a Bearer JWE plus a
`fidlarcaptchasolution` reCAPTCHA v3 token, both minted by the page. The adapter
runs Playwright. `/breeze/Settings` and `/breeze/DocumentTypes` need no auth and
are fetched over plain HTTP.

Also binding: 5-day cursor lag (portal states documents appear five days after
recording) and exact-match party search only (`UseWildcardSearches: false`).

---

### SB-8 — Portal throttling: none observed (2026-08-05)
Recorded so we can schedule around it like Harris if it starts.

    backfill run  2026-07-01..07-31, 9 searches, ~1.5s apart, 0 throttle events
    bisect proof  15 searches, ~1.5s apart, 0 throttle events
    HTTP statuses observed: 200 only. No 429, no 503, no degradation.

The adapter retries with linear backoff (5s x attempt, 3 attempts) and records
any 429/503 with a timestamp into the run summary and the review queue. The
daily cron is set to 09:00 UTC (04:00 Indianapolis). If throttling appears at
that hour, shift the cron rather than fight it and append the signature here.

### SB-9 — xcerebroai/marion-dashboard does not exist
The daily-automation request specified pushing the regenerated dashboard to
`xcerebroai/marion-dashboard`. That repository does not exist under the org.

The workflow therefore keeps publishing from `marion-county-intel`, which is the
live Pages source today (https://xcerebroai.github.io/marion-county-intel/) and
already works. Creating a second public repo is an outward-facing action with
the same PII exposure profile as the first, so it is left as an operator
decision rather than done implicitly.

### SB-10 — "score desc" requested but no score exists
The daily-automation request asks for default sort "new leads first, then score
desc within same-day cohorts", and for an updated score distribution.

This build has NO scoring by explicit earlier instruction ("NO SCORING — do not
compute, rank, or display any composite score"), and the dashboard is verified
to contain zero occurrences of the word. The cohort tiebreak is therefore
signals-on-parcel descending, then filing date descending — the two strongest
non-derived indicators available. Reported as lead-type distribution instead of
a score distribution. Reversible if scoring is ever introduced.

## COVERAGE NOTES

### CN-0 — the two lead types still empty after the first full run (17/19)
Neither is an adapter failure:

- **Construction Lien** can never populate separately. Marion's recorder has ONE
  code (24, "MECHANIC LIEN") covering both mechanic and construction liens
  (recon §3.2), and it maps to `MECHANICS_LIEN`. Emitting `CONSTRUCTION_LIEN`
  would require inventing a distinction the county's own taxonomy does not make.
  Counting these as two lead types overstates achievable coverage; realistically
  the ceiling is 18, not 19.
- **Federal Tax Lien** (code 21) returned `TotalResults: 0` for the sampled
  2026-01-05..09 window. A genuine zero for five days, not a fetch error — the
  search returned HTTP 200 with an empty result set. It will populate over a
  wider window.

### CN-1 — tax sale PDF kerning corrupts text fields
The source PDFs carry kerning that survives layout extraction as stray spaces
inside words ("INDIANAP O LIS", "Enc roa c hme nt Is s ue"). Numeric fields
(parcel number, amounts) are clean because whitespace is stripped before
parsing. Owner and address text is NOT clean.

Mitigated for status strings by matching on the alpha-only reduction against a
known vocabulary; 9 rows still failed to match and went to review rather than
being guessed. Owner/address text from the tax sale PDFs should not be used for
matching — the parcel number is already present and authoritative.

## COVERAGE NOTES (from recon)

- Recorder → parcel join works only for platted lots: 114,831 of 347,050 parcels
  (33%) have both `SUBDIVISION_TAG > 0` and a populated `LOTNUM` (recon §1.5).
  Metes-and-bounds parcels are unreachable by that path.
- Six lead types are NOT_SEPARABLE in Marion's recorder taxonomy (lis pendens,
  abstract of judgment, state tax lien, heirship affidavit, executor deed,
  administrator deed) — they have no dedicated document-type code and sit inside
  generic AFFIDAVIT / DEED / LIEN / COURT DOCUMENT buckets (recon §3.2).
- Excluded cities (Beech Grove, Lawrence, Southport, Speedway) run their own code
  enforcement; DBNS/Accela coverage has holes there (recon §4.5).
