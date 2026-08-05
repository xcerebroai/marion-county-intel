# 13. Lead origination contract (v5.2.0+)

The lead origination contract defines what produces a lead. It is the rule that keeps the
framework a lead intelligence harness and not a parcel dashboard.

This file is the architecture-level contract. `MASTER_PROMPT.md §4.33` carries the
hard-constraint summary that every build session must obey; this file is the full
specification §4.33 points to.

This contract is **consolidating, not greenfield.** The framework already states earlier
versions of these rules across several MASTER_PROMPT.md §4.x sections (§4.10, §4.13,
§4.14, §4.16, §4.17, §4.21). §13.10 maps each of them. This document's job is to (a)
consolidate those scattered rules into one authoritative statement, (b) elevate the
EVENT-vs-STATE primary/enrichment distinction explicitly, and (c) define the migration
policy for non-compliant builds.

---

## 13.0 Status and scope

- **Version:** v5.2.0 (introduces clerk-driven lead origination as a framework-level hard
  rule, consolidating the pre-existing §4.x rules).
- **Date:** 2026-05-17.
- **Authoritative for:** every county build, every source ingestion, every dashboard or
  export output the framework produces.
- **Supersedes:** any prior implicit rules about what produces a lead row. As a
  CONSOLIDATED CONTRACT it is the authoritative statement of the lead origination
  principle over MASTER_PROMPT.md §4.10, §4.13, §4.14, §4.16, §4.17, and §4.21 — those
  sections are NOT deleted; they remain valid as detailed implementation references
  (§13.10). Pre-v5.2.0 builds may not comply and must be re-evaluated or
  explicitly archived (§13.11).
- **Scope:** defines what counts as a primary lead source, what counts as enrichment, the
  hard rule that enrichment alone cannot create a lead row, the row provenance rule,
  partial-board labeling requirements, permitted output modes, and forbidden patterns.

This document does NOT define implementation. The v5.2.0 patches that implement and
enforce it — Build Eligibility Gate, Auto-Resolve Protocol, Lead Taxonomy, Dashboard
Contract, Self-Verification Gate, Watchdog + Rollback — are separate and reference this
contract (§13.13).

---

## 13.1 The product principle

The framework is a **clerk-driven county lead intelligence harness.** It is not a parcel
dashboard, not an assessor dashboard, not a GIS dashboard, not a tax-roll viewer, and not
a lead-count tool.

Every lead row originates from a **primary recorded distress event.** Enrichment
decorates leads; enrichment does NOT create leads.

If primary sources are blocked or absent, the system does NOT fill the dashboard with
parcel records to look alive. It stops, or it ships a clearly labeled partial output. An
empty-but-honest board beats a full-but-fabricated one — the same principle the prime
directive states for synthetic data, applied to source composition.

---

## 13.2 Primary lead sources (lead-originating)

A **primary lead source** is an EVENT recorded by an official authority — clerk,
recorder, court, sheriff, or equivalent — that signals distress, transfer, encumbrance,
or change of legal status on real property. Only primary lead sources can create a lead
row.

The canonical primary lead source categories:

    1.  County clerk records / recorder records / official recorded documents
    2.  Court events (case filings, judgments, decrees)
    3.  Foreclosure filings
    4.  Sheriff sale records
    5.  Lis pendens
    6.  Tax liens (federal, state, local)
    7.  Tax delinquency events
    8.  Tax sale certificates
    9.  Judgments (any type, when recorded)
    10. Probate records
    11. Estate records
    12. Affidavits of heirship
    13. Executor deeds
    14. Administrator deeds
    15. Construction liens / mechanic's liens
    16. Hospital liens
    17. Child support liens
    18. Code liens / code violations
    19. Demolition records
    20. Condemnation records
    21. Recorded notices (distress-related)
    22. Bankruptcy filings (where publicly recorded)
    23. Divorce filings (where publicly recorded and tied to property)
    24. Eviction filings (where publicly recorded and tied to property)

Plus a catch-all: **any other official distress event recorded by the clerk, recorder,
court, or equivalent primary authority.** The category list is not a closed enumeration —
the unifying property is the test.

