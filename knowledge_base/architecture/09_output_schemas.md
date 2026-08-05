# 09 — Output Schemas

The build must create strict schemas before production scraping. The AI cannot invent fields during the build. Every adapter must emit into these shapes.

This file is the schema contract. It defines the 10 record types the framework produces. Every pipeline stage validates input and output against these schemas. Validation failure routes to review or halts the build depending on severity.

---

## Why strict schemas matter

A prior county build had loosely-typed records. Different scrapers emitted different field names for the same concept (`owner` vs `owner_name` vs `OWNER_NAME`). The build script normalized at join time, which meant bugs in normalization showed up only at the end of the pipeline, after data was committed. Strict schemas push validation to the boundary: a scraper can't write a record that doesn't conform.

---

## 1. Raw source record

The output of every scraper, before any normalization. One record per source row / document / case.

```json
{
  "raw_record_id": "raw_<uuid>",
  "source_id": "clerk_recordings",
  "source_class": "lead_generating",
  "captured_at": "2026-05-07T15:00:00Z",
  "source_url": "https://example.source/record/123",
  "source_document_id": "DOC123456",
  "source_row_id": "row_00042",
  "raw_payload": {},
  "raw_text": "",
  "parser_name": "clerk_recordings_v1",
  "parser_version": "1.0.0",
  "parser_confidence": 0,
  "errors": []
}
```

`raw_payload` holds the structured data as the source returned it (JSON object, parsed table row, etc.). `raw_text` holds OCR or unstructured text when applicable. Either may be empty; never both.

Stored at `data/raw/<source_id>.jsonl`, one record per line.

---

## 2. Normalized signal

A raw record that has been parsed into the framework's pattern/subtype taxonomy. One signal per distinct event.

```json
{
  "signal_id": "sig_<uuid>",
  "raw_record_id": "raw_<uuid>",
  "source_id": "clerk_recordings",
  "source_class": "lead_generating",
  "raw_doc_type": "LIS PEND",
  "normalized_doc_type": "LIS_PENDENS",
  "doc_type_confidence": 95,
  "doc_type_normalization_reason": "exact_match_universal_registry",
  "pattern": "foreclosure",
  "subtype": "lis_pendens",
  "event_date": "2026-05-07",
  "lifecycle_status": "ACTIVE",
  "lifecycle_stage": "suit_filed",
  "suppressed_by": null,
  "supersedes": null,
  "document_priority": 75,
  "party_names": [],
  "party_roles": {},
  "property_refs": {
    "parcel_id": null,
    "situs_address": null,
    "legal_description": null,
    "case_number": null,
    "instrument_number": null
  },
  "amounts": [],
  "status": "Confirmed",
  "change_status": "NEW_RECORD",
  "first_seen_at": "2026-05-07T15:00:00Z",
  "last_seen_at": "2026-05-07T15:00:00Z",
  "evidence_ids": []
}
```

`pattern` must be one of the 14 patterns from `domain/01_lead_types.md`. `subtype` must be a recognized subtype for that pattern. `normalized_doc_type` must be a key in `canonical_doc_types.json`. `property_refs` may have all-null values when the source doesn't link to property — in that case the signal is an orphan and routes to review for property matching.

`change_status` is one of:
- `NEW_RECORD` — first appearance in any framework run
- `UPDATED_RECORD` — record existed in prior runs; one or more fields changed
- `UNCHANGED_RECORD` — record existed and is identical to the prior run's snapshot
- `REMOVED_RECORD` — record was in a prior run but no longer appears in the current source pull (does NOT delete the record; marks it as no-longer-current — TTL governs eventual archival)

`first_seen_at` is set on creation and never updated. `last_seen_at` is updated every run where the record appears. These two timestamps combined with `change_status` answer the dashboard question "what's new today?" without recomputing diffs across the full record store.

`doc_type_normalization_reason` is one of: `exact_match_county_synonym`, `exact_match_universal_registry`, `punctuation_tolerant_match`, `fuzzy_match`, `ocr_repair`, `semantic_inference`. Used for audit and to trigger review queue when speculative matches are used.

`lifecycle_status` is one of: `ACTIVE`, `RELEASED`, `SATISFIED`, `DISCHARGED`, `DISMISSED`, `EXPIRED`, `SUPERSEDED`, `UNKNOWN` (see `domain/09_document_lifecycle.md`). `lifecycle_stage` is the named stage within the lifecycle sequence. `suppressed_by` (if non-null) is the `signal_id` of the negative signal that suppressed this one. `supersedes` (if non-null) is the `signal_id` of the prior-stage signal this one supersedes in lifecycle tracking.

