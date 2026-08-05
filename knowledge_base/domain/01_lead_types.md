# 01 — Lead Types

The framework classifies every signal into one of 14 patterns. Each pattern has subtypes. Each subtype maps to one or more of the six client deal paths (wholesale, flip, sub-to, seller-finance, partial-interest, messy-title) defined in `00_client_business_model.md`.

This file is the canonical taxonomy. Scoring rules (`03_scoring_and_stacking.md`) reference the pattern keys exactly as written here.

**The pattern keys here correspond to the `lead_pattern` field on every entry in `knowledge_base/domain/canonical_doc_types.json`.** Raw recorder/court abbreviations are normalized to canonical document types per `08_document_normalization.md`, and each canonical type carries one of these patterns. **Raw abbreviations never carry patterns directly. Only canonical types do.**

---

## The 14 patterns

```
foreclosure          — pre-sale and at-sale distress
tax                  — tax delinquency, tax sale certificates, tax foreclosure
lien                 — non-tax liens (mechanic, construction, judgment, HOA, federal, state)
estate               — probate, heirship, inheritance-tax events
code                 — code enforcement, condemnation, demo orders
transfer             — distressed deed sub-types (quitclaim, sheriff's, executor's, etc.)
bankruptcy           — Ch 7/11/13 filings, foreclosure-stay bankruptcies
divorce              — family court filings affecting real property
eviction             — landlord-tenant filings (precursor to tired-landlord signal)
tired_landlord       — derived: eviction history + multi-property + landlord pain signals
surplus_owed         — post-foreclosure-sale surplus funds owed to former owner
commercial_distress  — receivership, ABC assignment, commercial foreclosure
title_issue          — partition, quiet title, adverse possession, ownership disputes
utility_distress     — water/sewer/utility liens or shutoff orders
```

---

## Pattern detail

### `foreclosure`

The strongest single signal. Highest call urgency.

**Subtypes:**
- `Lis Pendens` (LISPEN, NOTLIS, NTCELIS in clerk records) — foreclosure suit filed
- `Notice of Sale` (NTCSALE) — sale scheduled, typically 30–60 days out
- `Sheriff Sale` — actual auction listing
- `Sheriff's Deed` (post-sale, fires `transfer` too)
- `Final Judgment` (FINJUDGE) — court has ruled
- `Notice of Trustee Sale` (in non-judicial states) — comparable to Notice of Sale

**Callable for:** sub-to (strongest), wholesale (high), flip (moderate)

**Source:** county clerk recorded instruments, sheriff sales, court foreclosure dockets

**TTL:** 180 days from filing

---

### `tax`

Tax pressure is one of the most reliable seller-motivation signals. Tax balances are public, persistent, and growing (penalties + interest).

**Subtypes:**
- `Tax Delinquent` — owner is N years behind
- `Tax Sale Certificate` (TSC, MTSC) — third party has bought the tax debt
- `Federal Tax Lien` (FEDLIEN) — IRS lien recorded
- `State Tax Lien` (INSTLIEN, STATELIEN) — state department of revenue
- `In Rem` (INREM) — municipal in-rem foreclosure on tax debt
- `Tax Foreclosure Notice` — final notice before tax-foreclosure sale

**Callable for:** wholesale (high), flip (moderate), sub-to (low — usually no mortgage), partial-interest (high when stacked with multi-owner)

**Source:** tax collector / assessor delinquency rolls, county clerk tax-lien recordings

**TTL:** none (tax debt is persistent until paid or foreclosed)

---

### `lien`

A bucket for non-tax monetary judgments and liens. Signals seller pressure and often title-cloud opportunity.

**Subtypes:**
- `Construction Lien` (CONLIEN) — contractor unpaid
- `Mechanic's Lien` (MECHLIEN) — same family
- `Mechanic's Notice of Intent` (MECHNOI) — pre-lien warning
- `Hospital/Physician Lien` (PHYSLIEN) — medical debt against settlement or property
- `HOA Lien` — association assessments unpaid
- `Judgment Lien` (DSJUDLIEN, WAREXEC, WRITEXEC) — civil judgment recorded against property
- `Wage Claim Lien` (WAGECLM)
- `Stop Notice` (STOPNOT)
- `Brewery / Liquor Lien` (BRTYLIEN)

**Negative subtypes (de-escalation):**
- `Discharge of Lien` (DSCOLIEN, DSMELIEN, DPHYLIEN, DSJUDLIEN, WARSATFN) — cancels prior signal

**Callable for:** wholesale (moderate), messy-title (high when stacked), partial-interest (when multi-lien on one parcel)