**Unifying property:** a primary lead source is an EVENT recorded by an official
authority that signals distress, transfer, encumbrance, or change of legal status on real
property. If a candidate source is not an officially-recorded event, it is not a primary
lead source — it is enrichment (§13.3) or it is out of scope.

---

## 13.3 Enrichment sources (lead-decorating only)

An **enrichment source** is STATE data about a property or its owner. It describes what
the property IS, not what HAPPENED to it. Enrichment cannot create a lead row. It
attaches to, qualifies, and filters existing leads.

The enrichment source categories:

    1.  Parcel data (assessor parcel records, parcel master files, parcel boundaries)
    2.  GIS data (geographic boundaries, zoning, flood zones, etc.)
    3.  Assessor data (assessed value, property class, exemptions)
    4.  Tax roll data (tax bill records, payment history when NOT in delinquency)
    5.  MOD IV data (a state-level parcel data extract) and equivalent state-level parcel records
        in other jurisdictions
    6.  Ownership data (current legal owner, mailing address)
    7.  Valuation data (assessed, market, equity estimates)
    8.  Absentee owner indicators (out-of-county, out-of-state, foreign address)
    9.  Estate-owner indicators (LLC names, trust names, estate-of names)
    10. Deceased-owner indicators (death records cross-referenced)
    11. Vacancy indicators (utility data, USPS vacancy, visual inspection)
    12. Property attributes (beds, baths, year built, square footage, lot size,
        property type)
    13. Equity proxies (estimated equity, loan-to-value)
    14. Skip trace data (phone, email, alternate addresses)

**Unifying property:** enrichment is STATE data about a property or owner — what the
property IS. It is not an EVENT. A tax-roll record is enrichment; a tax-delinquency event
is a primary lead source. A parcel's assessed value is enrichment; a recorded tax lien on
that parcel is a primary lead source. The same property can carry both — the distinction
is event-vs-state, not source-vs-source.

---

## 13.4 The hard rule — enrichment alone cannot create a lead row

**HARD RULE 13.4.1.** Every dashboard row, every CSV export row, and every operator-facing
lead artifact MUST be born from at least one verified primary lead event (§13.2). A row
with only enrichment data and no primary lead event is FORBIDDEN as an active lead.

**HARD RULE 13.4.2.** A parcel record alone is NOT a lead. An assessor record alone is NOT
a lead. A GIS polygon alone is NOT a lead. A tax-roll record alone (without delinquency)
is NOT a lead. A MOD IV or state parcel-transfer record alone is NOT a lead. An LLC
ownership detection alone is NOT a lead. A vacancy detection alone is NOT a lead. An
out-of-state owner detection alone is NOT a lead.

What §13.3 enrichment CAN do:

- **Attach** to a lead row that already exists, as enrichment — decorating it with owner,
  value, vacancy, equity, contactability, and property-attribute context.
- **Filter** within a lead board — an operator may narrow a board to absentee owners, to
  high-equity parcels, to LLC owners, and so on.
- **Inform recon** — enrichment-only data is legitimate operator background research and
  legitimate recon output (§13.8 `ENRICHMENT_ONLY`).

What §13.3 enrichment CANNOT do: originate a row. No quantity of enrichment, however
rich, promotes a property to a lead. Only a §13.2 event does.

---

## 13.5 The row provenance rule

**HARD RULE 13.5.1.** Every Matched lead row (per `09_output_schemas.md` record type 4)
MUST contain at least one signal from a primary lead source as defined in §13.2. The
signal MUST carry source provenance — `source_id`, `source_url`, recorded date / event
date, and a raw document reference — sufficient for an operator to verify the event
independently.

**Verification implication.** If a lead row's signals are inspected and ZERO of them
originate from a §13.2 category, the row is INVALID and MUST NOT appear in any active
lead output. This is a checkable property: it operates on the `signals[]` of a Matched
lead and the primary-vs-enrichment classification of each signal's source.

