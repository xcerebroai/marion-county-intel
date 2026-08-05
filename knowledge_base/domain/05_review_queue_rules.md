# 05 — Review Queue Rules

The review queue is what protects the operator's client from low-quality leads. A record routes to review when any one of the conditions in this file fires. Records in review are NOT exported to the dashboard or CRM until a human (or downstream rule) clears them.

The review queue is not a failure state. It is the framework's quality gate. Empty review queues are suspicious — either the source data is exceptionally clean (rare) or rules aren't firing. Healthy review-queue ratio is 5%–40% depending on source quality.

---

## Match-confidence triggers

A record routes to review when property-matching falls below threshold:

- Match confidence < 80 → review (`match_confidence_low`)
- No match found at all (orphan signal) → review (`no_property_match`)
- Multiple plausible matches with no clear winner → review (`ambiguous_match`)
- Match made on owner name only (no parcel ID, no address) → review (`name_only_match`)

The matcher uses parcel ID first, full address second, owner name + city third. Confidence scoring:

| Match path | Confidence |
|---|---|
| Parcel ID exact | 100 |
| Parcel ID after normalization | 95 |
| Address exact (street + number + city + state + zip) | 90 |
| Address fuzzy (street similarity > 0.85, city/state/zip exact) | 80 |
| Owner name + city | 50 |
| Owner name only | 30 |

Review threshold is 80. Below that, do not auto-export.

---

## Field-completeness triggers

A record routes to review when required fields are missing:

- No source URL → review (`source_url_missing`)
- No recording date AND no filing date → review (`date_missing`)
- No property address AND no parcel ID → review (`property_identifier_missing`)
- No owner name AND no party name → review (`party_missing`)
- No document type → review (`doc_type_unknown`)
- No callable contact path (no phone, no email, no mailing address) → review (`no_contact_path`)

The minimum viable lead has: source URL + date + property identifier + party + doc type + contact path. Anything less is incomplete.

---

## Data-conflict triggers

A record routes to review when sources disagree:

- Owner name in clerk record ≠ owner name in parcel master (and difference is not a clear marriage/entity transition) → review (`owner_name_conflict`)
- Mailing address in clerk record ≠ mailing address in parcel master (>30 days difference and not explained) → review (`mailing_conflict`)
- Tax balance in tax collector ≠ tax balance in clerk tax-lien recording (>$500 difference) → review (`tax_balance_conflict`)
- Sale amount in clerk DEED ≠ sale amount in parcel master last sale (>10% difference) → review (`sale_amount_conflict`)

When sources conflict, the framework does NOT pick a winner automatically. It surfaces the conflict for human review. The hierarchy in `02_signals_and_sources.md` (clerk wins for events, parcel master wins for state) is for non-conflicting joins; conflicts go to review.

---

## Parser-confidence triggers

A record routes to review when the parser indicates low confidence:

- Parser confidence < 80% (parser self-reports based on field-extraction success) → review (`parser_confidence_low`)
- Source HTML/PDF layout differs from baseline (regex misses, missing expected elements) → review (`source_layout_changed`)
- Document type didn't map to a known pattern → review (`doc_type_unmapped`)

When `source_layout_changed` fires repeatedly across a refresh, it indicates the source has been redesigned and the scraper needs updating. The framework alerts via Telegram.

---

## Status-clarity triggers

A record routes to review when the status of an event is unclear:

- Foreclosure status is "adjourned" but no rescheduled date → review (`foreclosure_status_unclear`)
- Auction status doesn't match expected values (active / sold / cancelled / postponed) → review (`auction_status_unclear`)
- Probate case status doesn't match expected values (pending / closed / dismissed) → review (`case_status_unclear`)
- Lien is recorded but discharge ambiguous → review (`discharge_ambiguous`)

---

## Duplicate-detection triggers

A record routes to review when it might be a duplicate:

- Parcel ID matches existing lead AND new pattern is not stack-additive (same pattern, same date range) → review (`possible_duplicate`)
- Address matches existing lead but parcel ID differs → review (`parcel_id_mismatch`)
- Same case number across two different parcels (legitimate when one case affects multiple parcels — review confirms) → review (`multi_parcel_case`)

Dedupe is hard. The framework's dedupe is conservative — when in doubt, route to review and let a human merge or split.

---

## Document-normalization triggers

