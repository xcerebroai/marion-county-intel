# 04 — Deal Path Classifier

The deal path classifier is the bridge between **what fired on a parcel** (patterns + attributes + lifecycle stage + title complexity) and **which client persona should call it**.

Supported deal paths:

```
wholesale            — assignment or double-close exit
flip                 — buy, renovate, retail resale
sub_to               — take title subject to existing loan
seller_finance       — buy with seller acting as bank
partial_interest     — buy out one or more co-owners
messy_title          — clear title cloud, then exit
rental_acquisition   — buy and hold for cash flow
dispo_only           — already-controlled inventory routed to buyer outreach
do_not_pursue        — known-blocker conditions; skip
```

The first six are the original client personas. `rental_acquisition`, `dispo_only`, and `do_not_pursue` are operational paths — `rental_acquisition` for buy-and-hold investors who want different filters than flippers, `dispo_only` for inventory the operator already controls (skip-trace and re-marketing rather than acquisition), `do_not_pursue` for properties with hard blockers (active bankruptcy stay, condemned without rehab path, etc.) where any deal path is currently infeasible.

Every lead must emit at least one suggested deal path. A lead with no deal path is incomplete and routes to review.

---

## How it works

For each lead, the classifier evaluates rules across multiple dimensions:
1. **Patterns** that fired (from `domain/01_lead_types.md`)
2. **Attributes** that fired (high_equity, absentee, etc.)
3. **Lifecycle stage** (from `domain/09_document_lifecycle.md`) — early-stage foreclosure routes differently than imminent-sale-stage
4. **Title complexity** (from `domain/10_title_complexity.md`) — gates which paths are operationally viable

Each rule produces a `(deal_path, confidence, rationale)` tuple where confidence is `high` / `moderate` / `low`. A single lead can emit multiple deal paths (a foreclosure + tax + estate stack might fire wholesale-high, sub-to-high, and partial-interest-high simultaneously).

Output format on each lead:

```json
{
  "suggested_deal_paths": [
    {"path": "sub_to", "confidence": "high", "rationale": "foreclosure stage=sale_scheduled + Ch 13 stay; title_complexity=Light, sub-to entry viable"},
    {"path": "wholesale", "confidence": "high", "rationale": "high_equity proxy + absentee; title_complexity=Light supports wholesale timeline"},
    {"path": "partial_interest", "confidence": "low", "rationale": "single owner; not a fit"}
  ]
}
```

The dashboard shows the highest-confidence path as the primary chip, with secondary paths visible on hover or in the expanded detail view.

---

## Wholesale rules

A lead fires `wholesale candidate` when the parcel has both **motivation** and **equity**.

**Motivation signals (any of):**
- `foreclosure` pattern (any subtype)
- `tax` pattern (any subtype)
- `estate` pattern (any subtype)
- `code` pattern (any subtype)
- `divorce` pattern with property
- `tired_landlord` derived

**Equity signals (any of):**
- `high_equity` attribute
- `long_term_owned` (15+ yrs) — heuristic for likely paid-down or paid-off
- Assessed value at least 1.5× recorded mortgage balance (when clerk mortgage data available)
- `free_and_clear` attribute

**Confidence:**
- **High:** motivation + at least 2 equity signals
- **Moderate:** motivation + 1 equity signal
- **Low:** motivation only, no equity confirmation
- **Skip:** no motivation OR confirmed low equity (mortgage balance >= assessed value)

**Rationale template:** `"<motivation> + <equity signals> = wholesaler can offer 70-80% ARV minus repairs and leave room"`

---

## Flip rules

A lead fires `flip candidate` when the parcel has **equity spread**, **renovation potential**, and **resale market viability**.

**Equity spread signals:**
- Same as wholesale (high_equity, long_term_owned, free_and_clear, assessed > mortgage)

**Renovation-potential signals (any of):**
- `code` pattern with subtype `Open Code Violation` or `Vacant Property Registration` (cosmetic distress)
- `estate` pattern (often dated properties from older owners)
- Year built > 35 years ago + low assessed-to-land ratio (deferred maintenance proxy)

**Resale-market viability:**
- Property class is residential SFR (most flippable)
- Property is not condemned (excluded if `code` subtype is `Condemnation Notice` or `Demolition Order`)
- Acreage is typical residential (< 1 acre for SFR, varies for rural counties)

**Confidence:**
- **High:** equity spread + renovation potential + residential SFR
- **Moderate:** equity spread + renovation potential, non-SFR
- **Low:** equity OR renovation alone
- **Skip:** condemned property OR commercial/industrial use

**Rationale template:** `"<equity spread> + <renovation signal> + residential SFR = flip spread likely after repairs"`

---

## Sub-to rules

A lead fires `sub_to candidate` when there is **payment pressure** and a **favorable existing loan** (or proxy for one).

**Payment-pressure signals (any of):**
- `foreclosure` pattern (especially Notice of Sale, Sheriff Sale, Final Judgment)
- `bankruptcy` pattern (especially Foreclosure-Stay)
- `tax` pattern + recent filing (90 days)
- Mortgage arrears recorded at clerk

**Favorable-loan signals (any of):**
- Last sale date 2020-01-01 to 2022-06-30 (the era of sub-3% rates) — strong proxy
- Last sale date 2009 to 2015 (sub-5% era) — moderate proxy
- Confirmed mortgage rate from clerk (rare but definitive)

