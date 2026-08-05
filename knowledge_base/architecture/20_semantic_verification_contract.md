# 20. Semantic Verification Contract (v5.3.0+)

Mechanical verification confirms the system produces output. Semantic verification
confirms the output is *meaningful*. This contract defines the semantic verification
surface every county build must pass before deployment.

This file is the universal contract. Per-county check implementations live under
`runs/<county_slug>/build/`; per-county sample sizes and thresholds live in
`config/counties/<county_slug>.json`.

---

## 20.0 Status and scope

- **Version:** v5.3.0 (Session A3 — Gap 4).
- **Date:** 2026-05-18.
- **Authoritative for:** the deploy-phase gate of every county build. A build that has
  not passed semantic verification MUST NOT deploy.
- **Scope:** universal — the 12 check classes, the three-state outcome model, the
  sample-size rules, and the deploy verdicts. Per-county check implementations and
  customized thresholds are county-scoped.

---

## 20.A Purpose

Mechanical verification (lead count > 0, dashboard renders, schema validates) is
necessary but insufficient. Semantic verification validates that the *meaning* of the
data is correct: owners are debtors not filers, entity types are classified correctly,
parcel-to-record joins are plausible, and dashboard counts reflect the actual underlying
data. This contract defines the semantic verification surface every county build must
pass before deployment.

---

## 20.B The mechanical-versus-semantic distinction

- **Mechanical verification** answers: "Does the system produce output?"
- **Semantic verification** answers: "Is the output meaningful?"

A build can pass mechanical verification — a four-figure lead count emitted, the
dashboard renders, no console errors — while failing semantic verification: 80% of leads
have wrong-party owners, or every estate signal is a real-estate-company false positive.
Mechanical verification cannot catch class-level data-integrity bugs; semantic
verification can.

---

## 20.C Required semantic checks (per build, county-agnostic)

Every county build MUST pass all twelve checks below before deployment.

**Check 1 — Debtor attribution sampling.** Sample ≥5 rows per `canonical_doc_type`. For
each, confirm `owner_name` matches the expected debtor party per §17 (not the filer).
Spot-check that known filer patterns (governments, hospitals, mortgage entities, federal
agencies) are not emitted as `owner_name`. Failure threshold: any sampled row with
filer-as-owner.

**Check 2 — Owner type classification sampling.** Sample ≥5 rows per `owner_type`
(ENTITY, ESTATE, TRUST, INDIVIDUAL). For ESTATE rows, confirm `owner_name` matches a true
decedent pattern (`ESTATE OF X`, `EST OF X`, `X ESTATE`, `HEIRS OF X`); reject substring
false positives (a real-estate company). For TRUST rows, confirm a true family/decedent
trust pattern; reject corporate trust-company false positives. For ENTITY rows, confirm a
corporate suffix is present. Failure threshold: any sampled row misclassified.

**Check 3 — Parcel-resolution plausibility.** Sample ≥5 rows where
`parcel_resolution_status = RESOLVED`. For each, confirm the `situs_address` tokens
overlap meaningfully with the debtor-name search key (Jaccard ≥ 0.5, or ≥ 2 shared
significant tokens at ≥ 40% overlap). Reject implausible joins — a debtor resolved to a
parcel owned by an unrelated party. Failure threshold: any implausible join sampled.

**Check 4 — Enrichment status decoupling integrity.** Confirm rows exist across the four
valid `(parcel_resolution_status, enrichment_status)` combinations from §13.14. Confirm
no rows are dropped due to `enrichment_status = UNENRICHED`. Confirm `UNRESOLVED` rows
retain `debtor_name`, signal, and source URL. Failure threshold: any rows dropped for
enrichment failure.

**Check 5 — Signal aggregation integrity.** Sample ≥3 rows with signal count > 1. For
each, confirm `count` = the number of distinct `instrument_numbers` (legitimate
stacking). Reject rows where signal count > distinct instrument count (dedup failure).
Failure threshold: any dedup-failure pattern.

**Check 6 — Cross-source aggregation integrity.** Sample ≥3 leads with signals from
multiple sources. Confirm the aggregation key `(parcel_id, canonical_doc_type,
signal_type)` correctly merges cross-source duplicates, and that distinct `signal_type`
values remain distinct (anti-collapse rule, §18). Failure threshold: any cross-source
over-merge or under-merge.

**Check 7 — OCR confidence routing.** For sources that depend on OCR (scanned PDFs,
image documents), sample ≥5 OCR'd records. Confirm rows with OCR confidence below 0.85
are flagged for review, not silently emitted as authoritative leads. Failure threshold:
any low-confidence OCR row emitted without a review flag.

**Check 8 — CSV output schema validation.** Generate the operator-facing CSV export.
Confirm column headers match the documented export schema, row counts match dashboard
counts (no silent truncation), and no enrichment-only synthetic rows appear in the
export. Failure threshold: any schema mismatch or row-count discrepancy.

**Check 9 — Source proof link validation.** Sample ≥5 leads per source. For each,
confirm `source_urls` resolve to a real document/record (HTTP 200 or a valid offline
path), and that the linked document corresponds to the lead's `instrument_number` and
`recorded_date`. Failure threshold: any broken or wrong-document source link.