**Source:** county clerk recorded instruments

**TTL:** none (liens persist until released)

---

### `estate`

Probate, heirship, and inheritance signals. The framework's highest-margin lead type because heirs are typically motivated, equity is often clean, and deals close fast.

**Subtypes:**
- `Probate Case Opened` — court petition for estate administration
- `Affidavit of Heirship` — recorded outside probate, declares heirs
- `Inheritance Tax Waiver` (TAXWAIVE) — state confirms estate cleared tax — often signals imminent transfer
- `Disclaimer` (DISCLAIM) — heir formally rejects inheritance share
- `Trust Agreement` (TRUSTAGR) — property moved to/from trust
- `Letters Testamentary` — court appoints executor
- `Notice to Creditors` — mandatory probate notice

**Callable for:** wholesale (high — heirs often want cash fast), partial-interest (very high — multiple heirs), seller-finance (moderate when single heir + property)

**Source:** probate / surrogate court, county clerk recorded affidavits

**TTL:** 365 days from filing

---

### `code`

Property-condition signals. Code enforcement, condemnation, demolition orders.

**Subtypes:**
- `Open Code Violation` — active citation
- `Condemnation Notice` — building unfit
- `Demolition Order` — city has ordered demo
- `Nuisance Determination` — repeated complaints
- `Vacant Property Registration` — required in some jurisdictions

**Callable for:** wholesale (high — distress signal), flip (moderate when cosmetic), messy-title (when stacked)

**Source:** municipal code enforcement (per-municipality scrapers required), county clerk recorded municipal liens

**TTL:** 365 days from notice

---

### `transfer`

Distressed deed sub-types. **Only fires from clerk DEED records** with sub-type metadata, never from parcel-master alone. (See `02_signals_and_sources.md` for why.)

**Subtypes:**
- `Quitclaim Deed` — no warranty, often family/distress
- `Sheriff's Deed` — post-foreclosure transfer (fires `foreclosure` too)
- `Executor's Deed` — estate transfer (fires `estate` too)
- `Administrator's Deed` — intestate estate transfer (fires `estate` too)
- `Deed in Lieu of Foreclosure` — voluntary transfer to lender
- `Estate Deed` — generic estate-grantor deed
- `Tax Deed` — post-tax-foreclosure transfer (fires `tax` too)

**Callable for:** wholesale (varies by sub-type), partial-interest (when fractional consideration), messy-title (when chain-of-title issues)

**Source:** county clerk DEED records with grantor/grantee/consideration/sub-type fields

**TTL:** 1095 days (3 years) from recording

**Critical rule:** A deed with consideration ≤ $10 from the parcel master is **enrichment metadata**, not a transfer signal. The clerk's recorded DEED with grantor/grantee/sub-type is the lead. Same data point, different source class.

---

### `bankruptcy`

Federal bankruptcy filings affecting real property.

**Subtypes:**
- `Chapter 7` — liquidation
- `Chapter 11` — reorganization (rare for individuals)
- `Chapter 13` — repayment plan
- `Foreclosure-Stay Bankruptcy` — Ch 13 filed to stop a foreclosure sale (sheriff PDFs often note this in the status field)

**Callable for:** sub-to (high — homeowner wants debt relief), wholesale (moderate — equity often low)

**Source:** PACER (paid), or sheriff sale status fields, or clerk bankruptcy notices

**TTL:** 720 days

---

### `divorce`

Family court filings where real property is at issue.

**Subtypes:**
- `Divorce Filing` (with property as marital asset)
- `Property Settlement Order`
- `Sale of Marital Home Order`

**Callable for:** wholesale (high — both parties often want out), sub-to (moderate)

**Source:** family court (often sealed; public-records fallback in some states)

**TTL:** 720 days

---

### `eviction`

Landlord-tenant filings. Standalone they're weak signals (the landlord is winning), but stacked with multi-property ownership they fire the `tired_landlord` derived pattern.

**Subtypes:**
- `Eviction Filing`
- `Writ of Possession`
- `Default Judgment for Possession`

**Callable for:** seller-finance (high — landlord ready to exit), sub-to (moderate)

**Source:** special civil / justice / magistrate court (varies by state, often no public docket)

**TTL:** 365 days

---

### `tired_landlord` (derived)

Not a primary source pattern. Fires when an owner has 2+ eviction filings in 24 months AND owns 3+ properties AND has at least one of: code violation, deferred maintenance signal, mailing address differs from any property.

**Callable for:** seller-finance (very high), sub-to (high)

**Source:** derived from `eviction` + `multiple_properties` + `code` signals

**TTL:** 365 days from most recent contributing signal

