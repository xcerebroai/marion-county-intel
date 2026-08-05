# 01. County Recon Protocol (v5.6.0)

The county recon protocol is the deterministic procedure Claude Code follows during
Phase 0 of a county build. It turns a freshly bootstrapped county run folder into a
complete recon dossier and one Build Eligibility Gate verdict.

This is the first document in the `knowledge_base/protocols/` family. Protocols are
reusable, county-agnostic execution procedures — distinct from `architecture/` docs
(which define contracts and schemas) and `domain/` docs (which define investor-side
knowledge).

**v5.3.0 amendment.** Every county recon MUST produce a complete **Source-of-Record
Matrix** as its required output artifact — see `knowledge_base/architecture/16_source_of_
record_matrix.md` and the v5.3.0 amendment block in §01.20–§01.26 of this protocol. The
amendment adds the lead type sweep and three mandatory Phase 0 sub-steps (PDF/sample
inspection, documented API discovery, bulk-data availability classification) that apply
WITHIN Phases 0.A–0.H, before any source is classified deferred or limited-coverage.

**v5.5.0 amendment.** Phase 0.A now requires five additional mandatory search queries
(§01.27) covering bankruptcy/federal courts, public notices, land bank/vacant property,
property tax treasurer, and UCC/entity enrichment portals. The canonical lead type sweep
expands from 27 to 29 types (adding Bankruptcy Notice and Public Notice — see §16.B).
UCC/entity portals are classified as `ENRICHMENT_SOURCE` + `build_priority: future` —
recon locates and records the portal URL but does not build an adapter.

**v5.6.0 amendment.** Four additional mandatory recon steps (§01.28–§01.32) apply
within Phases 0.A–0.H, before any source is classified blocked, deferred, or
limited-coverage: access-control ENFORCEMENT verification (Gap 4 — a control that
exists is not a control that blocks), canonical lead-type TERMINOLOGY verification
(Gap 5 — framework lead-type names are not local names, and the originating event
is not the downstream stage), tax roll and delinquency ENRICHMENT discovery
(Gap 6), and source FRESHNESS verification (Gap 7 — catalog cadence is a claim,
max record date is the evidence).

---

## 01.0 Status and scope

- **Version:** v5.6.0 (extends v5.5.0 and v5.3.0; does not require any later patch to function).
- **Date:** 2026-08-04.
- **Purpose:** a county-agnostic Phase 0 recon procedure.
- **Authoritative for:** Phase 0 work for any new county, after
  `scaffold/bootstrap_county.py` has created the flat run folder and the user has
  approved bootstrap.
- **Scope IN:** source discovery, official source verification, portal fingerprinting,
  access classification, source role classification, document type discovery, blocker
  classification, and Build Eligibility Gate handoff using the active
  `MASTER_PROMPT.md §4.10` verdict enum.
- **Scope OUT:** scraper code, translator code, dashboard code, source-specific
  knowledge, county-specific examples, scoring weights, scoring overrides, and the
  stepwise gate algorithm (not yet formalized in the active framework — see §01.16).
- **Style:** matches the writing conventions of `knowledge_base/architecture/`
  documents — 4-space indented prose blocks for structured content, no triple-backtick
  code fences, inline backticks for filenames and field names.
- **Companion files:** this protocol is the first in the `knowledge_base/protocols/`
  family. Subsequent protocols (auto-resolve, scrape, translate, and others) are queued
  for future framework patches and are not assumed to exist yet.

---

## 01.1 Purpose

This protocol turns a freshly bootstrapped county run folder into a complete recon
dossier with eight named artifacts and one Build Eligibility Gate verdict.

It is the deterministic procedure Claude Code follows during Phase 0 of a county build.
It is **county-agnostic**: nothing in this document hardcodes a specific county, state,
vendor, or portal. Every county-specific value enters as a runtime input read from the
LAUNCH file (§01.3) and is substituted into the placeholders this protocol uses.

The recon dossier answers one operator question: **can this county produce a real lead
board, and if not, what is blocking it?** It answers that question with evidence — a
chain of named artifacts an operator can review without re-running the recon.

---

## 01.2 When this protocol runs

**Triggers — all must hold:**

- `scaffold/bootstrap_county.py` has completed for a new county, creating
  `runs/<county_slug>/LAUNCH_<SLUG>.md` and `runs/<county_slug>/operator_notes.md`.
- The user has approved bootstrap (per the bootstrap approval gate documented in
  `START_HERE.md`).
- `runs/<county_slug>/recon/` does not yet contain a populated `recon_summary.md` —
  this protocol is what creates it.

**This protocol does NOT run:**

- before `scaffold/bootstrap_county.py` has completed;
- if `recon_summary.md` already exists with a final verdict (re-running a completed
  recon requires explicit operator instruction);
- as part of any task that is not a county build.

---

## 01.3 Inputs

Claude Code reads every input from `runs/<county_slug>/LAUNCH_<SLUG>.md`, the launch
file written by `scaffold/bootstrap_county.py` (its `generate_launch_file_content`
function produces that file). Required inputs:

- `county_slug` — a validated slug (lowercase letters, digits, underscores; no leading,
  trailing, or consecutive underscores — the `SLUG_PATTERN` enforced by
  `scaffold/bootstrap_county.py`). Conventional form is `<county>_<state>`.
- `county_name` — the operator-readable county name (conventionally `<County> County`
  or the equivalent local term).
- `state_code` — the 2-letter, lowercase state code.
- `state_name` — the full state name.
- `bootstrap_phase` — the framework phase recorded at bootstrap time.

The protocol does NOT derive these inputs from anywhere else. It reads them from the
LAUNCH file. If the LAUNCH file is missing or malformed, **halt and report** — do not
guess the county or state.

---

## 01.4 Expected run folder location

All recon artifacts written by this protocol go under:

    runs/<county_slug>/recon/

`scaffold/bootstrap_county.py` (function `create_run_folder`) creates a **flat** run
folder containing only `LAUNCH_<SLUG>.md` and `operator_notes.md`. The `recon/`
subdirectory does **not** exist when this protocol begins; §01.5 creates it.

