# Vendor Portal Library — Baseline (v5.1.0-beta+)

**Universal reference. No county-specific examples.**

Common county portal vendor families that Phase 0 should recognize. When a source URL matches one of these patterns, the framework pre-populates `portal_family`, `recommended_adapter`, and `known_blockers` on the source proof packet.

This is a baseline catalog. Each entry lists generic identification patterns, NOT specific counties or live URLs.

---

## Tyler Technologies

- **Identify by:** `.tylertech.cloud`, `.tylerhost.net`, `tylerhost.com`, often subdomain patterns like `recorder.<county>.tylerhost.net`
- **Typical source types:** clerk recordings, court dockets, tax collector, code enforcement
- **Common URL patterns:** `/search`, `/Doc/Search`, `/Tyler/Recordings`
- **Common access method:** `SEARCHABLE_PUBLIC_PORTAL` or `LOGIN_REQUIRED` depending on county contract
- **Common blockers:** Login wall for document images; CAPTCHA on heavy queries
- **Document images:** Often locked behind login or paid per-document download
- **Login common:** Yes — many Tyler deployments require free account for advanced search
- **Paid access common:** Document images often per-fee
- **Possible adapter families:** `tyler_eagle_recordings`, `tyler_odyssey_court`, `tyler_munis_tax`
- **Notes:** Tyler products vary widely. Always check the specific product (Eagle vs Odyssey vs Munis) before assuming behavior.

## Landmark Web

- **Identify by:** `landmarkweb.com`, `landmarkweb.net`, often as iframe within county clerk pages
- **Typical source types:** clerk recordings, land records, official records
- **Common URL patterns:** `/web/search`, `/cgi-bin/landmark`
- **Common access method:** `SEARCHABLE_PUBLIC_PORTAL` typically; document images often free
- **Common blockers:** Older sessions expire fast; pagination can be tricky
- **Document images:** Often public, sometimes require captcha
- **Login common:** Rarely
- **Paid access common:** Rarely
- **Possible adapter families:** `landmark_web_recordings`
- **Notes:** Older vendor; HTML scraping is often the cleanest path. Watch for session state.

## Aumentum Technologies (Thomson Reuters)

- **Identify by:** `aumentumtech.com`, `aumentum.tech`, often white-labeled with county branding
- **Typical source types:** tax collector, tax assessor, parcel master, tax delinquency
- **Common URL patterns:** `/Aumentum`, `/tax`, `/Property`
- **Common access method:** Often `OPEN_PUBLIC_PORTAL` or `SEARCHABLE_PUBLIC_PORTAL`
- **Common blockers:** Pagination quirks; some counties WAF-protect heavy queries
- **Document images:** Tax bills typically public PDF
- **Login common:** Rarely
- **Paid access common:** Sometimes for bulk download
- **Possible adapter families:** `aumentum_tax`, `aumentum_assessor`
- **Notes:** Strong on tax data; weaker on clerk-style recordings.

## GovOS (formerly SimpliCity)

- **Identify by:** `govos.com`, `simplicityweb.com`, `municipalonlinepayments.com`
- **Typical source types:** clerk recordings, vital records, code enforcement payments
- **Common URL patterns:** `/search`, `/clerk`, `/permits`
- **Common access method:** Often `LOGIN_REQUIRED` or `FREE_ACCOUNT_REQUIRED`
- **Common blockers:** Account creation requirement; payment walls for document images
- **Document images:** Often paid per-document
- **Login common:** Yes
- **Paid access common:** Yes — document fees standard
- **Possible adapter families:** `govos_recordings`, `govos_permits`
- **Notes:** Operator credentials typically required. Cost gating applies.

## Kofile (Cott Systems)

- **Identify by:** `cottsystems.com`, `kofile.com`, often as `<county>.kofile.us`
- **Typical source types:** clerk recordings, land records
- **Common URL patterns:** `/RecordSearch`, `/cms`, `/kofile`
- **Common access method:** Varies — some `SEARCHABLE_PUBLIC_PORTAL`, others `LOGIN_REQUIRED`
- **Common blockers:** Subscription tiers gate full document access
- **Document images:** Often paid for non-subscribers
- **Login common:** Common for subscriber access
- **Paid access common:** Yes — subscription model common
- **Possible adapter families:** `kofile_recordings`
- **Notes:** Free-tier search often available; paid tier unlocks bulk.

## CountyFusion (US Imaging)

- **Identify by:** `countyfusion.com`, `usimaging.com`
- **Typical source types:** clerk recordings, land records
- **Common URL patterns:** `/countyweb`, `/recorder`
- **Common access method:** Often `SEARCHABLE_PUBLIC_PORTAL`
- **Common blockers:** Session timeouts; image viewer requires specific browser flags
- **Document images:** Usually public for older records; sometimes paid for recent
- **Login common:** Rarely for search; sometimes for downloads
- **Paid access common:** Sometimes
- **Possible adapter families:** `countyfusion_recordings`
- **Notes:** Image viewer is often a Flash legacy port or proprietary; Playwright usually required for document image extraction.

## Fidlar Technologies