**Check 10 — Dashboard row integrity (browser-rendered count match).** With browser
automation, load the dashboard. Confirm the header lead count matches the visible row
count across ≥5 filter states (all, single signal-type filter, date-range filter,
owner-type filter, multi-signal filter). Confirm `REVIEW_REQUIRED` rows are visually
distinct from `RESOLVED` rows. Failure threshold: any count mismatch or visual
classification failure.

**Check 11 — Methodology consistency.** The build report's stated methodology — which
sources contributed, how many records were ingested, the enrichment hit rate, the
`REVIEW_REQUIRED` count — must match the dashboard's actual data. Confirm the reported
numbers reconcile with the underlying `matched_leads.json` counts. Failure threshold:
any reported number that does not match actual data.

**Check 12 — Filer-as-owner spot check (universal patterns).** Search
`matched_leads.json` for known universal filer patterns (`CITY OF *`, `COUNTY OF *`,
`STATE OF *`, `UNITED STATES OF AMERICA`, `IRS`, hospital systems, mortgage entities,
federal mortgage agencies). Confirm none appears as `owner_name` in any row — such an
entity may appear only as `filer_entity` on a `REVIEW_REQUIRED` row. Failure threshold:
any universal filer pattern emitted as `owner_name`.

---

## 20.D Three-state outcome model

Each semantic check returns one of three states:

- **VALID** — the sampled data matches the expected pattern.
- **INVALID** — the sampled data contradicts the expected pattern (a definitive failure;
  must be fixed before deploy).
- **AMBIGUOUS** — the sampled data is suspicious but might be legitimate (route to
  operator review; do NOT auto-reject).

Example: a `foreclosure_notice` whose `owner_name` is a mortgage company name might be a
legitimate mortgage-company-as-property-owner (REO inventory being re-foreclosed) OR a
filer-as-owner inversion. The check returns AMBIGUOUS, surfaces the row for operator
review, and does not auto-reject.

The third state is critical. Binary VALID/INVALID produces false rejections of
legitimate edge cases. AMBIGUOUS preserves the lead, surfaces it for triage, and lets the
operator make the final call.

---

## 20.E Sample size and statistical sufficiency

The sample sizes specified per check are MINIMUMS. For builds with more than 1,000
leads, sample sizes should scale to ≥ 1% of the population per check class, with a floor
of 5 samples and a cap of 50 samples per class to keep verification time bounded.

Random sampling is required — not first-N or last-N. The sampling seed must be recorded
for reproducibility.

---

## 20.F Failure routing

A semantic verification run produces a report containing:

- per-check status (VALID / INVALID / AMBIGUOUS);
- per-check sampled rows (original data plus classification);
- per-check failure threshold and whether it was crossed;
- an overall verdict.

The overall verdict:

- **`DEPLOY_OK`** — all checks VALID.
- **`DEPLOY_BLOCKED`** — any check INVALID.
- **`NEEDS_OPERATOR_REVIEW`** — at least one check AMBIGUOUS, none INVALID.

A build with `DEPLOY_BLOCKED` MUST NOT deploy. A build with `NEEDS_OPERATOR_REVIEW`
deploys only after explicit operator approval, with the AMBIGUOUS sample rows surfaced
for triage.

---

## 20.G Relationship to mechanical verification

Semantic verification runs AFTER mechanical verification passes (lead count > 0, schema
validates, dashboard renders, no console errors). A mechanical failure blocks semantic
verification from running. Semantic verification is the second gate.

The `build_verdict` (per §13 / §16) is the recon-phase output. The semantic verification
verdict is the deploy-phase output. Both are required for a county to ship.

---

## 20.H Reference implementation

A county-agnostic reference implementation template is provided at
`scaffold/ops/semantic_verify_template.py`. The template is DOCUMENTATION-GRADE: it
describes the structure of each check, the required inputs (the `matched_leads.json`
path, the dashboard URL, sample sizes), and the expected output (a verification-report
markdown file). Counties copy the template to
`runs/<county_slug>/build/semantic_verify_<county_slug>.py` and specialize the check
implementations for their source taxonomy, browser-automation tooling, and CSV export
format.

The template is NOT a production tool. v5.3.0 explicitly does NOT ship a working
production semantic verifier — that is deferred to v5.4.0 or later. The template defines
the contract; counties implement against it.

---

## 20.I Cross-references

- **§13** Lead Origination Contract — which sources originate leads.
- **§16** Source of Record Matrix — recon output, authoritative for build eligibility.
- **§17** Debtor Party Rules — `owner_name` attribution.
- **§18** Signal Aggregation Contract — signal collapse logic.
- **§19** Aggregator Idempotency Rule — pipeline integrity.
- Build Mode Protocol (Session A4, forthcoming) — deploy-gate sequencing.

---

## 20.J Universal versus county-specific separation

- **Universal** — the 12 check classes, the three-state outcome model, the sample-size
  rules, and the deploy verdicts. They live in this file.
- **County-specific** — the per-county check implementations live in
  `runs/<county_slug>/build/semantic_verify_<county_slug>.py`. Per-county sample sizes
  and thresholds, where customized above the universal floors, live in
  `config/counties/<county_slug>.json` under `semantic_verification`.

This file contains no county name, no state name, and no county-specific example. The
county-agnostic regression scanner enforces this.
