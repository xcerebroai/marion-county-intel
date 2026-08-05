# 18. Signal Aggregation Contract (v5.3.0+)

The signal aggregation contract defines how multiple raw records about the same property
collapse into the signal chips, signal counts, and stacked-signal totals visible on the
lead dashboard.

This file is the universal contract. The per-county canonical doc-type taxonomy and the
per-county signal-type display labels live in `config/counties/<county_slug>.json`.

---

## 18.0 Status and scope

- **Version:** v5.3.0 (Session A2 — Gap 6).
- **Date:** 2026-05-18.
- **Authoritative for:** every pipeline component that groups raw records into signals
  on a matched lead.
- **Scope:** universal — the aggregation key, the within-group merge contract, the
  cross-source rule, the legitimate-stacking-versus-dedup-failure test, and the
  anti-collapse rule. Per-county taxonomy and display labels live in the county config.

---

## 18.A Purpose

The signal aggregation contract defines how multiple raw records about the same property
collapse into the signal chips, signal counts, and stacked-signal totals visible on the
lead dashboard. Without an explicit contract, aggregation produces duplicate chips,
inflated counts, or signal collapse (multiple distinct signals merging into one).

---

## 18.B The aggregation key

Signals are grouped by the tuple `(parcel_id, canonical_doc_type, signal_type)`:

- **`parcel_id`** — the resolved property identifier, in county-canonical form.
- **`canonical_doc_type`** — the doc type after county taxonomy normalization (e.g.
  `hospital_lien`, `executor_deed`).
- **`signal_type`** — the operator-facing semantic category (e.g. "Hospital Lien",
  "Estate-Titled Property", "Federal Tax Lien").

The aggregation key is the dedup boundary. Multiple raw records that share the full key
collapse into a single signal with a count badge. Records that differ in any tuple
component remain distinct signals.

---

## 18.C What gets merged within a signal group

When N raw records share the aggregation key, the resulting signal carries:

- **`count`** — N.
- **`instrument_numbers`** — array of distinct instrument numbers, one per source record.
- **`source_urls`** — array of distinct source proof URLs.
- **`evidence_ids`** — array of distinct evidence file paths (PDF paths, screenshot
  paths).
- **`earliest_recorded_date`** — the earliest of the N record dates.
- **`latest_recorded_date`** — the latest of the N record dates.
- **`recorded_date_range`** — the pair `(earliest, latest)` for display.

The signal's display label remains the canonical `signal_type`. The count badge displays
N if N > 1. There is no display change for N = 1.

---

## 18.D Cross-source aggregation

When a lead is anchored to a parcel and signals originate from multiple sources
(`clerk_recordings` + `foreclosure_notices`, for example), each source contributes its
own signals to the lead's signal list. Cross-source signals MUST be deduplicated by the
same `(parcel_id, canonical_doc_type, signal_type)` key.

Example: a clerk-recorded foreclosure notice plus a foreclosure-portal foreclosure notice
for the same parcel and same recording date collapse to one signal with `count = 2` and
`source_urls` containing both URLs. If the recording dates differ but parcel and doc type
match, they still collapse — it is the same legal event recorded across two sources.

---

## 18.E Distinguishing legitimate stacking from dedup failures

Legitimate stacking (`count > 1` expected):

- multiple distinct hospital liens against the same patient over time — different
  instrument numbers, different dates;
- multiple state tax liens for sequential filing periods;
- an executor's deed filed N times when an estate filed N separate deeds for N parcels
  under one administrator.

Dedup failure (`count > 1` is a bug):

- the same `instrument_number` appearing N times in the input stream;
- the same source URL appearing N times;
- an identical raw record duplicated across multiple ingest passes.

The aggregator MUST union by `instrument_number` within a group. If the union reduces the
count below the input record count, the difference is dedup; if it does not, the count is
legitimate stacking.

---

## 18.F Anti-collapse rule

Distinct `signal_type` values MUST NOT collapse into one, even when they share
`parcel_id` and source. Example: a parcel with a `hospital_lien` AND an `executor_deed`
AND a `federal_tax_lien` produces THREE signals on the lead, not one. The `signal_type`
component of the aggregation key prevents collapse across types.

---

## 18.G Per-type caps and visual treatment (display contract)

When `count` exceeds a display threshold (e.g. `count > 5`), the signal chip displays
"Signal Type × N" with N visible. The dashboard MUST NOT truncate or hide high-count
signals — operators need to see when stacking is unusually high, which is a signal of
either genuine high engagement with the property OR a dedup failure to investigate.

---

## 18.H Cross-reference to §13 and §17

- **§13** (`13_lead_origination_contract.md`) determines which records originate leads.
- **§17** (`17_debtor_party_rules.md`) determines which party in the record is the
  debtor (`owner_name`).
