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

    HEADLESS-BROWSER PASS COMPLETED 2026-08-05. Four sources moved to GREEN
    (recorder, tax sale, Accela, Gateway); no source moved down. The recorder
    enforcement test is done and it is NOT blocked. §01.22 sample-document
    inspection is now discharged for every GREEN source. Full changes in §12.

Findings that overturn common assumptions about this county — from the build
request, the prior `marion-in-intel` recon, and the pre-browser pass of this
recon — are detailed in §8.

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

    0. DIRECT PARCEL KEY — no bridge needed (CONFIRMED 2026-08-05)
       Three sources turned out to carry a parcel key directly and need no
       matching at all. This was not known before the browser pass:
         - Tax sale Parcel Status List and Surplus PDFs are keyed on the LOCAL
           parcel number (e.g. 1000182 = PARCEL_C). §4.2.
         - MapIndy Abandoned and Vacant is keyed on PARCEL_I. §4.5.
         - MapIndy Registered Landlord is keyed on PARCEL_C. §4.5.
         - Accela code enforcement exposes a parcel-number SEARCH field
           (`txtGSParcelNo`), so the live system is parcel-aware even though the
           open-data extract has no parcel column. §4.4.
       Use the key. Do not build an address match for these.

    1. LEGAL DESCRIPTION -> SUBDIVISION + LOT (the recorder's only path)
       PROVEN END-TO-END 2026-08-05. The recorder exposes no address and no
       parcel by statute (§4.1), but every indexed document carries a
       `LegalSummary` such as "Sub: SADDLEBROOK NORTH SEC 1  Lot: 2". Chain:

         recorder LegalSummary
           -> MapIndy layer 19 "Subdivisions" WHERE UPPER(RECORDED_NAME) matches
              -> SUBDIV_TAG
           -> MapIndy layer 10 Parcel WHERE SUBDIVISION_TAG=<tag> AND LOTNUM=<lot>
              -> STATEPARCELNUMBER + PARCEL_C

       Verified against a real record: "SADDLEBROOK NORTH SEC 1 / Lot 2"
       resolved to SUBDIV_TAG 6785, then to EXACTLY ONE parcel,
       49-06-05-112-029.000-600 (PARCEL_C 6023323, 3619 CATALPA AVE), whose own
       LEGAL_DESCRIPTION_ reads "SADDLEBROOK NORTH SECTION 1 L 2". Deterministic,
       not fuzzy.

         COVERAGE CEILING: 114,831 of 347,050 parcels (33%) have both
         SUBDIVISION_TAG > 0 and a populated LOTNUM. Metes-and-bounds and
         unplatted parcels have no lot number and are unreachable this way.
         DO NOT join on SUBDIVNUM — it is '0' for many subdivisions and will
         match hundreds of unrelated parcels. Use SUBDIVISION_TAG / SUBDIV_TAG.

    2. ADDRESS NORMALIZATION (primary bridge for the address-bearing sources)
       Normalize source address -> match against parcel layer STNUMBER +
       FULL_STNAME + ZIPCODE -> read STATEPARCELNUMBER and PARCEL_I.
       Still required for: Accela code enforcement result rows, sheriff sale
       list, and the tax sale Surplus PDF's "Parcel Location" column.
       Supporting asset: the county publishes address point layers ("Buildings
       with Addresses", "Building Unit Addresses", both CSV on the open data
       portal, and MapIndy layer 0 "Unit Address Points") which give an
       authoritative address->parcel spine rather than fuzzy string matching.

    3. SHERIFF SALE AS THE ADDRESS BRIDGE FOR FORECLOSURE (high value)
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

Revised 2026-08-05 after the headless-browser pass. Verdict changes marked.

    RANK  SOURCE                        ROLE          PRIORITY  VERDICT
    1     MyCase — Indiana Courts       PRIMARY       P0        GREEN
    2     MapIndy Parcel layer          ENRICHMENT    P2        GREEN
    3     Tax sale lists (indy.gov PDF) PRIMARY       P1        GREEN  (was YELLOW)
    4     MapIndy Abandoned & Vacant    PRIMARY       P1        GREEN
    5     Marion County Recorder        PRIMARY       P1        GREEN  (was RED)
    6     Accela code enforcement       PRIMARY       P0        GREEN  (was YELLOW)
    7     Indiana Gateway tax bills     ENRICHMENT    P2        GREEN  (was YELLOW)
    8     MapIndy Registered Landlord   ENRICHMENT    P2        GREEN
    9     Sheriff sale list (GovEase)   SUPPORTING    P1        YELLOW
    10    Open-data code enforcement    BACKFILL ONLY —         RED as live
    11    PACER bankruptcy              PRIMARY       future    RED

Build order recommendation: **1 -> 2 -> 3 -> address crosswalk (§1.5) -> 4 ->
6 -> 5 -> 7 -> 9**. Tax sale moves up sharply: it is a static PDF set already
keyed on the parcel number, so it needs no crosswalk and delivers tax
delinquency, tax sale certificate, and surplus leads immediately.

Ship an MVP on MyCase + parcel layer + tax sale lists; that combination produces
foreclosure, eviction, probate, tax deed, tax delinquency and surplus leads, and
only the court sources need the address crosswalk.

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

Live MF examples pulled 2026-08-04 (filed 06/02/2026), defendant names redacted:

    49D33-2606-MF-030447  Rocket Mortgage, LLC v. <individual>, Indiana Housing
                          & Community Development Authority, State of Indiana
    49D33-2606-MF-030448  Lakeview Loan Servicing, LLC v. <individuals>,
                          Eagles Landing Homeowners Association, Inc.
    49D33-2606-MF-030449  U.S. BANK NATIONAL ASSOCIATION v. <individual>, ...
    49D33-2606-MF-030468  KeyBank National Association v. <individuals>,
                          JPMorgan Chase Bank, National Association

The `Style` field reliably reads "<lender> v. <borrower(s)>", so the plaintiff
is the lender and the first individual defendant is the distressed owner — the
shape the debtor-party engine needs.

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
    Lis Pendens                NO DEDICATED RECORDER CODE — §4.1      NOT_SEPARABLE
    Civil Judgment             CC - Civil Collection (MyCase)         LIVE, high volume
    Abstract of Judgment       NO DEDICATED RECORDER CODE — §4.1      NOT_SEPARABLE
    Mechanic Lien              MECHANIC LIEN (code 24), recorder      LIVE (unblocked)
    Construction Lien          MECHANIC LIEN (code 24) — same code    LIVE (unblocked)
    Federal Tax Lien           FEDERAL TAX LIEN (code 21), recorder   LIVE (unblocked)
    State Tax Lien             NO DEDICATED CODE — generic LIEN (23)  NOT_SEPARABLE
    Probate                    EU / ES / EM (MyCase, category PR)     LIVE
    Affidavit of Heirship      AFFIDAVIT (code 3) — generic bucket    NOT_SEPARABLE
    Executor Deed              DEED (code 18) — generic bucket        NOT_SEPARABLE
    Administrator Deed         DEED (code 18) — generic bucket        NOT_SEPARABLE
    Code Lien                  Enforcement/Violation/* (Accela)       LIVE
    Demolition                 Enforcement/Violation/Demolition       LIVE
    Condemnation               Enforcement/Investigation/Unsafe Bldgs LIVE
    Eviction                   EV - Evictions, two dockets (MyCase)   LIVE, very high vol
    Divorce                    DR / DC (MyCase, category FAM)         LIVE, low value
    Bankruptcy                 PACER — S.D. Indiana                   BLOCKED, paid
    Surplus                    Tax Sale Surplus Details PDF — §4.2    LIVE (resolved)
    Bankruptcy Notice          PACER                                  BLOCKED, paid
    Public Notice              newspaper of record / posted notices   UNCERTAIN — §9

    Bonus lead type not in the framework sweep, found empirically:
    TP - Verified Petition for Issuance of a Tax Deed (MyCase). The court step
    where a tax sale certificate holder converts to a deed. Low volume (~1 per
    5 filing days) but an extremely high-intent distress signal.

**Coverage summary (revised 2026-08-05).** 19 of 29 framework lead types are
LIVE and buildable now — up from 15. The recorder is unblocked (§4.1), which
delivered Mechanic Lien, Construction Lien and Federal Tax Lien outright, and
the tax sale PDFs resolved Surplus.

    LIVE                19   (was 15)
    NOT_SEPARABLE        6   Lis Pendens, Abstract of Judgment, State Tax Lien,
                             Affidavit of Heirship, Executor Deed,
                             Administrator Deed — the recorder is reachable but
                             has no dedicated code for these; they sit inside
                             generic AFFIDAVIT / DEED / LIEN / COURT DOCUMENT
                             buckets and can only be separated by reading the
                             paywalled document image
    NOT_APPLICABLE       3   trustee sale variants — judicial state
    BLOCKED (paid)       2   Bankruptcy, Bankruptcy Notice — PACER
    UNCERTAIN            1   Public Notice (§9)

**Important correction.** The pre-browser recon said "9 lead types are blocked
behind the single recorder blocker — one unblock recovers all nine." The unblock
happened, and it recovered THREE, not nine. The other six are limited by the
county's document-type vocabulary, not by access. That is a taxonomy limit, and
no amount of access work fixes it — only paying for document images would, and
even then it means OCR-classifying generic DEED and AFFIDAVIT filings at volume.
Recorded plainly because the earlier framing overstated the prize.

    Additional lead types found in the recorder taxonomy, not in the framework
    sweep: SHERIFF DEED (code 33) — the post-sale transfer, confirming a
    completed foreclosure; VACATED PROPERTY (code 7); ASSESSMENT LIEN (46),
    SEWER LIEN (35), HOSPITAL LIEN (50); ASSIGNMENT OF LAND CONTRACTS (49),
    a creative-finance signal.

---

## 4. Source-by-source findings

### 4.1 Marion County Recorder — recorded documents

**STATUS CHANGED 2026-08-05 (headless-browser pass): RED -> GREEN.**

    Authority:      Marion County Recorder, 200 E. Washington St, Suite 1040
    Portal:         https://inmarion.fidlar.com/INMarion/DirectSearch/
    Vendor:         Fidlar Technologies (NOT Doxpop, NOT Landex, NOT county-native)
    Product:        "Direct Search" v5.0.10-rel (appConfig.json)
    Live status:    HTTP 200, title "Direct Search"
    Architecture:   Angular SPA (Angular Material). Server-rendered HTML has zero
                    forms; all search UI is client-rendered.
    API base:       https://inmarion.fidlar.com/INMarion/Scrap.WebService.DirectSearch/
                    (from appConfig.json -> "webApiBase") — a Breeze service
    Server:         Microsoft-IIS/10.0, ASP.NET
    Access class:   SEARCH_ONLY_PUBLIC — index/metadata free, document images paid
    Bulk (§01.24):  BATCH_QUERY — date-range + party or doc-type queries return
                    full result sets in one JSON response (90 results in 100 KB)
    Freshness:      LAGGING BY DESIGN — "Document information is available five
                    days after recording" (portal's own InfoMessage). Build the
                    cursor with a 5-day lag or records will be missed.
    Scrapeability:  GREEN (browser-driven) / RED (pure HTTP — see enforcement)

**Endpoints (captured from live network traffic).** All under the API base:

    GET  /breeze/Settings        capability matrix — no auth required (HTTP 200
                                 via plain HTTP, no browser, no token)
    GET  /breeze/DocumentTypes   the 50-value doc type registry — no auth required
    POST /breeze/Search          the search endpoint — AUTH REQUIRED (see below)

Search request body (verbatim, from the captured XHR):

    {"FirstName":"","LastBusinessName":"SMITH","StartDate":"2026-01-01",
     "EndDate":"2026-01-31","DocumentName":"","DocumentType":"",
     "SubdivisionName":"","SubdivisionLot":"","SubdivisionBlock":"",
     "MunicipalityName":"","TractSection":"","TractTownship":"","TractRange":"",
     "TractQuarter":"","TractQuarterQuarter":"","AddressHouseNo":"",
     "AddressStreet":"","AddressCity":"","AddressZip":"","ParcelNumber":"",
     "Book":"","Page":"","ReferenceNumber":"",
     "DisplayStartDate":"01/01/2026","DisplayEndDate":"01/31/2026"}

**§01.29 ENFORCEMENT TEST — PERFORMED 2026-08-05. Control present AND enforced,
but machine-satisfiable without a human.**

    Test A — POST /breeze/Search with no auth and no captcha header
             RESULT: HTTP 401 Unauthorized. Enforcement is REAL.

    Test B — same search driven through a headless browser
             RESULT: HTTP 200, 100,457 bytes, TotalResults 90.
             No challenge was displayed at any point. No human interaction.
             Post-search DOM check: recaptcha bframe present but NOT visible,
             body text contains no captcha/"not a robot" prompt.

Two headers are required on `/breeze/Search` and both are minted automatically
by the page:

    authorization: Bearer <JWE>   an encrypted JWT issued to the anonymous session
    fidlarcaptchasolution: <token> a reCAPTCHA **v3 invisible** token
                                   site key 6LckDLwaAAAAAFdkFeW-dkX0IMirFhqiB_tXcRZE

**§01.29 tiering: `PER_REQUEST_CHALLENGE`.** The token is minted per search and
there is no durable session to hand off. Critically, though, reCAPTCHA v3 is
*score-based and invisible* — there is no puzzle for a human to solve, so this
is NOT an operator-assisted source and NOT a `SINGLE_LAYER_HUMAN_VERIFIABLE`
one. It is simply a source whose adapter must run in a real browser context that
executes the reCAPTCHA JS, rather than as a plain HTTP client. Cost: a
Playwright-driven adapter instead of a `requests`-style one. That is an
engineering cost, not a blocker, and no CAPTCHA is ever solved.

**API discovery (§01.23) — documented API found: NO** (the Breeze service is
undocumented but discoverable). Paths checked, all 404:

    /INMarion/api            /INMarion/api/swagger      /INMarion/swagger
    /INMarion/swagger/index.html                        /INMarion/api-docs
    /INMarion/docs           /api                       /swagger
    /swagger/v1/swagger.json /INMarion/DirectSearch/api /INMarion/api/Search
    /INMarion/api/documents  /breeze/Metadata (404 — Breeze metadata disabled)

**Search capability matrix (`/breeze/Settings`, verbatim).** This is decisive for
the join strategy and was invisible before this pass:

    PartySearchEnabled            true
    DateRangeSearchEnabled        true
    DocumentNumberSearchEnabled   true
    DocumentTypeSearchEnabled     true
    SubdivisionLotBlockSearchEnabled  true
    ParcelSearchEnabled           FALSE   <-- IC 36-1-8.5 restricted addresses
    AddressSearchEnabled          FALSE
    UseWildcardSearches           FALSE   <-- exact-match party names only
    ViewImages                    FALSE   <-- images are pay-per-view (Tapestry)
    ViewParcel                    FALSE
    ViewAddress                   FALSE
    ViewParty / ViewLocation / ViewNotes   true
    CountyDisplayName             "IN, Marion"   (correct county confirmed)

    CONSEQUENCE: the recorder exposes NO address and NO parcel number, by
    statute, in both search AND detail. Recorder records therefore cannot be
    joined to a parcel by address or parcel id at all. The ONLY join path is the
    legal description — see §1.5, which this pass rewrote around that finding.

**Sample record (§01.22 — INSPECTED).** Saved to
`runs/marion_in/recon/samples/fidlar/05_search_response.json`. Fields returned
per document:

    Id, DocumentType, RecordedDateTime, DocumentName (instrument no.),
    Book, Page, ConsiderationAmount, DocumentDate, ReferenceNumber,
    LegalSummary, Legals[], Notes, Party1, Party2,
    Parties[] {Id, PartyTypeId, Name, AdditionalName},
    AssociatedDocuments[], Fees[], ReturnTo{}, ImagePageCount,
    UCCData{}, TapestryLink, CanViewImage (false)

    Real example (party names redacted — see the PII note at the end of §11):
      DocumentName   A202600008247
      DocumentType   DEED
      RecordedDateTime 1/30/2026 3:12:20 PM
      Party1         <individual, LAST FIRST MIDDLE form>
      Party2         <individual, LAST FIRST MIDDLE form>
      LegalSummary   "Sub: SADDLEBROOK NORTH SEC 1  Lot: 2"
      CanViewImage   false

    Party name shape matters for the matcher: the recorder stores names as
    LAST FIRST MIDDLE in separate `Name` / `AdditionalName` sub-fields, while
    MyCase returns FIRST LAST in a single string. Any cross-source party match
    must normalize that difference.

    Text-extractable JSON, not scanned images. Layout is uniform. No OCR needed
    for the index; document IMAGES are a separate paid product (Tapestry) and
    are not required to produce leads.

**Correction to the build request.** The request suggested Doxpop, Landex, or
county-native. It is Fidlar. Doxpop does carry Marion County data but is a
third-party aggregator and is therefore out of scope per framework §01.6
(resellers are not primary recon targets). Be careful with search results here:
`rep3laredo.fidlar.com/OHMarion/` is Marion County **Ohio** — the `OH`/`IN`
prefix is the only thing distinguishing them, and it is easy to mis-target.
`inmarion.fidlar.com/INMarion/AvaWeb/` returns 404; `/INMarion/DirectSearch/`
is the live path.

**Document type taxonomy (§01.12) — CAPTURED 2026-08-05.** 50 types, retrieved
from `/breeze/DocumentTypes` (saved to `samples/fidlar/02_document_types.json`).
The registry is COARSER than the framework lead-type sweep assumed, and that
materially limits what unblocking the recorder actually delivers:

    DISTINCTLY TYPED — directly filterable, genuinely unblocked:
      24 MECHANIC LIEN              25 MECHANIC LIEN RELEASE
      21 FEDERAL TAX LIEN           22 FEDERAL TAX LIEN RELEASE
      46 ASSESSMENT LIEN            47 ASSESSMENT LIEN RELEASE
      35 SEWER LIEN                 50 HOSPITAL LIEN
      33 SHERIFF DEED               23 LIEN
      7  VACATED PROPERTY           49 ASSIGNMENT OF LAND CONTRACTS
      27 MORTGAGE                   28 MORTGAGE RELEASE
      18 DEED                       12 CONTRACT
      16 COURT DOCUMENT             3  AFFIDAVIT
      29 PLAT                       30 POWER OF ATTORNEY
      (plus 30 further administrative/UCC/misc types)

    NOT DISTINCTLY TYPED — these framework lead types have NO dedicated code in
    Marion County and collapse into generic buckets:
      Lis Pendens            -> no code. Likely filed as COURT DOCUMENT or MISC.
      Abstract of Judgment   -> no code. LIEN / COURT DOCUMENT.
      State Tax Lien         -> no code. LIEN (only FEDERAL is broken out).
      Affidavit of Heirship  -> AFFIDAVIT (generic, code 3)
      Executor Deed          -> DEED (generic, code 18)
      Administrator Deed     -> DEED (generic, code 18)

    Isolating those six from their generic buckets requires reading the document
    IMAGE, which is paywalled (`ViewImages: false`). From index metadata alone
    they cannot be separated. This is an honest downgrade of the earlier
    "one unblock recovers all nine lead types" claim — see §3.2.

**Correction to the earlier recon.** The pre-browser pass concluded the Angular
bundle "yields no extractable API base." That was wrong in a recoverable way:
the base is not in the bundle, it is in `appConfig.json`, fetched at runtime and
trivially readable. Checking a SPA's runtime config file is now the first thing
to try before declaring an API base undiscoverable.

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
the administrator, but the *auction platform for Marion is GovEase*, not SRI's
own Zeus. Target GovEase for the auction.

**MAJOR CORRECTION 2026-08-05 — the lists are published, and they are the best
tax-distress source in the county. Verdict YELLOW -> GREEN.**

The pre-browser pass concluded tax sale reports existed "for 2010 through 2017
only." That was true of the data.indy.gov open-data portal and false of the
county itself. Rendering `indy.gov/activity/tax-sale-reports` shows report sets
for **2018 through 2025**, hosted on the county's Hygraph CDN:

    https://us-east-1-indy.graphassets.com/ActDBC5rvRWeCZlNNnLrDz/<asset-id>

Four documents per year. The 2025 set, downloaded and inspected (§01.22):

    2025 Tax Sale - Parcel Status List 12.3.25.pdf     946 KB, 54 pages
    2025 Tax Sale - Purchase Details 12.3.25.pdf       334 KB
    2025 Tax Sale - Surplus Details 12.3.25.pdf         47 KB, 1 page
    2025 Tax Sale Information and Procedures

    Format: text-extractable PDF (PDF-1.3), tabular, uniform layout, no OCR
    required. Saved under runs/marion_in/recon/samples/taxsale/.

**Parcel Status List — the delinquency feed.** Columns:

    Seq # | Parcel # | Owner Name | Parcel Status | Face Value | Overbid |
    Purchase Amount | Last Updated

    Real rows (individual owner names redacted; entity names retained):
      A1  1000182  VGM CAPITAL HOLDINGS LLC   Sold             6,441.79  59,001.00
      A3  1000372  <individual>               Encroachment Issues  994.29
      A6  1000616  <individual>               Payment Plan     3,513.93
      A18 1002347  <individual>               Owner Redeemed   1,574.93  46,001.00
      A21 1002414  <individual>               Bankruptcy       3,561.11

    Observed Parcel Status values: Sold, Paid, Owner Redeemed, Payment Plan,
    Bankruptcy, Encroachment Issues, Removed - Miscellaneous.

    THE PARCEL COLUMN IS THE LOCAL PARCEL NUMBER (PARCEL_C). It joins straight
    to the parcel layer with no address matching. This is the only distress
    source in the county that arrives pre-keyed.

    "Bankruptcy" as a status is also a free bankruptcy signal for those parcels
    without touching PACER.

**Surplus Details — resolves the §9 Surplus flag.** Columns:

    Bidder ID | Parcel # | Primary Owner | Parcel Location | Face Value |
    Overbid Amount | Purchase Amount

    Carries BOTH the parcel number AND a full situs address in the form
    "<house no> <street> INDIANAPOLIS, IN <zip>". Surplus moves from UNCERTAIN
    to LIVE.

    Cadence: annual, published after the autumn sale and revised (the 2025 set
    is stamped 12.3.25). The 2026 set is not yet posted as of the recon date.
    Bulk class: FULL_COUNTY_BULK per sale year.

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

**Path B — Accela Citizen Access. The live source. YELLOW -> GREEN 2026-08-05.**

    Entry URL:   https://permitsandcases.indy.gov/citizenaccess/Cap/CapHome.aspx
                 ?module=Enforcement
    REDIRECTS TO: https://aca-prod.accela.com/INDY/...
                 (permitsandcases.indy.gov is a vanity host; the real origin is
                 Accela's aca-prod tenant "INDY". Target aca-prod directly.)
    Search page: https://aca-prod.accela.com/INDY/Cap/CapHome.aspx
                 ?module=Enforcement&TabName=Enforcement
    Access:      OPEN_PUBLIC
    Bulk:        PER_RECORD_ONLY via UI, but see "Reports" below
    Verdict:     GREEN

**§01.29 enforcement check — PERFORMED. No control is enforced.**

    password fields on page      0
    captcha nodes                0
    window.grecaptcha            undefined
    login required to search     NO ("Login" and "Register" links exist, but
                                 they gate saved searches and applications, not
                                 the public case search)
    __VIEWSTATE present          yes — standard ASP.NET WebForms postback

**A parcel search field exists — this corrects the recon's earlier claim.**
The Enforcement General Search form exposes:

    ctl00$PlaceHolderMain$generalSearchForm$txtGSParcelNo    <-- PARCEL NUMBER
    ...$txtGSStartDate / $txtGSEndDate                       date range
    ...$txtGSPermitNumber                                    case number
    ...$txtGSFirstName / $txtGSLastName / $txtGSBusiName     party
    ...$txtGSStreetName / $txtGSNumber$ChildControl0/1       address
    plus a Case Type dropdown

    So code enforcement IS parcel-addressable in the live system. The "no parcel
    identifier" finding in §1.5 applies only to the frozen open-data EXTRACT,
    which drops the column. Corrected accordingly.

**Case types in the live dropdown** include the distress set as first-class
entries: "Enforcement - Demolition", "Enforcement - Repair w/no Hearing",
"Enforcement - Vacant Board Order", alongside the investigation/violation types
seen in the extract.

**Reports.** The portal exposes a "Reports" menu with a **Case Research Report**
and **Case Summary** report per module. Not yet exercised — this is the most
likely bulk path and should be tried before building a page-scraping adapter.
Recorded as an open item rather than assumed to work.

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

    Authority:  Marion County Sheriff, Judicial Enforcement (JED) Real Estate
    Page:       https://www.indy.gov/activity/sheriff-real-estate-sales
    LIST URL:   https://liveauctions.govease.com/PublicPortal/
                RegistrationDetail?AuctionID=1375&Edit=False
                (CONFIRMED 2026-08-05 by rendering the indy.gov page)
    Cost:       FREE. County states plainly: "The Marion County Sheriff sale
                mortgage foreclosure list is available for free... You do not
                have to register to get the list."
    Lead time:  lists posted 30 days ahead; removals updated in real time
    Schedule:   CONFIRMED 2026 dates published on the page —
                01/16, 02/20, 03/20, 04/17, ... (third Friday monthly)
    Archive:    archived lists held with City Base back to 2005
    Contact:    MCSO-SheriffSaleRealEstate@indy.gov, 317.327.2459
    Verdict:    YELLOW — list URL now known and free, but the GovEase portal
                itself was not driven this pass, so the list's on-page format
                and field set remain unverified. Downgraded honestly rather
                than assumed.

**Origination confirmed.** The county's own wording settles §3.1: "When a
property has been foreclosed on in Marion County and the judgment is certified
to the Marion County Sheriff by the Marion County Clerk, that property is then
sold at the Sheriff's Sale." The sheriff sale is the execution of an already-
entered MF judgment — downstream, exactly as §3.1 concluded.

    Also on the page and relevant: a "Notice of Sheriff Sale Form" and a
    "Sheriff's Deed Form", which pair with the recorder's SHERIFF DEED doc type
    (code 33) to close the foreclosure lifecycle end to end.

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

**DRIVEN 2026-08-05. YELLOW -> GREEN. Answers to the four open questions:**

    (c) PARCEL FORMAT — Gateway speaks ONLY the state parcel number. The
        punctuated form "49-06-05-112-029.000-600" is accepted as input and the
        result grid displays the digits-only form "490605112029000600", which is
        exactly the `parcel_id_state_n` normalization defined in §1.6. The LOCAL
        parcel number (6023323) returns "No records to display."
        This independently validates the canonical key choice.

    (d) DELINQUENCY IS EXPOSED. The parcel detail page carries a dedicated
        "Penalty and Delinquent Taxes" block:
            Personal Property Late Penalty
            Personal Property Underpay Penalty
            Prior Year Delinquent Payment
            Prior Year Delinquent Penalty
        (all $0.00 on the current-paid sample parcel, but the fields are there).

    (a)(b) EXPORT — UNCONFIRMED. The "Export to Excel" control is present,
        enabled and visible (105x21 px, not disabled), but clicking it did not
        produce a download event within 30 s in headless Chromium. Whether it
        exports the result set only or can span a whole county is therefore NOT
        established. Recorded as unproven rather than claimed.

**Search result grid** (year + county + parcel):

    Pay Year | Parcel Number | Taxpayer | Total Tax Bill
    2025     | 490605112029000600 | AMERICAN HOMES 4 RENT | $4,726.40

The taxpayer name matches the parcel layer's FULLOWNERNAME for the same parcel —
a clean cross-source validation of the join key.

**Parcel detail fields (§01.22 — INSPECTED),** saved to
`runs/marion_in/recon/samples/gateway/04_parcel_detail.txt`:

    Tax Bill ID, Total Gross Assessed Value, Gross AV of Homestead Property,
    Gross AV of Other Residential Property and Farmland, Gross AV of all Other
    Property, Local/State Personal Property AV, Total Deductions and Exemptions,
    Total Net Assessed Value, Local Tax Rate, Gross Tax, Total Credits,
    Net Current Property Tax Liability, Exemptions,
    Property Tax Cap / Adjustment to Cap / Maximum Tax Under Cap,
    the four Penalty and Delinquent Taxes fields above,
    and a full Units in the District breakdown (unit, code, fund, rate).

    "Gross AV of Homestead Property = $0.00" on this parcel is an
    owner-occupancy signal: no homestead deduction means non-owner-occupied.
    That is a free absentee-owner indicator across the county.

    Pay Year selector covers 2007-2026, so historical tax series are available.

    STABILITY CAVEAT: the detail page leaked a raw SQL exception below the
    rendered content — "There is already an object named 'credit_temp' in the
    database" — which is why Total Credits rendered empty. The page is partially
    broken server-side. Build defensively and do not treat a blank credits field
    as authoritative.

Marion-specific alternatives, both blocked behind the indy.gov SPA shell:
`indy.gov/activity/property-tax-history-reports` (payments, amounts billed, and
outstanding balances across multiple tax years) and the Assessor Property Cards
application (searchable **by state parcel number** — independent confirmation
that STATEPARCELNUMBER is the right canonical key). Treasurer contact:
317-327-4444, mytaxes@indy.gov. Property tax due dates 2026: May 11 and Nov 10.

### 6.3 DELINQUENCY_LIST — the real gap

**RESOLVED 2026-08-05 — a county-wide delinquent-parcel list DOES exist.**
The annual **Tax Sale Parcel Status List** (§4.2) is exactly that: every parcel
that reached tax-sale eligibility, with owner, status, face value and amounts,
keyed on the local parcel number, published as a text-extractable PDF for each
year 2018-2025. Combined with Gateway's per-parcel "Penalty and Delinquent
Taxes" block (§6.2), the delinquency picture is covered:

    county-wide annual snapshot   Tax Sale Parcel Status List (bulk PDF)
    per-parcel current detail     Indiana Gateway parcel detail (per-record)

The remaining gap is narrower than first recorded: there is still no *continuous*
(monthly or nightly) county-wide delinquency feed. The annual list is a snapshot
of parcels already at sale eligibility, so parcels that fall behind mid-year and
cure before the sale never appear. A standing delivery request to the Treasurer
remains the way to close that, but it is now an optimization rather than a hole.

Original finding, retained for the audit trail:

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

Revised 2026-08-05.

    SOURCE                       MAX RECORD DATE  LAG          VERDICT
    MapIndy Parcel layer         2026-08-03       1 day        LIVE
    MyCase courts                current period   current      LIVE
    Recorder (Fidlar)            2026-01-30 in    5 days by    LAGGING
                                 sampled window   design       (by design)
    indy.gov tax sale reports    2025 sale year   annual       LIVE for cadence
    Indiana Gateway              pay year 2026    annual       LIVE for cadence
                                 selectable
    MapIndy Abandoned & Vacant   not exposed      —            UNKNOWN
    MapIndy Reg. Landlord        not exposed      —            UNKNOWN
    Accela code enforcement      not measured     —            UNKNOWN
    Open-data code enforcement   2024-02-27       ~2.4 yr      FROZEN
    Open-data tax sale reports   2017             ~9 yr        FROZEN

**Recorder lag is structural, not a defect.** The portal states: "Document
information is available five days after recording." Any incremental cursor must
lag five days or it will silently miss documents. This is a build requirement.

Three UNKNOWNs remain, all on sources whose cadence could not be measured
because the layer or portal exposes no record-date field to aggregate. None is
load-bearing for the MVP. The two FROZEN sources must never be counted as live
feeds — see §4.4.

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

    SURPLUS / OVERAGE — RESOLVED 2026-08-05.
    The county publishes "Tax Sale - Surplus Details" as an annual PDF with
    parcel number, owner, situs address and overbid/purchase amounts (§4.2).
    Sheriff sale overage remains unconfirmed and is presumably held by the
    Clerk or Auditor; the Auditor was still not probed. Partial resolution:
    tax sale surplus LIVE, sheriff overage still unknown.

    PUBLIC NOTICE — UNCERTAIN.
    Indiana's statewide public notice portal and the county's newspaper of
    record were not confirmed. Worth pursuing: public notices often publish
    foreclosure and sheriff sale ahead of the recorded/updated counterpart,
    which would add lead time on top of the MF filing.

    RECORDER DOC-TYPE TAXONOMY — CAPTURED 2026-08-05 (§4.1). 50 types via
    /breeze/DocumentTypes. Closed.

    PDF / SAMPLE DOCUMENT INSPECTION (§01.22) — DISCHARGED 2026-08-05 for every
    GREEN source. Samples saved under runs/marion_in/recon/samples/ and each
    source's claimed fields verified against the real record. See §11.

    ACCELA REPORTS MODULE — NOT EXERCISED.
    The portal exposes a "Case Research Report" and "Case Summary" report per
    module (§4.4). These are the most likely bulk path for code enforcement and
    were not run. New open item from this pass.

    GOVEASE SHERIFF SALE LIST — NOT DRIVEN.
    The free list URL is now known (§5.1) but the portal itself was not
    rendered, so the list's field set and format are unverified.

    GATEWAY EXPORT — ATTEMPTED, DID NOT COMPLETE (§6.2). Whether bulk county
    export is possible is unresolved.

    MARION COUNTY AUDITOR — STILL NOT PROBED.
    Relevant to sheriff sale overage. Gap carried forward.

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

## 11. Section-to-artifact index (Protocol 01 §01.14 / §01.33)

    RECON FORMAT: CONSOLIDATED

This recon uses the CONSOLIDATED format permitted by §01.14 as amended in
v5.6.0. The eight §01.14 artifacts were intentionally NOT produced as separate
files under `runs/marion_in/recon/`. This index is mandatory under §01.33 and
maps every artifact to the section(s) of this document carrying its content.

Format chosen because the findings here are heavily cross-cutting — the parcel
join key (§1), the recorder blocker (§4.1) that gates nine lead types, and the
MF-vs-sheriff-sale origination correction (§3.1) are each load-bearing across
four or more artifacts. Restating them per-file would risk the restatements
drifting out of sync.

### The eight §01.14 artifacts

    source_discovery.md
        §4 (all subsections) — every candidate source with URL, authority, and
        records covered. §5 — additional sources found during recon.
        §4.2, §5.1 — dead/moved URLs recorded rather than dropped.

    source_verification.md
        §4 per-source "Authority" / "Portal" / "Live status" lines, each with
        the observed HTTP status and byte count. §8 — the five verification
        results that overturned prior assumptions, with evidence.

    portal_fingerprints.md
        §4.1 (Fidlar: Angular SPA, IIS/ASP.NET, bundle names and sizes),
        §4.3 (Tyler Odyssey: ASP.NET MVC 5.2, Knockout, server volt-adc),
        §4.4 Path B (Accela: ASP.NET WebForms, __VIEWSTATE postback),
        §4.5 (ArcGIS REST: maxRecordCount, supportsPagination),
        §5.1 (indy.gov: client-rendered Phoenix SPA),
        §6.2 (Indiana Gateway: ASP.NET WebForms, full form field list).

    access_classification.md
        §4 per-source "Access class" lines using the §01.9 enum, each with the
        observed evidence required by §01.9. §2 — the consolidated verdict
        table. §4.3 — the CAPTCHA enforcement test (§01.29) with the live
        request and response recorded.

    source_role_classification.md
        §2 — ROLE column (PRIMARY / SUPPORTING / ENRICHMENT) with priority
        tier per source. §6.1 — tax roll classified ENRICHMENT per §13.
        Machine-readable form in `config/counties/marion_in.json` → `sources[]`
        → `source_role`.

    document_type_discovery.md
        §3.2 — full 29-type lead sweep mapped to local vocabulary.
        §3.1 — court case-type taxonomy with observed frequencies.
        §4.4 — the 29 code enforcement CASE_TYPE values, distress vs noise.
        §4.3 — MyCase Categories enum (CR/CV/FAM/PR) and probate type counts.
        GAP: recorder document-type taxonomy NOT captured — see §9.

    build_eligibility_handoff.md
        §0 — verdict and P0 gate result. §2 — source priority order and counts.
        §7 — freshness table (§01.32). §9 — blocker and uncertainty register.
        §10 — recommended operator next actions and required decisions.

    recon_summary.md
        §0 — executive verdict, the operator-facing summary.

### v5.3.0 Source-of-Record Matrix companions (§01.20)

    source_of_record_matrix.md / .json
        §3.2 — lead type to source-of-record mapping with access pattern and
        buildability per type. §2 — rank, role, priority, verdict per source.

    source_coverage_map.md
        §3.2 coverage summary (15 live / 9 blocked / 3 N/A / 2 uncertain) and
        the §4.5 excluded-cities coverage caveat.

    api_discovery_report.md
        §4.1 — the 12 API paths checked on the recorder host, all 404, with the
        explicit "documented API found: NO" answer required by §01.23.
        §4.3 — the MyCase endpoints discovered. §6.3 — tax/delinquency search
        paths checked.

    build_eligibility_report.md
        §0, §2, §10 — same content as build_eligibility_handoff.md above.

    operator_verified_sources.yml
        GAP — not produced. No operator-surfaced source links were supplied
        during this recon, so there is nothing to record. This entry exists to
        state that explicitly rather than leave the artifact unaccounted for.

    fingerprints/<source_id>.fingerprint.json
        GAP — still no per-source JSON fingerprint files. The fingerprint
        CONTENT is now considerably richer after the browser pass (endpoints,
        payloads, control state, capability matrices — §4.1, §4.4, §6.2) but
        remains in prose. Generating the machine-readable files is a Phase 1
        adapter-selection task.

### §01.22 sample documents (added 2026-08-05)

Raw samples are immutable and stored under `runs/marion_in/recon/samples/`:

    fidlar/     01_rendered.html, 01_controls.json, 01_network.json,
                01_landing.png, 02_document_types.json (50 types),
                02_settings.json (capability matrix),
                05_search_request.json, 05_search_response.json (90 records),
                06_results_rendered.png, 06_results_text.txt
    taxsale/    2025_status_list.pdf (54 pp), 2025_sold_list.pdf,
                2025_county_lien_list.pdf (= Surplus Details)
    gateway/    search_state-parcel-dashed.txt/.png,
                search_local-parcel.txt/.png (negative control),
                04_parcel_detail.txt/.png
    accela/     01_home_text.txt, 03_enforcement_search.txt/.png
    mycase/     sample_civil_2026-06-02.json (287 cases incl. MF)
    mapindy/    sample_parcel.json, sample_layer11.json, sample_layer27.json
    indygov/    sheriff_text.txt/_links.json, taxsale_text.txt/_links.json,
                treasurer_*, taxhistory_* (+ screenshots)

**These sample files are NOT committed.** They are raw source records carrying
real owner names, situs addresses and party names — the same class as
`data/raw/`. Framework v5.6.1 gitignores `runs/*/recon/samples/` and exempts it
from the PII guard for exactly this reason: §01.22 requires recon to FETCH and
INSPECT real documents, and equally requires it not to publish them. The files
live on the recon operator's disk; this report carries the findings, the field
lists and the structural evidence, with individual person names redacted and
entity names retained.

Every GREEN source's claimed fields were re-verified against its real sample.
One discrepancy found and recorded: the parcel layer reports
ASSESSORYEAR_TOTALAV 212,100 for parcel 49-06-05-112-029.000-600 while Gateway
reports Total Gross Assessed Value 211,000 for pay year 2025. These are
different vintages (assessor current vs billed year), not an error — but a
build must not treat the two as interchangeable.

### Outstanding protocol obligations

Recorded here so the index never reads as full compliance when it is not:

    §01.22 sample-document inspection — DISCHARGED 2026-08-05 for all GREEN
           sources (list above). Not performed for GovEase sheriff sale list
           (§5.1) or PACER (paid).
    §01.12 recorder document-type taxonomy — CAPTURED 2026-08-05 (§4.1).
    Remaining open items are enumerated in §9 and §12.

### Deviations from §01.17

Both directed by the build request, recorded for the audit trail:

    - §01.17 forbids committing or pushing during recon. This report is
      committed and pushed as instructed.
    - §01.17 forbids writing outside `runs/<county_slug>/recon/`. This report
      is at `recon/marion-in-recon.md`. Sample documents from the browser pass
      ARE inside `runs/marion_in/recon/samples/`, per §01.22.

---

## 12. Headless-browser pass — change log (2026-08-05)

Everything below was established by driving a real browser. Each entry replaced
an inference or an untested assumption.

### Verdict changes

    Marion County Recorder    RED    -> GREEN   §4.1
    Tax sale lists            YELLOW -> GREEN   §4.2  (and promoted rank 7 -> 3)
    Accela code enforcement   YELLOW -> GREEN   §4.4
    Indiana Gateway           YELLOW -> GREEN   §6.2
    Sheriff sale list         YELLOW -> YELLOW  §5.1  (URL found, portal not driven)

No source moved down. Nothing previously GREEN was contradicted.

### Newly unblocked lead types

    Mechanic Lien         recorder code 24
    Construction Lien     recorder code 24 (same code)
    Federal Tax Lien      recorder code 21
    Surplus               tax sale Surplus Details PDF

    LIVE lead types: 15 -> 19 of 29.

    NOT delivered, contrary to the earlier claim that one unblock would recover
    nine: Lis Pendens, Abstract of Judgment, State Tax Lien, Affidavit of
    Heirship, Executor Deed, Administrator Deed. The recorder is reachable; its
    doc-type vocabulary simply has no codes for these. See §3.2.

### The §01.29 enforcement test, in full

    Recorder  CONTROL PRESENT and ENFORCED — /breeze/Search returns 401 with no
              headers, 200 through a browser. Tier PER_REQUEST_CHALLENGE, but
              reCAPTCHA v3 invisible: no human step, no operator handoff. Costs
              a browser-context adapter, blocks nothing. No CAPTCHA was solved.
    Accela    NO control enforced — 0 captcha nodes, no grecaptcha, no password
              field, public search without login.
    Gateway   NO control — plain ASP.NET WebForms postback.
    MyCase    (prior pass) control present, NOT enforced.

### Corrections to this report's own earlier pass

    1. "The Angular bundle yields no extractable API base." Wrong — the base is
       in appConfig.json, fetched at runtime. Check a SPA's runtime config
       before declaring an API undiscoverable.
    2. "Tax sale reports exist for 2010-2017 only." True of data.indy.gov,
       false of the county — indy.gov publishes 2018-2025 on its Hygraph CDN.
    3. "Code enforcement carries no parcel id." True of the frozen open-data
       extract, false of live Accela, which has a parcel-number search field.
    4. "One recorder unblock recovers nine lead types." It recovered three.

### New findings with build impact

    - Deterministic recorder -> parcel join via legal description
      (subdivision + lot -> SUBDIVISION_TAG + LOTNUM), proven to a single
      parcel. 33% coverage ceiling. §1.5.
    - Tax sale lists arrive pre-keyed on the local parcel number — the only
      distress source needing no crosswalk at all. §4.2.
    - Recorder data is 5 days stale BY DESIGN; cursors must lag. §7.
    - Gateway exposes homestead AV, giving a free absentee-owner signal, and
      2007-2026 tax history. §6.2.
    - Gateway's parcel detail page leaks a SQL error and renders Total Credits
      blank. Build defensively. §6.2.
    - Recorder party search is EXACT MATCH only — no wildcards. §4.1.

### Still open after this pass

    Accela Reports module (likely bulk path) not exercised; GovEase sheriff
    list not driven; Gateway export unproven; Auditor not probed; Public Notice
    still uncertain; per-source fingerprint JSON files not written.