- **Identify by:** `fidlar.com`, `landshark.com`, `idoc.com`
- **Typical source types:** clerk recordings, land records
- **Common URL patterns:** `/LandShark`, `/IDOC`, `/Fidlar`
- **Common access method:** Often `LOGIN_REQUIRED` for advanced access
- **Common blockers:** Account creation; subscription gates
- **Document images:** Often paid
- **Login common:** Yes
- **Paid access common:** Yes — LandShark Pro is paid tier
- **Possible adapter families:** `fidlar_landshark_recordings`
- **Notes:** Free tier often exists with limited results count.

## CivilView (Vision Government Solutions / Patriot)

- **Identify by:** `civilview.com`, `patriotproperties.com`, `vgsi.com`
- **Typical source types:** parcel master, assessor data, property record cards
- **Common URL patterns:** `/Property`, `/AssessmentList`, `/index.aspx?Page=PropertySearch`
- **Common access method:** Usually `OPEN_PUBLIC_PORTAL`
- **Common blockers:** None typical — assessor data is public
- **Document images:** Property record cards often public PDF
- **Login common:** No
- **Paid access common:** No
- **Possible adapter families:** `civilview_assessor`, `patriot_assessor`, `vgsi_assessor`
- **Notes:** Enrichment-only source. `source_role: ENRICHMENT_SOURCE`.

## RealAuction

- **Identify by:** `realauction.com`, `<county>.realtaxdeed.com`, `<county>.realforeclose.com`
- **Typical source types:** tax sale, tax deed auctions, foreclosure sales
- **Common URL patterns:** `/index.cfm`, `/Auctions`
- **Common access method:** Often `SEARCHABLE_PUBLIC_PORTAL` with registration for bidding
- **Common blockers:** Bidder registration required to access full lot details; results sometimes locked
- **Document images:** Auction notices often public
- **Login common:** Required for bidding; not for browsing in most cases
- **Paid access common:** Bidder deposit required
- **Possible adapter families:** `realauction_tax_deed`, `realauction_foreclosure`
- **Notes:** Strong primary lead source for foreclosure / tax deed / tax sale in counties where the auctioneer is contracted with RealAuction. Auction calendars often publicly viewable.

## ArcGIS / Esri

- **Identify by:** `arcgis.com`, county GIS subdomains using ArcGIS REST `/FeatureServer/`, `/MapServer/`
- **Typical source types:** parcel master, GIS parcels, zoning, code enforcement (sometimes)
- **Common URL patterns:** `/FeatureServer/0/query`, `/MapServer/0/query`
- **Common access method:** `API_ENDPOINT` — usually `OPEN_PUBLIC_PORTAL`
- **Common blockers:** Rate limits; some counties WAF the REST endpoint
- **Document images:** N/A for GIS
- **Login common:** No
- **Paid access common:** No
- **Possible adapter families:** `arcgis_parcel_query`, `arcgis_feature_server`
- **Notes:** Enrichment unless the GIS layer happens to expose code violations / liens / demolition orders. Always check what layers the county publishes.

## Accela (Tyler subsidiary)

- **Identify by:** `accela.com`, `aca.accela.com`, `permits.<city>.gov` (white-labeled)
- **Typical source types:** code enforcement, permits, business licenses, building inspections
- **Common URL patterns:** `/CitizenAccess`, `/Cap/CapHome.aspx`
- **Common access method:** Often `SEARCHABLE_PUBLIC_PORTAL`
- **Common blockers:** Pagination; sometimes JS-heavy
- **Document images:** Permit PDFs sometimes public, sometimes login-walled
- **Login common:** For applicants only; public search usually open
- **Paid access common:** No for search; yes for permit downloads in some cities
- **Possible adapter families:** `accela_citizen_access`, `accela_permits`
- **Notes:** Code enforcement events are PRIMARY_LEAD_SOURCE when the violation/lien/demolition signal is present. Otherwise REFERENCE_ONLY.

## EnerGov (Tyler subsidiary)

- **Identify by:** `energov.com`, `energov.tylerhost.net`
- **Typical source types:** permits, code enforcement, business licensing
- **Common URL patterns:** `/EnerGov_Prod`, `/CSS/`
- **Common access method:** Often `SEARCHABLE_PUBLIC_PORTAL`
- **Common blockers:** Heavy JS rendering; pagination
- **Document images:** Often public for permits
- **Login common:** Applicant-only
- **Paid access common:** No
- **Possible adapter families:** `energov_permits`, `energov_code_enforcement`
- **Notes:** Similar to Accela. Treat code enforcement events as PRIMARY_LEAD_SOURCE when distress signals are exposed.

---

## How Phase 0 uses this library

When a candidate URL is being verified (Section 4.7 Layer 1), Phase 0 checks the URL pattern against this library. On a match:

1. Set `portal_family` to the matching vendor name
2. Pre-populate `recommended_adapter` from the family's adapter list
3. Pre-populate `known_blockers` array from the family's common blockers
4. Note login/paid access expectations in `verification_note`

This does NOT skip verification — Layers 2-5 still run. But the library accelerates the work and produces consistent classifications across counties.

## v5.2.0 backlog

The vendor portal library will grow with each county build. v5.2.0 adds:

- `seen_in_counties_count` — how many county builds have encountered this family (without naming the counties)
- `fingerprint_signatures` — specific DOM/header patterns to confirm a family match
- `adapter_test_fixtures` — sample HTML/JSON fixtures per family for adapter testing

The current library is a starting baseline. Phase 0 should record observations in the source proof packet's `fingerprint_summary` for later incorporation into the library.
