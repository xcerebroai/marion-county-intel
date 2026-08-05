# 08 — Document Normalization

This file is the universal document normalization and intelligence layer. It defines how raw recorder/court abbreviations, OCR-corrupted text, and inconsistent document labels translate into canonical document types before any scoring, classification, or routing happens.

**The machine-readable source of truth is `knowledge_base/domain/canonical_doc_types.json`.** This file explains how that registry is used. The pipeline reads the JSON; the AI reads this markdown.

---

## Why this layer exists

Every county labels documents differently. The same legal instrument might appear as:
- `AOH` in one county
- `AFFIDAVIT OF HEIRSHIP` in another
- `AFFT OF H` in a third
- `AFFlDAVlT OF HElRSHlP` in OCR output where `i` got read as `l`

All four are the same canonical document: `AFFIDAVIT_OF_HEIRSHIP`. Without a normalization layer, the framework would treat them as four different things and miss three of them in pattern matching.

The normalization layer exists so the rest of the framework — scoring, deal-path classification, lifecycle reasoning, dashboard rendering — operates on canonical types only. **Raw abbreviations never score, never classify, never route. Only canonical types do.**

---

## Architecture

```
RAW DOC LABEL
   │
   ├──▶ Normalization Pipeline ────▶ canonical_doc_type + confidence
   │       (deterministic match → fuzzy match → semantic inference)
   │
   ▼
canonical_doc_types.json (registry)
   │
   ├──▶ lead_pattern, subtype, source_class, document_priority
   │
   ▼
Downstream: scoring (03), deal path (04), lifecycle (09), title complexity (10)
```

---

## Universal vs county-specific split

**The universal `canonical_doc_types.json` registry holds:**
- Canonical document types (one entry per legal instrument)
- Industry-common abbreviations that appear across many counties
- Default confidence, document priority, lead pattern, source class
- Suppression relationships (which negative signals invalidate which prior signals)

**Per-county `<county>.json` `doc_type_synonyms` block holds:**
- County-specific shorthand the universal library does not cover
- County-specific numeric codes (e.g., `DOC TYPE 217` → `MECHANICS_LIEN`)
- Recorder-vendor abbreviations unique to that county's portal
- County overrides where the local meaning of an abbreviation differs from industry-common

The normalization pipeline checks the county synonyms first, then falls back to the universal registry. This way a county can override an industry-common interpretation when local recorder practice differs.

---

## Backward-compatible county synonym format

Existing county configs use a flat string→string map:

```json
"doc_type_synonyms": {
  "QCD": "QUITCLAIM_DEED",
  "FINJUDGE": "Final Judgment"
}
```

This format continues to work and should be preferred when a one-line mapping is enough.

The new richer format is also supported for cases where confidence and notes matter:

```json
"doc_type_synonyms": {
  "QCD": "QUITCLAIM_DEED",
  "DOC TYPE 217": {
    "raw_code": "DOC TYPE 217",
    "normalized_doc_type": "MECHANICS_LIEN",
    "confidence": 88,
    "notes": "County-specific numeric code observed during Phase 0 recon"
  }
}
```

The pipeline accepts either shape. A flat string value implies confidence 90 and no notes. The richer object form lets a county override defaults.

---

## Normalization pipeline

For every raw document label, the pipeline runs these steps in order. The first step that produces a high-confidence match wins; otherwise the next step runs.

### Step 1 — Exact match (deterministic)

1. Uppercase the raw label
2. Trim whitespace and collapse internal whitespace
3. Look up in the county's `doc_type_synonyms` block first
4. If not found, look up in the universal `canonical_doc_types.json` `common_abbreviations` arrays

If found, set `doc_type_confidence = 100` minus any minor preprocessing penalty.

### Step 2 — Punctuation-tolerant match (deterministic)

If Step 1 missed:
1. Strip punctuation that does not change meaning (`.`, `,`, `:`, `;`, parentheses)
2. Preserve `/` and `&` (both can change meaning, e.g., `D/T`, `H/W`)
3. Re-run lookup

If found, set `doc_type_confidence = 95`.

### Step 2 — Punctuation-tolerant match (deterministic)

If Step 1 missed:
1. Strip punctuation that does not change meaning (`.`, `,`, `:`, `;`, parentheses)
2. Preserve `/` and `&` (both can change meaning, e.g., `D/T`, `H/W`)
3. Collapse whitespace produced by punctuation removal (so `A.O.H.` → `A O H` → `AOH`)
4. Re-run lookup against both the spaced form (`A O H`) and the collapsed form (`AOH`)

If found, set `doc_type_confidence = 95`.