`party_roles` is a map from party name to role (per `canonical_doc_types.json` party_roles list).

Stored at `data/signals.jsonl`.

---

## 3. Parcel record

A property's metadata. One record per parcel ID, sourced from the parcel master / appraisal district.

```json
{
  "parcel_id": "",
  "alternate_parcel_ids": [],
  "situs_address": "",
  "situs_city": "",
  "situs_state": "",
  "situs_zip": "",
  "legal_description": "",
  "owner_name": "",
  "owner_mailing_address": "",
  "property_class": "",
  "assessed_value": null,
  "land_value": null,
  "improvement_value": null,
  "last_sale_date": null,
  "last_sale_price": null,
  "source_id": "parcel_master",
  "source_url": "",
  "evidence_ids": []
}
```

`alternate_parcel_ids` carries any historical or formatted variants (with/without dashes, pre-renumbering values) so the matcher can join on legacy IDs.

Stored at `data/parcels.jsonl`.

---

## 4. Matched lead

The output of the join + scoring + classification pipeline. This is what the dashboard reads.

```json
{
  "lead_id": "lead_<uuid>",
  "primary_parcel_id": "",
  "normalized_address": "",
  "owner_entity_id": "ent_<uuid>",
  "signals": [],
  "patterns": [],
  "attributes": [],
  "score": 0,
  "score_reasons": [],
  "deal_paths": [],
  "deal_path_reasons": [],
  "match_confidence": 0,
  "parser_confidence_avg": 0,
  "doc_type_normalization": {
    "raw_doc_types_seen": [],
    "normalized_doc_types": [],
    "doc_type_confidences": [],
    "doc_type_review_required": false
  },
  "lifecycle_states": [
    {
      "lifecycle": "",
      "current_stage": "",
      "stage_entered_at": "",
      "lifecycle_status": "active",
      "active_signals": [],
      "suppressed_signals": []
    }
  ],
  "title_complexity_score": 0,
  "title_complexity_tier": "Clean",
  "title_complexity_contributors": [],
  "document_priority_max": 0,
  "evidence_ids": [],
  "review_flags": [],
  "lead_status": "STACKED_LEAD",
  "lead_status_history": [],
  "export_status": "Needs Review"
}
```

**Field reference for the new normalization/lifecycle/complexity blocks:**

- `doc_type_normalization` — summary of canonical-type normalization across all signals on this lead (per `domain/08_document_normalization.md`). Arrays parallel each other by index. `doc_type_review_required` is true if any signal's normalization confidence fell below 80.
- `lifecycle_states` — one entry per active lifecycle on the parcel (per `domain/09_document_lifecycle.md`). A parcel may have multiple lifecycles simultaneously (e.g., open probate AND active mechanics lien). Each carries its current stage and the signals contributing to it.
- `title_complexity_score` — 0–100 (per `domain/10_title_complexity.md`). Independent of the motivation `score`.
- `title_complexity_tier` — one of `Clean`, `Light curative`, `Moderate curative`, `Complex`, `Very complex / specialist required`.
- `title_complexity_contributors` — array of `{factor, weight}` showing what drove the complexity score. Required when `title_complexity_score > 0`.
- `document_priority_max` — highest `document_priority` across all signals on this lead, used for in-tier sort on the dashboard.

`signals` is an array of `signal_id` references. `patterns` is the deduplicated pattern list across those signals. `attributes` is the parcel-attribute list (`vacant`, `absentee`, etc.). `score_reasons` carries the arithmetic chain. `deal_paths` carries `[{path, confidence, rationale}]` tuples. `export_status` is one of `Ready`, `Needs Review`, `Hold`, `Archive`.

**`lead_status`** captures where the lead is in its full lifecycle from raw scrape to operator outreach:

| Status | Meaning |
|---|---|
| `RAW_RECORD` | Scraped from source, not yet normalized |
| `NORMALIZED_SIGNAL` | Doc-type normalized to canonical, pattern assigned, not yet matched to a parcel |
| `MATCHED_PARCEL` | Signal joined to a parcel record with sufficient match confidence |
| `STACKED_LEAD` | At least one signal stacked into a scored lead with deal-path classification |
| `REVIEW_REQUIRED` | Triggered a review queue rule per `domain/05_review_queue_rules.md` |
| `APPROVED_FOR_DASHBOARD` | Passed all review gates, visible on the client dashboard |
| `EXPORTED_TO_CRM` | Operator pulled the CSV export or pushed to CRM via integration |
| `CONTACTED` | Operator or operator's client has attempted outreach (set by CRM webhook if integrated) |
| `DEAD` | Owner not interested, do-not-contact, property already sold, etc. (set by CRM webhook) |
| `ARCHIVED` | Stale or aged out per TTL; preserved in record store but not displayed |

**`lead_status_history`** is an append-only array of `{status, transitioned_at, reason}` entries. Every status change is logged so the framework can answer "when did this lead become a lead and where is it now?"

Transitions are gated:
- A lead cannot skip from `RAW_RECORD` to `APPROVED_FOR_DASHBOARD`. It must move through intermediate states.
- `REVIEW_REQUIRED` is a side-state — a lead can enter from any earlier state and return to its prior state once review clears.
- `DEAD` and `ARCHIVED` are terminal — once set, a lead cannot return to `APPROVED_FOR_DASHBOARD` without a new signal firing (which creates a new lead lifecycle).
- `CONTACTED` requires CRM-side input. The framework cannot self-promote a lead to `CONTACTED` from internal signals alone.

Stored at `data/leads.json` (single file, indented, dashboard-readable).

---

## 5. Review queue record

Records held back from auto-export.

```json
{
  "review_id": "rev_<uuid>",
  "lead_id": "lead_<uuid>",
  "reason": "match_confidence_low",
  "severity": "medium",
  "field": "owner_name",
  "current_value": null,
  "suggested_value": null,
  "evidence_ids": [],
  "created_at": "2026-05-07T15:00:00Z",
  "status": "open"
}
```

`reason` matches the trigger names from `domain/05_review_queue_rules.md`. `severity` is `low`, `medium`, or `high`. `status` is `open`, `approved`, `rejected`, or `merged`.

Stored at `data/review_queue.jsonl`.

---

## 6. Dashboard record

A subset of the matched-lead record, optimized for dashboard rendering. The pipeline projects this view from `data/leads.json` records.

```json
{
  "lead_id": "lead_<uuid>",
  "display_address": "",
  "owner_name": "",
  "patterns": [],
  "score": 0,
  "deal_paths": [],
  "status_chips": [],
  "source_chips": [],
  "evidence_summary": {},
  "review_flags": [],
  "last_updated_at": "2026-05-07T15:00:00Z"
}
```

`status_chips` and `source_chips` are small UI-ready arrays the dashboard renders without further processing. `evidence_summary` matches the rollup from `08_evidence_ledger.md`.

---

## 7. CRM export record

The CSV row format the operator's client imports into Go High Level (or equivalent CRM).

```json
{
  "lead_id": "lead_<uuid>",
  "owner_name": "",
  "property_address": "",
  "mailing_address": "",
  "phone_1": null,
  "phone_2": null,
  "email_1": null,
  "lead_pattern": "",
  "score": 0,
  "deal_path": "",
  "source_name": "",
  "source_url": "",
  "match_confidence": 0,
  "parser_confidence": 0,
  "review_required": false,
  "notes": ""
}
```

`phone_*` and `email_*` are null at framework boundary — the framework produces clean leads, downstream skip-trace fills contact paths.

---

## 8. Evidence object

Defined in `08_evidence_ledger.md`. Every evidence object has its own ID and links to one or more `record_id` (lead, parcel, signal, entity).

Stored at `data/evidence.jsonl`.

---

## 9. Source run log

One entry per scraper invocation.

```json
{
  "run_id": "run_<uuid>",
  "source_id": "tax_collector",
  "started_at": "2026-05-07T15:00:00Z",
  "finished_at": "2026-05-07T15:05:00Z",
  "status": "success",
  "records_seen": 0,
  "records_new": 0,
  "records_updated": 0,
  "records_failed": 0,
  "cursor_before": null,
  "cursor_after": null,
  "errors": []
}
```

`status` is one of `success`, `partial`, `failure`, `aborted`. `cursor_before`/`cursor_after` reference the cursor state per `10_source_heartbeat_and_cursors.md`.

