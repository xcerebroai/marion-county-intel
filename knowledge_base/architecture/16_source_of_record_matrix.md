# 16. Source of Record Matrix (v5.3.0+)

The Source-of-Record Matrix is the authoritative output of county recon. It maps every
canonical lead type to its official source of record in a given county, records the
verification state of each candidate source, and determines build eligibility per lead
type.

This file is the universal contract — the matrix schema, the enums, and the required
artifact list. The matrix *instances* are county-specific and live under
`runs/<county_slug>/recon/`. The recon procedure that produces a matrix is
`knowledge_base/protocols/01_county_recon.md`.

---

## 16.0 Status and scope

- **Version:** v5.5.0 (Session A1 of the v5.5.0 patch cycle — source category expansion).
- **Date:** 2026-06-26.
- **Authoritative for:** every county recon. No county may enter Build Mode without a
  complete Source-of-Record Matrix.
- **Scope:** the matrix schema (mirrored in `config/counties/_schema.json`), the lead
  type sweep, the source-role / access-status / bulk-availability contracts, the
  five-layer per-lead-type verification, the required county-scoped artifacts, and the
  universal-versus-county-specific separation.
- **Out of scope:** scraper/translator/dashboard code, the stepwise Build Eligibility
  Gate algorithm, and any county-specific source list — those are elsewhere or are
  county-scoped.

---

## 16.A Purpose

The Source-of-Record Matrix answers, for one county, the question recon exists to
answer: **for each lead type, where is the official source of record, and can the
framework build from it?**

- It is the recon output that maps each lead type to its official source.
- It is the authoritative artifact that determines `build_eligibility` per lead type — a
  county's overall build verdict is derived from it.
- It is county-scoped: one matrix per county, written under
  `runs/<county_slug>/recon/`.

Without a complete matrix, recon is incomplete and Build Mode cannot begin
(`MASTER_PROMPT.md §4.35`).

---

## 16.B Required lead type sweep

Every county recon MUST investigate the full canonical lead type sweep. The 29 canonical
lead types:

    1.  Foreclosure
    2.  Trustee Sale
    3.  Notice of Trustee Sale
    4.  Notice of Substitute Trustee Sale
    5.  Sheriff Sale
    6.  Tax Lien Foreclosure
    7.  Tax Sale
    8.  Tax Sale Certificate
    9.  Tax Delinquency
    10. Lis Pendens
    11. Civil Judgment
    12. Abstract of Judgment
    13. Mechanic Lien
    14. Construction Lien
    15. Federal Tax Lien
    16. State Tax Lien
    17. Probate
    18. Affidavit of Heirship
    19. Executor Deed
    20. Administrator Deed
    21. Code Lien
    22. Demolition
    23. Condemnation
    24. Eviction
    25. Divorce
    26. Bankruptcy
    27. Surplus
    28. Bankruptcy Notice
    29. Public Notice

Each lead type is classified per-county. A lead type that does not exist in the county's
state carries `state_applicability = NOT_APPLICABLE_IN_STATE`; one whose applicability
cannot be determined carries `UNKNOWN`; otherwise `APPLICABLE`. Each lead type also
carries a per-lead-type `status` (see §16.C). A recon that does not produce a complete
sweep — an entry for every one of the 29 lead types — is incomplete and cannot proceed
to Build Mode.

**v5.5.0 notes on the two new lead types:**

- **Bankruptcy Notice (28)** — a federal court filing (Chapter 7, 11, 13) in the U.S.
  Bankruptcy Court for the county's federal district. Distinct from the existing
  `Bankruptcy` type (which covers recorded abstract-of-judgment instruments post-filing).
  Expected authority: U.S. Bankruptcy Court / PACER. Typically `LOGIN_REQUIRED` or
  `PAID_SUBSCRIPTION_REQUIRED`; flag for operator decision. Source role:
  `PRIMARY_LEAD_SOURCE`.

