# County Config Schema

Every county build starts with a config file at `config/counties/<county>.json`. This file is the **only** input that varies between counties — the rest of the framework is county-agnostic.

The config maps the framework's universal source classifications (clerk / court / sheriff / tax / code / parcel master) to the specific URLs, access patterns, and field mappings for the target county. Phase 0 recon populates this file before any scraper is built.

---

## Schema reference

The full schema lives in `_schema.json` (JSON Schema draft 2020-12). What follows is the human-readable explanation.

### Top-level structure

```json
{
  "county_id": "<short identifier, used in URLs and file names>",
  "county_name": "<full name>",
  "state": "<two-letter state code>",
  "subject_state_full": "<full state name>",
  "fips_code": "<5-digit county FIPS>",
  "timezone": "<IANA tz name>",
  "operator_market_priority": "<primary | secondary | exploratory>",
  
  "geography": { ... },
  "sources": { ... },
  "scoring_overrides": { ... },
  "storage": { ... },
  "dashboard": { ... },
  "deployment": { ... }
}
```

### `geography`

Describes how the county is structured for parcel matching and dashboard filters.

```json
{
  "geography": {
    "municipalities": [
      {"name": "<Municipality Name>", "code": "<MC>", "fips_place": "12345"},
      ...
    ],
    "parcel_id_format": "<regex pattern>",
    "parcel_id_normalization": "<rule, e.g. 'strip-dashes' | 'pad-to-13-digits'>",
    "address_format_notes": "Some counties use 'Block-Lot-Qualifier' instead of street address as primary identifier"
  }
}
```

`municipalities` drives the dashboard's municipality filter. It also drives recon — each municipality has its own code enforcement system in many states.

### `sources`

The heart of the config. One entry per source the framework will pull from.

Each source has this shape:

```json
{
  "<source_id>": {
    "category": "lead | enrichment",
    "subtype": "<see allowed subtypes below>",
    "url": "<base URL>",
    "access_pattern": "open_api | static_html | spa_with_api | spa_recaptcha | waf_imperva | paywall | saml | sealed | public_records_only",
    "source_reliability_grade": "A | B | C | D | E",
    "source_priority": "P0 | P1 | P2",
    "build_priority": "mvp_required | high_value | enrichment | optional | future",
    "auth_required": false,
    "rate_limit_rpm": null,
    "scraper_module": "scrapers/<filename>.py",
    "fields": { ... },
    "doc_type_synonyms": { ... },
    "refresh_cadence": "daily | weekly | monthly | on_demand",
    "ttl_days": 180,
    "blocked_unblock_paths": ["public_records_request", "seeded_session", "captcha_solver", "manual_pull"],
    "last_verified_at": "<ISO 8601 timestamp>",
    "known_limitations": [],
    "notes": "free-form recon notes"
  }
}
```

**`source_reliability_grade` values** (per `architecture/08_evidence_ledger.md` "Source reliability grading"):
- `A` — official source of truth (clerk, court, sheriff, tax collector direct)
- `B` — official but delayed (records-request bulk, monthly extracts)
- `C` — vendor mirror of official source (third-party portal republishing official data)
- `D` — scraped public display only (aggregator search results)
- `E` — enrichment only, never proof (USPS, utility, geocoder)

**`official_status` values** (set during Phase 0 recon — describes what kind of entity owns the source URL):
- `OFFICIAL_COUNTY` — the source is the target county's own government website (e.g. `*.<county>.gov`, `<county>clerk.org`, county-owned record portal)
- `OFFICIAL_STATE` — the source is the state government's website, exposing data for this county (e.g. state-level court system, state recorder, state tax authority)
- `OFFICIAL_CITY` — the source is a municipality within the county (e.g. city code-enforcement portal, city permit office)
- `OFFICIAL_COURT` — the source is the court of jurisdiction's own portal (e.g. federal bankruptcy court, state-administered court system)
- `OFFICIAL_VENDOR_PORTAL` — the source is a vendor-hosted portal (Tyler iDocket, CivicPlus, GovOS, Catalis, etc.) that the official county / state / municipal / court website links to or designates as its records portal
- `UNVERIFIED` — the source appears to exist but recon could not confirm its official status by following an official navigation path. Cannot be built against unless `operator_override: true`.
- `NOT_FOUND` — the category does not exist for this county, OR Phase 0 recon could not locate a URL. Cannot be built against unless `operator_override: true`.