---

### `surplus_owed`

Post-foreclosure-sale surplus funds owed to the former owner. The owner is no longer in the property but has a recoverable claim. Niche but high-margin lead type.

**Subtypes:**
- `Sheriff Sale Surplus`
- `Tax Foreclosure Surplus`

**Callable for:** specialty surplus-recovery operators (a different client persona than the six core ones; flag and route separately)

**Source:** sheriff and clerk post-sale records

**TTL:** 1825 days (5 years — many states have multi-year claim windows)

---

### `commercial_distress`

Distress signals affecting commercial real estate or owner entities. Distinct from individual foreclosure because the lifecycle, parties, and deal paths differ.

**Subtypes:**
- `Receivership Order`
- `ABC Assignment` (Assignment for Benefit of Creditors)
- `Commercial Foreclosure`
- `Default Judgment` (against business borrower)
- `Secured Creditor Claim`

**Callable for:** wholesale (specialist commercial wholesalers), partial-interest (when ownership is fractional across business entities), messy-title (when receivership creates title-control issues)

**Source:** county clerk recordings, civil court (receivership), bankruptcy filings

**TTL:** 540 days

---

### `title_issue`

Litigation or filings whose purpose is resolving title questions. Strong messy-title and partial-interest signal.

**Subtypes:**
- `Partition Action` — lawsuit to force sale of co-owned property
- `Quiet Title Action` — litigation to clear title cloud
- `Adverse Possession Claim` — claim to title via long-term occupation
- `Boundary Dispute`
- `Cloud on Title` (general)

**Callable for:** partial-interest (very high — partition is partial-interest by definition), messy-title (very high), wholesale (low — most retail buyers won't take on)

**Source:** civil court dockets, county clerk recordings (lis pendens for these actions)

**TTL:** 720 days

---

### `utility_distress`

Utility-account distress that has been recorded against the property. Weak as a standalone signal, valuable when stacked with other distress.

**Subtypes:**
- `Water Lien`
- `Sewer Lien`
- `Utility Disconnect Order`

**Callable for:** wholesale (when stacked), seller-finance (when stacked with tired_landlord), messy-title (when stacked with multiple liens)

**Source:** municipal utility billing systems, county clerk recordings (when liens are recorded)

**TTL:** 365 days

---

## Parcel attributes (state-driven, not patterns)

These decorate every lead. They are not lead types. They are properties of the parcel that affect callability and deal-path classification.

```
vacant              — USPS / utility / code-noted vacancy
absentee            — mailing city ≠ situs municipality
out_of_state        — mailing state ≠ subject state
senior_owner        — proxy: long-term owned + age signal (where available)
long_term_owned     — 15+ years from deed date
free_and_clear      — no recorded mortgage (requires clerk mortgage data)
high_equity         — proxy: assessed >= 2× last sale price + 5+ years owned
entity_owned        — owner is LLC/Corp/Trust (regex on owner name)
multiple_properties — same owner on 3+ parcels in county
```

Attributes are computed by `pipeline/build_leads.py` from parcel-master enrichment data and joined to leads. They never generate a lead on their own (see `02_signals_and_sources.md`).

---

## Lead-type to deal-path mapping (fast lookup)

When the deal-path classifier (`04_deal_path_classifier.md`) runs, it consults this matrix:

| Pattern → | wholesale | flip | sub_to | seller_fin | partial_int | messy_title |
|-----------|-----------|------|--------|------------|-------------|-------------|
| foreclosure | high | moderate | **high** | low | low | moderate |
| tax | **high** | moderate | low | low | high (multi-owner) | moderate |
| lien | moderate | low | low | low | moderate | **high** |
| estate | high | moderate | low | moderate (single heir) | **high** | moderate |
| code | high | moderate | low | low | low | moderate |
| transfer | varies | low | low | low | high (fractional) | high (chain-of-title) |
| bankruptcy | moderate | low | **high** | low | low | low |
| divorce | high | moderate | moderate | low | moderate | moderate |
| eviction | low | low | low | moderate | low | low |
| tired_landlord | high | low | high | **high** | low | low |
| surplus_owed | n/a — separate persona | | | | | |
| commercial_distress | moderate | low | low | low | moderate | high |
| title_issue | low | low | low | low | **high** | **high** |
| utility_distress | low (stacks only) | low | low | low | low | moderate |

**Stacking amplifies.** A parcel with foreclosure + tax + estate isn't three separate leads. It's one lead with stack depth 3, and the deal-path classifier favors paths that benefit from multiple distress signals (sub-to and partial-interest both score higher when the stack is deep).
