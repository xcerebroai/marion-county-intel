# 02 — Signals and Sources

This file is the rule that prevents the framework from repeating a prior county-build mistake of treating parcel-master nominal-consideration deeds as leads. Every source — and every canonical document type produced from it — is classified as one of four classes:

- **`lead_generating`** — discrete, dated, recorded events that signal distress, transfer, or legal action
- **`enrichment`** — parcel state metadata (assessed value, year built, owner name, etc.)
- **`negative_signal`** — releases, satisfactions, discharges, dismissals, vacated judgments — events that suppress prior lead-generating signals
- **`review_required`** — documents the framework cannot confidently classify; routed to human review

The pipeline must respect this classification. Source classification flows from the canonical-document-type registry (`canonical_doc_types.json`) which carries `source_class` per type.

---

## Phase 0 source-category checklist

This is the exhaustive checklist Phase 0 recon walks for every county build. Each category is a *potential* source — the recon discovers whether the target county exposes it, where, and how. **No category may be skipped without explicit recording.** If a category does not exist for the target county, mark it `NOT_FOUND` in the county config and continue. If it exists but cannot be confirmed as official, mark it `UNVERIFIED`. Both states require `operator_override: true` before any later phase can build against them.

The categories below are universal — they apply to every county built on this framework. The specific URL, vendor portal, access pattern, and field shape are county-specific and live in `config/counties/<county_slug>.json`.

### Lead-generating recorder / clerk sources