This rule does not change the evidence ledger. It is a constraint on lead-row
*composition*; the per-field provenance ledger (§13.9, `08_evidence_ledger.md`) is the
mechanism by which a signal's provenance is recorded and audited. It is also the
consolidated authoritative form of the pre-existing MASTER_PROMPT.md §4.17 rule
("If there is no event proof, the row does not exist as a lead row") — see §13.10.

---

## 13.6 Partial board rules

A partial board ships real leads from the primary sources that ARE working, while being
explicit that coverage is incomplete.

**Partial board ALLOWED when:**

- at least one verified primary lead source is available and producing signals;
- other primary sources are blocked, unavailable, or pending;
- enrichment is attached only to the available primary signals.

**Partial board REQUIRED LABELING — visible to both operator and client:**

- the label "Partial Lead Board";
- the list of available primary sources (e.g. "Sheriff Sale only");
- the list of blocked / pending primary sources, with reason (e.g. "Clerk records
  blocked — pending public-records request / CAPTCHA resolution");
- the statement "Enrichment attached only to verified lead events";
- the statement "Not full county coverage".

**Partial board FORBIDDEN patterns:**

- hiding the partial status;
- showing enrichment data without an attached primary signal;
- allowing CSV export without a partial-status header row;
- allowing the dashboard to render without a partial-status banner.

A partial board is honest and shippable. A board that is partial but presented as
complete is a fabrication and is forbidden. This section is the consolidated authoritative
form of the pre-existing MASTER_PROMPT.md §4.16 Partial Build Contract (§13.10).

---

## 13.7 Forbidden patterns

**FORBIDDEN 13.7.1.** Showing parcel records, assessor records, MOD IV records, tax-roll
records, or any other §13.3 enrichment as standalone lead rows.

**FORBIDDEN 13.7.2.** Treating nominal transfer data — deed transfers with no distress
signal, e.g. routine arm's-length sales, family transfers, refinance recordings — as
distress events.

**FORBIDDEN 13.7.3.** Filling a dashboard with enrichment rows when the primary source is
blocked.

**FORBIDDEN 13.7.4.** Calling an enrichment-only output a "lead board" or "lead
dashboard".

**FORBIDDEN 13.7.5.** Producing dashboard output without a build-eligibility
classification (the Build Eligibility Gate — MASTER_PROMPT.md §4.10, extended by a
forthcoming v5.2.0 patch).

**FORBIDDEN 13.7.6.** Showing internal source codes (e.g. "jfc", "tax", "lien",
"transfer") in operator-facing or client-facing UI. Use operator-readable lead type
names — restating MASTER_PROMPT.md §4.13, to be formalized by `canonical_lead_types.json`
in a forthcoming v5.2.0 patch.

**FORBIDDEN 13.7.7.** Visually elevating enrichment to look equivalent to lead events.
Lead types render as chips; enrichment attributes render as smaller badges or icons —
the visual hierarchy must make the event-vs-state distinction obvious at a glance.

---

## 13.8 Permitted output modes

Every county build produces exactly one of these output modes. The mode must be declared,
not implied.

**`READY_TO_BUILD`** — a full active lead dashboard.

- real event-based rows from primary sources;
- enrichment attached;
- no partial-status banner.

**`PARTIAL_LEAD_BOARD`** — an active lead dashboard with partial coverage.

- real event-based rows from the available primary sources only;
- enrichment attached only to those rows;
- partial-status banner required (§13.6).

**`RECON_ONLY`** — NOT a lead dashboard.

- labeled "Recon Only", clearly distinguished from a lead board;
- may contain source-discovery notes, enrichment samples, and what-is-blocked findings;
- MUST NOT be exported as a lead CSV or pitched as lead intelligence.

**`ENRICHMENT_ONLY`** — NOT a lead dashboard.

- labeled "Enrichment Only", clearly distinguished from a lead board;
- may contain parcel / owner / property data without attached primary signals;
- MUST NOT be exported as a lead CSV or pitched as lead intelligence;
- useful for operator background research, NOT for client delivery as leads.

**`NO_BUILD`** — no active dashboard.

- a `VERIFICATION_FAILURE.md` or `BUILD_NOT_READY.md` report explaining why;
- a list of attempted primary source paths and their resolution status.

### 13.8.1 Build-status outcomes (build-eligibility classification)

Distinct from the five *output modes* above, the v5.2.0 **Build Eligibility Gate**
classifies a build ATTEMPT — before building — into one of five **build-status
outcomes**:

    READY_TO_BUILD             primary sources verified; full board buildable
    PARTIAL_LEAD_BOARD         some primary sources working; partial board buildable
    WAITING_ON_PRIMARY_SOURCE  primary sources pending auto-resolve / operator action
    RECON_ONLY                 only recon/enrichment discovery is possible right now
    NOT_BUILDABLE_YET          no primary lead path available; no board

These are two related five-value vocabularies — output modes (what the system PRODUCES)
and build-status outcomes (the eligibility classification BEFORE building). They share
`READY_TO_BUILD`, `PARTIAL_LEAD_BOARD`, and `RECON_ONLY`, and differ on the remaining two
(`WAITING_ON_PRIMARY_SOURCE` / `NOT_BUILDABLE_YET` vs. `ENRICHMENT_ONLY` / `NO_BUILD`).

**A third vocabulary already exists:** MASTER_PROMPT.md §4.10 (Build Eligibility Gate)
defines `build_verdict` values `READY_TO_BUILD` / `READY_WITH_BLOCKERS` / `RECON_ONLY` /
`WAITING_ON_ACCESS` / `NOT_BUILDABLE_YET`. The build-status outcomes above are a v5.2.0
re-statement of that existing verdict set with two values renamed
(`READY_WITH_BLOCKERS` → `PARTIAL_LEAD_BOARD`, `WAITING_ON_ACCESS` →
`WAITING_ON_PRIMARY_SOURCE`). **Unifying these vocabularies is an open question** (§13.12),
owned by the Build Eligibility Gate patch — Patch 1 records all three rather than
silently collapsing them.

---

## 13.9 Relationship to existing framework concepts

- **Matched lead** (`09_output_schemas.md` record type 4) — the lead row. This is the
  artifact §13.4 and §13.5 govern. Every Matched lead MUST contain at least one §13.2
  primary signal. This contract does not change the Matched lead schema; it constrains
  what may legally appear in it.
- **Evidence ledger** (`08_evidence_ledger.md`) — per-field provenance. UNCHANGED by this
  contract. The term "evidence" remains reserved for the per-field provenance ledger
  (`evidence_id`, `field`, `value`, `status`, `source_reliability_grade` A–E); it is NOT
  reused to mean the lead row. The row provenance rule (§13.5) and the evidence ledger
  are complementary: §13.5 governs row composition, the ledger records field provenance.
- **Entity resolution** (`12_entity_resolution.md`) — how signals match to parcels. A
  §13.2 signal is matched to a parcel where possible; this contract does not change
  resolution, it adds the requirement that at least one signal on a Matched lead be
  primary-sourced. Parcel resolution is NOT a gate on lead existence — a lead whose
  parcel could not be resolved is still emitted (`parcel_resolution_status = UNRESOLVED`)
  with its debtor name, signal, and source provenance retained. See §13.14.
- **Signals** (translator output) — events emitted by translators. Signals from §13.2
  sources are lead-originating. Signals from §13.3 sources, if a translator emits any,
  are enrichment-only and CANNOT independently produce a Matched lead.
- **`source_role`** — this field ALREADY EXISTS in the framework. MASTER_PROMPT.md §4.7
  (Five-Layer Source Verification Gate, Layer 4) and §4.17 use `source_role` with values
  `PRIMARY_LEAD_SOURCE` and `SUPPORTING_LEAD_SOURCE` (and §4.14 references a
  `BLOCKED_SOURCE` role). The §13.2/§13.3 primary-vs-enrichment distinction maps onto
  this existing field, but the existing value set has no explicit "enrichment" role —
  whether enrichment sources reuse `SUPPORTING_LEAD_SOURCE`, or a new
  `ENRICHMENT_SOURCE` value is added, is an open question (§13.12). This contract does
  NOT invent a new `source_role` field; it relies on the existing one.
- **Canonical doc types** (`canonical_doc_types.json`) — every canonical doc type must be
  classified primary or enrichment. This tagging is a task queued for the Lead Taxonomy
  patch or the implementation phase; this contract does not modify
  `canonical_doc_types.json`.

---

## 13.10 Relationship to existing MASTER_PROMPT.md sections

This contract consolidates rules that already exist, scattered, across MASTER_PROMPT.md
§4. Each related section is cited below with what it covers and how §13 relates to it.
**None of these sections is deleted.** §4.33 (the MASTER_PROMPT.md summary of this
contract) is the authoritative *statement of the principle*; the sections below remain
valid as detailed *implementation references*.

- **§4.7 — Five-Layer Source Verification Gate.** Layer 4 establishes the `source_role`
  field (`PRIMARY_LEAD_SOURCE` / `SUPPORTING_LEAD_SOURCE`). §13.2/§13.3 build the
  event-vs-state primary/enrichment distinction on top of this existing field (§13.9).
- **§4.10 — Build Eligibility Gate.** Defines `build_verdict` (`READY_TO_BUILD` /
  `READY_WITH_BLOCKERS` / `RECON_ONLY` / `WAITING_ON_ACCESS` / `NOT_BUILDABLE_YET`) and
  the authorization rule for entering Build Mode. §13.8.1's build-status outcomes are a
  v5.2.0 re-statement of this verdict set; FORBIDDEN 13.7.5 restates the gate requirement.
  Reconciliation of the two verdict vocabularies is owned by the v5.2.0 Build Eligibility
  Gate patch (§13.12).
- **§4.13 — Operator-readable lead names.** Forbids internal lead codes in operator/
  client UI and lists required readable names. FORBIDDEN 13.7.6 restates this; the
  forthcoming `canonical_lead_types.json` (Lead Taxonomy patch) supersedes the inline
  list with a maintained registry.
- **§4.14 — Phase 0.5 Auto-Resolve Blockers.** Attempts approved resolution paths for
  blocked primary sources before a stop verdict. The v5.2.0 Auto-Resolve Protocol patch
  builds on this; a source pending auto-resolve maps to the §13.8.1 build-status
  `WAITING_ON_PRIMARY_SOURCE`.
- **§4.16 — Partial Build Contract.** Already states that a build may proceed from one
  primary source while marking others pending, must label the dashboard, and "cannot
  fill the dashboard with enrichment records as leads." §13.6 is the consolidated
  authoritative form of this rule. (Note: §4.16 uses dashboard labels `PARTIAL_BUILD` /
  `SOURCE_LIMITED` / `PRIMARY_SOURCE_PENDING`; §13.6 uses the operator-facing label
  "Partial Lead Board" — label-vocabulary reconciliation is flagged in §13.12.)
- **§4.17 — Evidence-First Dashboard Row Contract.** Already states "every dashboard row
  must be created by a lead event" and "if there is no event proof, the row does not
  exist as a lead row. Parcel records alone cannot create dashboard rows." §13.4 and
  §13.5 are the consolidated authoritative form of this exact rule — §13 elevates it
  from a row-field contract to a stated origination principle and extends it with the
  explicit §13.2/§13.3 source taxonomy.
- **§4.21 — Production self-verification + watchdog + rollback.** Its Phase 6.5 check
  list already includes "No enrichment-only rows shown as leads." The v5.2.0
  Self-Verification Gate and Watchdog + Rollback patches enforce HARD RULE 13.5.1; §4.21
  is the contract they implement.
- **§4.27 — v5.2.0 deferred.** The existing placeholder acknowledging v5.2.0 work was
  intentionally not done in v5.1.0-beta. This contract is part of the v5.2.0 work that
  placeholder anticipated.

In short: §13 does not introduce the lead-origination principle — the framework already
held it in pieces. §13 names it, unifies it, and makes the EVENT-vs-STATE distinction the
explicit organizing rule.

---

## 13.11 Migration of pre-v5.2.0 builds

- Pre-v5.2.0 county builds may not comply with this contract.
- Before any further client delivery, each pre-v5.2.0 build MUST be re-evaluated against
  §13.2 / §13.3 / §13.4 / §13.5.
- A non-compliant build MUST be either:
  - **(a) Corrected** to v5.2.0 standards — remove rows with no §13.2 primary signal,
    apply partial-status labeling where coverage is incomplete, demote enrichment-only
    output to the `ENRICHMENT_ONLY` mode; or
  - **(b) Explicitly archived** as "pre-v5.2.0 build, does not meet current lead
    origination contract".
- After v5.2.0 is finalized, NO pre-v5.2.0 build may be presented as a current-standard
  lead board.

This contract does not perform any migration. It states the policy; the re-evaluation of
specific pre-v5.2.0 counties is separate operator work.

---

## 13.12 Open questions for operator review

1. **Property-tied distress events.** Should bankruptcy, divorce, and eviction filings
   always count as primary lead sources, or only when explicitly tied to a property
   record? Likely answer: only when property-tied — a divorce with no real-property
   nexus is not a real-estate lead. Marked **TBD**; §13.2 currently qualifies these
   three with "where publicly recorded and tied to property".
2. **`source_role` value set.** The existing `source_role` field (§4.7 / §4.17) has
   values `PRIMARY_LEAD_SOURCE` and `SUPPORTING_LEAD_SOURCE` (plus `BLOCKED_SOURCE`).
   Enrichment sources (§13.3) have no explicit role value. Should they reuse
   `SUPPORTING_LEAD_SOURCE`, or should a new `ENRICHMENT_SOURCE` value be added? And
   should the role be stamped at the source-config level (recommended — each translator
   is bound to one source) or per-record? Marked **TBD**.
3. **Minimum-evidence per primary lead type.** Should the contract specify a
   minimum-evidence requirement per primary lead type (e.g. a foreclosure signal must
   carry at least `source_url` + recorded date + grantor)? Likely yes — deferred to a
   future minimum-evidence-per-lead-type spec.
4. **Three related status vocabularies.** §13.8 defines five OUTPUT MODES
   (`READY_TO_BUILD` / `PARTIAL_LEAD_BOARD` / `RECON_ONLY` / `ENRICHMENT_ONLY` /
   `NO_BUILD`); §13.8.1 defines five BUILD-STATUS OUTCOMES (`READY_TO_BUILD` /
   `PARTIAL_LEAD_BOARD` / `WAITING_ON_PRIMARY_SOURCE` / `RECON_ONLY` /
   `NOT_BUILDABLE_YET`); and §4.10 already defines five `build_verdict` values
   (`READY_TO_BUILD` / `READY_WITH_BLOCKERS` / `RECON_ONLY` / `WAITING_ON_ACCESS` /
   `NOT_BUILDABLE_YET`). All three must be preserved for now. The operator should confirm
   whether all three should exist as distinct vocabularies, or be unified — reconciliation
   is owned by the Build Eligibility Gate patch. §4.16's dashboard labels (`PARTIAL_BUILD`
   / `SOURCE_LIMITED` / `PRIMARY_SOURCE_PENDING`) are a fourth, related label set.
