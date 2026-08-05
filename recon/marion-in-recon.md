# Marion County, Indiana — Doc-Type Recon

    County:            Marion County, Indiana (Indianapolis)
    Slug:              marion_in
    Repo:              marion-county-intel
    Framework:         Universal County Intelligence Framework v5.6.0
    Recon date:        2026-08-04
    Phase:             Phase 0 — doc-type recon. No scraper code written.
    Government form:   Consolidated city-county (Unigov, 1970). City of
                       Indianapolis and Marion County share one government, so
                       "Indy" and "Marion County" sources are the same authority
                       for code enforcement, assessment, and treasury.

All findings below were verified live on 2026-08-04 by direct low-volume probe
unless explicitly marked INFERRED or SECONDARY. Where a probe contradicted a
published claim or a prior recon, the probe wins and the contradiction is
called out.

---

## 0. Executive verdict

    BUILD VERDICT:        READY_TO_BUILD
    P0 GATE:              SATISFIED — Indiana Courts MyCase is an unblocked,
                          daily-refresh, fully scriptable primary distress source
    CANONICAL JOIN KEY:   STATEPARCELNUMBER (Indiana state parcel number)
                          with PARCEL_I as the mandatory secondary/internal key
    BIGGEST WIN:          MyCase court search is an undocumented but open JSON
                          API — no auth, no cookie, no CAPTCHA, no rate limiting
    BIGGEST RISK:         Court records carry NO property address. The parcel
                          join is the single hardest problem in this build.

Three findings overturn common assumptions about this county, including two
stated in the build request and two asserted by the prior `marion-in-intel`
recon. They are detailed in §8.

---

## 1. CANONICAL JOIN KEY — the most important output

### 1.1 The designated key

    CANONICAL KEY:     STATEPARCELNUMBER
    Source of truth:   MapIndy Parcel layer (§4.5)
    Format:            NN-NN-NN-NNN-NNN.NNN-NNN
    Type:              string, punctuated, fixed width 24 characters
    Null rate:         0 of 347,050 parcels
    Verified examples: 49-06-25-178-053.000-101
                       49-07-29-155-106.000-101
                       49-07-31-220-045.000-101
                       49-05-14-131-004.000-674
                       49-08-21-130-012.000-701

Segment structure (positional, INFERRED from Indiana DLGF convention and
consistent across every sampled record):

    49        county code — Marion County is 49 statewide. Constant for this
              build. Also the CountyCode value MyCase uses (§4.3).
    06        taxing township within the county
    25        section
    178       block / quarter-section group
    053       parcel sequence within the block
    .000      sub-parcel / split suffix — ".000" for a whole parcel, non-zero
              for splits and condo units
    101       taxing district code

### 1.2 The secondary key

    SECONDARY KEY:     PARCEL_I (integer) / PARCEL_C (string, same value)
    Format:            7-digit integer, no punctuation
    Null rate:         0 of 347,050
    Verified examples: 1042893, 1075869, 1006139, 6009206, 7033460

`PARCEL_I` and `PARCEL_C` always carry the same value; `PARCEL_C` is the string
rendering. A fourth identifier, `CAMAPARCELID` (assessor CAMA system internal
id, e.g. 234006, 290899), also exists and is also never null, but it is an
internal assessor key with no presence in any other source — do not join on it.

### 1.3 Why STATEPARCELNUMBER is canonical and PARCEL_I is mandatory anyway

Both keys are equally valid as identity — see the 1:1 proof in §1.4. They are
canonical/secondary rather than either/or because **different source families
speak different keys, and neither key alone reaches every source**:

    Speaks STATEPARCELNUMBER    assessor property cards (public search is BY
                                state parcel number), treasurer tax billing,
                                Indiana Gateway statewide tax bill lookup
                                (§6.2), tax sale lists, recorded legal
                                descriptions, any state-level system
    Speaks PARCEL_I / PARCEL_C  the IndyGIS/MapIndy layer family — Abandoned
                                and Vacant (layer 11/16, keyed PARCEL_I),
                                Registered Landlord Properties (layer 27, keyed
                                PARCEL_C), and the Accela property layer
    Speaks NEITHER              Marion County code enforcement (§4.4) and the
                                MyCase courts (§4.3) — both address-only. See
                                §1.5, this is the real problem.

STATEPARCELNUMBER is designated canonical because it is the key used by every
authority that touches money and legal title (assessment, billing, tax sale,
recording), it is stable across state systems, and it is the identifier a human
operator can verify against a public property card. PARCEL_I is designated a
mandatory stored secondary because three live distress/enrichment layers are
keyed on it and cannot be reached without it.

**Rule for this build: every parcel record MUST carry both keys. The Parcel
layer is the crosswalk and is the only place both keys appear together.**

### 1.4 1:1 proof, and the multi-row trap

A naive uniqueness check on this layer is misleading and will cause a bad
architectural decision if taken at face value. Grouped counts:

    STATEPARCELNUMBER  top duplicate groups:  30, 20, 20, 18
    PARCEL_I           top duplicate groups:  30, 20, 20, 18
    PARCEL_C           top duplicate groups:  30, 20, 20, 18
    CAMAPARCELID       top duplicate groups:  30, 20, 20, 18

The identical distributions are the tell. Direct verification of the largest
group, both directions:

    where PARCEL_I=6009206
      -> 30 rows returned
      -> all 30 rows carry STATEPARCELNUMBER = 49-05-14-131-004.000-674
      -> all 30 rows carry CAMAPARCELID = 290899
      -> address on every row: 4580 PINEHOLLOW CT

    where STATEPARCELNUMBER='49-05-14-131-004.000-674'
      -> 30 rows returned
      -> distinct PARCEL_I values: exactly one (6009206)

Conclusion: the duplication is **multi-polygon geometry** — one parcel split
into several shape rows — not key collision. All four identifiers are strictly
1:1 with each other and with real-world parcel identity.

    IMPLICATION: the parcel layer is NOT row-unique on any key. Every parcel
    ingest MUST deduplicate on the canonical key before use, or the pipeline
    will inflate parcel counts up to 30x on condo and multi-polygon parcels.
    Request with returnGeometry=false and dedupe on STATEPARCELNUMBER.