---

## 01.5 Recon folder creation rule

Before writing any recon artifact, Phase 0.A creates the recon subdirectory:

    runs/<county_slug>/recon/

This is the **only** directory this protocol creates. No nested subdirectories under
`recon/` are required (no `raw_html/`, no `fixtures/`, no `screenshots/` — those are
Phase 1+ artifacts and out of scope here).

If `runs/<county_slug>/recon/` already exists with prior contents, the protocol does
**not** overwrite. It reads the existing artifacts to determine whether a prior recon
was partial:

- if a prior recon was partial (some artifacts present, `recon_summary.md` absent or
  without a final verdict), resume from the first missing artifact;
- otherwise (a complete prior recon), halt and ask the operator before re-running.

---

## 01.6 Phase 0.A — Source discovery procedure

Use web search to find candidate official county sources. Every query uses placeholders
that Claude Code substitutes from the §01.3 inputs.

Required search queries, in priority order:

    1.  "<county_name> <state_name> county clerk official records"
    2.  "<county_name> <state_name> county recorder of deeds"
    3.  "<county_name> <state_name> district clerk court records"
    4.  "<county_name> <state_name> sheriff sale schedule"
    5.  "<county_name> <state_name> tax assessor delinquent"
    6.  "<county_name> <state_name> tax sale records"
    7.  "<county_name> <state_name> probate court records"
    8.  "<county_name> <state_name> foreclosure notice"
    9.  "<county_name> <state_name> mechanics lien filings"
    10. "<state_name> appraisal district"  OR  "<state_name> property assessor"
        (state-dependent enrichment search)

The five additional queries required by the v5.5.0 amendment (§01.27) are appended
after the core ten above and run in the same Phase 0.A pass.

For each candidate URL found:

- visit the page;
- confirm it appears to be an official county government source (URL pattern, a
  vendor-hosted-for-county subdomain, county branding);
- capture the exact URL, the page title, and a brief note on what records the source
  covers;
- distinguish official sources from third-party aggregators. Paid-data aggregators and
  reseller portals are NOT primary recon targets and are explicitly out of scope for
  the framework — they are reseller layers over official data, not the official record
  authority.

Save findings to `runs/<county_slug>/recon/source_discovery.md`. One entry per source,
with fields:

    name
    official_url
    page_title
    gov_or_aggregator
    records_covered
    discovered_via_query

---

## 01.7 Phase 0.B — Official source verification layers

For each source recorded in `source_discovery.md`, verify it is genuinely the official
county source for its record class. Verification layers:

- **Layer 1 — Government domain check.** The domain ends in `.gov` or `.us`, or is a
  recognizable county-named subdomain.
- **Layer 2 — Vendor portal check.** If the source is hosted by a known portal vendor
  (consult `knowledge_base/engineering/08_vendor_portal_library.md` for recognized
  vendor patterns), confirm the vendor-hosted page is the official county-contracted
  portal — footer attribution, county branding, and a link inbound from the county's
  own `.gov` website.
- **Layer 3 — Cross-reference check.** The county's own `.gov` homepage links to this
  source.
- **Layer 4 — Records authority check.** The source corresponds to a recognized county
  records authority (Clerk of Court, County Clerk, Recorder of Deeds, Sheriff, Tax
  Assessor-Collector, District Clerk, Probate Court, or the local equivalent).

Classification rule:

- passes Layer 1 OR (Layer 2 AND Layer 3), AND passes Layer 4 → `VERIFIED_OFFICIAL`;
- passes some layers but not the rule above → `UNVERIFIED`, with a note on which layers
  passed;
- fails Layer 4 (no recognized records authority) → `NOT_RECORDS_AUTHORITY`; exclude
  from further processing.

Save to `runs/<county_slug>/recon/source_verification.md`. One entry per source, with
fields:

    name
    official_url
    layers_passed
    verification_status
    notes

---

## 01.8 Phase 0.C — Portal fingerprinting procedure

For each `VERIFIED_OFFICIAL` source, fingerprint the portal:

- **Portal vendor** — consult `knowledge_base/engineering/08_vendor_portal_library.md`
  for known vendor recognition patterns.
- **Detection heuristics used** — the HTML markers, URL patterns, JS bundle paths,
  `robots.txt` entries, or footer vendor branding that identified the vendor.
- **Page architecture** — single-page app (JS-rendered) versus server-rendered HTML.
- **Search interface type** — form-based POST, REST API, GraphQL, vendor-proprietary,
  or other.
- **Result page URL pattern.**
- **Detail page URL pattern.**
- **Estimated technical scrape difficulty:**
  - `LOW` — server-rendered HTML, no authentication;
  - `MEDIUM` — single-page app, no authentication;
  - `HIGH` — single-page app plus dynamic authentication or per-request tokens;
  - `VERY_HIGH` — Cloudflare challenge, CAPTCHA gate, IP block, or anti-scrape headers.

Save to `runs/<county_slug>/recon/portal_fingerprints.md`. One entry per source, with
fields:

    name
    vendor
    detection_heuristics
    architecture
    search_interface
    result_url_pattern
    detail_url_pattern
    scrape_difficulty

---

## 01.9 Phase 0.D — Access classification taxonomy

Canonical access classifications — use exactly these enum values:

    OPEN_PUBLIC                 searchable without login or payment; search results and
                                detail metadata fully visible
    SEARCH_ONLY_PUBLIC          search and result metadata are free; document images /
                                PDFs are behind payment. Acceptable for the framework —
                                document images are not required to produce matched
                                leads from search metadata
    FREE_ACCOUNT_REQUIRED       requires signup, but the account is free
    PAID_SUBSCRIPTION_REQUIRED  paid access required to use search at all
    LOGIN_REQUIRED              credentials required; paid/free status unknown
    CAPTCHA_PROTECTED           a CAPTCHA gates search results
    DOCUMENT_IMAGES_LOCKED      search works but document images are locked behind
                                payment. When document images are needed for the build,
                                this is a blocker; when they are not needed, it is
                                equivalent to SEARCH_ONLY_PUBLIC
    BLOCKED                     Cloudflare challenge, IP block, or anti-scrape headers
                                prevent access
    UNKNOWN                     could not be determined without taking a forbidden
                                action (see §01.17)