**`lead_value` values** (describes what role this source plays in the lead pipeline):
- `LEAD_GENERATING` — produces discrete dated events that fire patterns (clerk recordings, court filings, sheriff calendars, code violations, tax delinquency)
- `ENRICHMENT` — produces parcel/owner state metadata that attaches to leads but does not fire patterns (parcel master, GIS, USPS)
- `REFERENCE_ONLY` — useful for human verification or context but never feeds the pipeline (e.g. official county homepage used as the anchor for discovering other sources)
- `UNKNOWN` — recon could not classify. Treated like `UNVERIFIED` for build purposes.

**`operator_override`** (boolean, default `false`). When `official_status` is `UNVERIFIED` or `NOT_FOUND`, no later phase may build against this source unless `operator_override: true`. The schema enforces this — validation fails if `official_status` is `UNVERIFIED` or `NOT_FOUND` and `operator_override` is not `true`. Used when the operator has out-of-band knowledge (e.g. "this URL is correct even though I couldn't link to it from the official site") and explicitly accepts the risk.

**`verification_note`** (string, free-form). Captured during Phase 0 recon. What was observed: "Followed official county clerk site → records-search link → vendor portal. Vendor is Tyler iDocket. Confirmed records returned for sample search." This is the audit trail for `official_status`.

**`open_questions`** (array of strings, free-form). Questions the operator must resolve before this source can be built. "Does the county expose foreclosure cases on the public docket, or only in the attorney portal?" or "Is the daily refresh cron available, or do they batch overnight?" Phase 0 produces these; the operator answers them before Phase 1 begins.

**`source_priority` values** (per `domain/02_signals_and_sources.md` "Source priority tiers"):
- `P0` — daily-refresh distress source (required for shippable build)
- `P1` — weekly-refresh distress source (acceptable supplement)
- `P2` — enrichment source (supporting only)

**`build_priority` values** (when this source should be built in implementation sequence):
- `mvp_required` — must run for minimum viable lead pipeline; build first
- `high_value` — high-value lead source; build after mvp_required is proven
- `enrichment` — supports leads but is not itself a lead source; build after at least one lead source is live
- `optional` — nice-to-have; build only if time allows
- `future` — planned but not in current scope; document and skip