### Step 3 — Fuzzy match (deterministic)

If Step 2 missed:
1. Compute Levenshtein similarity to every abbreviation in the registry
2. If best match has similarity ≥ 0.90, accept with `doc_type_confidence = max(70, 90 * similarity)`
3. If best match is 0.80–0.89, hold the candidate but **continue to Step 4**. Do not route to review yet — OCR repair may rescue it deterministically.
4. If best match is below 0.80, hold no candidate; continue to Step 4.

**Polarity-protection rule:** if the raw label contains any of the keywords `DISCHARGE`, `RELEASE`, `SATISFACTION`, `SATISFIED`, `RECONVEY`, `VACATED`, `CANCEL`, `WITHDRAW`, `DISMISS`, the fuzzy match MUST resolve to a canonical type with `source_class: negative_signal`. If the best-similarity candidate is a `lead_generating` or `enrichment` type (i.e., the polarity is wrong), reject it and route to review with reason `polarity_conflict`. This prevents `DISCHARGE OF JUDGMENT LIEN` from fuzzy-matching to `JUDGMENT_LIEN` — the suppression engine depends on negative signals being classified as negative signals.

### Step 4 — Context-aware OCR repair (conditional)

OCR repair runs **always when Step 3 did not produce a confident match (≥0.90 similarity)**. It does not depend on Step 3 producing a candidate. This is not a blanket character substitution.

Repair candidates:
- `0` ↔ `O` only inside alphabetic runs (e.g., `M0RTGAGE` → `MORTGAGE`, never `2026` → `Z0Z6`)
- `1` ↔ `I` or `l` only inside alphabetic runs (e.g., `L1S PEND` → `LIS PEND`)
- `5` ↔ `S` only inside alphabetic runs (e.g., `JUDGEMENT` → `JUDGMENT`)
- `8` ↔ `B` only inside alphabetic runs

**Rules for OCR repair:**
- Apply substitution only if the resulting string would match an entry in the registry exactly, OR fuzzy-match an entry at ≥0.90 similarity
- Never substitute inside a run of consecutive digits (preserves dates, parcel IDs, dollar amounts, case numbers)
- Never substitute inside mixed alphanumeric tokens that are likely identifiers (e.g., `CV-2026-0123`)
- Each substitution lowers confidence by 5 points (starting from 100 for exact-after-repair, or from `90 * similarity` for fuzzy-after-repair)
- If 3 or more substitutions are needed to reach a match, route to review with reason `ocr_repair_speculative`
- **If OCR repair produces an exact registry match with ≤2 substitutions, the result is accepted with confidence ≥90 and does NOT route to review** (this is the case that rescues `L1S PEND` and `M0RTGAGE`)
- If Step 4 fails to produce any match AND Step 3 had a 0.80–0.89 candidate, route Step 3's candidate to review with reason `low_doc_type_confidence`

### Step 5 — Semantic inference (last resort)

If Steps 1–4 fail and the raw label contains keywords matching a canonical type's full name (e.g., `THIS IS A NOTICE OF DEFAULT FILED BY...`), match on substring with `doc_type_confidence = 70` and route to review with reason `semantic_inference_used`.

### Step 6 — Unknown

If all five steps fail, the document is unmapped:
- `normalized_doc_type = null`
- `doc_type_confidence = 0`
- Route to review with reason `unknown_doc_type`
- Operator decides: add to county synonyms, or add to universal registry if industry-common, or reject as noise

---

## Confidence and review thresholds

| Confidence range | Action |
|---|---|
| 90–100 | Accept; flow downstream |
| 80–89 | Accept but flag for periodic operator audit |
| 70–79 | Route to review; do NOT score |
| 0–69 | Route to review with high severity; do NOT score |

The thresholds match `domain/05_review_queue_rules.md`. New review triggers added in this layer:
- `unknown_doc_type` — Step 6 fired
- `low_doc_type_confidence` — confidence below 80
- `conflicting_doc_type_mapping` — county synonym disagrees with universal registry on the same raw label
- `ocr_repair_speculative` — Step 4 needed too many substitutions
- `abbreviation_maps_to_multiple_doc_types` — raw label has plural valid normalizations (e.g., `LP` could be `LIS_PENDENS` or `LIMITED_PARTNERSHIP`)
- `negative_signal_without_prior_positive` — release/satisfaction/discharge fired but the framework has no record of the signal it suppresses
- `chronology_conflict` — document dates conflict with lifecycle expectations
- `doc_type_not_allowed_for_source` — canonical type fired from a source class that should not produce it (e.g., a clerk recording subtype claimed from parcel-master metadata)

---

## Ambiguity rules