For each `VERIFIED_OFFICIAL` source, classify access by visiting the source and
observing — without taking any forbidden action (§01.17).

Save to `runs/<county_slug>/recon/access_classification.md`. One entry per source, with
fields:

    name
    access_classification
    evidence
    notes

The `evidence` field records what was observed that led to the classification — the
specific page behavior, header, challenge, or paywall seen. An access classification
without observed evidence is not acceptable.

---

## 01.10 Phase 0.E — Source role classification

Canonical source role values, per `knowledge_base/architecture/13_lead_origination_
contract.md` §13.2 and §13.3:

    PRIMARY_LEAD_SOURCE     clerk records, court filings, foreclosure notices, sheriff
                            sales, tax liens, tax delinquency, lis pendens, probate,
                            estate records, mechanics liens, judgments, and other
                            recorded distress events (full canonical list in §13.2)
    SUPPORTING_LEAD_SOURCE  related event sources that confirm a primary signal but do
                            not originate a lead on their own (for example, a trustee
                            sale appointment supporting a foreclosure notice)
    ENRICHMENT_SOURCE       parcel, GIS, CAD, assessor, tax roll, ownership, valuation,
                            vacancy, equity proxy, and property-attribute data (full
                            canonical list in §13.3)
    REFERENCE_ONLY          sources that provide context but are not used in the build
                            (county informational pages, vendor documentation)
    REJECTED_SOURCE         sources excluded from the build (third-party aggregators,
                            paywalled redundancies, sources that failed verification)

For each `VERIFIED_OFFICIAL` source, classify the role per §13. For unverified or
excluded sources, record `REJECTED_SOURCE` with a reason.

Save to `runs/<county_slug>/recon/source_role_classification.md`. One entry per source,
with fields:

    name
    source_role
    rationale
    section_13_reference

---

## 01.11 Primary lead source vs enrichment source rule

The hard rules from `knowledge_base/architecture/13_lead_origination_contract.md` §13.4
and §13.5 are restated here so Claude Code cannot miss them during Phase 0:

**HARD RULE (restated from §13.4.1).** A lead row MUST originate from a primary
event-based recorded source. Enrichment alone cannot create a lead row.

**HARD RULE (restated from §13.4.2).** Parcel data, GIS data, CAD data, assessor data,
tax roll data, ownership data, valuation data, vacancy data, equity proxies, and
property attributes are ENRICHMENT. They CANNOT create a lead row. They CAN attach to a
lead row that already exists from a primary source.

**HARD RULE (restated from §13.5.1).** Every Matched lead row (the record type defined
in `knowledge_base/architecture/09_output_schemas.md`) MUST contain at least one signal
from a §13.2 primary lead source category. This is a checkable property; the framework
verifies it before emitting any active lead output.

**Consequence for recon.** If zero `PRIMARY_LEAD_SOURCE` entries pass verification
(§01.7) AND access classification (§01.9) AND end up accessible — `OPEN_PUBLIC` or
`SEARCH_ONLY_PUBLIC` — then the Build Eligibility Gate verdict cannot be
`READY_TO_BUILD` or `READY_WITH_BLOCKERS`. The framework will not produce an active
lead dashboard from enrichment alone. Recon's job is to discover whether that primary
path exists; it does not get to wish one into being.

---

## 01.12 Phase 0.F — Document type discovery

For each `VERIFIED_OFFICIAL` source classified as `PRIMARY_LEAD_SOURCE` or
`SUPPORTING_LEAD_SOURCE` with an access classification of `OPEN_PUBLIC` or
`SEARCH_ONLY_PUBLIC`, perform a lightweight document type discovery:

- identify the document type taxonomy the portal uses — document type codes, document
  categories, or filing types;
- capture the available document type values, for example the contents of any
  "document type" dropdown on the search interface;
- cross-reference each discovered document type against the §13.2 primary lead source
  categories, to identify which document types are PRIMARY_LEAD signals and which are
  NOISE — administrative, lifecycle/suppression, or unrelated;
- reference `knowledge_base/domain/canonical_doc_types.json` for the canonical doc type
  registry. When a discovered type matches a canonical type, note the canonical name.

This phase is **metadata-only**. It does NOT scrape records. It captures the source's
document type vocabulary and proposes how that vocabulary maps to the §13.2 primary
categories.

Save to `runs/<county_slug>/recon/document_type_discovery.md`. Per source, with fields:

    source_name
    document_type_taxonomy_field_name
    total_types_observed
    types_mapped_to_canonical_primary
    types_mapped_to_canonical_enrichment
    types_unknown
    recommended_primary_doc_types_for_build

---

## 01.13 Phase 0.G — Blocker classification and auto-resolve boundaries

For each source with an access classification other than `OPEN_PUBLIC` or
`SEARCH_ONLY_PUBLIC`, classify the blocker type and identify whether auto-resolve (per
`MASTER_PROMPT.md §4.14`, Phase 0.5) is allowed.

**Technical blocker** — auto-resolve may be attempted in Phase 0.5:

- user-agent gating;
- a `robots.txt` that permits scraping;
- content server-rendered behind JavaScript that a headless browser can render;
- a simple session-cookie requirement.

**Permission blocker** — auto-resolve NOT allowed; requires operator escalation:

- `FREE_ACCOUNT_REQUIRED` — account creation is forbidden during recon;
- `PAID_SUBSCRIPTION_REQUIRED` — payment is forbidden during recon;
- `LOGIN_REQUIRED` — credentials are required;
- `CAPTCHA_PROTECTED` — solving CAPTCHAs is forbidden without an operator-approved
  solver;
- `DOCUMENT_IMAGES_LOCKED` when document images are required for the build.

**Hard blocker** — no auto-resolve; requires an operator decision:

- `BLOCKED` — Cloudflare challenge, IP block, or anti-scrape headers.

**Unknown blocker** — requires operator clarification, not an auto-resolve attempt.

Recon does NOT execute auto-resolve. Recon only classifies blockers and records what
type of operator action would be needed to clear each one. The actual auto-resolve
procedure is owned by `MASTER_PROMPT.md §4.14` (Phase 0.5) and is a separate phase.
Strategy detail for blocked sources lives in
`knowledge_base/engineering/04_blocked_source_strategies.md`.

This blocker classification feeds the Build Eligibility Gate verdict (§01.15).

---

## 01.14 Phase 0.H — Recon artifacts to write

All artifacts are written under `runs/<county_slug>/recon/`:

    source_discovery.md            Phase 0.A output — candidate sources from web search
    source_verification.md         Phase 0.B output — verification layer pass/fail
    portal_fingerprints.md         Phase 0.C output — vendor and architecture
    access_classification.md       Phase 0.D output — access tier per source
    source_role_classification.md  Phase 0.E output — PRIMARY / SUPPORTING /
                                   ENRICHMENT / REFERENCE / REJECTED
    document_type_discovery.md     Phase 0.F output — document type taxonomy
    build_eligibility_handoff.md   Phase 0.G + §01.15 output — blocker classification
                                   plus the gate handoff
    recon_summary.md               final operator-facing summary with the Build
                                   Eligibility Gate verdict (§01.15 / §01.16)

That is eight artifacts. Each uses 4-space indented prose blocks for structured content,
matching the existing harness convention — no triple-backtick code fences.

**v5.6.0 amendment — permitted recon formats.** The eight artifacts above are a
CONTENT contract, not a filesystem contract. Two layouts satisfy this protocol:

    SPLIT_ARTIFACTS   the eight files named above, written under
                      runs/<county_slug>/recon/. The default.
    CONSOLIDATED      one recon document containing every field the eight
                      artifacts require, accompanied by the mandatory
                      section-to-artifact index defined in §01.33.

Both are fully compliant. Neither is preferred by default — pick per §01.33.

A consolidated recon WITHOUT the §01.33 index is NOT compliant. The index is
what keeps the content contract mechanically checkable when the file boundaries
that used to encode it are gone; without it, a consolidated recon is an
undocumented exception rather than a permitted format.

---

## 01.15 Build Eligibility Gate handoff

Phase 0.G plus the verdict computation produce
`runs/<county_slug>/recon/build_eligibility_handoff.md`, containing:

- **Counts** — `VERIFIED_OFFICIAL` sources, sources by role, sources by access
  classification.
- **Accessible primary sources count** — `PRIMARY_LEAD_SOURCE` intersected with
  `OPEN_PUBLIC` / `SEARCH_ONLY_PUBLIC` / `DOCUMENT_IMAGES_LOCKED`-when-acceptable.
- **Accessible primary document types** — the PRIMARY_LEAD signals from the §01.12
  discovery, for the accessible primary sources.
- **Blockers by type** — technical / permission / hard / unknown.
- **Recommended provisional verdict** — one of the five §4.10 values listed in §01.16.
- **Justification trail** — every source examined, its role, its access classification,
  and how it contributed to the verdict. The trail must let an operator reconstruct the
  verdict without re-running the recon.
- **Recommended operator next actions.**

Then write `runs/<county_slug>/recon/recon_summary.md` as the operator-facing executive
summary, citing `build_eligibility_handoff.md` for the detail.

---

## 01.16 Current §4.10 verdict definitions

Use the `MASTER_PROMPT.md §4.10` verdict enum — five values, no others:

- **`READY_TO_BUILD`** — at least one verified primary lead source is fully accessible
  without operator escalation (`OPEN_PUBLIC` or `SEARCH_ONLY_PUBLIC`), with at least one
  accessible primary document type; enrichment may or may not be available; no critical
  blocker prevents Phase 1+ work.
- **`READY_WITH_BLOCKERS`** — at least one verified primary source is accessible, but
  other primaries are blocked; partial coverage is achievable; operator authorization is
  required to proceed past the partial scope.
- **`RECON_ONLY`** — sources have been discovered but none is currently buildable as a
  primary lead source (for example, all primaries are `CAPTCHA_PROTECTED`, `BLOCKED`, or
  `PAID_SUBSCRIPTION_REQUIRED`); enrichment may be available but cannot independently
  produce a lead board per §13.
- **`WAITING_ON_ACCESS`** — a primary source has been identified and verified, but is
  blocked at the access layer (`FREE_ACCOUNT_REQUIRED`, `LOGIN_REQUIRED`, or
  `DOCUMENT_IMAGES_LOCKED` when document images are required); the build awaits operator
  credentials, account creation, or paid-subscription approval before it can proceed.
- **`NOT_BUILDABLE_YET`** — no primary source was identified after a reasonable search;
  the county may have no online official primary records, or all candidates failed
  verification.

Important note:

    The stepwise Build Eligibility Gate algorithm is not yet formalized in the active
    framework. Until the future gate enforcement patch lands, Claude Code applies §4.10
    using documented operator judgment from recon outputs.

The justification trail in `build_eligibility_handoff.md` is the transparency record
for that judgment — it is what makes an operator-judgment verdict reviewable.

---

## 01.17 What is forbidden during recon

Strict prohibitions during this protocol, consistent with the §01.13 auto-resolve
boundary:

- creating accounts, free or paid;
- paying for any service;
- solving CAPTCHAs;
- using proxy services;
- bypassing `robots.txt`;
- bypassing access controls of any kind;
- scraping records — recon is metadata-only: vendor identification, access
  classification, and document type taxonomy capture. Actual record extraction belongs
  to a later phase;
- submitting public records requests;
- modifying any framework file;
- modifying any file outside `runs/<county_slug>/recon/`;
- committing or pushing;
- writing scraper, translator, or dashboard code;
- producing Matched lead output;
- producing any operator-facing or client-facing artifact other than the eight recon
  artifacts listed in §01.14.

