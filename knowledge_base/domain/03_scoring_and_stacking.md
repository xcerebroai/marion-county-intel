# 03 — Scoring and Stacking

Every lead gets a score from 0–100. Every score has reasons. The score determines tier (Hot / Strong / Workable / Low / Archive), which determines what the operator's clients see at the top of their dashboard.

**Critical rule:** Only canonical document types from `canonical_doc_types.json` produce scores. Raw recorder/court abbreviations (`AOH`, `LIS PEND`, `NOD`, etc.) do not score directly. They score only after normalization to canonical types per `domain/08_document_normalization.md`. This prevents the same legal instrument from scoring inconsistently across counties.

**Score is one dimension. Title complexity (`domain/10_title_complexity.md`) is a separate dimension** that measures how hard the deal is to close, independent of seller motivation. Both dimensions render on the dashboard. The operator's client uses score to gauge motivation and complexity to gauge closeability.

**Lifecycle status from `domain/09_document_lifecycle.md` gates whether a signal contributes to score.** Signals marked `RELEASED`, `SATISFIED`, `DISCHARGED`, `DISMISSED`, `EXPIRED`, or `SUPERSEDED` do not score. Only `ACTIVE` signals count.

---

## Base scores by pattern

These are the starting points before stacking, attributes, or penalties.

### Foreclosure family

| Subtype | Base score | Notes |
|---|---|---|
| Notice of Trustee Sale | 45 | Imminent sale (non-judicial states) |
| Notice of Sale (judicial) | 45 | Sale date scheduled |
| Sheriff Sale (active listing) | 45 | Live auction record |
| Final Judgment | 40 | Court has ruled, sale forthcoming |
| Lis Pendens | 35 | Suit filed, may be 6–18 months from sale |
| Sheriff's Deed (post-sale) | 25 | Already sold — surplus_owed lead instead |

### Tax family

| Subtype | Base score | Notes |
|---|---|---|
| Tax Foreclosure Notice | 45 | Final notice before sale |
| In Rem Tax Foreclosure | 45 | Municipality has filed |
| Tax Sale Certificate sold | 35 | Third party owns the tax debt |
| Federal Tax Lien | 30 | IRS lien recorded |
| State Tax Lien | 25 | State revenue lien |
| Tax Delinquent (1+ year) | 35 | Owner is behind |

### Estate family

| Subtype | Base score | Notes |
|---|---|---|
| Probate Case Opened | 35 | Estate in active administration |
| Affidavit of Heirship | 35 | Heirs declared, no probate |
| Inheritance Tax Waiver | 30 | Estate cleared, transfer imminent |
| Disclaimer | 25 | Heir rejected share |
| Trust Agreement | 20 | Property in/out of trust |
| Executor's Deed | 25 | Estate transfer recorded (also fires `transfer`) |
| Administrator's Deed | 25 | Intestate estate transfer (also fires `transfer`) |

### Lien family

| Subtype | Base score | Notes |
|---|---|---|
| Construction Lien | 20 | Contractor unpaid |
| Mechanic's Lien | 20 | Same |
| Judgment Lien (Abstract of Judgment) | 25 | Civil judgment recorded |
| Federal Tax Lien | 30 | (overlaps tax — score under whichever fires first) |
| HOA Lien | 20 | Association unpaid |
| Hospital/Physician Lien | 20 | Medical debt |

### Code family

| Subtype | Base score | Notes |
|---|---|---|
| Demolition Order | 30 | City ordered demo |
| Condemnation Notice | 30 | Building unfit |
| Open Code Violation | 20 | Active citation |
| Vacant Property Registration | 20 | Required filing |

### Transfer family (clerk-recorded only)

| Subtype | Base score | Notes |
|---|---|---|
| Sheriff's Deed | 25 | Post-foreclosure (also fires `foreclosure`) |
| Executor's / Administrator's Deed | 25 | Estate transfer (also fires `estate`) |
| Tax Deed | 25 | Post-tax-foreclosure |
| Quitclaim Deed | 20 | No-warranty transfer |
| Deed in Lieu | 25 | Voluntary transfer to lender |

### Bankruptcy

| Subtype | Base score | Notes |
|---|---|---|
| Foreclosure-Stay Bankruptcy | 35 | Ch 13 filed to stop a sale |
| Chapter 7 | 30 | Liquidation |
| Chapter 13 | 25 | Repayment plan |
| Chapter 11 | 25 | Reorganization |

### Divorce

| Subtype | Base score | Notes |
|---|---|---|
| Divorce Filing (with property) | 20 | Marital home at issue |
| Sale of Marital Home Order | 30 | Court has ordered sale |

### Eviction / Tired Landlord

| Subtype | Base score | Notes |
|---|---|---|
| Eviction Filing (single) | 5 | Weak alone |
| `tired_landlord` derived | 30 | Multi-eviction + multi-property + signal |

### Surplus Owed

| Subtype | Base score | Notes |
|---|---|---|
| Sheriff Sale Surplus | 30 | Niche persona |
| Tax Foreclosure Surplus | 30 | Same |

---

## Stack bonuses

Stacking is what makes this framework different from PropStream. A parcel with three stacked patterns is more valuable than three single-pattern leads on different parcels.