1. Official county homepage (anchor for discovering everything else)
2. County clerk recorder — main portal
3. Official public records (general statutory records portal)
4. Deed records (warranty deeds, special warranty, quitclaim, gift, trustee, sheriff's deeds, etc.)
5. Mortgage / deed-of-trust records
6. Lien records (mechanic's, judgment, federal tax, state tax, municipal, HOA, hospital, etc.)
7. Lis pendens / pending suit records (if the county exposes these separately)
8. Recorder document image access (where the actual recorded PDFs can be retrieved)

### Lead-generating court sources

9. Court records — main portal
10. Civil case search
11. Foreclosure case search (where it's separated from civil)
12. Probate court / estate records (often a separate jurisdiction)
13. Eviction / unlawful detainer / forcible entry & detainer search
14. Family court records (divorce filings where exposed)

### Lead-generating tax sources

15. Tax collector / treasurer — main portal
16. Delinquent tax search
17. Tax lien sale / tax certificate sale
18. Tax deed sale
19. Tax foreclosure sale

### Lead-generating sheriff / auction sources

20. Sheriff sale / foreclosure auction calendar
21. Trustee sale calendar (in non-judicial states where the trustee, not sheriff, conducts the auction)

### Lead-generating code / municipal sources

22. Code enforcement records
23. Vacant property registry
24. Nuisance abatement records
25. Demolition list / demolition orders
26. Condemnation orders
27. Permit portal
28. Building department records
29. Water / utility shutoff feeds (where exposed publicly)

### Enrichment sources

30. Tax assessor / property appraiser — main portal
31. Parcel search (individual parcel lookups)
32. Property data download (per-parcel detail in machine-readable form)
33. Bulk property roll download (full county roll as CSV / TSV / shapefile / etc.)
34. GIS parcel viewer
35. Open data portal (Socrata, ArcGIS Hub, custom)

### Vendor and PDF publication sources

36. Vendor-hosted portals used by the county (Tyler, CivicPlus, Granicus, GovOS, Catalis, Kofile, Landmark, Aumentum, Accela, EnerGov, Cityworks — name whichever the county uses)
37. PDF publication pages (sheriff weekly PDFs, treasurer's delinquency PDF, court docket PDFs)

### Per-source field requirements

For every category above that the recon confirms exists in the target county, the populated county config source block must include:

- `source_name`, `category`, `subtype`, `url`
- `official_status` — one of `OFFICIAL_COUNTY`, `OFFICIAL_STATE`, `OFFICIAL_CITY`, `OFFICIAL_COURT`, `OFFICIAL_VENDOR_PORTAL`, `UNVERIFIED`, `NOT_FOUND`
- `lead_value` — one of `LEAD_GENERATING`, `ENRICHMENT`, `REFERENCE_ONLY`, `UNKNOWN`
- `source_priority` (P0 / P1 / P2)
- `build_priority` (`mvp_required` / `high_value` / `enrichment` / `optional` / `future`)
- `source_reliability_grade` (A / B / C / D / E per `architecture/08_evidence_ledger.md`)
- `source_freshness` (e.g. `DAILY`, `WEEKLY`, `MONTHLY`, `ANNUAL`, `ON_REQUEST`)
- `access_pattern`, `auth_required`, `rate_limit_rpm`
- `enabled`, `paused_reason`, `pause_until`, `allowed_to_export` (kill-switch fields per `architecture/10_source_heartbeat_and_cursors.md`)
- `verification_note` — free text capturing what was observed during recon
- `open_questions` — free text capturing questions the operator must answer before building this source
- `operator_override` — boolean. Default `false`. Required to be `true` before any source with `official_status` of `UNVERIFIED` or `NOT_FOUND` can be wired into a scraper, dashboard, or pipeline path.
- `last_verified_at` — ISO 8601 timestamp set when recon confirmed the source

### No guessed URLs

Phase 0 recon does not invent URLs. Every URL must be reached by following links from the official county / state / municipal / court website (or the county's declared vendor portal). When a county uses a vendor (e.g. Tyler iDocket, CivicPlus, GovOS), the vendor URL is acceptable only when the official county site links to it — that link is the proof of official status. If you cannot find a URL by following official navigation, mark the category `NOT_FOUND`.

---

## Source priority tiers

**The product is fresh county-level distress intelligence with daily refresh.** Sources are tiered by how directly they serve that thesis. Every county source identified in Phase 0 recon must be classified into one of three tiers. The build cannot ship as a county intelligence platform without at least one working P0 source.

### P0 — Daily-refresh distress sources (REQUIRED)

These sources expose recorded distress events with daily-or-faster cadence. They are the moat. They are why the framework exists.

| Source category | Examples | Refresh requirement |
|---|---|---|
| County Clerk recorded instruments | Lis pendens, foreclosure notices, liens, deeds, probate filings, tax sale certificates | Daily |
| Court dockets (civil, foreclosure, probate, family, eviction) | Case filings, judgments, dispositions | Daily |
| Sheriff foreclosure sale calendars | Active sales, postponed, sold, bankruptcy stays | Daily where exposed |
| Tax collector / treasurer delinquency rolls | Year-by-year delinquency, in-rem foreclosures | Daily where exposed |
| Code enforcement | Violations, demolition orders, condemnations, board-and-secure | Daily where exposed |

**Rule:** A county build with zero working P0 sources is not a county intelligence build. It is a parcel viewer. Phase 0 must surface this honestly. If all P0 sources for a target county are blocked (reCAPTCHA, WAF, paywall, login wall, no public docket), the framework's blocked-source strategies (`engineering/04_blocked_source_strategies.md`) define the unblock paths: public-records request, seeded session, residential proxy + solver, operator-credentialed login. **At least one P0 source must be unblocked before the build is shippable.**

### P1 — Weekly-refresh distress sources (acceptable when same signal not available at P0)

These sources expose distress events but with cadence slower than daily, typically because the upstream publishes weekly or because the data is bulk-released on a periodic schedule.

| Source category | Examples | Why P1 not P0 |
|---|---|---|
| Sheriff sale weekly PDFs | Weekly publication of upcoming auction calendar | Upstream cadence is weekly |
| Court bulk extracts via public-records request | Monthly or quarterly bulk releases of docket data | Cadence bound by request response time |
| Bankruptcy filings via paywalled federal systems | Federal Ch 7/11/13 filings | Paywall + lag |

P1 sources can ship as part of a build, but they cannot be the *only* distress source. The product premise is daily freshness; a build whose entire distress feed is weekly fails the premise.

### P2 — Enrichment sources (any cadence, supporting role only)

These sources describe parcel state, owner state, or property metadata. They enrich P0/P1 leads with context (assessed value, mailing address, ownership length, equity proxy). They do not produce leads on their own.

| Source category | Examples | Refresh acceptable |
|---|---|---|
| Tax assessor / appraisal district / parcel master | Assessed value, owner name, mailing address, last sale, year built | Per-publication |
| GIS parcel layers | Parcel geometry, ownership polygons | Annual |
| USPS vacancy data | Mail-deliverability flag | Monthly |
| Utility shutoff feeds | Active disconnects | Where available |
| Statewide bulk parcel data layers | Statewide assessor extracts in any state | Per upstream cadence |

**Rule:** P2 sources are NEVER the headline of a county build. The framework treats P2 as supporting context for P0/P1 leads. A dashboard whose primary content is P2 enrichment is a parcel viewer, not a county intelligence product. P2 enrichment without a working P0 source is rejected at the Phase 0 gate.

### Phase 0 recon is gated on P0

`MASTER_PROMPT.md` Phase 1 requires the recon document (`RECON.md`) to:

1. List every source identified for the target county
2. Assign each source a tier (P0 / P1 / P2)
3. Identify the access pattern (open / reCAPTCHA / WAF / paywall / public-records-only / login-wall) for each P0 source
4. For each blocked P0 source, identify which unblock path from `engineering/04_blocked_source_strategies.md` applies
5. Confirm at least one P0 source is currently unblocked OR a specific unblock plan is committed to before Phase 1 begins

If the recon cannot satisfy step 5, the build halts. The framework does not let the operator ship a parcel viewer wearing the county-intelligence label.

### Source priority vs build priority

`source_priority` (P0/P1/P2 — defined here) and `build_priority` (mvp_required / high_value / enrichment / optional / future — defined in `config/counties/_schema.md`) are **independent fields** that answer different questions.

- `source_priority` measures **what the source is** — cadence and distress-vs-enrichment classification. It's a property of the source's nature.
- `build_priority` measures **when to build it** — implementation sequencing during the county build.

A P0 distress source may be `mvp_required` (build first because it IS the moat) or `high_value` (build second because something else is the MVP for this county). A P2 enrichment source is usually `enrichment` but may be `mvp_required` if joins require it before the first lead can render.

Phase 0 recon sets both fields. Phase 2 build order follows `build_priority`. The P0 gate enforces that at least one P0 source has a working access strategy regardless of its build_priority.

---

## The classification rule

A source is **lead-generating** if and only if its records describe a discrete, dated, recorded event that signals distress, transfer, or legal action. Examples: a lis pendens recorded on day X. A tax sale certificate sold on day Y. A probate case opened on day Z.

A source is **enrichment-only** if its records describe parcel state — the property's metadata at a point in time. Examples: assessed value, year built, last sale price, mailing address, owner name, ownership length. These are facts about a property that exist whether or not anything is currently happening to it.

A source is a **negative-signal** source when it produces release, satisfaction, discharge, dismissal, or vacatur events. These are recorded events but their function is to invalidate prior lead-generating signals, not to generate new leads. See `domain/09_document_lifecycle.md` for the suppression engine.

**A parcel-master row with a $1 sale price is enrichment.** The parcel exists, has an assessed value, has an owner. The $1 price is metadata. To turn it into a lead, the framework must find the corresponding clerk DEED record with grantor / grantee / sub-type, which makes it an *event* (someone recorded a transfer on a date) rather than a *state* (the parcel last sold for $1 at some point).

---

## Lead-generating sources

### County Clerk recorded instruments

**What it can prove:**
- Recording date, document number, book/page
- Grantor and grantee names
- Document type (deed, mortgage, lien, lis pendens, etc.)
- Consideration (sale price)
- Document sub-type (quitclaim, sheriff's, executor's, etc.)
- Recorded full text in some jurisdictions

**Patterns it generates:**
- `foreclosure` (lis pendens, notice of sale, sheriff's deed, final judgment)
- `tax` (tax sale certificates, federal/state tax liens)
- `lien` (construction, mechanic, judgment, HOA, hospital — and their discharges)
- `estate` (inheritance tax waivers, disclaimers, trust agreements, executor/administrator deeds)
- `transfer` (all DEED sub-types when grantor/grantee/consideration tell us the sub-type)
- `code` (rare — only when a municipality records a code lien at the county level)

**Access patterns:**
- Open API (rare, prized — check first)
- Open search UI without CAPTCHA (common in older systems)
- reCAPTCHA v3 server-enforced (vendor-hosted recorder portals — common across many counties)
- Tyler / iDocket / Eagle Recorder — varies by deployment
- Fully closed, public-records-only (some smaller counties)

**Strategy when blocked:**
1. public-records request for monthly bulk extracts (statutory channel, bypasses website entirely)
2. Seeded session (operator clears CAPTCHA in real browser, scraper replays cookies)
3. CAPTCHA-solving service

---

### Court dockets

**Civil court** (foreclosure cases, judgments):
- Case number, status, parties
- Filing date, latest activity date
- Cause of action

**Probate / Surrogate court:**
- Decedent name, date of death
- Executor / administrator
- Heirs (where listed)
- Estate inventory in some states

**Family court:**
- Divorce filings (often sealed)
- Property settlement orders

**Special civil / Justice court:**
- Eviction filings
- Writs of possession

**Patterns generated:** `foreclosure`, `estate`, `divorce`, `eviction`, `bankruptcy` (when state court records federal bankruptcy notices)

**Access patterns:**
- State unified court portal — often Imperva-walled or behind state-level WAF
- County-level court searches — varies
- PACER for federal bankruptcy — paid

**Strategy when blocked:**
- public-records request
- Manual operator pull where volumes are low
- Court-clerk records typically duplicate county-clerk recordings (lis pendens, judgments) for foreclosure/lien purposes

---

### Sheriff sales

**What it proves:**
- Sale date, case number
- Plaintiff (lender or governmental body)
- Defendant (property owner)
- Property block/lot/address
- Opening bid / final bid
- Sale status (active, adjourned, cancelled, bankruptcy stay)

**Patterns generated:** `foreclosure`, `bankruptcy` (edge case when status field notes stay)

**Access patterns:**
- PDF (weekly publication common in some counties)
- Vendor-hosted civil-court portals (varies by county and state)
- In-house ASP (smaller counties)

**Strategy:** Almost always open access. Parser reliability is the main concern.

---

### Tax collector / treasurer delinquency rolls

**What it proves:**
- Owner name (often more current than parcel master)
- Tax balance owed
- Years delinquent
- Property identifier
- Current status (active, in tax sale, paid)

**Patterns generated:** `tax`

**Access patterns:**
- Open ArcGIS REST endpoint (some county treasurers expose this)
- Open vendor portals (third-party tax-collector platforms vary by state)
- HTML scrape required (most counties)
- Bulk download (some counties publish quarterly files)

**Strategy:** Almost always open. Tax debt is a public record by statute.

---

### Code enforcement

**What it proves:**
- Open violations
- Violation type and description
- Property identifier
- Notice dates
- Compliance status

**Patterns generated:** `code`

**Access patterns:**
- Per-municipality (each municipality typically runs its own code enforcement system)
- Open Data Portal (many cities — Socrata, ArcGIS)
- Vendor systems (Tyler, Energov, Cityworks, Accela)
- HTML scrape

**Strategy:** Out of scope unless the operator explicitly prioritizes a single municipality. The cost-to-coverage ratio is poor for county-wide builds.

---

## Enrichment-only sources

### County tax assessor / appraisal district / parcel master

The parcel master goes by different names in different states — statewide layers in some states, per-county appraisal districts in others, county GIS / land records systems in still others. The format varies; the role does not.

**What it provides for enrichment:**
- Parcel ID (the join key for everything)
- Block / lot / qualifier
- Situs (property) address
- Mailing (owner) address
- Owner name (where not redacted)
- Year built
- Square footage
- Assessed value (land + improvement)
- Last sale price + date
- Deed book / page reference
- Property class / land use code
- Acreage

**What it does NOT do:**
- Generate leads on its own
- Provide reliable timing on transfers (sale dates can be 6+ months stale relative to clerk recording)
- Provide doc-type metadata for recent transfers
- Indicate distress events

**Critical rule:** A nominal-consideration sale ($1, $10) in the parcel master is NOT a `transfer` signal. It is metadata indicating a non-arm's-length transfer happened at some point. To turn that into a lead, the framework must find the corresponding clerk DEED record. If the clerk DEED record exists and shows grantor/grantee/sub-type, the lead fires. If the clerk DEED record is unreachable, the framework must NOT fabricate a transfer lead from parcel-master metadata alone.

---

### GIS parcel layers

Geographic data — lat/lng, parcel polygons, neighborhood boundaries.

**Used for:** map rendering, deep-link generation, neighborhood filtering, comp-set selection (downstream).

**Never:** primary lead source.

---

### USPS vacancy data

Address-level vacancy indicators based on mail-delivery status.

**Used for:** `vacant` attribute computation.

**Access:** USPS does not publish freely. Vendors (DataTree, FirstAm) sell access. Self-service vacancy detection requires per-municipality utility shutoff feeds.

**Strategy:** v3 work — not blocking initial county builds.

---

### Utility shutoff feeds

Per-municipality water / electric / gas service interruption data.

**Used for:** `vacant` attribute computation, `code` precursor signal.

**Access:** mostly public-records-only. Per-municipality. Out of scope for initial county builds.

---

## What to do when a lead source is blocked

When recon reveals a lead source is unreachable (reCAPTCHA, Imperva, paywall, no public access):

1. **Document the blocker** in `RECON.md` with the specific access pattern observed
2. **Generate a public-records request PDF** automatically via `pipeline/records_request.py` for sources where statutory records-request is the fallback
3. **Build the seeded-session path** if the source is reCAPTCHA v3 (operator clears CAPTCHA, framework replays cookies)
4. **Mark the pattern as 0-fired in the dashboard** with a tooltip explaining the unblock path
5. **Do NOT generate leads from enrichment to fill the gap.** Empty buckets are honest.

The framework's value is honest pipelines, not inflated counts. A dashboard that says "Tax distress: 0 (clerk data not yet ingested — see methodology)" is correct. A dashboard that says "Tax distress: 6,921 (derived from $1 deeds in parcel master)" is broken.

---

## Source quality hierarchy (when sources conflict)

When two sources disagree on a fact:

1. **County clerk recorded instrument** wins for: ownership, deed sub-type, lien existence, consideration, recording date
2. **Court docket** wins for: case status, parties, judgment amounts
3. **Tax collector** wins for: tax balance, delinquency status, paid-through date
4. **Parcel master** wins for: assessed value, square footage, year built, last sale (when no clerk data)
5. **GIS** wins for: parcel boundary, lat/lng, legal description geometry

A clerk record from 2023 supersedes a parcel-master record from 2025 on ownership questions, because the clerk records the legal event and the parcel master eventually catches up (often quarterly).

---

## Source Hierarchy (v5.0.0+)

The v5.0.0 Source Verification Gate (MASTER_PROMPT Section 4.7) classifies every source into one of three tiers via the `source_role` field. The tier determines what the source can do in the pipeline. This is the central trust rule of v5.0.0.

### Tier 1 — Primary lead sources (`source_role: PRIMARY_LEAD_SOURCE`)

**Can create leads.** Phase 0 must verify at least one Tier 1 source for the county build to be eligible. Without a verified Tier 1 source, the county is `NOT_BUILDABLE_YET` and the framework stops at the Build Eligibility Gate.

- Clerk records / recorder records (deeds, mortgages, liens, lis pendens, releases, satisfactions, judgments, federal tax liens, mechanics liens)
- Court filings (civil, probate, family, eviction)
- Foreclosure filings
- Sheriff sale records
- Tax delinquency events
- Tax sale events
- Probate events
- Judgments
- Liens
- Lis pendens
- Recorded notices
- Code enforcement events (when they expose violations, liens, demolition, condemnation, nuisance, or unsafe-structure data)
- Demolition events
- Condemnation events

### Tier 2 — Supporting lead sources (`source_role: SUPPORTING_LEAD_SOURCE`)

**Strengthens or confirms leads.** Cannot create lead volume on its own. Used to enrich Tier 1 events with detail.

- Court case detail pages
- Document images
- Auction detail pages
- Sale status pages
- Probate case metadata
- Judgment detail pages
- Recorded document metadata

### Tier 3 — Enrichment sources (`source_role: ENRICHMENT_SOURCE`)

**Enriches leads only.** Cannot create leads under any circumstances. A county whose only verified sources are Tier 3 is not buildable.

- Parcel data
- GIS data
- CAD / appraisal district data
- Assessor data
- Owner mailing data
- Tax roll data
- Bulk property roll
- Valuation data (beds / baths / square footage / year built / land use)
- Equity estimate proxies
- Absentee-owner status (when derived from owner mailing address)
- Vacancy status (when derived from USPS or utility data)

### Two other source_role values

- `REFERENCE_ONLY` — informational sources that can't create leads (e.g. a county's published treasurer schedule, an open-data portal index page)
- `BLOCKED_SOURCE` — a Tier 1 or Tier 2 source that exists but is currently inaccessible. Carries a `next_access_strategy` describing the unblock plan. Cannot create leads until access is solved.
- `NOT_FOUND` — searched for but the source does not exist in this jurisdiction (e.g. counties without an online clerk portal)

This tier system is enforced by the schema. A source with `source_role: ENRICHMENT_SOURCE` cannot have `lead_value: LEAD_GENERATING`. The Build Eligibility Gate reads these fields to produce the `build_verdict`.