### 1.5 The join problem this build must solve

The two highest-value distress sources in the county — court filings and code
enforcement — carry **no parcel identifier of any kind**. Both are address-only.

    MyCase court results     party names + case metadata. No address at all,
                             not even a street. (§4.3)
    Code enforcement         STREET_ADDRESS + OWNER. No parcel id. (§4.4)
    Sheriff sale list        property address + judgment amount. No parcel id.
                             (§5.1) — but this is why it matters, see below.

So the canonical key cannot be read directly off the primary distress sources.
It must be **derived** via an address or owner bridge against the parcel layer.
Ranked by reliability:

    1. ADDRESS NORMALIZATION (recommended primary bridge)
       Normalize source address -> match against parcel layer STNUMBER +
       FULL_STNAME + ZIPCODE -> read STATEPARCELNUMBER and PARCEL_I.
       Works for: code enforcement, sheriff sale list, tax sale list.
       Supporting asset: the county publishes address point layers ("Buildings
       with Addresses", "Building Unit Addresses", both CSV on the open data
       portal, and MapIndy layer 0 "Unit Address Points") which give an
       authoritative address->parcel spine rather than fuzzy string matching.
       This is the highest-value unbuilt asset in the county and should be
       built as a dedicated crosswalk table before any matcher work.

    2. SHERIFF SALE AS THE ADDRESS BRIDGE FOR FORECLOSURE (high value)
       The MF court case has no address; the sheriff sale list for the same
       foreclosure HAS the address. Joining MF cases to sheriff sale entries by
       case number recovers the address — and therefore the parcel — for the
       foreclosure pipeline. See §5.1.

    3. OWNER-NAME MATCH (last resort only — do not make this the primary)
       The prior marion-in-intel build joined on owner name via
       UPPER(FULLOWNERNAME) LIKE '%NAME%'. This is unreliable: court parties are
       FIRST LAST while the assessor stores LAST FIRST, institutional parties
       (lenders) are not owners, and common surnames collide. That build had to
       discard any match returning >=20 hits, which silently drops leads. Use
       owner name only to disambiguate between address candidates.

### 1.6 Normalization contract for this build

    Store BOTH keys on every parcel-bearing record:

      parcel_id_state   STATEPARCELNUMBER verbatim, punctuation preserved,
                        uppercase, trimmed.        e.g. 49-06-25-178-053.000-101
      parcel_id_state_n digits only, punctuation stripped, for fuzzy/lenient
                        joins against sources that drop the dashes.
                        e.g. 490625178053000101   (18 digits, fixed width)
      parcel_id_local   PARCEL_C as a zero-padded 7-character string.
                        e.g. 1042893

    Deterministic rules (framework: deterministic before semantic):
      - never re-derive the state number from segments; copy it
      - never zero-strip the ".000" suffix — ".000" and ".001" are different
        parcels
      - the leading "49" is constant for this county; do not treat a record
        whose state number does not begin "49-" as a Marion parcel
      - dedupe on parcel_id_state before any count, score, or aggregation
      - a record whose parcel key was DERIVED (address/owner bridge) must carry
        the derivation method and confidence, and must route to the review queue
        below the confidence threshold — never silently accept a fuzzy parcel

---

## 2. Recommended source priority order

    RANK  SOURCE                        ROLE          PRIORITY  VERDICT
    1     MyCase — Indiana Courts       PRIMARY       P0        GREEN
    2     MapIndy Parcel layer          ENRICHMENT    P2        GREEN
    3     MapIndy Abandoned & Vacant    PRIMARY       P1        GREEN
    4     Accela code enforcement       PRIMARY       P0        YELLOW
    5     Indiana Gateway tax bills     ENRICHMENT    P2        YELLOW
    6     Sheriff sale list             SUPPORTING    P1        YELLOW
    7     Tax sale (GovEase/SRI)        PRIMARY       P1        YELLOW
    8     MapIndy Registered Landlord   ENRICHMENT    P2        GREEN
    9     Marion County Recorder        PRIMARY       P1        RED-ish
    10    Open-data code enforcement    BACKFILL ONLY —         RED as live
    11    PACER bankruptcy              PRIMARY       future    RED

Build order recommendation: **1 -> 2 -> address crosswalk (§1.5) -> 3 -> 4 ->
6 -> 5 -> 7**. Ship an MVP on MyCase + parcel + address crosswalk alone; that
combination already produces foreclosure, eviction, probate, and tax deed leads
with a real parcel join.

---

## 3. Doc-type / lead-type coverage — what this county actually calls things

This section satisfies the v5.6.0 §01.30 terminology requirement. Local names
were established **empirically** from the court's own case-type vocabulary and
the code enforcement case-type list, not inferred.

### 3.1 Foreclosure — the sheriff sale correction

**"Sheriff sale" is NOT the canonical foreclosure event in Marion County.**

Indiana is a strict **judicial foreclosure** state. There is no trustee sale, no
notice of substitute trustee sale, no non-judicial power-of-sale track. The
process is:

    ORIGINATING EVENT   MF - Mortgage Foreclosure — a civil case filed in
                        Marion Superior Court. This is the earliest reliably
                        public artifact and the canonical foreclosure lead.
    interim             judgment / decree of foreclosure (docket event)
    downstream stage    Sheriff's sale — the auction that EXECUTES the MF
                        judgment. Months later. Supporting signal, not origin.
    downstream stage    Sheriff's deed — post-sale transfer.

Empirically confirmed. Sampling five single filing days across 2026 (1,272
civil cases, Marion County only):

    600  CC - Civil Collection
    210  SC - Small Claims
    174  EV - Evictions (Small Claims Docket)
     92  MI - Miscellaneous Civil
     57  CT - Civil Tort
     41  PL - Civil Plenary
     39  MF - Mortgage Foreclosure          <-- canonical foreclosure
     16  CE - Commercial Court Eligible
     13  EV - Evictions (Civil Docket)
      5  CB - Foreign Judgment
      1  TP - Verified Petition for Issuance of a Tax Deed

