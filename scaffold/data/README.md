# Synthetic Data Harness — Phase 1 of the Build

This directory contains the synthetic test data the framework runs against **before** any real-source scraper is built. The harness exists to catch structural bugs in the pipeline / dashboard before they become "broken in production" — a failure mode prior county builds suffered from.

---

## What's in here

```
scaffold/data/
├── synthetic_parcels.jsonl       # 12 synthetic parcels, 1 per scenario
├── synthetic_signals.jsonl       # 24 synthetic signals across all 11 patterns
├── synthetic_expectations.json   # what the build should produce
└── README.md                     # this file
```

---

## How the harness works

1. **Phase 0** of the master prompt: AI reads the knowledge base.
2. **Phase 2:** AI runs the build pipeline against synthetic data only:
   ```
   py -3.12 pipeline/build_leads.py --synthetic
   ```
   This flag tells the pipeline to read `scaffold/data/synthetic_parcels.jsonl` and `synthetic_signals.jsonl` instead of `data/raw/*.jsonl`.
3. **Pipeline produces** `data/leads_synthetic.json` (separate from production `data/leads.json`).
4. **Verifier asserts** the synthetic output matches `synthetic_expectations.json`:
   - All 12 parcels appear
   - All 11 patterns are represented in `pattern_counts`
   - Every parcel attribute combination appears
   - Every deal-path classification fires at least once
   - Stack-depth distribution matches expected
   - Score distribution covers all 5 tiers (Hot / Strong / Workable / Low / Archive)
5. **Dashboard renders** synthetic data in real browser via Playwright:
   - All filter chips appear
   - All pre-canned views render with non-zero rows
   - All deal-path tabs work
   - CSV export validates

If any check fails, the pipeline / dashboard has a structural bug. **Fix it before touching real sources.**

---

## What the synthetic dataset covers

### 12 synthetic parcels designed to fire every pattern + attribute combination

| Parcel | Patterns | Attributes | Expected deal paths |
|---|---|---|---|
| SYN-001 (Synthtown A) | foreclosure (Notice of Sale) + bankruptcy (Ch 13 stay) | absentee, long_term_owned | sub_to:high, wholesale:high |
| SYN-002 (Synthtown B) | tax (Tax Sale Cert) + lien (judgment) | high_equity, long_term_owned | wholesale:high, messy_title:high |
| SYN-003 (Synthtown C) | estate (Affidavit of Heirship) + transfer (Quitclaim) | multiple_properties, out_of_state | partial_interest:high, wholesale:moderate |
| SYN-004 (Synthtown D) | code (Demolition Order) | vacant, absentee | wholesale:high, flip:low (condemned skips flip) |
| SYN-005 (Synthtown E) | foreclosure (Sheriff Sale) | long_term_owned | sub_to:moderate, wholesale:moderate |
| SYN-006 (Synthtown F) | tax (federal tax lien) + lien (mechanic) + lien (judgment) | high_equity, free_and_clear | messy_title:high, wholesale:high |
| SYN-007 (Synthtown G) | divorce (sale of marital home order) | none | wholesale:moderate |
| SYN-008 (Synthtown H) | eviction (3 filings) + multiple_properties | entity_owned, multiple_properties | tired_landlord:fired → seller_finance:high |
| SYN-009 (Synthtown I) | estate (probate) + tax (delinquent) | senior_owner, long_term_owned | wholesale:high, partial_interest:moderate |
| SYN-010 (Synthtown J) | foreclosure (lis pendens only) + lien (HOA) | absentee, vacant | wholesale:moderate |
| SYN-011 (Synthtown K) | surplus_owed (post-sheriff sale) | none | surplus_recovery (separate persona) |
| SYN-012 (Synthtown L) | transfer (executor's deed alone, no other patterns) | none | wholesale:low (single-pattern, weak score) |

### 24 synthetic signals

Two per parcel on average. Mix of:
- Recent (within 30 days) — fires recent-filing stack bonus
- Aged (90-180 days) — within TTL but not bonused
- Expired (250+ days) — should be GC'd from active records

### What it doesn't cover

The harness intentionally does **not** include:
- Real PII (all names are obviously fake — "TEST_OWNER_001", "SYN_GRANTOR_LLC")
- Real addresses (synthetic parcels use real-sounding street names but invented numbers)
- Production source URLs (synthetic source URLs are `synthetic://parcel/SYN-001`)

This makes synthetic data trivially distinguishable from real data, so the framework can refuse to commit synthetic data to production `leads.json`.

---

## The hallucination guardrail

`pipeline/build_leads.py --synthetic` writes output to `data/leads_synthetic.json`, NOT `data/leads.json`. The dashboard's production view reads `data/leads.json` only.

The framework refuses to run `git push` if `data/leads.json` contains any record with:
- `source_url` starting with `synthetic://`
- `parcel_id` matching `^SYN-`
- `owner_name` matching `^TEST_OWNER_` or `^SYN_`

This is the rule from `domain/06_hallucination_controls.md` (no synthetic data co-mingled with real data) made enforceable.

---

## When to update synthetic data

Update `synthetic_parcels.jsonl` and `synthetic_signals.jsonl` when:

- A new pattern or subtype is added to `domain/01_lead_types.md`
- A new attribute is added
- A new deal-path rule is added to `domain/04_deal_path_classifier.md`
- A new pre-canned view is added to a county config

Update `synthetic_expectations.json` accordingly. Re-run Phase 1 to confirm the framework still passes against the new expectations.

---

## Why this is Phase 2, not Phase 0

Phase 0 is the combined source recon and onboarding gate — the AI reads the knowledge base, looks at the actual county sources, maps them to the framework's source classifications, and produces a validated county config. Phase 1 runs the synthetic harness because it requires the AI to have already understood the domain and the source landscape from Phase 0, so the synthetic data exercises the right scenarios.

If Phase 1 fails, the framework has a bug. If Phase 1 passes, the framework will produce correctly-shaped output against real sources, leaving only source-specific scraper bugs to debug in Phases 2-6.

Prior county builds skipped Phase 2 and found structural bugs only after committing real data. The framework refuses to allow that anymore.