When access cannot be determined without taking one of these forbidden actions, the
correct outcome is the `UNKNOWN` access classification (§01.9) and an operator
escalation — never the forbidden action.

---

## 01.18 Completion checklist

Recon is complete when ALL of the following are true:

- `runs/<county_slug>/recon/` exists;
- `source_discovery.md` exists with at least one entry;
- `source_verification.md` exists with a verification status for every source in
  `source_discovery.md`;
- `portal_fingerprints.md` exists for every `VERIFIED_OFFICIAL` source;
- `access_classification.md` exists for every `VERIFIED_OFFICIAL` source;
- `source_role_classification.md` exists for every `VERIFIED_OFFICIAL` source;
- `document_type_discovery.md` exists for every accessible `PRIMARY_LEAD_SOURCE` or
  `SUPPORTING_LEAD_SOURCE`;
- `build_eligibility_handoff.md` exists with a §4.10 verdict and a justification trail;
- `recon_summary.md` exists with the operator-facing summary;
- no file was written outside `runs/<county_slug>/recon/`;
- no commit, no push, no stash operation occurred.

Then:

- if the verdict is `READY_TO_BUILD` or `READY_WITH_BLOCKERS`, the protocol hands off to
  Phase 1+ (scraper / translator / evidence / dashboard work — out of scope for this
  protocol);
- if the verdict is `RECON_ONLY`, `WAITING_ON_ACCESS`, or `NOT_BUILDABLE_YET`, the
  protocol STOPS and awaits an operator decision.

---

## 01.19 End marker

Protocol complete. The recon artifacts are operator-reviewable. The Build Eligibility
Gate verdict in `recon_summary.md` determines the next phase or the stop.

---

## 01.20 v5.3.0 amendment — Source of Record Matrix recon requirements

v5.3.0 extends this protocol. The requirements in §01.20–§01.26 are mandatory Phase 0
recon requirements; they apply WITHIN Phases 0.A–0.H, before any source is classified
deferred, limited-coverage, or not-buildable. They do not replace §01.0–§01.19 — they
extend it.

The required output artifact of every county recon is the **Source-of-Record Matrix**,
defined by `knowledge_base/architecture/16_source_of_record_matrix.md` and schema-checked
against the `sourceOfRecordMatrix` definition in `config/counties/_schema.json`. The
matrix and its companion artifacts are written under `runs/<county_slug>/recon/`:
`source_of_record_matrix.json`, `source_of_record_matrix.md`, `source_coverage_map.md`,
`api_discovery_report.md`, `operator_verified_sources.yml`,
`fingerprints/<source_id>.fingerprint.json`, and `build_eligibility_report.md`. A recon
that does not produce a complete matrix cannot proceed to Build Mode.

## 01.21 Lead Type Sweep requirement

Every county recon MUST walk the full canonical lead type sweep — the 29 lead types
enumerated in `§16.B` (Foreclosure, Trustee Sale, Notice of Trustee Sale, Notice of
Substitute Trustee Sale, Sheriff Sale, Tax Lien Foreclosure, Tax Sale, Tax Sale
Certificate, Tax Delinquency, Lis Pendens, Civil Judgment, Abstract of Judgment,
Mechanic Lien, Construction Lien, Federal Tax Lien, State Tax Lien, Probate, Affidavit
of Heirship, Executor Deed, Administrator Deed, Code Lien, Demolition, Condemnation,
Eviction, Divorce, Bankruptcy, Surplus, Bankruptcy Notice, Public Notice).

For each lead type, recon MUST answer: where is the official source of record? what is
its URL? what is its access pattern? is it buildable? A recon that does not produce a
complete sweep — an entry per lead type — is incomplete and cannot proceed to Build
Mode.

## 01.22 Required Step — PDF/Sample Document Inspection (Gap 1)

Before classifying any source as deferred or limited-coverage based on the listing/index
page alone, recon MUST fetch and inspect at least 3 sample source documents (PDF,
scanned image, downloaded XML, or whatever the underlying record format is).

The inspection must answer:

- What fields does the actual source document carry that the listing/index page does
  not expose?
- Does the document carry: property address (situs), debtor/owner name, parcel
  identifier, sale/event date, document reference number, legal description?
- Is the document text-extractable or scanned-image (OCR required)?
- Does the layout vary across documents (multiple templates)?

Classifying a source as deferred without sample-document inspection is a recon defect.
The recon report must explicitly answer: "Sample documents inspected: Y/N. If N, evidence
of why inspection was not possible (access blocked, document images locked, etc.)."

Rationale: A source's listing/index page may expose only minimal metadata, while the
underlying document carries the address, debtor, and event date directly. Deferring such
a source based on listing-page inspection alone is a false negative — buildable sources
get misclassified as not-buildable.

## 01.23 Required Step — Documented API Discovery (Gap 2)

For every candidate source, recon MUST explicitly search for documented APIs before
settling on HTML scraping. Required search locations:

- `<domain>/api`
- `<domain>/api/swagger`
- `<domain>/swagger`
- `<domain>/docs`
- `<domain>/api-docs`
- Postman public collections (search vendor name + "postman")
- GitHub (search "<county_name> api" / "<vendor_name> api")
- Vendor documentation (if the portal is vendor-built)

The recon report must explicitly answer: "Documented API found: Y/N. If N, list of
search paths checked."

If a documented API is found, prefer it over HTML scraping. Document the API in
`runs/<county_slug>/recon/api_discovery_report.md` and link it from the
Source-of-Record Matrix.

Rationale: Documented APIs are more stable, faster, and exempt from anti-bot/WAF
protections that block HTML scrapers. Stopping recon at HTML/WAF classification when a
documented API exists is a false-negative recon outcome.

## 01.24 Required Step — Bulk-Data Availability Classification (Gap 3)

For every candidate source, recon MUST classify its bulk-data availability as one of:

- `FULL_COUNTY_BULK`
- `BATCH_QUERY`
- `PER_RECORD_ONLY`
- `UNKNOWN`