`source_priority` and `build_priority` are independent. `source_priority` measures *what the source is* (cadence + distress-vs-enrichment). `build_priority` measures *when to build it* (implementation sequence). A P0 source can be `mvp_required` (build first because it's the distress feed) or `high_value` (build second because something else is the MVP). A P2 enrichment source is usually `enrichment` build priority but can be `mvp_required` if joins require it.

**`last_verified_at`** is set by Phase 0 recon and updated on every re-recon (`--rerun-recon` flag). It is the timestamp when the source was last confirmed reachable AND the reliability grade was last evaluated.

**`known_limitations`** is a free-form array of strings documenting what the source cannot do or what's blocked (e.g., `"owner names redacted in public layer"`, `"only last 7 days searchable"`, `"PDFs are scanned without OCR layer"`).

**Allowed `subtype` values:**

For `category: "lead"`:
- `clerk_recordings` — county clerk recorded instruments
- `court_civil` — civil court foreclosure / judgment dockets
- `court_probate` — probate / surrogate court
- `court_family` — family court (divorce)
- `court_eviction` — special civil / justice / magistrate
- `sheriff_sales` — sheriff sale listings
- `tax_delinquency` — tax collector / treasurer delinquency rolls
- `tax_certificates` — tax sale certificate sales
- `code_enforcement` — municipal code violation rolls

For `category: "enrichment"`:
- `parcel_master` — tax assessor / appraisal district / equivalent statewide or county-level parcel layer
- `gis_parcels` — GIS parcel layer
- `usps_vacancy` — USPS vacancy data
- `utility_shutoff` — water/electric/gas service interruption

**`access_pattern` values map to engineering KB strategies:**

- `open_api` → `engineering/00_tooling_decision_tree.md` Question 1, Path A
- `static_html` → Path C
- `spa_with_api` → Path D + D1 (replay API)
- `spa_recaptcha` → Path E (public-records request / seeded session / CAPTCHA solver)
- `waf_imperva` → Path F (public-records request / manual pull / residential proxy)
- `paywall` → `engineering/04_blocked_source_strategies.md` (paywall section)
- `saml` → blocked, public-records request fallback
- `sealed` → blocked, indirect signals only
- `public_records_only` → no website access, public-records request only

**`fields` block:** maps the framework's canonical field names to the source's actual field names.

```json
{
  "fields": {
    "parcel_id": "PARCEL_NUM",
    "owner_name": "OWNER",
    "owner_mailing_addr1": "MAILING_ADDR_1",
    "owner_mailing_city": "MAILING_CITY",
    "owner_mailing_state": "MAILING_STATE",
    "owner_mailing_zip": "MAILING_ZIP",
    "situs_address": "SITUS_ADDR",
    "situs_city": "SITUS_CITY",
    "situs_zip": "SITUS_ZIP",
    "year_built": "YR_BUILT",
    "assessed_value": "ASSD_VAL",
    "land_value": "LAND_VAL",
    "improvement_value": "IMPRVT_VAL",
    "last_sale_date": "LAST_SALE_DT",
    "last_sale_price": "LAST_SALE_PRC",
    "deed_book": "DEED_BOOK",
    "deed_page": "DEED_PAGE",
    "property_class": "PROP_CLASS",
    "land_use_code": "LU_CODE",
    "acreage": "ACRES"
  }
}
```

This is what `scrapers/parcel_master.py` reads to build the universal record format. Every county will have different source field names; the canonical names stay constant.

**`doc_type_synonyms` block:** maps county-specific raw labels to canonical document types from `knowledge_base/domain/canonical_doc_types.json`. The county synonym map is checked FIRST during normalization (`domain/08_document_normalization.md`); the universal registry is the fallback. This lets a county override a universal-default interpretation when local recorder practice differs.

The block accepts two formats interchangeably. Both can appear in the same map.

**Simple form** (one-line mapping, confidence implied 90):

```json
{
  "doc_type_synonyms": {
    "DEEDQ": "QUITCLAIM_DEED",
    "DEEDS": "SHERIFF_DEED",
    "DEEDE": "EXECUTORS_DEED",
    "DEEDA": "ADMINISTRATORS_DEED",
    "MTGE": "MORTGAGE",
    "LISPEN": "LIS_PENDENS",
    "NTCSALE": "NOTICE_OF_SALE",
    "FINJUDGE": "FINAL_JUDGMENT_OF_FORECLOSURE",
    "FEDLIEN": "FEDERAL_TAX_LIEN",
    "INSTLIEN": "STATE_TAX_LIEN",
    "TSC": "TAX_SALE_CERTIFICATE",
    "MECHLIEN": "MECHANICS_LIEN",
    "DSJUDLIEN": "VACATED_JUDGMENT",
    "TAXWAIVE": "INHERITANCE_TAX_WAIVER",
    "DISCLAIM": "DISCLAIMER_OF_INTEREST",
    "TRUSTAGR": "TRUST_AGREEMENT"
  }
}
```

**Richer object form** (use when confidence is below 90 or notes are needed):

```json
{
  "doc_type_synonyms": {
    "DOC TYPE 217": {
      "raw_code": "DOC TYPE 217",
      "normalized_doc_type": "MECHANICS_LIEN",
      "confidence": 88,
      "notes": "County-specific numeric document code observed during Phase 0 recon"
    },
    "LP-EM": {
      "raw_code": "LP-EM",
      "normalized_doc_type": "LIS_PENDENS",
      "confidence": 85,
      "notes": "Local recorder uses LP-EM for emergency lis pendens; universal registry treats as LIS_PENDENS"
    }
  }
}
```

The pipeline accepts either shape per-entry. A flat string value implies confidence 90 and no notes. The object form lets a county override defaults.

**The values must match canonical type keys in `canonical_doc_types.json`.** Free-text values like `"deed"` or `"Quitclaim Deed"` will not normalize correctly. Use the canonical key (`QUITCLAIM_DEED`, all caps with underscores).

**This block is the recon output.** Phase 0 recon's primary deliverable is filling out this synonym map for any county-specific shorthand the universal registry does not already cover. Industry-common abbreviations (`AOH`, `LIS PEND`, `NOD`, `MTG`, etc.) are already in the universal registry — only add to county synonyms when the county uses something the universal layer wouldn't recognize.

### `scoring_overrides`

When a county's data quality differs from the framework defaults, scoring weights can be adjusted here.

```json
{
  "scoring_overrides": {
    "match_confidence_floor": 80,
    "review_queue_ratio_alert_threshold": 0.50,
    "high_equity_assessed_to_sale_ratio": 2.0,
    "long_term_owned_years": 15,
    "senior_owner_proxy_years": 25,
    "favorable_loan_era_start": "2020-01-01",
    "favorable_loan_era_end": "2022-06-30"
  }
}
```

Default values from `domain/03_scoring_and_stacking.md` apply unless overridden here.

### `storage`

Tells the framework which storage backend to use.

```json
{
  "storage": {
    "mode": "STATIC_JSON_MODE",
    "supabase_enabled": false,
    "dashboard_payload": "data/leads.json",
    "retain_raw_records_days": 30,
    "retain_source_runs_days": 365
  }
}
```

`mode` must be one of `STATIC_JSON_MODE`, `SUPABASE_MODE`, `HYBRID_MODE`. See `architecture/11_database_and_storage.md` for the full mode contract. Default for new counties is `STATIC_JSON_MODE`.

### `dashboard`

Per-county dashboard customization.

```json
{
  "dashboard": {
    "title": "<County Name> Lead Intelligence",
    "subtitle": "Daily-refreshed real estate distress signals",
    "primary_color": "#0F172A",
    "accent_color": "#3B82F6",
    "default_view": "all_leads",
    "precanned_views": [
      {"id": "sheriff_calls", "label": "Sheriff sales — call list", "filter": "pattern:foreclosure AND subtype:'Sheriff Sale'"},
      {"id": "estate_absentee", "label": "Estate + absentee", "filter": "pattern:estate AND attribute:absentee"},
      {"id": "tax_longterm", "label": "Tax delinquent + 15+ yrs", "filter": "pattern:tax AND attribute:long_term_owned"}
    ]
  }
}
```

`precanned_views` are the operator's curated lists for the client. Each county can have a different set based on which deal types the client market favors.

### `deployment`

```json
{
  "deployment": {
    "github_org": "xcerebroai",
    "github_repo": "<county>-intel",
    "live_url": "https://xcerebroai.github.io/<county>-intel/",
    "scheduled_task_name": "<county>-intel-refresh",
    "watchdog_task_name": "<county>-intel-watchdog"
  }
}
```

---

## Schema validation

The config is validated against `_schema.json` at the start of every build. Invalid configs halt the build with `BUILD_BROKEN.md` listing schema violations.

```python
import jsonschema, json
from pathlib import Path

schema = json.loads(Path("config/counties/_schema.json").read_text())
config = json.loads(Path(f"config/counties/{county_id}.json").read_text())
jsonschema.validate(config, schema)
```

---

## What's NOT in the config

- Scraper logic (lives in `scrapers/<source>.py`)
- Scoring formulas (live in `domain/03_scoring_and_stacking.md` — universal across counties)
- Deal-path classifier rules (live in `domain/04_deal_path_classifier.md` — universal)
- Branding (lives in `index.html` and the framework's CSS — branded once per build)

Keep the config focused on **what varies between counties**: URLs, field names, doc-type synonyms, blocked-source paths. Everything else stays universal.

---

## Sample template

One template ships with the framework:
- `_template.json` — empty schema-shaped skeleton for new counties

**Template validation behavior:** `config/counties/_template.json` is intentionally not valid as a live county config until placeholders are filled. The template is a starting point. A copied real county config must validate against `_schema.json` before Phase 0 can pass.

**Why this matters:** Required fields like `state` and `fips_code` are empty strings in the template, which fails schema validation. This is by design — the schema enforces population correctness at build time, so a forgotten field produces a loud error rather than a silent skip. The first county built on this framework should copy `_template.json` to `config/counties/<county_id>.json` and populate every field during Phase 0 recon. Validation passes only once the populated config is complete.

---

## v5.0.0 — Source Verification Gate, Source Proof Packet, and Build Eligibility Gate

v5.0.0 introduces a trust layer on top of v4.1.0's autonomous first-run flow. The schema gains 26 new source-level fields and 3 new top-level fields, plus 7 new enum types. These fields are populated by Phase 0 recon and consumed by the Build Eligibility Gate.

### New top-level fields

| Field | Type | Purpose |
|---|---|---|
| `build_verdict` | enum string | Phase 0 / Phase 0.5 verdict on whether the county is ready to build. One of: `READY_TO_BUILD`, `READY_WITH_BLOCKERS`, `RECON_ONLY`, `WAITING_ON_ACCESS`, `NOT_BUILDABLE_YET`, `AUTO_RESOLVED_READY_TO_BUILD`, `PARTIALLY_RESOLVED_BUILDABLE`, `AUTO_RESOLVE_FAILED`, or `""` (empty during recon). |
| `build_verdict_reason` | string | Plain-English explanation of the verdict. Required when `build_verdict` is set. |
| `build_verdict_at` | string | ISO 8601 timestamp of when Phase 0 produced the verdict. |

### New source-level fields (the proof packet)

Every source block in `sources.<source_id>` gains these fields. Phase 0 populates them during recon. The Build Eligibility Gate reads them to produce the verdict.

| Field | Type | Purpose |
|---|---|---|
| `verified_from_url` | string | The official government page (or officially-linked vendor index) from which the source URL was discovered. Required for `verification_confidence` HIGH or MEDIUM. |
| `verification_method` | enum string | How verification was performed. See enum below. |
| `official_entity` | string | Name of the official government entity that owns/operates this source (e.g. `"<County Name> Clerk's Office"`). |
| `portal_type` | string | Free-text describing what the portal actually is (e.g. `"land records search"`, `"tax delinquency lookup"`). |
| `records_available` | array of string | Record types this source actually exposes (e.g. `["deeds", "mortgages", "liens", "lis_pendens"]`). |
| `search_fields` | array of string | Search fields the portal exposes (e.g. `["name", "parcel_id", "date_range", "document_type"]`). |
| `access_method` | enum string | How records are accessed. 17 values — see enum below. |
| `public_access_status` | enum string | Whether the general public can use this source. 12 values — see enum below. |
| `document_access_status` | enum string | Whether the general public can view document images. 7 values — see enum below. |
| `source_role` | enum string | The role this source plays in the lead pipeline. 6 values — see enum below. **Only `PRIMARY_LEAD_SOURCE` can create leads.** |
| `verification_confidence` | enum string | How confident Phase 0 is in this source. 5 values: `HIGH`, `MEDIUM`, `LOW`, `BLOCKED`, `NOT_FOUND`. |
| `verification_note` | string | Free-text explaining the verification outcome and any caveats. |
| `open_questions` | array of string | Free-text questions the operator must answer before this source can ship. |
| `sample_record_path_confirmed` | boolean | True if Phase 0 confirmed the path to records exists. Does NOT mean a record was scraped — just that the search/index/list page was located. |
| `sample_record_type` | string | Type of sample record path confirmed (e.g. `"search_form"`, `"docket_list"`, `"pdf_index"`, `"api_endpoint"`). |
| `sample_search_possible` | boolean | True if a public user can perform a search on this portal without login or payment. |
| `sample_document_view_possible` | boolean | True if a public user can view at least one document image / page result on this portal without additional access requirements. |
| `blocker` | string | Short description of what's blocking access (empty if not blocked). |
| `next_access_strategy` | enum string | The strategy for unblocking access. 15 values — see enum below. |

`official_status` is widened to a 5-way `OFFICIAL_*` split (`OFFICIAL_COUNTY`, `OFFICIAL_STATE`, `OFFICIAL_CITY`, `OFFICIAL_COURT`, `OFFICIAL_VENDOR_PORTAL`) plus `UNVERIFIED` and `NOT_FOUND`. The legacy single value `OFFICIAL` is retained for backward compatibility but new builds should use the granular values.

### New enum types

#### `access_method` (17 values)

`OPEN_PUBLIC_PORTAL`, `SEARCHABLE_PUBLIC_PORTAL`, `DOWNLOADABLE_FILE`, `PDF_PUBLICATION`, `API_ENDPOINT`, `MAP_LAYER`, `PUBLIC_BUT_CAPTCHA_PROTECTED`, `PUBLIC_BUT_WAF_PROTECTED`, `PUBLIC_BUT_SESSION_REQUIRED`, `FREE_ACCOUNT_REQUIRED`, `PAID_SUBSCRIPTION_REQUIRED`, `LOGIN_REQUIRED`, `OPERATOR_CREDENTIAL_REQUIRED`, `REQUEST_ONLY`, `MANUAL_PUBLIC_RECORDS_DELIVERY`, `NOT_SEARCHABLE`, `UNKNOWN`.

#### `public_access_status` (12 values)

`FULL_PUBLIC_ACCESS`, `PUBLIC_SEARCH_ONLY`, `PUBLIC_SEARCH_DOCUMENTS_LOCKED`, `FREE_ACCOUNT_REQUIRED`, `PAID_SUBSCRIPTION_REQUIRED`, `LOGIN_REQUIRED`, `CLERK_APPROVAL_REQUIRED`, `CAPTCHA_PROTECTED`, `WAF_PROTECTED`, `REQUEST_ONLY`, `BLOCKED`, `UNKNOWN`.

#### `document_access_status` (7 values)

`DOCUMENTS_PUBLIC`, `DOCUMENTS_PUBLIC_WITH_CAPTCHA`, `DOCUMENTS_LOGIN_REQUIRED`, `DOCUMENTS_PAID_SUBSCRIPTION_REQUIRED`, `DOCUMENTS_CLERK_APPROVAL_REQUIRED`, `DOCUMENTS_NOT_AVAILABLE`, `DOCUMENTS_UNKNOWN`.

#### `source_role` (6 values)

- `PRIMARY_LEAD_SOURCE` — can create leads (clerk recordings, court dockets, sheriff sales, tax delinquency, code enforcement events, etc.)
- `SUPPORTING_LEAD_SOURCE` — strengthens or confirms leads (case detail pages, document images, sale status)
- `ENRICHMENT_SOURCE` — enriches leads with property metadata (parcel master, GIS, owner data)
- `REFERENCE_ONLY` — informational, cannot create leads
- `BLOCKED_SOURCE` — valuable but inaccessible until next_access_strategy is solved
- `NOT_FOUND` — source category was searched but no portal exists

**Only `PRIMARY_LEAD_SOURCE` creates leads.** Enrichment-only configurations are not buildable.

#### `verification_confidence` (5 values)

`HIGH`, `MEDIUM`, `LOW`, `BLOCKED`, `NOT_FOUND`.

For required P0 primary lead sources: must be `HIGH` or `MEDIUM`, OR `source_role` is `BLOCKED_SOURCE` with a clear `next_access_strategy`, OR `operator_override: true`.

#### `verification_method` (8 values)

`official_domain`, `official_page_link`, `official_vendor_link`, `state_portal`, `court_portal`, `city_portal`, `manual_operator_verified`, `not_verified`.

#### `next_access_strategy` (15 values)

`try_open_public_portal`, `find_official_vendor_link`, `discover_hidden_api`, `use_playwright`, `use_seeded_session`, `use_captcha_solver`, `use_stealth_browser`, `use_residential_proxy`, `use_operator_login`, `request_free_account`, `use_paid_subscription_if_operator_provides`, `manual_operator_assisted_pull`, `standing_records_delivery`, `public_records_request_last_resort`, `not_available`.

`public_records_request_last_resort` is **not** the default. It is only chosen when a real portal exists but remains unsolved after technical access attempts, OR when no portal exists at all and official recurring delivery is the configured access path.

### Build verdict semantics

Phase 0 produces `build_verdict` based on the populated source proof packets:

| Verdict | Meaning |
|---|---|
| `READY_TO_BUILD` | At least one verified `PRIMARY_LEAD_SOURCE` is accessible (verification_confidence HIGH/MEDIUM, sample_search_possible true) AND at least one enrichment source is available. |
| `READY_WITH_BLOCKERS` | At least one primary lead source is verified, but access constraints or missing enrichment still need work. |
| `RECON_ONLY` | Sources identified but not enough is accessible to build yet. |
| `WAITING_ON_ACCESS` | Needed lead source exists but requires login, paid subscription, clerk approval, CAPTCHA solve, seeded session, operator credential, or records delivery. |
| `NOT_BUILDABLE_YET` | No reliable primary lead source was found. |
| `AUTO_RESOLVED_READY_TO_BUILD` | Phase 0.5 auto-resolve cleared the blockers on a primary lead source; the county is now buildable. |
| `PARTIALLY_RESOLVED_BUILDABLE` | Phase 0.5 auto-resolve cleared some but not all blockers; a partial build is possible. |
| `AUTO_RESOLVE_FAILED` | Phase 0.5 auto-resolve was attempted on the blocked primary lead source(s) and did not succeed; operator action is required. |

The five `READY_*` / `RECON_ONLY` / `WAITING_ON_ACCESS` / `NOT_BUILDABLE_YET` values are produced by Phase 0; the three `AUTO_*` / `PARTIALLY_RESOLVED_*` values are produced by Phase 0.5 (Auto-Resolve Blockers, see `MASTER_PROMPT.md §4.14`). All eight, plus `""`, are valid `build_verdict` values; `_schema.json` is authoritative for the enum.

Build Mode (Phase 1+) requires `build_verdict == "READY_TO_BUILD"` OR `build_verdict == "AUTO_RESOLVED_READY_TO_BUILD"` OR operator explicit authorization to proceed with blockers OR operator explicit approval to use a blocked / low-confidence source.

### Backward compatibility

This is a breaking schema change. v4.x county configs do not validate against the v5.0.0 schema until the proof packet fields are populated (the template defaults them to empty strings, empty arrays, or `false`, which the schema accepts during recon). The legacy `official_status: "OFFICIAL"` value is retained, so v4.x configs with the binary value continue to validate.

---

## v5.3.0 — Source of Record Matrix

v5.3.0 adds four top-level recon-output properties and a `$defs` block to the schema. The
properties are the machine-readable form of the Source-of-Record Matrix; the architecture
contract is `knowledge_base/architecture/16_source_of_record_matrix.md`. All four are
optional and nullable — they are `null` until recon populates them, and the universal
`_template.json` ships them as `null` placeholders.

### New top-level fields

| Field | Type | Purpose |
|---|---|---|
| `source_of_record_matrix` | object or null | The Source-of-Record Matrix — maps each canonical lead type to its official source for this county, with per-lead-type status and per-source verification. `$defs/sourceOfRecordMatrix`. |
| `source_coverage_map` | object or null | Summary of recon coverage: live, blocked, limited-coverage, not-found, and operator-review sources/lead types. `$defs/sourceCoverageMap`. |
| `api_discovery` | object or null | Documented-API discovery search log and findings. `$defs/apiDiscoveryReport`. |
| `enrichment_index_strategy` | object or null | Strategy for resolving the enrichment index — bulk versus per-record query. `$defs/enrichmentIndexStrategy`. |

### `status` (per-lead-type, 10 values)

The `status` of each `leadTypeEntry` in `source_of_record_matrix.lead_types[]`:

`LIVE_SOURCE_FOUND`, `LIVE_SOURCE_FOUND_LIMITED_COVERAGE`, `SOURCE_FOUND_BLOCKED`,
`SOURCE_FOUND_NEEDS_LOGIN`, `SOURCE_FOUND_PAID`, `SOURCE_FOUND_CAPTCHA`,
`SOURCE_NOT_FOUND`, `NOT_APPLICABLE_IN_STATE`, `NEEDS_OPERATOR_REVIEW`, `ENRICHMENT_ONLY`.

### `source_role` (candidate source, 5 values — v5.3.0)

The `source_role` of each `candidateSource`. Distinct from the v5.0.0 source-level
`source_role` enum documented above; the v5.3.0 SoR-matrix enum uses the `*_EVENT_SOURCE`
naming:

- `PRIMARY_EVENT_SOURCE` — originates leads (per `§13` Lead Origination Contract).
- `SUPPORTING_EVENT_SOURCE` — adds event detail for leads originated elsewhere.
- `ENRICHMENT_SOURCE` — attaches context to leads but never originates them.
- `REFERENCE_SOURCE` — informational lookup, no event content.
- `BLOCKED_SOURCE` — found but inaccessible.

Only `PRIMARY_EVENT_SOURCE` creates leads.

### `access_status` (9 values)

The `access_status` of each `candidateSource`:

`OPEN_PUBLIC`, `SEARCH_ONLY_PUBLIC`, `FREE_ACCOUNT_REQUIRED`,
`PAID_SUBSCRIPTION_REQUIRED`, `LOGIN_REQUIRED`, `CAPTCHA_PROTECTED`,
`DOCUMENT_IMAGES_LOCKED`, `BLOCKED`, `UNKNOWN`.

### `bulk_availability` (4 values)

The `bulk_availability` of each `candidateSource`:

- `FULL_COUNTY_BULK` — the entire roll is obtainable in bulk.
- `BATCH_QUERY` — partial bulk via date range or filter.
- `PER_RECORD_ONLY` — must be queried record-by-record; coverage is bounded by the
  externally-resolved parcel set. Not a buildability blocker, but a coverage constraint
  recon must surface.
- `UNKNOWN` — not yet classified.

### `api_type` (discovered API, 9 values)

The `api_type` of each `discoveredAPI` in `api_discovery.found[]`:

`REST`, `GraphQL`, `SOAP`, `OData`, `ArcGIS`, `Postman_Collection`, `Swagger_OpenAPI`,
`Other`, `Unknown`.

Migrating a v4.x county to v5.0.0 means running Phase 0 recon again to populate the new proof packet fields.
