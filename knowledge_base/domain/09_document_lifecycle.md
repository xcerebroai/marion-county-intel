# 09 — Document Lifecycle

This file is the framework's chronology and status engine. Where `08_document_normalization.md` translates raw labels into canonical types, this file reasons about how those canonical types relate to each other over time.

The framework's per-instance pattern logic answers "what is this document?" Lifecycle answers "where in the legal process is this property right now?"

---

## Why lifecycle reasoning matters

A property with a `NOTICE_OF_DEFAULT` from 6 months ago and a `NOTICE_OF_SALE` from yesterday is not two separate foreclosure leads. It is one lead, currently in the **post-NOS, pre-sale** stage of the foreclosure lifecycle. The operator's client needs to know: sale is days away.

A property with a `MECHANICS_LIEN` from 2024 and a `RELEASE_OF_LIEN` from 2025 is not a title-cloud lead. The lien is satisfied. Active stack depth on liens is zero.

A property with a `PROBATE_CASE_OPENED` from 2024, `LETTERS_TESTAMENTARY` from 2024, and `EXECUTORS_DEED` from 2025 has completed the probate transfer. The estate signal is now **closed**, but the executor's deed is the lead — heirs converted the property and may be motivated to sell.

Lifecycle intelligence converts a flat list of recorded events into a structured timeline with a current stage.

---

## Lifecycle sequences

The framework recognizes these canonical lifecycles. Each sequence has stages; the property's current stage is the latest stage with a recorded event in the active timeline.

### Foreclosure (non-judicial)

```
NOTICE_OF_DEFAULT
   ↓
APPOINTMENT_OF_SUBSTITUTE_TRUSTEE  (some states; optional)
   ↓
NOTICE_OF_SALE / NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE
   ↓
TRUSTEES_DEED_UPON_SALE
```

Stages: `default_recorded` → `sale_scheduled` → `post_sale`.

Suppression: `RECONVEYANCE` or `SATISFACTION_OF_MORTGAGE` after `NOTICE_OF_DEFAULT` resolves the lifecycle to `cured` (current stage `none_active`).

### Foreclosure (judicial)

```
LIS_PENDENS
   ↓
FINAL_JUDGMENT_OF_FORECLOSURE
   ↓
SHERIFF_DEED
```

Stages: `suit_filed` → `judgment_entered` → `post_sale`.

Suppression: `RELEASE_OF_LIS_PENDENS` resolves to `dismissed`.

### Tax foreclosure

```
TAX_SALE_CERTIFICATE
   ↓
TAX_FORECLOSURE_NOTICE
   ↓
TAX_DEED
```

Stages: `cert_sold` → `final_notice` → `post_sale`.

### Probate

```
APPLICATION_FOR_PROBATE
   ↓
LETTERS_TESTAMENTARY  or  LETTERS_OF_ADMINISTRATION
   ↓
PERSONAL_REPRESENTATIVE_DEED  or  EXECUTORS_DEED  or  ADMINISTRATORS_DEED
```

Stages: `petition_filed` → `representative_appointed` → `transfer_recorded`.

Parallel path (no formal probate):
```
AFFIDAVIT_OF_HEIRSHIP
   ↓
QUITCLAIM_DEED  (heir-to-heir)  or  WARRANTY_DEED  (heirs to buyer)
```

### Lien lifecycle (any lien type)

```
<LIEN_TYPE>  (active)
   ↓
RELEASE_OF_LIEN  or  type-specific release  or  VACATED_JUDGMENT
```

Stages: `active` → `released`.

### Bankruptcy + foreclosure interaction

```
NOTICE_OF_DEFAULT  or  NOTICE_OF_SALE  (foreclosure scheduled)
   ↓
BANKRUPTCY_PETITION  (automatic stay)
   ↓
[stay relief or dismissal]
   ↓
NOTICE_OF_SALE  (re-noticed)  or  TRUSTEES_DEED_UPON_SALE
```

Stages: `pre_stay` → `under_stay` → `post_stay`.

---

## Status engine

Every canonical signal on a parcel carries a status:

| Status | Meaning |
|---|---|
| `ACTIVE` | Signal is current, contributes to scoring and stacking |
| `RELEASED` | Lien-type signal has been released |
| `SATISFIED` | Mortgage or judgment has been paid |
| `DISCHARGED` | Bankruptcy discharge or similar |
| `DISMISSED` | Court action dismissed before judgment |
| `EXPIRED` | Signal has aged past its TTL (per `domain/01_lead_types.md`) |
| `SUPERSEDED` | A later document in the same lifecycle replaced this one (e.g., `NOS` supersedes prior `NOD` in stage tracking) |
| `UNKNOWN` | Status cannot be determined from available evidence |

Only `ACTIVE` signals contribute to score and pattern stacking. Non-active signals stay in the record for audit and lifecycle reconstruction.

---

## How status is determined

For each canonical signal on a parcel:

1. **Check for negative-signal suppression.** If a `negative_signal` canonical type from the registry's `suppresses` array fires on the same parcel after this signal's event date, mark this signal `RELEASED` / `SATISFIED` / `DISCHARGED` / `DISMISSED` / `VACATED` per the negative type.