**Property-condition signals:**
- Property is livable or rentable (no condemnation, no demo order)
- Year built indicates standing structure

**Confidence:**
- **High:** payment pressure + favorable-loan era + livable property
- **Moderate:** payment pressure + neutral-loan era + livable
- **Low:** payment pressure alone
- **Skip:** condemned, demolished, vacant land, no payment pressure

**Rationale template:** `"<payment pressure> + last sale <YYYY> (favorable rate era) + livable = sub-to candidate"`

---

## Seller-finance rules

A lead fires `seller_finance candidate` when the parcel is **likely free-and-clear** and the owner has **income-or-exit motivation**.

**Free-and-clear signals (any of):**
- `free_and_clear` attribute (when clerk mortgage data available)
- `long_term_owned` 25+ yrs (heuristic — most 30-year mortgages paid off)
- Last sale price > 80% of assessed value AND last sale date > 25 yrs ago
- No `mortgage` recording in clerk data within ownership tenure

**Motivation signals:**
- `tired_landlord` derived
- `estate` pattern with single heir (heir wants income, not lump sum + tax hit)
- `senior_owner` attribute fires
- `multiple_properties` + recent sale of another property in same owner's portfolio (downsizing signal)

**Confidence:**
- **High:** free-and-clear + tired_landlord OR senior_owner + multiple_properties
- **Moderate:** free-and-clear + 1 motivation signal
- **Low:** free-and-clear alone, no motivation
- **Skip:** confirmed mortgage OR recent purchase (< 5 yrs)

**Rationale template:** `"<free_and_clear evidence> + <motivation> = owner may accept payments over lump sum"`

---

## Partial-interest rules

A lead fires `partial_interest candidate` when **multiple owners** are on record AND there is at least one **fractionalization signal**.

**Multiple-owner signals:**
- 2+ grantees on most recent recorded deed
- `estate` pattern with multiple heirs declared
- `transfer` subtype `Quitclaim Deed` with consideration ≤ $10 (often heir-to-heir conveyance)

**Fractionalization signals (any of):**
- `estate` pattern (probate or affidavit of heirship)
- Quiet title case in court docket
- Partition lawsuit in court docket
- Tax delinquent + multiple owners (often owners can't agree to pay)
- Different mailing addresses for different owners

**Confidence:**
- **High:** multiple owners + 2+ fractionalization signals
- **Moderate:** multiple owners + 1 fractionalization signal
- **Low:** multiple owners alone
- **Skip:** single owner

**Rationale template:** `"<owner count> owners + <fractionalization signals> = buy-out or partition opportunity"`

**Critical rule:** Partial-interest leads must NOT be auto-marked as clean acquisition leads. The classifier flags the candidate; the operator's client (specialist investor) handles ownership-share research before contacting.

---

## Messy-title rules

A lead fires `messy_title candidate` when the property has a **title cloud** that scares retail buyers but is **resolvable**.

**Title-cloud signals (any of):**
- Multiple recorded liens without discharges
- Old judgment liens (> 3 years, no satisfaction)
- Unreleased mortgages from past sales (chain-of-title issue)
- `estate` pattern without distribution
- Multiple grantor names across recent deeds (chain confusion)
- Quiet title pending

**Resolvable signals:**
- Liens are monetary (can be negotiated/settled), not statutory (eminent domain, etc.)
- Estate path exists (heirs identifiable, no missing-heir signal)
- Owner is alive and reachable

**Confidence:**
- **High:** 3+ title-cloud signals + resolvable
- **Moderate:** 2 title-cloud signals + resolvable
- **Low:** 1 title-cloud signal
- **Skip:** unresolvable (missing heir with no probate path, eminent domain, etc.)

**Rationale template:** `"<cloud signals> = retail buyers will pass; messy-title specialist can clear and resell"`

---

## Edge cases

### Surplus owed

`surplus_owed` pattern routes to a separate persona (surplus-recovery operator, not one of the six core personas). Flag with `deal_path: "surplus_recovery"` and route to a separate dashboard tile. Do not include in the standard six-path classifier.

### Pure enrichment without patterns

A parcel with only attributes (`absentee`, `out_of_state`, `long_term_owned`) and zero patterns is NOT a lead. The framework does not generate "potential motivated seller" leads from attributes alone. This is the rule that prevents the v2 mistake of flooding the dashboard with parcel-master rows. Attributes are decoration; patterns are events.

### Conflicting deal paths

A lead can fire `wholesale-high` AND `flip-high` simultaneously (they're not exclusive — investor decides which exit). The classifier emits all qualifying paths; the dashboard shows them as a sortable list per lead.

A lead can fire `sub_to-high` AND `seller_finance-high` only when the loan-status data is ambiguous; the operator's client reads the rationale and picks. The framework doesn't force a single answer when the data supports multiple.

### No deal path fires

If a lead has zero qualifying deal paths after running all six rules, the lead is incomplete and routes to review queue with reason `no_deal_path_classified`. The reviewer either adds missing data, flags as unsupported, or marks as low-priority archive.

---

## Implementation note

The classifier lives in `pipeline/deal_path_classifier.py` and is called by `pipeline/build_leads.py` after scoring. It writes `suggested_deal_paths[]` onto each record in `leads.json`. The dashboard reads this array directly — no client-side classification.

This means the classifier rules can change in one place (this file's logic) and propagate through the next refresh without dashboard changes.
