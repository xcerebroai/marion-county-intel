# 10 — Title Complexity

This file defines the framework's title-complexity dimension. Title complexity is **not** the same as score, lead pattern, or deal path. It is a separate scalar that measures how hard it will be to clear title and close, regardless of how motivated the seller is.

A property can be high-motivation and low-complexity (motivated heir of a single-owner estate with no liens). A property can be low-motivation and high-complexity (long-time owner with multiple unreleased liens, a quitclaim chain, and an open probate). Title complexity tells the operator's client which deal path actually fits.

---

## Why title complexity is a separate dimension

The score in `domain/03_scoring_and_stacking.md` answers "how likely is this seller motivated?" The deal-path classifier answers "what type of deal does the pattern stack suggest?" Neither answers "how much title work does this take to close?"

A wholesaler can flip a clean title in 14 days. A messy-title specialist needs 90+ days and an attorney. The operator's client picks deals based on which timeline they can absorb. Title complexity gates that decision.

---

## Title complexity score

Per parcel, the framework emits a `title_complexity_score` 0–100. Higher means harder to close.

Tiers:

| Score | Tier | Typical close timeline |
|---|---|---|
| 0–19 | Clean | 14–30 days |
| 20–39 | Light curative | 30–45 days |
| 40–59 | Moderate curative | 45–75 days |
| 60–79 | Complex | 75–120 days |
| 80–100 | Very complex / specialist required | 120+ days, attorney involvement |

The dashboard renders title complexity as a chip alongside the score chip so the operator's client can sort or filter by closeability.

---

## What contributes to title complexity

Each contributor has a weight. Total is capped at 100.

### Ownership fragmentation

| Condition | Weight |
|---|---|
| Single owner | 0 |
| Married couple, both on title | 0 |
| 2 owners, unrelated | +10 |
| 3+ owners | +20 |
| Heirs declared but no formal probate | +25 |
| Multiple heirs across multiple states | +15 (stacks with above) |
| Missing heir or unknown party | +30 |

### Curative requirements

| Condition | Weight |
|---|---|
| `CORRECTION_DEED` in chain (recent, within 5 years) | +10 |
| Multiple `QUITCLAIM_DEED` instruments in last 10 years | +15 |
| Open probate without `PERSONAL_REPRESENTATIVE_DEED` or equivalent | +20 |
| `AFFIDAVIT_OF_HEIRSHIP` without supporting probate | +15 |
| Trust without identifiable trustee | +25 |
| `PARTITION_ACTION` open | +30 |
| `QUIET_TITLE_ACTION` open | +30 |
| `ADVERSE_POSSESSION_CLAIM` recorded | +20 |

### Liens and clouds

| Condition | Weight |
|---|---|
| One active monetary lien | +10 |
| Two active monetary liens | +20 |
| Three or more active monetary liens | +30 |
| `FEDERAL_TAX_LIEN` (active) | +20 (stacks with above) |
| `STATE_TAX_LIEN` (active) | +10 (stacks) |
| Old judgment lien (>3 years, no satisfaction) | +10 |
| Mortgage on record without `SATISFACTION_OF_MORTGAGE` after a deed transfer (possible chain-of-title break) | +25 |

### Lifecycle interactions

| Condition | Weight |
|---|---|
| Active foreclosure lifecycle (any stage) | +5 |
| Active bankruptcy stay | +30 (closing cannot proceed during stay) |
| `LIS_PENDENS` open (any cause) | +15 |
| Multiple active lifecycles on same parcel (e.g., probate + foreclosure) | +20 |

### Chain-of-title issues

| Condition | Weight |
|---|---|
| Grantor on most recent deed does not match grantee on prior deed | +25 |
| Deed gap (period where no recorded ownership document exists) | +20 |
| Same owner appearing under multiple name variants without clear linkage | +15 |
| Quiet title action pending | +30 (already counted under curative — do not double) |

---

## How title complexity feeds deal-path classification

The deal-path classifier (`domain/04_deal_path_classifier.md`) reads title complexity as a routing input:

- **Wholesale** — works best on title_complexity ≤ 39. Above 40, the wholesaler needs a buyer who will tolerate the curative timeline. Above 60, route to messy-title specialists instead.
- **Flip** — needs title_complexity ≤ 30 for typical retail-buyer financing. Above that, retail buyers walk during inspection.
- **Subject-to** — works through most complexity ranges since the buyer takes title with the existing loan; complexity affects exit timing, not entry.
- **Seller-finance** — works through most ranges; the seller is taking back paper, not relying on clean title for a cash sale.
- **Partial-interest** — assumes complexity by definition. Title_complexity ≥ 40 is normal here; below 40 may indicate the partial-interest framing is wrong.
- **Messy-title** — assumes complexity ≥ 60. Below that, deal is too clean for a messy-title specialist's margin.

The classifier writes complexity reasoning into `deal_path_reasons` so the operator's client sees why a path was suggested or skipped.

---

## How title complexity feeds review queue

Title complexity above 60 routes to review with reason `high_title_complexity_review` for operator confirmation that the deal-path classifier picked the right specialist persona. This is informational, not blocking — the lead can still export, but the operator's client sees a flag.

Title complexity score with high uncertainty (e.g., chain-of-title issues that the framework cannot fully resolve from available evidence) routes with `title_complexity_uncertain` and lists the unresolved evidence gaps.

---

## What title complexity does NOT do

- It does not predict actual closing timelines. The tier table is a rough guide, not a guarantee. Court delays, recording delays, missing-heir searches, and lien negotiations can extend any timeline.
- It does not score motivation. A property with title_complexity 80 but no distress signals is a complex parcel nobody is selling. The operator's client filters by score AND complexity.
- It does not replace attorney review. For complexity ≥ 80, the framework's job is to surface the lead with full evidence; the closing path requires legal work outside the framework's scope.
- It does not assume any particular state's curative procedures. Title complexity is intentionally jurisdiction-agnostic — what counts as "complex" is universal (multiple unreleased liens, missing heirs, broken chain) even though the specific cure varies by state.

---

## Output schema field

The matched-lead schema (`architecture/09_output_schemas.md`) carries title complexity as:

```json
{
  "title_complexity_score": 0,
  "title_complexity_tier": "Clean",
  "title_complexity_contributors": [
    {"factor": "active_federal_tax_lien", "weight": 20},
    {"factor": "multiple_heirs_no_probate", "weight": 25},
    {"factor": "two_active_monetary_liens", "weight": 20}
  ]
}
```

The `contributors` array lets the operator's client see exactly what's driving the complexity score — which is essential when an attorney later asks "what curative work is needed?"