5. **Overlap with existing MASTER_PROMPT.md sections.** §13.10 maps §4.10, §4.13, §4.14,
   §4.16, §4.17, §4.21 and frames §4.33 as the consolidated authoritative contract.
   Whether the §4.x sections should eventually be trimmed to pure implementation detail
   (with the principle removed and left to §4.33) — or left fully intact — is **not
   resolved in Patch 1** and should be addressed as the v5.2.0 milestone proceeds.

---

## 13.13 Closing

This contract is the foundation of the v5.2.0 milestone. It defines what a lead IS — an
officially-recorded distress event — and what a lead is NOT — enrichment, state data, a
parcel record dressed up to look alive. It does not invent that principle; it consolidates
the pieces already present in MASTER_PROMPT.md §4.10/§4.13/§4.14/§4.16/§4.17/§4.21 (§13.10)
into one authoritative statement and makes the EVENT-vs-STATE distinction explicit.

The subsequent v5.2.0 patches implement and enforce the rules defined here:

- **Build Eligibility Gate** — classifies each build into a build-status outcome
  (§13.8.1), reconciles the verdict vocabularies, and refuses dashboard output without
  that classification (FORBIDDEN 13.7.5).
- **Auto-Resolve Protocol** — attempts to unblock primary sources before declaring
  `WAITING_ON_PRIMARY_SOURCE` or `NOT_BUILDABLE_YET`.