Per-record-only sources are buildable, but their coverage is bounded by the
externally-resolved parcel set. Recon must surface this constraint and document the
coverage implication.

The recon report must explicitly answer for each source: "Bulk availability: <class>.
Coverage implication: <description>."

Rationale: A per-record-only source cannot enumerate the universe of distressed
properties — it can only be queried for known parcel identifiers. Discovering this
constraint during build instead of recon causes scope re-estimation mid-build and
undermines build_verdict accuracy.

## 01.25 Operator-Verified Sources

When the operator manually surfaces a direct source link that recon missed, the link
must be captured in `runs/<county_slug>/recon/operator_verified_sources.yml` with:

- `lead_type`
- `discovered_by` (operator)
- `official_url`
- `official_origin_evidence` (how the operator confirmed the source is official)
- `reason_added` (why recon missed it)
- `review_status` (`accepted` | `rejected` | `pending`)
- `notes`

This is a recon supplement, not an override. Subsequent recon runs should still attempt
to discover the source independently; the operator-verified entry is provenance, not
exemption.

## 01.26 Halt condition (v5.3.0)

Recon halts when no verified primary event source is found across the complete lead type
sweep. Clerk and recorder are the most common primary event sources but not the only
valid ones — court portals, district clerks, sheriffs, tax offices, tax collectors,
trustee-sale portals, foreclosure-listing portals, auction vendors, official vendor
portals, and posted-notices pages are all valid primary event sources. Recon does not
halt merely because clerk or recorder access is blocked, provided another verified
primary event source exists for at least one lead type.

---

## 01.27 v5.5.0 amendment — Additional mandatory Phase 0.A search queries

v5.5.0 adds five mandatory search queries to Phase 0.A. These run after the core ten
queries in §01.6 in the same Phase 0.A pass. Every new county recon MUST execute all
fifteen queries before declaring source discovery complete.

Required additional queries (11–15), in order:

    11. "<county_name> <state_name> bankruptcy court federal district"
        Purpose: locate the federal bankruptcy court district serving this county.
        Source role: PRIMARY_LEAD_SOURCE (Bankruptcy Notice lead type).
        Expected authority: U.S. Bankruptcy Court for the district; PACER.
        Build priority: high_value — PACER requires a funded account; classify
        access as LOGIN_REQUIRED or PAID_SUBSCRIPTION_REQUIRED and flag for
        operator decision. Do not auto-resolve.

    12. "<county_name> <state_name> public notices legal foreclosure estate"
        Purpose: locate the county's official or state-designated public notice
        publication (legal newspaper, state public notice portal, or official
        county posting page).
        Source role: PRIMARY_LEAD_SOURCE (Public Notice lead type); may also surface
        Foreclosure, Sheriff Sale, Probate, and Tax Sale leads ahead of their
        recorded counterparts — filing date precedes recording date.
        Expected authority: official state public notice site (.gov or
        state-designated), county-linked newspaper of record, or sheriff posting page.
        Build priority: high_value.

    13. "<county_name> <state_name> land bank vacant property"
        Purpose: locate the county or city land bank and its available-property list.
        Source role: PRIMARY_LEAD_SOURCE (Demolition, Condemnation, Eviction signals
        for land-bank-owned or land-bank-eligible parcels).
        Expected authority: municipal or county land bank authority (.gov or
        official city/county link).
        Build priority: high_value.

    14. "<county_name> <state_name> property tax treasurer billing delinquent"
        Purpose: locate the county treasurer's tax billing and delinquency portal,
        DISTINCT from the tax sale portal already found in query 6.
        Source role: PRIMARY_LEAD_SOURCE (Tax Delinquency lead type — active
        delinquent balance, not yet in tax sale).
        Expected authority: county treasurer or tax collector (.gov or official
        county link).
        Build priority: mvp_required when the tax sale portal does not expose
        current delinquency balances; otherwise enrichment.

    15. "<state_name> UCC lien search" AND "<county_name> <state_name> business entity
        search"
        Purpose: locate the state UCC filing portal and the state business entity /
        LLC registry.
        Source role: ENRICHMENT_SOURCE — UCC liens and entity lookups are NOT
        lead-originating; they validate ownership structure and lien position after
        a lead is generated from a primary source.
        Build priority: future — recon MUST record the portal URL and access status
        but MUST NOT build an adapter in the current phase. Classify as
        `build_priority: future` in the county config.
        Note: do NOT add UCC or entity sources to the P0 distress source count or
        use them in the Build Eligibility Gate verdict. They are enrichment-only.

Classification rules for the new queries:

- Queries 11–14 follow the same verification pipeline as queries 1–10 (§01.7–§01.13).
  Sources discovered via these queries are added to `source_discovery.md` and proceed
  through all subsequent Phase 0 steps.
- Query 15 (UCC/entity) produces ENRICHMENT_SOURCE entries only. They skip the
  PRIMARY_LEAD_SOURCE verification path but are still recorded in
  `source_role_classification.md` and fingerprinted.
- All fifteen queries must be documented in `api_discovery_report.md` with the
  outcome of each (source found / not found / blocked / enrichment-only).

---

## 01.28 v5.6.0 amendment — four additional mandatory recon steps

v5.6.0 extends this protocol with four required steps (§01.29–§01.32). Like the
v5.3.0 gaps, they apply WITHIN Phases 0.A–0.H and must be satisfied BEFORE any
source is classified blocked, deferred, limited-coverage, or not-buildable.

Each of the four exists because the absence of the step produced a specific
class of false recon outcome: a buildable source recorded as blocked, a lead
type recorded as absent because it is named differently locally, an enrichment
layer never discovered, or a frozen archive trusted as a live feed. All four
are false negatives or false positives that recon is supposed to catch.

## 01.29 Required Step — Access-control enforcement verification (Gap 4)

The presence of an access-control mechanism is NOT evidence that the mechanism
is enforced. Recon MUST distinguish a control that EXISTS from a control that
BLOCKS.