| Condition | Bonus |
|---|---|
| 2 distinct patterns on same parcel | +15 |
| 3 distinct patterns on same parcel | +25 |
| 4+ distinct patterns on same parcel | +35 |
| Recent filing (within 30 days) | +10 |
| Multiple filings (3+ within 6 months) | +10 |

**Stack-bonus cap:** +35. A parcel can't compound infinitely.

---

## Attribute bonuses

Parcel attributes (from `01_lead_types.md`) add to the score when stacked with a pattern. They never generate score on their own.

| Attribute | Bonus | Applies when |
|---|---|---|
| `high_equity` | +20 | Any pattern + assessed >= 2× last sale + 5+ yrs |
| `absentee` | +10 | Any pattern + mailing city ≠ situs |
| `out_of_state` | +10 | Any pattern + mailing state ≠ subject state |
| `long_term_owned` | +10 | Any pattern + 15+ yrs owned |
| `senior_owner` | +10 | Any pattern + senior proxy fires |
| `entity_owned` | +5 | Any pattern + LLC/Corp/Trust owner |
| `multiple_properties` | +10 | Any pattern + 3+ parcels same owner |
| `vacant` | +15 | Any pattern + USPS or utility vacancy |
| `free_and_clear` | +20 | Any pattern + no recorded mortgage |

**Attribute-bonus cap:** +40. Multiple attributes compound up to this ceiling.

---

## Penalties

Penalties prevent garbage from inflating the dashboard.

| Condition | Penalty |
|---|---|
| Property match confidence < 80 | -20 |
| No property match (orphan signal) | -30 |
| Record older than 180 days | -15 |
| Missing source URL | -15 |
| Unclear document type | -20 |
| Unsupported claim (any field labeled `Possible` or `Estimated` without derivation) | -30 |
| Conflicting ownership data across sources | -20 |
| Discharged signal (negative doc type recorded after positive) | -50 |
| Duplicate of existing lead | route to dedupe, not score |

A discharged signal stays in the record as historical context but is excluded from active stack-depth calculations and tier ranking.

---

## Tier thresholds

| Score | Tier | Treatment |
|---|---|---|
| 80–100 | **Hot** | Top of dashboard, daily Telegram alert when new |
| 60–79 | **Strong** | Default-visible, sortable to top |
| 40–59 | **Workable** | Visible with filter |
| 20–39 | **Low Priority** | Hidden by default, surface via filter |
| 0–19 | **Archive** | Persisted but not shown |

Negative scores get clamped to 0 and routed to review queue.

---

## Score reasons — the audit trail

Every score must come with a reasons array. Format:

```json
{
  "score": 78,
  "tier": "Strong",
  "reasons": [
    "+45 base: Notice of Sale (foreclosure)",
    "+15 stack bonus: 2 distinct patterns (foreclosure + tax)",
    "+10 attribute: absentee (mailing out-of-state)",
    "+10 attribute: long_term_owned (24 yrs)",
    "-15 penalty: source URL missing for tax record",
    "+8 stack bonus: recent filing within 30 days",
    "+5 stack bonus: 3 filings within 6 months",
    "= 78"
  ]
}
```

The reasons array is what the operator's client sees when they ask "why is this a 78?" If reasons can't be generated, the lead is incomplete and goes to review.

---

## Stacking examples

### Example 1: Hot lead

**Parcel:** synthetic SFR, suburban municipality
**Patterns:**
- `foreclosure` — Sheriff Sale on 2026-05-12 (+45)
- `bankruptcy` — Foreclosure-Stay (+35)

**Attributes:**
- `absentee` (mailing differs from situs) — +10

**Stack bonus:** 2 distinct patterns — +15

**Score:** 45 + 35 + 10 + 15 = **105 → clamped to 100, Hot**

**Deal paths:** sub-to (high — foreclosure pressure + Ch 13), wholesale (high — equity proxy + distress)

### Example 2: Workable lead

**Parcel:** synthetic SFR, exurban municipality
**Patterns:**
- `foreclosure` — Sheriff Sale on 2026-05-12 (+45)

**Attributes:**
- `long_term_owned` (24 yrs) — +10

**Stack bonus:** none (single pattern)

**Score:** 45 + 10 = **55, Workable**

**Deal paths:** sub-to (high — foreclosure), wholesale (moderate — long-term owner often has equity but not confirmed)

### Example 3: Stacked partial-interest lead

**Parcel:** synthetic SFR, dense municipality
**Patterns:**
- `estate` — Affidavit of Heirship (+35)
- `tax` — Tax Sale Certificate sold (+35)
- `transfer` — Quitclaim Deed from one heir (+20)

**Attributes:**
- `multiple_properties` — owner has 4 parcels — +10
- `out_of_state`: heir mailing address is outside the target property state. +10

**Stack bonus:** 3 distinct patterns — +25

**Score:** 35 + 35 + 20 + 10 + 10 + 25 = **135 → clamped to 100, Hot**

**Deal paths:** partial-interest (very high), messy-title (high), wholesale (moderate — may need title work)

---

## Recomputation rules

Scores are recomputed every refresh. Reasons:
- New signals may have appeared (re-stack)
- Existing signals may have aged past TTL (de-score)
- Discharges may have been recorded (de-escalate)
- Property attributes may have updated (re-attribute)

The pipeline does not store cached scores. It recomputes from records every build. This is the only way to guarantee the dashboard reflects current truth.