- **Lead Taxonomy** (`canonical_lead_types.json`) — supplies the operator-readable lead
  type names FORBIDDEN 13.7.6 requires, and the primary/enrichment tagging §13.9 calls
  for.
- **Dashboard Contract** — enforces the partial-board labeling (§13.6) and the
  chip-vs-badge visual hierarchy (FORBIDDEN 13.7.7).
- **Self-Verification Gate** — checks HARD RULE 13.5.1 (every row has a primary signal)
  before output is written.
- **Watchdog + Rollback** — monitors production builds for drift away from this
  contract.

Every one of those patches references this file. Get §13.4 and §13.5 right, and the rest
of v5.2.0 has a foundation to stand on.

---

## 13.14 v5.3.0 amendment — primary sources are never enrichment-gated

A primary event source originates a lead at the moment its record is recognized as a
distress event. Subsequent parcel/owner enrichment from an enrichment-only source (CAD
enrichment, GIS, tax-roll enrichment, assessor enrichment, a parcel/owner valuation API)
attaches context to the lead but **never gates its existence**.

Two status fields are tracked separately:

- **`parcel_resolution_status`** — whether the primary-source record has been linked to
  a county-canonical parcel identifier.
- **`enrichment_status`** — whether enrichment sources have attached supplementary data
  (situs address, assessed value, owner type, absentee / homestead flags).