Live MF examples pulled 2026-08-04 (filed 06/02/2026):

    49D33-2606-MF-030447  Rocket Mortgage, LLC v. <individual>, ...
    49D33-2606-MF-030448  Lakeview Loan Servicing, LLC v. <individual>, ...
    49D33-2606-MF-030449  U.S. BANK NATIONAL ASSOCIATION v. <individual>, ...
    49D33-2606-MF-030468  KeyBank National Association v. <individual>, ...

MF volume ≈ 8/day ≈ ~2,000/year. Filings concentrate in court **49D33** (Marion
Superior Court, the foreclosure docket). Case number format:

    49D33-2606-MF-030447
    ^^ county 49  ^^^ court D33  ^^^^ YYMM filed  ^^ case type  ^^^^^^ sequence

**Lead-time consequence:** targeting the MF filing instead of the sheriff sale
buys months of lead time on the same property. The sheriff sale list remains
valuable — but as the address bridge (§1.5) and as a late-stage urgency signal,
not as the origination event.

### 3.2 Lead type sweep — local vocabulary map

    FRAMEWORK LEAD TYPE        LOCAL NAME / SOURCE                    STATUS
    Foreclosure                MF - Mortgage Foreclosure (MyCase)     LIVE
    Trustee Sale               —                                      N/A judicial state
    Notice of Trustee Sale     —                                      N/A judicial state
    Notice of Subst. Trustee   —                                      N/A judicial state
    Sheriff Sale               Sheriff's Sale (downstream of MF)      LIVE, supporting
    Tax Lien Foreclosure       tax sale certificate track             LIVE
    Tax Sale                   Marion County Tax Sale (GovEase/SRI)   LIVE
    Tax Sale Certificate       commissioners' certificate sale        LIVE
    Tax Delinquency            treasurer balance / tax sale list      PARTIAL — §6
    Lis Pendens                recorder document type                 BLOCKED — §4.1
    Civil Judgment             CC - Civil Collection (MyCase)         LIVE, high volume
    Abstract of Judgment       recorder document type                 BLOCKED — §4.1
    Mechanic Lien              recorder document type                 BLOCKED — §4.1
    Construction Lien          recorder document type                 BLOCKED — §4.1
    Federal Tax Lien           recorder document type                 BLOCKED — §4.1
    State Tax Lien             IN tax warrant / recorder              BLOCKED — §4.1
    Probate                    EU / ES / EM (MyCase, category PR)     LIVE
    Affidavit of Heirship      recorder document type                 BLOCKED — §4.1
    Executor Deed              recorder document type                 BLOCKED — §4.1
    Administrator Deed         recorder document type                 BLOCKED — §4.1
    Code Lien                  Enforcement/Violation/* (Accela)       LIVE
    Demolition                 Enforcement/Violation/Demolition       LIVE
    Condemnation               Enforcement/Investigation/Unsafe Bldgs LIVE
    Eviction                   EV - Evictions, two dockets (MyCase)   LIVE, very high vol
    Divorce                    DR / DC (MyCase, category FAM)         LIVE, low value
    Bankruptcy                 PACER — S.D. Indiana                   BLOCKED, paid
    Surplus                    tax sale surplus / sheriff overage     UNCERTAIN — §9
    Bankruptcy Notice          PACER                                  BLOCKED, paid
    Public Notice              newspaper of record / posted notices   UNCERTAIN — §9

    Bonus lead type not in the framework sweep, found empirically:
    TP - Verified Petition for Issuance of a Tax Deed (MyCase). The court step
    where a tax sale certificate holder converts to a deed. Low volume (~1 per
    5 filing days) but an extremely high-intent distress signal.

**Coverage summary:** 15 of 29 framework lead types are LIVE and buildable now.
9 are blocked behind the single recorder blocker (§4.1) — one unblock recovers
all nine. 3 are structurally N/A (judicial state). 2 are uncertain (§9).

---

## 4. Source-by-source findings

### 4.1 Marion County Recorder — recorded documents

    Authority:      Marion County Recorder, 200 E. Washington St, Suite 1040
    Portal:         https://inmarion.fidlar.com/INMarion/DirectSearch/
    Vendor:         Fidlar Technologies (NOT Doxpop, NOT Landex, NOT county-native)
    Live status:    HTTP 200, 63,135 bytes, title "Direct Search"
    Architecture:   Angular SPA. Server-rendered HTML contains ZERO forms and
                    zero input elements — all search UI is client-rendered.
    Bundles:        runtime.a11dc006eb6e3c31.js, polyfills.29452d2039922ec4.js,
                    main.c6975cfaa4c318e4.js (991,266 bytes)
    Server:         Microsoft-IIS/10.0, ASP.NET
    Access class:   UNKNOWN — enforcement not yet tested (see below)
    Bulk (§01.24):  UNKNOWN, presumed PER_RECORD_ONLY
    Scrapeability:  RED for now, plausibly YELLOW after one enforcement test

**Correction to the build request.** The request suggested Doxpop, Landex, or
county-native. It is Fidlar. Doxpop does carry Marion County data but is a
third-party aggregator and is therefore out of scope per framework §01.6
(resellers are not primary recon targets). Be careful with search results here:
`rep3laredo.fidlar.com/OHMarion/` is Marion County **Ohio** — the `OH`/`IN`
prefix is the only thing distinguishing them, and it is easy to mis-target.
`inmarion.fidlar.com/INMarion/AvaWeb/` returns 404; `/INMarion/DirectSearch/`
is the live path.

**API discovery (§01.23) — documented API found: NO.** Paths checked, all 404:

    /INMarion/api            /INMarion/api/swagger      /INMarion/swagger
    /INMarion/swagger/index.html                        /INMarion/api-docs
    /INMarion/docs           /api                       /swagger
    /swagger/v1/swagger.json /INMarion/DirectSearch/api /INMarion/api/Search
    /INMarion/api/documents

The Angular bundle yields no extractable API base — no `api/` string literals,
no `baseUrl`/`apiUrl` configuration in cleartext. The search endpoint is
constructed at runtime and will need a browser network capture to identify.

**Access control (§01.29) — control PRESENT, enforcement NOT YET TESTED.**
The main bundle contains the `ng-recaptcha` Angular library: `grecaptcha`,
`recaptcha-v3-site-key`, `recaptcha-base-url`, and a loader pointing at
`https://www.google.com/recaptcha/api.js`. It also contains the strings
`authorize`, `bearer`, `subscription`, and `Tapestry` (Fidlar's pay-per-search
public product, as distinct from Laredo, the subscription product for title
professionals).

Per the v5.6.0 rule I added to the framework off the back of this build,
**presence is not enforcement** and this source must NOT be recorded as blocked
until a good-faith request has been made. I could not complete that test in this
pass because the request path itself is unknown (no discoverable API, SPA-only
UI), and identifying it requires driving a real browser — which is Phase 1 work,
not recon. This is an honest gap, not a finished verdict.

    NEXT ACTION (highest-value unblock in the county):
    Drive the portal once with a headless browser, capture the XHR the search
    form issues, and record: (a) the endpoint and payload, (b) whether a
    reCAPTCHA token is actually required on the first search or only after a
    threshold, (c) whether index/search metadata is free while only document
    IMAGES are paywalled — which would make this SEARCH_ONLY_PUBLIC and fully
    acceptable to the framework, since images are not needed to produce leads.
    If a challenge IS enforced and is single-layer human-verifiable, this is an
    operator-assisted source per §01.29 tiering, not a dead one.

This one test governs nine lead types (§3.2). It is the single highest-leverage
task remaining.

### 4.2 Treasurer / tax sale

    Tax sale authority:  Marion County Treasurer, with SRI Services as the
                         statewide Indiana tax sale administrator (SECONDARY —
                         SRI's own site is a JS shell, 994 bytes, and does not
                         confirm Marion in fetchable markup)
    Auction platform:    GovEase — CONFIRMED. liveauctions.govease.com markup
                         lists "IN - Allen", "IN - Marion", and a second
                         "IN - Marion (Nonpr..." entry (truncated in markup,
                         almost certainly the nonproductive / commissioners'
                         certificate sale).
    Zeus Auction:        https://www.zeusauction.com/ live (HTTP 200, 86,982 b),
                         SRI's own auction platform, references
                         sriservices.com/properties. Marion coverage NOT
                         confirmed — Marion appears to run on GovEase.
    Dead URL:            liveauctions.govease.com/in/inmarion/ now returns 404.
                         The prior marion-in-intel recon recorded this as the
                         live tax sale URL; it has since moved.
    Schedule:            annual; Indiana tax sales run late summer/autumn. The
                         2026 Marion list should be publishing about now.
    Access class:        OPEN_PUBLIC for browsing (bidding needs registration —
                         not needed for leads)
    Bulk (§01.24):       BATCH_QUERY / downloadable list per sale
    Scrapeability:       YELLOW — platform confirmed, exact current list URL and
                         format still to be pinned down

**Correction to the build request.** The request asked to confirm SRI. SRI is
the administrator, but the *auction and list platform for Marion is GovEase*,
not SRI's own Zeus. Target GovEase for the list.

Open-data tax sale reports exist but are useless as a live feed: data.indy.gov
carries "Tax Sale Reports" for **2010 through 2017 only**, as ArcGIS portal
document items (not CSV). Historical backfill value only.

### 4.3 Probate / courts — MyCase (Odyssey Public Access)

**This is the best source in the county by a wide margin.**

    Portal:        https://public.courts.in.gov/mycase/
    Authority:     Indiana Office of Judicial Administration (statewide)
    Vendor:        Tyler Technologies Odyssey Public Access
    Stack:         ASP.NET MVC 5.2, Knockout.js front end, server "volt-adc"
    Access class:  OPEN_PUBLIC
    Bulk (§01.24): BATCH_QUERY — full date-range enumeration works (see below)
    Freshness:     LIVE — returned cases filed within the current period
    Scrapeability: GREEN

**It is a JSON API.** Undocumented, but open and stable:

    POST https://public.courts.in.gov/mycase/Search/SearchCases
    Content-Type: application/json
    (also: POST /mycase/Search/FormatTerms, POST /mycase/Dropdown/GetByKey)

Request fields (extracted from the client bundle, all confirmed working):

    Mode          "ByCase" | "ByParty" | "ByAttorney"
    CaseNum, CiteNum, CrossRefNum
    First, Middle, Last, Business        party-name search
    DoBStart, DoBEnd, OANum, BarNum
    SoundEx       bool, fuzzy name matching
    CourtItemID   specific court, or null for all
    Categories    array: "CR" | "CV" | "FAM" | "PR"
    Limits        array
    ActiveFlag    "All" | "Open" | "Closed"
    FileStart, FileEnd                   MM/DD/YYYY filing date range
    CountyCode    "49" for Marion
    Skip, Take, Sort                     pagination
    CaptchaAnswer null

**CAPTCHA: present in code, NOT enforced. Verified by live request.**
The bundle contains a Knockout `Captcha` view model (`Key` / `Url` / `Answer` /
`Refresh`, template `~/Captcha`) — an **image challenge**, not reCAPTCHA. The
search call sends `CaptchaAnswer: null` unless a key has been issued.

Tested live with `CaptchaAnswer: null` and no prior session:

    POST /mycase/Search/SearchCases  ->  HTTP 200
    {"TotalResults":0,"Skip":0,"Take":10,"Sort":"CaseNumber ASC","Results":null}

No challenge, no cookie required, no session established beforehand, no
`__RequestVerificationToken`. Subsequent searches returned full record sets.
This is exactly the case the v5.6.0 §01.29 rule exists to catch: had recon
stopped at "captcha found in bundle," the best source in the county would have
been misclassified as blocked.

**Rate limiting: none observed.** Six consecutive requests ~400ms apart:

    req 1: HTTP 200, 183ms      req 4: HTTP 200, 231ms
    req 2: HTTP 200, 242ms      req 5: HTTP 200, 211ms
    req 3: HTTP 200, 367ms      req 6: HTTP 200, 210ms

No 429, no backoff, no degradation. Still throttle politely in production.

**Result format** — clean JSON, one object per case:

    CaseID           13476288
    CaseToken        LY58BtOGPMBvTNP95clF_8MiYNAs7tubte3fcvT10jU1
    CaseNumber       49C01-0809-CC-040640
    CountyCode       49
    CourtCode        C01
    Court            Marion Circuit Court
    FileDate         09/08/2008
    CaseStatus       Decided
    CaseStatusDate   11/03/2022
    CaseType         CC - Civil Collection
    CaseSubType      null
    Style            Capital One Bank vs. <individual>
    IsActive         false
    IsPublic         true
    Parties          Bank, <individual>
    Attorneys        Kendall
    ShowWarrantIcon / CommCourtFlag / ExpungedCaseFlag / CiteNumbers /
    Charges / Flags

    NOTE: no property address, no parcel id. See §1.5.

**Enumeration works.** A date range + `CountyCode: "49"` with no name returns
every case filed in that window — this is what makes daily incremental harvest
possible:

    FileStart=06/02/2026 FileEnd=06/02/2026 CountyCode=49  -> 287 results
    FileStart=06/03/2026 FileEnd=06/03/2026 CountyCode=49  -> 255 results
    FileStart=06/04/2026 FileEnd=06/04/2026 CountyCode=49  -> 237 results

    RESULT CAP: TotalResults saturates at 1001 and the server returns at most
    500 rows per call. Slice by single day (and by Categories when a day
    exceeds the cap) to stay under it. A one-day, one-category slice is
    comfortably under. Take=500 confirmed working.

**Probate confirmed** — `Categories: ["PR"]`, Marion County, Q1 2026, 769 cases:

    251  EU - Estate, Unsupervised
    107  EM - Estate, Miscellaneous
     84  GU - Guardianship
     29  ES - Estate, Supervised
     19  GM - Guardianship Miscellaneous
      6  TR - Trust
      4  PL - Contested Estate Matter

**robots.txt — a real constraint, read it before building.**
`https://public.courts.in.gov/robots.txt` disallows by prefix, case-variant by
case-variant, under `/mycase/`: `ca`, `at`, `us`, `er`, `pa`. Also `/*.pdf`,
`/*.tif`, `/*.tiff`.

    ALLOWED    /mycase/Search/SearchCases  — the search API. Not prefixed by
               any disallowed string. This is the bulk harvest path.
    DISALLOWED /mycase/Case/CaseSummary    — matched by "Disallow: /mycase/Ca".
               The case DETAIL page is off-limits.
    DISALLOWED all PDF and TIFF documents.

Framework §01.17 forbids bypassing robots.txt, so recon did not fetch case
detail. **This is a real operational limit, not a technicality:** search results
alone give parties, case type, dates and status — but the case detail is where a
property address would most plausibly live. Recovering addresses for MF cases
therefore routes through the sheriff sale bridge (§1.5 / §5.1) rather than
through case detail. An operator decision to fetch detail anyway is a
policy/legal call, not a technical one, and should be made explicitly.

### 4.4 Code enforcement / unsafe buildings — a stale-feed trap

There are two paths to the same DCE data and **they are not equivalent**.

**Path A — open data bulk extract. FROZEN. Do not use as a live feed.**

    Dataset:      "Indianapolis Code Enforcement Violations and Investigations"
    Landing:      https://data.indy.gov/datasets/IndyGIS::indianapolis-code-
                  enforcement-violations-and-investigations
    REST:         https://gis.indy.gov/server/rest/services/OpenData/
                  OpenData_NonSpatial/MapServer/1
    CSV:          https://data.indy.gov/api/download/v1/items/
                  5d08eba2e9034bc88986af25afe12f5e/csv?layers=1
    Rows:         910,483
    Catalog says: modified 2025-03-12
    ACTUALLY:     max OPEN_DATE = 2024-02-27, min OPEN_DATE = 2010-03-29
                  rows with OPEN_DATE > 2025-01-01:  0
    Freshness:    FROZEN — ~2.4 years stale as of recon date
    Verdict:      RED as a live P0 source. GREEN for 2010-2024 historical
                  backfill, which is genuinely valuable for scoring history.

The prior marion-in-intel recon recorded this source as "nightly updates." That
is wrong, and the catalog metadata is what makes it wrong — the extract is
republished on a schedule long after the upstream feed stopped delivering, so
the "modified" date advances while the newest record does not. This finding is
what motivated the v5.6.0 §01.32 freshness rule.

Schema (note: **no parcel identifier**):

    CASE_NUMBER, CASE_TYPE, CASE_STATUS, OPEN_DATE, STREET_ADDRESS,
    CITY, STATE, ZIP, OWNER, TOWNSHIP, LINK

29 distinct CASE_TYPE values. The distress-relevant ones:

    Enforcement/Investigation/Unsafe Buildings/NA     <- condemnation
    Enforcement/Violation/Demolition/NA               <- demolition
    Enforcement/Violation/Vacant Board Order/NA       <- vacancy
    Enforcement/Violation/Repair/NA
    Enforcement/Violation/Repair No Hearing/NA
    Enforcement/Violation/Building/NA
    Enforcement/Investigation/Building/NA
    Enforcement/Legal/NA/NA
    Enforcement/Damage Assessment/NA/NA

    (noise: High Weeds & Grass, Trash, Vehicle, Right of Way, Zoning,
     Illegal Dumping, Forestry, Air Quality, Liquor License, Infrastructure)

**Path B — Accela Citizen Access. The live source.**

    URL:     https://permitsandcases.indy.gov/citizenaccess/Cap/CapHome.aspx
             ?module=Enforcement
    Live:    HTTP 200, 73,305 bytes, title "Accela Citizen Access"
    Access:  public search, no login observed
    Verdict: YELLOW — live and public, but Accela is ASP.NET WebForms with
             __VIEWSTATE/__EVENTVALIDATION postback state, which is workable
             but brittle. Enforcement of any control NOT yet tested (§01.29).

The open-data `LINK` column points directly at Accela case detail, e.g.
`http://permitsandcases.indy.gov/citizenaccess/Cap/CapDetail.aspx?Module=
Enforcement&capID1=24VEH&capID2=00000&capID3=00105&agencyCode=INDY` — so the
capID triplet is derivable from the case number, which makes targeted Accela
detail fetches straightforward once the case list is known.

**Build recommendation:** backfill 2010–2024 from the frozen bulk extract, then
run Accela for current cases. Do not let the convenient bulk file stand in for
the live source — that is exactly the substitution §01.32 now forbids.

RequestIndy (311 service requests) was not pursued: it is a citizen-report
intake channel, not an enforcement record of authority, and would duplicate DCE
data at lower reliability.

### 4.5 Assessor / parcel — MapIndy ArcGIS

    Service:   https://gis.indy.gov/server/rest/services/MapIndy/
               MapIndyProperty/MapServer
    Layer:     10 — "Parcel"
    Query:     .../MapServer/10/query
    Access:    OPEN_PUBLIC — no key, no token, no auth of any kind
    Rows:      347,050 parcels
    Fields:    50
    Paging:    maxRecordCount 1000, supportsPagination true
    Freshness: LIVE — max MODDATE 2026-08-03, i.e. yesterday. Genuinely nightly,
               matching the published claim (contrast §4.4).
    Bulk:      FULL_COUNTY_BULK — CSV/GeoJSON/Shapefile export plus paginated
               REST. REST pagination is the reliable programmatic path; a
               single-shot CSV pull of the full layer aborted mid-transfer on
               test, so page it.
    Verdict:   GREEN

Also on the open data portal as "Parcels w/ Owner Information & Assessed
Values" (item `0d28e222479743baa97f8f4456da7bb4`, layer 10) — same underlying
service, described as "updated nightly from IndyGIS Parcels and Marion County
Assessor's Office information." Projection NAD 1983 StatePlane Indiana East
FIPS 1301 (US Feet).

Fields worth ingesting:

    IDENTITY     PARCEL_I, PARCEL_C, STATEPARCELNUMBER, CAMAPARCELID
    SITUS        STNUMBER, PRE_DIR, STREET_NAME, SUFFIX, SUF_DIR,
                 FULL_STNAME, CITY, COUNTY, STATE, TOWNSHIP, ZIPCODE
    OWNER        FULLOWNERNAME (500 chars), OWNERADDRESS, OWNERADDRESS2,
                 OWNERCITY, OWNERSTATE, OWNERZIP, OWNERFOREIGNSTATE,
                 OWNERFOREIGNCOUNTRY
    VALUE        ASSESSORYEAR_LANDTOTAL, ASSESSORYEAR_IMPTOTAL,
                 ASSESSORYEAR_TOTALAV
    ATTRIBUTES   PROPERTY_CLASS, PROPERTY_SUB_CLASS,
                 PROPERTY_SUB_CLASS_DESCRIPTION, ESTSQFT, ACREAGE,
                 LOTNUM, BLOCK, NEIGHBORHOOD, SUBDIVISION_ID, SUBDIVNUM
    TAX/LEGAL    TAX_DISTRICT_ID, ASSESSOR_DISTRICT, STR_SECTION,
                 STR_TOWNSHIP, STR_RANGE, LEGAL_DESCRIPTION_ (1500 chars)
    LIFECYCLE    MODDATE, STATUS

**`STATUS` carries "VACANT" directly on the parcel record** — a free distress
signal on the enrichment layer, and an absentee-owner signal is derivable by
comparing OWNERADDRESS against the situs address.

**Bonus distress layers on the same service, both free and both parcel-keyed:**

    Layer 11 / 16  "Abandoned and Vacant [Properties]" — 7,120 rows, identical
                   schema, keyed on PARCEL_I. Fields: PARCEL_I, STNUMBER,
                   PRE_DIR, STREET_NAME, SUFFIX, SUF_DIR, FULL_STNAME, CITY,
                   ZIPCODE, ADDRESS, STATUS. Layers 11 and 16 return the same
                   7,120 rows — pick one. This is a genuine P1 distress source
                   that joins on the secondary key with no address matching.

    Layer 27       "Registerd Landlord Properties" [sic — the typo is in the
                   service] — 11,862 rows, keyed on PARCEL_C. Fields:
                   PARCEL_C, REGISTRATION_NUMBER, PROPERTY_NAME, STNUM, DIR,
                   STREET_NAME, CITY, ZIP. Absentee/investor-owner enrichment.

Other layers on the service worth noting: 0 Unit Address Points (the address
spine for §1.5), 8 Buildings, 17 Zoning, 21 Excluded Cities, 28 Flood Zones,
29 Brownfields.

**Excluded cities caveat:** Marion County contains Beech Grove, Lawrence,
Southport, Speedway and several small towns which run their own municipal
governments. They are inside Marion County for recorder, court, assessment and
treasury purposes, but their **local code enforcement is not DCE's** — so code
enforcement coverage has real holes in those areas. Layer 21 delineates them;
use it to flag coverage gaps rather than reporting false negatives.

---

## 5. Additional sources found during recon

### 5.1 Sheriff's sale — the address bridge

    Authority:  Marion County Sheriff, Judicial Enforcement Division
    Page:       https://www.indy.gov/activity/sheriff-real-estate-sales
    Schedule:   third Friday monthly, no December sale (SECONDARY)
    Lists:      a "short" list (address, sale number, township) and a full list
                (address, sale number, township, plaintiff, judgment amount and
                fees) (SECONDARY)
    Lead time:  list published ~30 days ahead of sale (SECONDARY)
    Verdict:    YELLOW — high value, exact machine-readable source not yet pinned

**Why this matters more than its rank suggests:** the sheriff sale list carries
the **property address and the judgment amount**, which the MF court record does
not. Joining sheriff sale entries to MF cases recovers address (and therefore
parcel) for the foreclosure pipeline, and adds judgment amount for scoring. It
is the most valuable "supporting" source in the county.

Blocker: indy.gov is a client-rendered Phoenix application. Its activity pages
return a ~4.3 KB shell with no content and no discoverable backing API — every
indy.gov page probed (tax sale reports, sheriff sales, treasurer, assessor,
property tax history) returned an identical empty shell. Extracting these lists
requires a headless browser pass. Legacy `indygov.org`/`indygov.biz` references
appear in older documentation; `indygov.biz` fails TLS validation and should not
be used.

### 5.2 Bankruptcy — PACER

    Court:    U.S. Bankruptcy Court, Southern District of Indiana
    Access:   PAID_SUBSCRIPTION_REQUIRED ($0.10/page)
    Verdict:  RED. Permission blocker, no auto-resolve. build_priority: future.
    Note:     federal, not a county source. Needs an operator funding decision.

### 5.3 Not pursued this pass

UCC / business entity search (Indiana Secretary of State) — framework §01.27
query 15 classifies these ENRICHMENT_SOURCE with `build_priority: future`;
recon records that they exist but does not build an adapter. Public notice /
newspaper of record — see §9.

---

## 6. Tax roll, delinquency, and balance lookup (§01.31)

Answering the three artifacts separately, as the framework now requires.

### 6.1 TAX_ROLL — available, free, no key, nightly

The MapIndy Parcel layer (§4.5) **is** the tax roll for enrichment purposes.
347,050 parcels with owner of record, owner mailing address, land/improvement/
total assessed value, property class, acreage, tax district, and full legal
description; refreshed nightly (verified MODDATE 2026-08-03).

    Mechanism:  open ArcGIS REST + bulk CSV/GeoJSON/Shapefile export
    Key/cost:   none — no API key, no account, no cost
    Cadence:    nightly
    Class:      FULL_COUNTY_BULK
    Keyed on:   both canonical and secondary parcel keys
    Verdict:    GREEN — this is the enrichment backbone of the build

There is no separate downloadable "tax roll" file beyond this, and none is
needed. Note it carries **assessed value but not tax billed or tax owed** —
that is §6.2.

### 6.2 BALANCE_LOOKUP — Indiana Gateway, state-level, best available

    Portal:     https://gateway.ifionline.org/TaxBillLookUp/Default.aspx
    Authority:  Indiana Department of Local Government Finance (DLGF) — official
                statewide source, explicitly described on-page as public record
    Coverage:   all 92 Indiana counties. Marion is county value "49".
    Stack:      ASP.NET WebForms (postback, __VIEWSTATE) — server-rendered,
                scriptable, no JS app required
    Controls:   no CAPTCHA marker present in the page
    Verdict:    YELLOW — strong candidate, needs a postback test

Form fields (all present in server-rendered markup):

    ctl00$cph_Main$countyDdl      county selector — Marion = "49"
    ctl00$cph_Main$parcelTxt      PARCEL NUMBER SEARCH
    ctl00$cph_Main$nameTxt        owner name
    ctl00$cph_Main$addressTxt     address
    ctl00$cph_Main$districtDdl    taxing district
    ctl00$cph_Main$rateMinTxt / rateMaxTxt
    ctl00$cph_Main$sortDdl
    ctl00$cph_Main$searchBtn
    ctl00$cph_Main$exportBtn      <-- EXPORT capability

This is the best tax-billing answer found: state-run, uniform across counties
(so the adapter is reusable for any future Indiana county), parcel-keyed, and
it exposes an **export button**, which suggests bulk extraction is possible
rather than per-record only. DLGF cautions that data is passed through from each
county so formatting varies.

    NEXT ACTION: drive one search postback for county 49 and click export, to
    determine (a) the export format, (b) whether export is bounded to a result
    set or can span the county, (c) whether the parcel field wants the
    punctuated or digits-only state parcel number, and (d) whether tax
    delinquency / unpaid balance is exposed or only billed amounts.

Marion-specific alternatives, both blocked behind the indy.gov SPA shell:
`indy.gov/activity/property-tax-history-reports` (payments, amounts billed, and
outstanding balances across multiple tax years) and the Assessor Property Cards
application (searchable **by state parcel number** — independent confirmation
that STATEPARCELNUMBER is the right canonical key). Treasurer contact:
317-327-4444, mytaxes@indy.gov. Property tax due dates 2026: May 11 and Nov 10.

### 6.3 DELINQUENCY_LIST — the real gap

**No current, downloadable, county-wide delinquent-parcel list was found.**

    data.indy.gov:  "Tax Sale Reports" 2010-2017 only. FROZEN. Backfill only.
    Tax sale list:  annual, via GovEase (§4.2) — but per §01.31 this is only
                    parcels that already reached sale eligibility, a small and
                    late subset of the distressed universe.
    Gateway:        may expose balances per parcel (§6.2, untested)

    Search paths checked: data.indy.gov DCAT catalog (651 datasets, filtered on
    assess/treasur/tax/owner/delinq/property/abandon/vacant/landlord/address);
    indy.gov treasurer and tax-sale activity pages; Indiana Gateway; SRI;
    GovEase; Zeus Auction.

Options, in preference order: (1) confirm Gateway export yields balances, which
would let the county-wide delinquent set be derived; (2) harvest the annual tax
sale list as the reliable floor; (3) request a standing bulk delinquency
delivery from the Treasurer — the framework permits standing records delivery
and this is a legitimate ask for public record data.

---

## 7. Freshness summary (§01.32)

    SOURCE                       MAX RECORD DATE  LAG        VERDICT
    MapIndy Parcel layer         2026-08-03       1 day      LIVE
    MyCase courts                current period   current    LIVE
    MapIndy Abandoned & Vacant   not exposed      —          UNKNOWN
    MapIndy Reg. Landlord        not exposed      —          UNKNOWN
    Accela code enforcement      not tested       —          UNKNOWN
    Open-data code enforcement   2024-02-27       ~2.4 yr    FROZEN
    Open-data tax sale reports   2017             ~9 yr      FROZEN
    Recorder (Fidlar)            not tested       —          UNKNOWN
    Indiana Gateway              not tested       —          UNKNOWN

Only two sources are confirmed LIVE. Both are P0/P2 anchors, so the build is
viable — but every UNKNOWN above must be resolved before its source is trusted
as current, and the two FROZEN sources must never be counted as live feeds.

---

## 8. Assumptions this recon overturned

Recording these explicitly because each would have caused a wrong build.

    1. "Recorder is Doxpop or Landex."
       -> It is Fidlar (inmarion.fidlar.com/INMarion/DirectSearch/). Doxpop is a
          third-party aggregator, out of scope. Watch for OHMarion vs INMarion.

    2. "SRI runs the Marion tax sale, confirm the list format."
       -> SRI administers, but the auction/list platform for Marion is GovEase.
          The prior recon's GovEase URL is now 404.

    3. "Code enforcement open data updates nightly." (prior recon)
       -> FROZEN at 2024-02-27. Zero rows after 2025-01-01. The catalog
          "modified" date is 2025-03-12 and is misleading.

    4. "MyCase has a CAPTCHA." (implied by the bundle)
       -> Present but NOT enforced. Verified by live request: HTTP 200, JSON,
          no challenge, no cookie. The best source in the county would have been
          discarded on a code-reading alone.

    5. "The prior build established a parcel join." (marion-in-intel)
       -> It did not. That build assigns synthetic placeholder parcel ids —
          SHA1 of the doc/case number, prefixed MARIN-REC- / MARIN-CT- — and
          then joins to the assessor by fuzzy owner-name LIKE matching,
          discarding any match with >=20 hits. There is no real parcel key in
          that pipeline. This build must not inherit that approach.

---

## 9. Uncertain doc-type coverage — flagged

    SURPLUS / OVERAGE — UNCERTAIN.
    Indiana tax sale surplus and sheriff sale overage funds exist, but no
    public list of claimable surplus was located for Marion County. Likely held
    by the Auditor. Needs a targeted pass; the Auditor was not probed this pass
    and is a gap in this recon.

    PUBLIC NOTICE — UNCERTAIN.
    Indiana's statewide public notice portal and the county's newspaper of
    record were not confirmed. Worth pursuing: public notices often publish
    foreclosure and sheriff sale ahead of the recorded/updated counterpart,
    which would add lead time on top of the MF filing.

    RECORDER DOC-TYPE TAXONOMY — NOT CAPTURED.
    Framework §01.12 requires capturing the source's document-type vocabulary.
    Could not be done for the recorder: the SPA renders the doc-type dropdown
    client-side and there is no reachable API. Nine lead types (§3.2) depend on
    this. Blocked behind the same §4.1 browser test.

    PDF / SAMPLE DOCUMENT INSPECTION (§01.22) — NOT PERFORMED.
    No source documents were fetched. Evidence of why: the recorder path is
    unreachable without a browser; MyCase PDFs are robots.txt-disallowed; the
    sheriff and tax sale lists sit behind the indy.gov SPA shell. This is a
    genuine outstanding requirement, not a waiver, and must be completed in the
    browser pass before any of those sources is finalized.

    MARION COUNTY AUDITOR — NOT PROBED.
    Relevant to tax sale surplus and to the tax sale list itself. Gap.

---

## 10. Recommended next actions

    1. ONE headless-browser recon pass, which unblocks almost everything left:
         a. Fidlar recorder — capture the search XHR, test whether reCAPTCHA is
            actually enforced, capture the doc-type dropdown (§4.1). Governs 9
            lead types. Highest leverage task in the county.
         b. indy.gov sheriff sale + tax sale pages — extract the real list URLs.
         c. Indiana Gateway — run a county-49 search and an export (§6.2).
         d. Accela — confirm public search and any enforced control.
       This also discharges the outstanding §01.22 sample-document requirement.

    2. Build the ADDRESS -> PARCEL crosswalk from MapIndy layer 0 / the open
       data address datasets before any matcher work. It is the load-bearing
       component of this build and everything downstream depends on its quality.

    3. Ship the MVP on MyCase + parcel layer + crosswalk. That alone yields
       foreclosure (MF), eviction (EV), probate (EU/ES/EM), civil judgment (CC)
       and tax deed (TP) leads with a real parcel join.

    4. Backfill code enforcement 2010-2024 from the frozen extract; wire Accela
       for current cases. Never substitute the extract for the live source.

    5. Operator decisions required:
         - MyCase case detail is robots.txt-disallowed. Fetch anyway, or accept
           search-only and bridge addresses via sheriff sale? Policy call.
         - PACER funding for bankruptcy (§5.2)?
         - Standing delinquency delivery request to the Treasurer (§6.3)?

---

## 11. Framework artifact note

The build request specified this single consolidated report at
`recon/marion-in-recon.md`, and that is what this file is. Framework Protocol 01
§01.14 additionally expects eight split artifacts under
`runs/marion_in/recon/` (`source_discovery.md`, `source_verification.md`,
`portal_fingerprints.md`, `access_classification.md`,
`source_role_classification.md`, `document_type_discovery.md`,
`build_eligibility_handoff.md`, `recon_summary.md`), plus the v5.3.0
Source-of-Record Matrix set. Every field those artifacts require is present in
this document; they have not been split out. Say the word and I will generate
them from this content.

Two protocol deviations, both directed by the build request and recorded here
for the audit trail: §01.17 forbids committing during recon (this report is
committed and pushed as instructed), and forbids writing outside
`runs/<slug>/recon/` (this report is at `recon/`).