Some abbreviations are genuinely ambiguous. The registry handles these explicitly:

- `LP` → `LIS_PENDENS` is the default canonical match. But `LP` can also mean `LIMITED_PARTNERSHIP` in entity records. The pipeline disambiguates by source class: clerk recordings → `LIS_PENDENS`; entity filings → `LIMITED_PARTNERSHIP`. If the source is unclear, route to review.

- `TD` → `TRUSTEE_DEED` is default. But `TD` in deed-of-trust states sometimes means `TRUST DEED` (which is the local term for `DEED_OF_TRUST`). The pipeline checks county context.

- `MOD` → `MORTGAGE_MODIFICATION` is default. Some counties use `MOD` for `ORDER MODIFICATION` on court dockets. Check source.

When the registry's default and the source class disagree, route to review with reason `abbreviation_maps_to_multiple_doc_types`.

---

## Negative-signal logic (suppression)

Some canonical types are tagged `source_class: negative_signal` in the registry. They include:
- `SATISFACTION_OF_MORTGAGE`
- `RECONVEYANCE`
- `RELEASE_OF_LIEN`
- `RELEASE_OF_LIS_PENDENS`
- `RELEASE_OF_FEDERAL_TAX_LIEN`
- `VACATED_JUDGMENT`

Each carries a `suppresses` array listing the canonical types it can invalidate. When a negative signal appears on the same property as one of its suppression targets, AND its event date is later than the target's event date, the prior signal is marked `status: SATISFIED` (or `RELEASED` / `DISCHARGED` / `VACATED` depending on the negative type).

Suppressed signals stay in the record for audit but are excluded from active scoring and pattern stacking. See `domain/09_document_lifecycle.md` for the full status-engine spec.

If a negative signal fires with no prior positive signal on record, that's `negative_signal_without_prior_positive` and routes to review. The framework does not silently drop release-only events because they may indicate the framework missed the original positive signal.

---

## Document priority

Each canonical type carries a `document_priority` 0–100. This is **not** the score; it's a sort key for downstream UI rendering and dashboard filtering. Higher priority means "more attention-worthy at first glance."

Examples:
- `NOTICE_OF_DEFAULT` = 95 (imminent foreclosure timeline)
- `NOTICE_OF_SALE` = 95 (imminent sale)
- `FEDERAL_TAX_LIEN` = 92 (high-impact title cloud)
- `AFFIDAVIT_OF_HEIRSHIP` = 88 (strong partial-interest signal)
- `MORTGAGE` = 20 (enrichment, not actionable alone)
- `PLAT` = 5 (pure metadata)

The dashboard uses `document_priority` to sort within tier (Hot, Strong, Workable, etc.) when multiple leads share the same score.

---

## What downstream files reference this layer

- `domain/01_lead_types.md` — the 14 patterns map onto canonical types here
- `domain/02_signals_and_sources.md` — `source_class` taxonomy includes `negative_signal`
- `domain/03_scoring_and_stacking.md` — only canonical types score, never raw abbreviations
- `domain/04_deal_path_classifier.md` — classifier reads canonical types and lifecycle stages
- `domain/05_review_queue_rules.md` — review triggers from this layer
- `domain/06_hallucination_controls.md` — explicit rule that the AI cannot invent canonical types
- `domain/09_document_lifecycle.md` — chronology and status engine
- `domain/10_title_complexity.md` — separate complexity dimension fed by canonical types
- `architecture/09_output_schemas.md` — matched-lead schema includes normalized fields
- `config/counties/<county>.json` — `doc_type_synonyms` block extends or overrides the universal registry

---

## Operator workflow when adding a new abbreviation

When recon discovers an abbreviation not yet in the universal registry:

1. **Determine if it's industry-common or county-specific.** Industry-common means it would appear in 3+ unrelated counties' recorder feeds. County-specific means it's a local code or vendor convention.

2. **County-specific** → add to that county's `doc_type_synonyms` block. Use the richer object form if confidence is below 90 or notes are needed.

3. **Industry-common** → propose addition to `canonical_doc_types.json`:
   - Add the abbreviation to the canonical type's `common_abbreviations` array
   - If it's a new canonical type, add a full entry with `lead_pattern`, `subtype`, `source_class`, `default_confidence`, `document_priority`, `common_abbreviations`, `notes`
   - Run synthetic test harness to confirm it doesn't conflict with existing entries

4. **Both ambiguous** (the abbreviation means different things in different counties) → keep in county synonyms only; do NOT promote to universal. Document the conflict in `RECON.md`.

The universal registry is meant to grow slowly with industry-common entries. Most additions belong in county synonyms.