A lead MUST NOT be dropped or hidden because enrichment failed. A lead MAY be marked
`UNRESOLVED` when no parcel can be linked, but the lead row remains in the dashboard with
its identifying fields (debtor name, signal, source URL) and source provenance.

### 13.14.1 Status decoupling matrix

`parcel_resolution_status` has three values — `RESOLVED`, `UNRESOLVED`, and
`REVIEW_REQUIRED` (the §17 routing value, distinct from both). `enrichment_status` has
two — `ENRICHED`, `UNENRICHED`. The four valid combinations:

    parcel_resolution_status   enrichment_status   meaning
    ------------------------   -----------------   ------------------------------------
    RESOLVED                   ENRICHED            fully enriched lead — parcel linked,
                                                   enrichment data attached
    RESOLVED                   UNENRICHED          parcel linked, but the enrichment
                                                   source returned no data
    UNRESOLVED                 UNENRICHED          neither — still emitted; debtor name,
                                                   signal, and source URL retained
    REVIEW_REQUIRED            UNENRICHED          debtor party could not be identified
                                                   (§17); routed to operator triage

`ENRICHED` requires a `RESOLVED` parcel — enrichment keys off the parcel identifier, so
`UNRESOLVED + ENRICHED` and `REVIEW_REQUIRED + ENRICHED` are not valid states.

### 13.14.2 Rationale

Enrichment sources have inherent coverage limits — per-record-only constraints, name-only
joins, page caps, suffix sensitivity. Gating leads on enrichment success means losing
leads that the primary event source legitimately surfaced. Foreclosure notices, for
example, carry property addresses in the source document directly — those leads are
buildable regardless of whether a separate enrichment join succeeds.

### 13.14.3 Cross-references

- **§17** (`17_debtor_party_rules.md`) — the `REVIEW_REQUIRED` `parcel_resolution_status`
  value and its routing contract are defined there.
- **§16** (`16_source_of_record_matrix.md`) — source role classification
  (`PRIMARY_EVENT_SOURCE` vs `ENRICHMENT_SOURCE`) is defined there; only a
  `PRIMARY_EVENT_SOURCE` originates a lead, and an `ENRICHMENT_SOURCE` only ever
  decorates one.