2. **Check for lifecycle supersession.** If a later canonical type in the same lifecycle sequence fires (e.g., `NOTICE_OF_SALE` after `NOTICE_OF_DEFAULT`), mark this signal `SUPERSEDED` for stage-tracking purposes. The earlier signal stays `ACTIVE` for scoring (the foreclosure pattern still fires) but the lifecycle stage advances.

3. **Check TTL.** If `event_date + ttl_days < today`, mark `EXPIRED`.

4. **Check chronology conflicts.** If a later document's stage appears before an earlier document's stage in the same sequence (e.g., `TRUSTEES_DEED_UPON_SALE` recorded before `NOTICE_OF_SALE`), do not auto-resolve. Route to review with reason `chronology_conflict`.

5. **Default.** If none of the above fires, status is `ACTIVE`.

---

## Current-stage computation per lifecycle

For each lifecycle sequence active on a parcel, the framework emits a `lifecycle_state`:

```json
{
  "lifecycle": "foreclosure_nonjudicial",
  "current_stage": "sale_scheduled",
  "stage_entered_at": "2026-04-15",
  "next_expected_stage": "post_sale",
  "next_expected_window_days": 21,
  "active_signals": ["sig_<uuid>", "sig_<uuid>"],
  "suppressed_signals": [],
  "lifecycle_status": "active"
}
```

`lifecycle_status` is one of `active`, `cured`, `dismissed`, `completed`, `under_stay`, `chronology_conflict`.

A parcel may have multiple lifecycles simultaneously (e.g., open probate + active mechanics lien). The framework tracks each independently. Stacking-bonus computation reads the count of active lifecycles, not the count of signals.

---

## Chronology rules

For a sequence to be valid, event dates must monotonically increase across stages. The framework enforces this:

- If an out-of-order recording is detected, route to review with `chronology_conflict`
- If two signals in different lifecycles have conflicting implications (e.g., `RECONVEYANCE` recorded *and* `NOTICE_OF_DEFAULT` on the same loan recorded later), route to review with `chronology_conflict`
- If a negative signal predates its positive signal, do not auto-suppress. Route to review.

**Implementation note:** the chronology check is bidirectional. For any two signals s1 and s2 in the same sequence with sequence indices idx1, idx2 and event dates d1, d2:
- Conflict if `idx1 < idx2 AND d1 > d2` (earlier-stage signal recorded later than a later-stage signal)
- Conflict if `idx1 > idx2 AND d1 < d2` (later-stage signal recorded earlier than an earlier-stage signal)

Either pattern means recorded chronology violates the canonical sequence. Both must be detected.

The framework does not silently reorder events. Recorded chronology is authoritative; conflicts surface to a human.

---

## Recording-date vs effective-date

Some documents have two dates:
- **Recording date** — when the clerk indexed it
- **Effective date** / **execution date** / **filing date** — when the underlying event occurred

Lifecycle reasoning uses **effective date** when both are available. If only recording date is available, use it. If a document's effective date is more than 90 days before its recording date, flag with `late_recording` (informational, not review-routing) — common for some document types and not a defect.

---

## Stacking interaction

`domain/03_scoring_and_stacking.md` computes stack bonuses based on the count of distinct *active* patterns on a parcel. Lifecycle reasoning affects stacking:

- A `MORTGAGE` followed by `SATISFACTION_OF_MORTGAGE` does not contribute to stacking (the mortgage is `SATISFIED`)
- A `MECHANICS_LIEN` followed by `RELEASE_OF_LIEN` does not contribute (the lien is `RELEASED`)
- An open probate (lifecycle in any active stage) contributes one `estate` pattern
- An open foreclosure (any active stage) contributes one `foreclosure` pattern

This is what prevents the framework from inflating scores on properties whose distress signals have all been resolved.

---

## Lifecycle stage and deal-path interaction

The deal-path classifier (`domain/04_deal_path_classifier.md`) reads lifecycle stage as input:

- Foreclosure stage `default_recorded` (early) → `sub_to` confidence high (time to negotiate)
- Foreclosure stage `sale_scheduled` (imminent) → `sub_to` confidence high but timeline-critical, `wholesale` confidence high
- Foreclosure stage `post_sale` → property has transferred; lead is now `surplus_owed` persona, not the original owner
- Probate stage `petition_filed` → estate is open; representative may not have authority to sell yet
- Probate stage `representative_appointed` → representative can negotiate; `wholesale` and `partial_interest` paths active
- Probate stage `transfer_recorded` → estate has closed; new owners are heirs; lead is now about heirs' motivation, not the decedent

The classifier writes `lifecycle_state` into each lead's `deal_path_reasons` array so the operator's client sees the timeline context in the rationale.

---

## What lifecycle reasoning does NOT do

- It does not predict timelines deterministically. `next_expected_window_days` is a rough estimate based on typical state-level statutory periods. Actual timing varies.
- It does not infer events that haven't been recorded. If a property is between stages with no recent recording, the lifecycle stays at the last known stage with a `stage_entered_at` of the most recent event.
- It does not interpret intent. A `QUITCLAIM_DEED` after `AFFIDAVIT_OF_HEIRSHIP` is "an heir conveyed their share to someone." Whether that someone is another heir, an investor, or a stranger is a question for downstream review or skip-trace work, not lifecycle reasoning.