A record routes to review when canonical-type normalization (`domain/08_document_normalization.md`) cannot confidently classify the underlying document:

- Raw document label could not be matched to any canonical type → review (`unknown_doc_type`)
- Normalization confidence below 80 → review (`low_doc_type_confidence`)
- County synonym disagrees with universal registry on the same raw label → review (`conflicting_doc_type_mapping`)
- OCR repair (Step 4 of normalization pipeline) needed 3+ character substitutions to reach a match → review (`ocr_repair_speculative`)
- Raw label has multiple valid normalizations and source class can't disambiguate → review (`abbreviation_maps_to_multiple_doc_types`)
- Canonical type fired from a source class that should not produce it (e.g., a clerk-recording-only type claimed from parcel-master metadata) → review (`doc_type_not_allowed_for_source`)
- Semantic inference (Step 5) was the only successful match → review (`semantic_inference_used`)

These triggers protect against the framework treating ambiguous or low-confidence document classifications as fact.

---

## Lifecycle and chronology triggers

A record routes to review when lifecycle reasoning (`domain/09_document_lifecycle.md`) detects a problem:

- Negative signal fires with no prior positive signal on record → review (`negative_signal_without_prior_positive`)
- Document dates are out of expected order within a lifecycle sequence → review (`chronology_conflict`)
- Multiple active lifecycles produce conflicting active-stage implications on same parcel → review (`multiple_active_conflicting_signals`)
- Recording date precedes effective/execution date by an unusual margin → informational flag `late_recording` (does not route to review unless paired with another concern)

---

## Title complexity triggers

A record routes to review when title complexity (`domain/10_title_complexity.md`) crosses thresholds:

- Title complexity score ≥ 60 → review (`high_title_complexity_review`) — informational, lead still exports but operator audits classifier's deal-path choice
- Title complexity score has unresolved evidence gaps (chain-of-title break, missing heir, etc.) → review (`title_complexity_uncertain`)

---

## Hallucination-risk triggers

A record routes to review when the framework's hallucination-risk score (`06_hallucination_controls.md`) is 50 or higher.

---

## Review queue structure

`data/review_queue.jsonl` — one record per line, same schema as `data/leads.json` records, plus:

```json
{
  "review_status": "pending" | "approved" | "rejected" | "merged",
  "review_reason": "match_confidence_low,parser_confidence_low",
  "review_notes": "operator notes after manual inspection",
  "queued_at": "2026-05-05T18:30:00Z",
  "reviewed_at": null,
  "reviewer": null
}
```

Review queue records are visible in the dashboard under a separate tile (`Needs Review`) with the same lead-card layout as live leads. The reviewer can click `Approve` (moves to leads.json on next build), `Reject` (archives), or `Merge` (combines with another lead).

The review queue is persistent across refreshes — records don't disappear when the source data refreshes. The reviewer's decision is honored.

---

## Dashboard treatment of review records

- Review records appear in the `Needs Review` tile only
- They do NOT appear in pre-canned views or default sort
- They do NOT count toward `lead_total` in the header
- They DO count toward `review_total` in a separate header field
- They can be filtered, sorted, exported just like live leads
- CSV export of review queue is separate from CSV export of leads (different file, different columns)

This separation prevents review records from polluting the operator's client's call list.

---

## When to auto-clear review

The framework can auto-approve review records when subsequent refreshes resolve the trigger:

- `source_url_missing` → if a later scrape finds the URL, auto-approve
- `match_confidence_low` → if a parcel-master refresh provides a better match, auto-approve
- `source_layout_changed` → if parser fix lands and re-extraction succeeds, auto-approve
- `possible_duplicate` → if dedupe detects a clean merge target, auto-approve

The framework never auto-rejects. Rejection is always a human decision.

---

## Healthy review-queue metrics

The framework tracks review-queue ratio per refresh:

```
review_ratio = review_queue_count / (review_queue_count + lead_total)
```

| Ratio | Health |
|---|---|
| 0% | suspicious — rules may not be firing |
| 5–15% | healthy for high-quality sources |
| 15–30% | healthy for mixed-quality sources |
| 30–50% | acceptable for low-quality sources (some clerk feeds) |
| > 50% | unhealthy — parser or matcher needs work |

When ratio exceeds 50%, refresh harness emits a Telegram alert: `[<county>-intel] Review queue at <pct>% — parser or matcher likely needs maintenance`.