- **§18** (this contract) determines how multiple records about the same property
  collapse into signals.

---

## 18.I Universal versus county-specific separation

- **Universal** — the aggregation key, the within-group merge contract, and the
  anti-collapse rule. They live in this file.
- **County-specific** — the per-county canonical doc-type taxonomy lives in
  `config/counties/<county_slug>.json`; the per-county signal-type display labels live
  in `config/counties/<county_slug>.json` under `signal_type_labels`.

This file contains no county name, no state name, and no county-specific example. The
county-agnostic regression scanner enforces this.

---

## 18.J Amendment note — v5.4.0 Session 3 reconciliations

v5.4.0 Session 3 implemented the §18 aggregation key engine
(`scaffold/pipeline/aggregation_key_engine.py`) and the leads-base writer
(`scaffold/pipeline/leads_base_writer.py`). The findings resolved during that
build are recorded here; the sections above are left unchanged for history and
this note is authoritative where it supersedes them.

### F-3 — null-parcel records must not over-collapse

§18.B keys signals on `(parcel_id, canonical_doc_type, signal_type)`, but
§13.14 emits UNRESOLVED leads with `parcel_id = null`. Grouping null-parcel
records by that key alone would collapse every distinct unresolved property of
the same doc type into one signal. **Resolution:** when `parcel_id` is null the
grouping tuple substitutes a per-record **fallback identity** —
`instrument_number`, else `raw_event_id` — so each distinct unresolved property
stays a distinct signal. The fallback is folded under a sentinel so it can
never compare equal to a real parcel id. A null-parcel key offered for grouping
with no fallback identity is a hard error, never a silent merge. The aggregator
MUST NEVER collapse two distinct properties because both have `parcel_id = null`.

### F-4 — signal_type is redundant for grouping; canonical_doc_type is the discriminator

§18.B places `signal_type` in the key; §18.I derives `signal_type` from
`canonical_doc_type` via the county `signal_type_labels` map. The relationship
is **many-to-one**: distinct canonical doc types legitimately share one
operator-facing label (an executor's deed and an administrator's deed surface
under one estate-titled label; a mechanic's lien and a construction lien share
one lien label). Because `signal_type` is a function of `canonical_doc_type` it
carries no grouping information beyond it. **Resolution:** `signal_type` is
retained in the key as the schema-required display component, but
`canonical_doc_type` is the **authoritative grouping discriminator**. The §18.F
anti-collapse guarantee is enforced by `canonical_doc_type` — grouping on
`signal_type` would itself be a collapse bug under the many-to-one relationship.

### F-5 — REVIEW_REQUIRED leads-base records may carry a null filer_entity

`leads_base_record.schema.json` originally required `filer_entity` to be
non-null whenever `parcel_resolution_status` is `REVIEW_REQUIRED`. The §17
engine's F-5 default rule (a `canonical_doc_type` with no §17.C rule) routes to
`REVIEW_REQUIRED` with `filer_entity = null` — no filer can be identified
without a rule. The constraint was stale (pre-F-5). **Resolution:** the
schema's `allOf` clause was relaxed to require only a non-empty `review_reason`
on a `REVIEW_REQUIRED` record; `filer_entity` may be null. This mirrors the
Session 2 reconciliation of the debtor-resolved contract to the same finding.

### Owner mailing address is not a leads-base field

The leads-base record is pipeline stage 3, built before any enrichment source
runs (`enrichment_status` is `UNENRICHED` at this stage). Owner mailing address
is appraisal-district / parcel-master **enrichment** data; it attaches
downstream when an enrichment source decorates the lead, never on the base
record. Carrying it on the base record would violate the §13 lead-versus-
enrichment boundary. The leads-base record has no mailing-address field, by
design. (Skip-traced phone / contact data is likewise downstream external
enrichment and is never carried on the leads-base record.)

### confidence_status — a rolled-up confidence label, computed once

`leads_base_record.schema.json` gains a `confidence_status` field, valued with
the four §08 prime-directive labels — Confirmed, Estimated, Possible, Unknown.
It is computed once, by the leads-base writer; the dashboard never computes
confidence itself. The roll-up rule is explicit and deterministic:

1. For every §08 evidence-ledger entry the record's `evidence_ids` point to,
   read its `status` and map it to a prime-directive label — Confirmed,
   Estimated, Possible, and Unknown map to themselves; `Needs Review` and
   `Unsupported`, which are not a positive confidence claim, map to Unknown; a
   referenced-but-missing entry or unrecognised status also counts as Unknown.
2. `confidence_status` is the **weakest** of those labels, ranked
   Confirmed > Estimated > Possible > Unknown. A lead is never labelled more
   confident than its least-supported claim.
3. A record with no evidence entries — or built with no evidence ledger
   available — is `Unknown`. Absence of evidence is not confidence.