Before classifying any source as `CAPTCHA_PROTECTED`, `LOGIN_REQUIRED`,
`BLOCKED`, or any other blocked access class, recon MUST attempt one
low-volume, good-faith request along the portal's ordinary public path and
record what the portal actually returned.

The distinction that must be drawn:

    CONTROL PRESENT      a CAPTCHA widget, login form, challenge script, or
                         anti-bot library is present in the markup, the client
                         bundle, or the request flow
    CONTROL ENFORCED     the control actually gates the records — the request
                         fails, returns a challenge, or returns no data until
                         the control is satisfied

A control that is present but not enforced is NOT a blocker. Common patterns
that produce false blocked classifications:

- a CAPTCHA library bundled into a client application but only invoked
  conditionally (after a request threshold, for a specific search mode, or for
  a specific record class);
- a login affordance that gates saved searches, alerts, or document images
  while leaving the search index itself public;
- an anti-bot script that fingerprints without challenging;
- a challenge that applies to one search mode while another mode of the same
  portal returns the same records unchallenged.

The recon report MUST explicitly answer, per source: "Access control present:
Y/N (which). Enforcement tested: Y/N. Observed result of the good-faith
request: <status, response shape, and whether records were returned>."

Recording a blocked classification without an enforcement test is a recon
defect.

**Enforcement tiering.** When a control IS enforced, recon MUST additionally
classify how many independent layers must be cleared, because this determines
whether the source is recoverable by an operator-assisted path:

    SINGLE_LAYER_HUMAN_VERIFIABLE   one human-solvable challenge (image
                                    challenge, checkbox attestation, emailed or
                                    SMS one-time code) gates a session that then
                                    persists for subsequent requests
    MULTI_LAYER                     two or more independent controls compound
                                    (for example a challenge plus credentialed
                                    login, or a per-request token that cannot
                                    outlive a single call)
    PER_REQUEST_CHALLENGE           the control re-fires on every request, so no
                                    durable session exists

`SINGLE_LAYER_HUMAN_VERIFIABLE` is NOT a build blocker. It is an
operator-assisted source. The framework's locked rules permit
`operator_seeded_session_allowed`, `captcha_solver_allowed`, and
`stealth_browser_allowed` in Build Mode; a single-layer human-verifiable
control is cleared once by the operator, and the adapter resumes against the
established session. Recon records the handoff requirement and the expected
session lifetime; it does not solve the challenge itself (§01.17 still binds
during recon) and it does not mark the source unbuildable.

Escalation order for an enforced control, recorded as the source's
`next_access_strategy`:

    1.  find an unchallenged equivalent path on the same portal (alternate
        search mode, documented API, bulk export, mirror layer)
    2.  operator-assisted manual verification with session handoff
        (SINGLE_LAYER_HUMAN_VERIFIABLE)
    3.  cost-gated or credential-gated strategies per `MASTER_PROMPT.md §4.14`
    4.  mark blocked and escalate to the operator

Only after steps 1–3 have been evaluated and recorded may a source carry a
blocked classification. Manual operator verification is an accepted resolution
path, not a failure state.

## 01.30 Required Step — Canonical lead-type terminology verification (Gap 5)

Lead type names in `§16.B` are FRAMEWORK vocabulary. They are not guaranteed to
be the vocabulary the jurisdiction uses, and the framework's name for a lead
type MUST NOT be assumed to be the local name for the underlying event.

For every lead type in the §01.21 sweep, recon MUST establish what the
jurisdiction actually calls the corresponding event, and MUST identify the
event that ORIGINATES the lead rather than a downstream stage of the same
process.

Required distinctions:

- **Originating event vs downstream stage.** A single distress process
  typically emits several public artifacts in sequence — an initiating filing,
  one or more interim notices, a judgment or order, a disposition or sale, and
  a post-disposition transfer. These are stages of ONE process, not independent
  lead types. Recon MUST identify which stage is the earliest reliably public
  artifact, because that stage carries the lead-time advantage. A later stage
  is a SUPPORTING signal for the same target, not the primary.
- **Local naming.** The same event carries different names across
  jurisdictions, and a name used in one jurisdiction may denote a different
  event in another. Terminology recon MUST be driven by the jurisdiction's own
  taxonomy — the court's case-type table, the recorder's document-type list,
  the tax authority's sale nomenclature, or the equivalent controlled
  vocabulary — not by the framework's label and not by general knowledge.
- **Procedural regime.** Whether a given lead type exists at all is a function
  of the jurisdiction's legal regime. A lead type may be structurally absent,
  and its framework name may still appear in unrelated local usage. Recon
  records `NOT_APPLICABLE_IN_JURISDICTION` with the regime evidence rather than
  `NOT_FOUND`.

Method — terminology must be established EMPIRICALLY, from the source's own
controlled vocabulary, not inferred:

    1.  retrieve the jurisdiction's authoritative type list (case-type table,
        document-type dropdown, sale-category list, violation-type list)
    2.  where the portal permits it, measure observed frequency per type over a
        bounded recent window, to separate live types from vestigial ones
    3.  map each observed local type to a canonical §16.B lead type, or to
        NOISE, recording the mapping and the evidence
    4.  for each mapped lead type, record which local type is the ORIGINATING
        event and which are downstream stages of the same process

The recon report MUST explicitly answer, per lead type: "Local name(s):
<names>. Originating event: <local type>. Downstream stages: <local types>.
Evidence: <how the vocabulary was obtained>."

A lead type recorded as `NOT_FOUND` without a terminology check against the
jurisdiction's own vocabulary is a recon defect. So is a lead type whose
recorded source of record is a downstream stage when an earlier public
originating artifact exists.

## 01.31 Required Step — Tax roll and delinquency enrichment discovery (Gap 6)

Recon MUST explicitly search for a property tax roll and a tax delinquency
feed, and MUST record the outcome even when the result is that none exists.
These are distinct from the tax sale source found by the §01.6 query 6 and from
the treasurer portal found by the §01.27 query 14: a tax sale list enumerates
only parcels that have already reached sale eligibility, which is a small and
late-stage subset of the distressed universe.