- **Public Notice (29)** — a legally-required published notice in the county's
  newspaper of record, state public notice portal, or official county posting page.
  Covers foreclosure notices, sheriff sale notices, estate notices, and tax notices
  published before they appear in recorded instruments. Filing date precedes recording
  date — this source may surface leads earlier than the recorder. Expected authority:
  official state public notice site, county-linked newspaper of record, or sheriff
  posting page. Source role: `PRIMARY_LEAD_SOURCE`.

---

## 16.C Matrix fields per lead type

Each entry in the matrix mirrors the `leadTypeEntry` definition in
`config/counties/_schema.json`. Per lead type:

- **`lead_type`** — the canonical lead type name (from the §16.B sweep).
- **`state_applicability`** — `APPLICABLE` / `NOT_APPLICABLE_IN_STATE` / `UNKNOWN`.
- **`expected_authorities`** — the authorities that typically publish this lead type
  (e.g. county clerk, district clerk, sheriff, tax office).
- **`candidate_sources`** — the sources investigated for this lead type (see §16.E for
  the per-source fields).
- **`selected_source_id`** — the `source_id` of the source chosen for the build.
- **`status`** — the per-lead-type status, one of: `LIVE_SOURCE_FOUND`,
  `LIVE_SOURCE_FOUND_LIMITED_COVERAGE`, `SOURCE_FOUND_BLOCKED`,
  `SOURCE_FOUND_NEEDS_LOGIN`, `SOURCE_FOUND_PAID`, `SOURCE_FOUND_CAPTCHA`,
  `SOURCE_NOT_FOUND`, `NOT_APPLICABLE_IN_STATE`, `NEEDS_OPERATOR_REVIEW`,
  `ENRICHMENT_ONLY`.
- **`coverage_notes`** — operator-readable explanation of any partial coverage.

The matrix container (`sourceOfRecordMatrix`) also carries `county_slug`, `county_name`,
`state`, `framework_version`, `generated_at`, `county_build_status`, and the
`lead_types[]` array.

---

## 16.D Required artifacts per county

Recon writes the following under `runs/<county_slug>/recon/`:

- `source_of_record_matrix.json` — machine-readable, schema-validated against the
  `sourceOfRecordMatrix` definition in `config/counties/_schema.json`.
- `source_of_record_matrix.md` — human-readable summary of the matrix.
- `source_coverage_map.md` — live / blocked / limited-coverage / not-found summary.
- `api_discovery_report.md` — the documented-API discovery search log and findings.
- `operator_verified_sources.yml` — captures any source links the operator surfaces (see
  §16.H).
- `fingerprints/<source_id>.fingerprint.json` — one per-source portal fingerprint.
- `build_eligibility_report.md` — the county-level build verdict derived from the
  matrix.

A recon is complete only when all required artifacts are present.

---

## 16.E Source role contract

Each candidate source is classified as exactly one `source_role`:

- **`PRIMARY_EVENT_SOURCE`** — originates leads. An officially-recorded distress,
  transfer, encumbrance, or legal-status event (per `§13` Lead Origination Contract,
  `13_lead_origination_contract.md`).
- **`SUPPORTING_EVENT_SOURCE`** — provides additional event detail for leads originated
  elsewhere; does not originate a lead on its own.
- **`ENRICHMENT_SOURCE`** — attaches context (parcel, owner, valuation, vacancy) to a
  lead but never originates one.
- **`REFERENCE_SOURCE`** — informational lookup, no event content.
- **`BLOCKED_SOURCE`** — found but inaccessible.

Per `§13`: **only `PRIMARY_EVENT_SOURCE` creates leads.** No quantity of enrichment,
supporting, or reference sources can substitute for a primary event source.

---

## 16.F Access status contract

Each candidate source carries one `access_status`, matching the
`config/counties/_schema.json` enum:

- `OPEN_PUBLIC` — searchable without login or payment; results and detail metadata fully
  visible.
- `SEARCH_ONLY_PUBLIC` — search and result metadata free; document images behind
  payment. Acceptable — document images are not required to originate leads from search
  metadata.