Stored at `data/source_runs.jsonl`.

---

## 10. Source heartbeat

Defined in `10_source_heartbeat_and_cursors.md`. One record per source, updated on every run.

Stored at `data/source_heartbeat.json` (one object per source, keyed by `source_id`).

---

## 11. Run manifest

One manifest per pipeline run (not per source — the manifest aggregates the entire run across all sources). The manifest answers the operator's question "what ran today and what came out of it?"

```json
{
  "run_id": "run_<uuid>",
  "county_id": "<county_id>",
  "county_name": "<county name>",
  "state": "<2-letter state code>",
  "started_at": "2026-05-07T06:00:00Z",
  "finished_at": "2026-05-07T06:42:18Z",
  "duration_seconds": 2538,
  "sources_attempted": 0,
  "sources_succeeded": 0,
  "sources_failed": 0,
  "records_collected": 0,
  "records_normalized": 0,
  "records_new": 0,
  "records_updated": 0,
  "records_unchanged": 0,
  "records_removed": 0,
  "leads_created": 0,
  "leads_updated": 0,
  "leads_status_transitions": {
    "RAW_RECORD": 0,
    "NORMALIZED_SIGNAL": 0,
    "MATCHED_PARCEL": 0,
    "STACKED_LEAD": 0,
    "REVIEW_REQUIRED": 0,
    "APPROVED_FOR_DASHBOARD": 0
  },
  "review_required": 0,
  "errors": [
    {
      "source_id": "<source_id>",
      "failure_classification": "<classification>",
      "message": "<error message>"
    }
  ],
  "output_files": [
    "data/leads.json",
    "data/signals.jsonl",
    "data/review_queue.jsonl",
    "data/source_heartbeat.json"
  ],
  "config_version": "<sha or version of config/counties/<county>.json used>",
  "framework_version": "v4-extension"
}
```

Stored at `data/runs/<run_id>.manifest.json`. The most recent manifest is also symlinked to `data/runs/latest.manifest.json`. The manifest is the single document the operator points a client to when asked "what ran today?"

### Source failure classification

The `errors[].failure_classification` field uses a controlled vocabulary so the operator can route fixes appropriately. Allowed values:

| Classification | What it means | Typical fix |
|---|---|---|
| `NO_RESULTS` | Scraper ran successfully but returned zero records (may be normal for the day, may be silent failure) | Compare to historical baseline; alert if >50% drop |
| `PARSER_CHANGED` | HTML/JSON structure differs from what parser expects | Re-run Phase 0 fingerprint; update adapter |
| `CAPTCHA_REQUIRED` | A CAPTCHA challenge appeared on a session that previously didn't need one | Re-seed session or escalate to solver path |
| `SESSION_EXPIRED` | Operator-seeded session cookies are no longer valid | Telegram alert for re-seed |
| `WAF_BLOCKED` | Imperva / Akamai / Cloudflare returned a challenge or 403 | Rotate residential proxy, stealth-browser update, or escalate |
| `RATE_LIMITED` | HTTP 429 or equivalent | Honor backoff and retry later; reduce concurrency |
| `LOGIN_REQUIRED` | Source has added authentication that wasn't required before | Configure operator-credentialed login path |
| `SOURCE_DOWN` | HTTP 5xx or connection refused | Re-probe on next schedule; alert if down >24h |
| `LAYOUT_CHANGED` | Page loads but the selectors / JSON keys the adapter expects don't exist | Re-run Phase 0 fingerprint; update adapter |
| `TIMEOUT` | Request or render exceeded configured timeout | Increase timeout, or rate-limit the source if pattern recurs |
| `UNKNOWN_ERROR` | Failure that didn't match the above patterns | Investigation required; default classification for unexpected failures |

Every error log entry must use one of these classifications. Free-form "failed" messages are rejected at validation.

---

## Validation rule

Every pipeline stage validates input and output against these schemas using `jsonschema`. Validation failure handling:

| Failure type | Action |
|---|---|
| Required field missing | Route record to review queue with reason `schema_violation` |
| Field type mismatch | Same |
| Enum value out of range | Same |
| Nested object missing | Halt pipeline, write `BUILD_BROKEN.md` |
| Schema file itself invalid | Halt pipeline, write `BUILD_BROKEN.md` |

The schema files themselves live at `pipeline/schemas/*.schema.json`. Each pipeline module imports the schema it produces and validates before write.