Three distinct artifacts must each be searched for and classified separately:

    TAX_ROLL             the full assessment/valuation/ownership roll for all
                         parcels — an ENRICHMENT_SOURCE providing owner of
                         record, mailing address, assessed and market values,
                         exemption flags, property class, and tax district
    DELINQUENCY_LIST     parcels carrying an unpaid balance but not yet in a
                         sale — a PRIMARY_LEAD_SOURCE for the Tax Delinquency
                         lead type
    BALANCE_LOOKUP       current amount owed for a given parcel — enrichment
                         that qualifies severity on an existing lead

For each, recon MUST record the delivery mechanism, preferring the most stable
available and searching in this order:

    1.  authenticated or open API with a documented contract (record whether a
        key is required, how it is obtained, cost, and rate limits)
    2.  bulk download — full-roll export in a structured format, with its
        refresh cadence
    3.  open-data portal dataset backed by a queryable service endpoint
    4.  per-parcel query interface (PER_RECORD_ONLY per §01.24)
    5.  scheduled or standing bulk delivery arranged with the authority
    6.  no programmatic access

Search targets must include, at minimum, the jurisdiction's assessment
authority, its tax billing and collection authority, its open-data portal, and
the corresponding STATE-level authority — many jurisdictions publish a
standardized statewide tax billing or assessment lookup that is more uniform,
better documented, and more scriptable than the local equivalent. A state-level
source covering the target jurisdiction is a valid and often preferable answer.

The recon report MUST explicitly answer: "Tax roll: <mechanism + cadence + key
requirement>. Delinquency list: <mechanism + cadence>. Balance lookup:
<mechanism>. Search paths checked: <list>."

Per §13, a tax roll is ENRICHMENT and cannot originate a lead. A delinquency
list IS a primary distress signal and counts toward the P0 gate.

## 01.32 Required Step — Source freshness verification (Gap 7)

Recon MUST verify the freshness of every source's ACTUAL RECORDS, not its
advertised or catalog-reported update cadence. A dataset's stated refresh
schedule, portal "last updated" stamp, or catalog metadata is a CLAIM. The
maximum event date present in the records is the EVIDENCE.

Publication metadata and record recency diverge routinely: an extract can be
republished on a schedule long after its upstream feed stopped delivering, so
the catalog timestamp advances while the newest record does not. A source in
this state is a historical archive presented as a live feed.

For every source, recon MUST determine and record:

    max_event_date        the newest event/filing/record date actually present
    min_event_date        the oldest, establishing backfill depth
    observed_lag          max_event_date measured against the recon date
    claimed_cadence       the refresh cadence the source advertises
    freshness_verdict     one of the values below

Freshness verdicts:

    LIVE                  observed lag is consistent with the claimed cadence
    LAGGING               records arrive but materially later than claimed
    FROZEN                no records after a fixed cutoff — a historical
                          archive regardless of what the catalog reports
    UNKNOWN               recency could not be determined without a forbidden
                          action (§01.17)

Consequences, which are binding on the §01.15 handoff:

- a `FROZEN` source MUST NOT be counted as a P0 daily-refresh distress source
  and MUST NOT satisfy the P0 gate, whatever its record volume;
- a `FROZEN` or `LAGGING` source may still be valuable for historical backfill,
  and recon should say so explicitly rather than discarding it;
- when a bulk extract is `FROZEN` but a live interactive portal exposes the
  same records, recon MUST record both — the extract for backfill and the
  portal as the current-data path — and MUST NOT let the convenient stale
  source displace the authoritative live one.

The recon report MUST explicitly answer, per source: "Max record date:
<date>. Observed lag: <duration>. Claimed cadence: <cadence>. Freshness
verdict: <verdict>."

Classifying a source as a live P0 feed without a freshness check is a recon
defect.

---

## 01.33 Consolidated recon format and the section-to-artifact index

§01.14 permits a CONSOLIDATED recon — one document carrying the content of all
eight artifacts — provided it includes the index defined here.

**Rationale.** §01.1 states the recon dossier's purpose: it answers one operator
question with evidence an operator can review without re-running the recon. That
purpose is served by the CONTENT being complete and reviewable, not by the
number of files it occupies. Splitting a coherent argument across eight
cross-referencing documents can reduce reviewability rather than increase it,
particularly where a single finding (a join key, a blocked source that gates
several lead types) is load-bearing across multiple artifacts and would have to
be restated or hyperlinked in each. The file boundaries, however, were doing real
work: they made completeness mechanically checkable. The index restores that
property without forcing the split.

**Choosing a format.** Neither layout is preferred by default:

- prefer SPLIT_ARTIFACTS when different artifacts have different audiences or
  review cadences, when artifacts are generated or consumed by tooling
  separately, or when the recon is large enough that one document becomes
  unnavigable;
- prefer CONSOLIDATED when the findings are heavily cross-cutting, when one
  operator reviews the whole dossier in a single pass, or when restating a
  load-bearing finding across artifacts would risk the restatements drifting
  out of sync.

**The index is mandatory.** A consolidated recon MUST contain an explicit
section-to-artifact index mapping every one of the eight §01.14 artifacts to the
section(s) of the consolidated document that carry its content. Requirements:

- all eight artifact names appear in the index, spelled as in §01.14;
- each maps to at least one concrete, locatable section reference within the
  document (a section number or heading, not a vague pointer);
- an artifact whose content is genuinely absent MUST be listed with an explicit
  gap statement and the reason, NOT silently omitted — an absent artifact is a
  recorded gap, never a blank row;
- the index states which format was used, so a reader knows the split files were
  intentionally not produced rather than lost;
- the v5.3.0 Source-of-Record Matrix companion artifacts (§01.20) follow the same
  rule: consolidate with an index entry, or produce them as separate files.

**Completion checklist interaction.** Where §01.18 requires that a named artifact
"exists," a consolidated recon satisfies that requirement when the index maps
that artifact to a populated section. The underlying obligation is unchanged:
every field the artifact requires must be present and reviewable.