- `FREE_ACCOUNT_REQUIRED` — requires signup, but the account is free.
- `PAID_SUBSCRIPTION_REQUIRED` — paid access required to search at all.
- `LOGIN_REQUIRED` — credentials required; paid/free status unknown.
- `CAPTCHA_PROTECTED` — a CAPTCHA gates search results.
- `DOCUMENT_IMAGES_LOCKED` — search works but document images are payment-locked; a
  blocker only when document images are required for the build.
- `BLOCKED` — Cloudflare challenge, IP block, or anti-scrape headers prevent access.
- `UNKNOWN` — could not be determined without a forbidden action.

Each access status carries an implication for build feasibility: `OPEN_PUBLIC` and
`SEARCH_ONLY_PUBLIC` are buildable without escalation; the remainder require
auto-resolve or operator action before a primary source counts as accessible.

---

## 16.G Bulk availability classification

Each candidate source carries one `bulk_availability`:

- **`FULL_COUNTY_BULK`** — the entire roll is obtainable in bulk.
- **`BATCH_QUERY`** — partial bulk via date range or filter.
- **`PER_RECORD_ONLY`** — must be queried record-by-record; coverage is bounded by the
  externally-resolved parcel set (the parcels appearing in clerk recordings, court
  records, and other primary signals).
- **`UNKNOWN`** — not yet classified.

`PER_RECORD_ONLY` is **not** a buildability blocker — a per-record source is still
usable. But it **is** a coverage constraint: such a source cannot enumerate the universe
of distressed properties, only resolve known parcel identifiers. Recon MUST surface this
constraint in `coverage_notes` and in `source_coverage_map.md` so build planning is not
surprised by it later.

---

## 16.H Operator-verified sources

When the operator manually surfaces a direct source link that recon missed, the link is
captured in `runs/<county_slug>/recon/operator_verified_sources.yml` as evidence. The
entry records the lead type, the official URL, how the operator confirmed it is
official, why recon missed it, and a review status.

This is a recon **supplement**, not an exception or an override. The framework does not
silently absorb operator overrides without provenance — the `operator_verified_sources`
entry is the provenance record. Subsequent recon runs should still attempt to discover
the source independently; the operator-verified entry documents that a human found it,
it does not exempt the source from verification.

---

## 16.I Five-layer verification per lead type per source

Each candidate source is run through the framework's five-layer verification gate — but
applied **per lead type**, because a source may be a valid primary source for one lead
type and merely a reference for another:

- **Layer 1 — Authority.** The source is operated by, or officially linked from, the
  county / state / court / tax / sheriff authority.
- **Layer 2 — Lead-type relevance.** The source actually publishes *this* lead type, not
  merely generic county records.
- **Layer 3 — Access.** The source can be searched or pulled lawfully under its
  documented `access_status`.
- **Layer 4 — Extractability.** The source yields enough fields to originate a real lead
  event — at minimum a property identifier or address, a party, and an event date.
- **Layer 5 — Refresh and provenance.** The source can be refreshed on the cadence the
  build needs, links back to verifiable proof, and is traceable per row.

The per-layer outcome is recorded in each `candidateSource.verification_layers` object
(`authority`, `lead_type_relevance`, `access`, `extractability`, `refresh_provenance`).

---

## 16.J Universal versus county-specific separation

- **Universal** — the matrix schema, the status / source-role / access-status /
  bulk-availability enums, the five-layer verification model, and the required-artifact
  list. These live in this file and in `config/counties/_schema.json`. They contain no
  county-specific URLs, vendor names, or examples.
- **County-specific** — the matrix *instances*: the actual sources, URLs, vendors,
  fingerprints, and verdicts for a given county. These live under
  `runs/<county_slug>/recon/` and never in universal framework files.

This file therefore contains no county name, no state-specific instruction, and no
portal URL. The county-agnostic regression scanner
(`scaffold/tests/test_county_agnostic_regression.py`) enforces this.
