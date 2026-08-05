# 08 — Evidence Ledger

The evidence ledger is mandatory. Every field shown in the dashboard, stored in the database, sent to an export, or used in scoring must have a source trail. **If there is no evidence, the field cannot be marked Confirmed.**

This file is the contract that enforces the prime directive from `MASTER_PROMPT.md`. The Hallucination Controls (`domain/06_hallucination_controls.md`) define what counts as fabrication; this file defines the data structure that prevents it.

---

## Purpose

The ledger prevents:
- Unsupported claims
- Fabricated certainty (a field labeled `Confirmed` with no source)
- Bad joins (two records merged without evidence the merge is correct)
- Weak exports (CSV rows the operator's client cannot trace back to a county source)

It also lets the operator prove provenance to a client. When a client asks "where did this lead come from?", the operator opens the lead's evidence drawer and points to the originating clerk record, court docket, or sheriff PDF.

---

## Evidence object schema

Every claim in the system has at least one evidence object backing it.

```json
{
  "evidence_id": "ev_<uuid>",
  "record_id": "lead_<uuid>",
  "field": "owner_name",
  "value": "Example Owner LLC",
  "status": "Confirmed",
  "source_id": "clerk_recordings",
  "source_name": "County Clerk Recorded Instruments",
  "source_class": "lead_generating",
  "source_reliability_grade": "A",
  "source_url": "https://example.source/record/123",
  "source_document_id": "DOC123456",
  "source_row_id": "row_00042",
  "captured_at": "2026-05-07T15:00:00Z",
  "parser_name": "clerk_recordings_v1",
  "parser_version": "1.0.0",
  "parser_confidence": 96,
  "match_confidence": 94,
  "derivation": null,
  "notes": "Owner name extracted from grantee field on recorded instrument."
}
```

**Field meanings:**
- `evidence_id` — UUID for the evidence object itself
- `record_id` — the lead, parcel, signal, or entity this evidence supports
- `field` — the canonical field name being evidenced
- `value` — the actual value as it appears in this evidence (may differ from final record value if multiple sources contribute)
- `status` — one of `Confirmed`, `Estimated`, `Possible`, `Unknown`, `Needs Review`, `Unsupported` (see status rules below)
- `source_id` — short identifier matching `config/counties/<county>.json` sources keys
- `source_class` — `lead_generating`, `enrichment`, `negative_signal`, or `review_required`, per `domain/02_signals_and_sources.md`
- `source_reliability_grade` — one of `A`, `B`, `C`, `D`, `E` (see source reliability grading below). Not all sources are equal — a search-result snippet is not the recorder. The grade gates how the framework treats the evidence.
- `source_url` — verbatim URL from scraper output, never templated
- `source_document_id` / `source_row_id` — pointers into the source for audit replay
- `captured_at` — when this evidence was collected
- `parser_name` / `parser_version` — which scraper produced it (lets the framework retire stale parser output during version upgrades)
- `parser_confidence` — 0–100, parser's self-report
- `match_confidence` — 0–100, only meaningful for evidence that joins one record to another
- `derivation` — required when `status == "Estimated"`; describes the formula or proxy used
- `notes` — free-form parser commentary

---

## Source reliability grading

Every source declared in `config/counties/<county>.json` must carry a `source_reliability_grade`. This is set during Phase 0 recon and lives in the county config alongside the access pattern and source priority. Every evidence object inherits the grade from its source.

| Grade | Meaning | Example |
|---|---|---|
| **A** | Official source of truth | County clerk recorder, county tax collector, court of jurisdiction, sheriff's office direct |
| **B** | Official but delayed | Same official source delivered via public-records request or monthly bulk extract |
| **C** | Vendor mirror of official source | Third-party portal that licenses or republishes the official data (e.g. ArcGIS feature service mirroring tax-assessor data) |
| **D** | Scraped public display only | Public-facing search interface where data is visible but not authoritative (e.g. property aggregator showing parsed clerk data) |
| **E** | Enrichment only, never proof | USPS vacancy flags, utility shutoffs, geocoder normalization, third-party demographic overlays |

**Rules:**

- **A and B grades can carry status `Confirmed`** when parser confidence is high.
- **C grades default to status `Estimated`** unless cross-confirmed by an A or B source.
- **D grades default to status `Possible`** and cannot promote to `Confirmed` without an A/B/C source.
- **E grades cannot back lead-generating signals.** An E grade can enrich a lead (add an attribute, decorate a row) but cannot fire a pattern or contribute to scoring.
- **Two D-grade sources do not promote each other.** Aggregator-to-aggregator agreement is not corroboration.
- **A grade requires direct access path** (open, seeded session, operator login, or scheduled records-request from the official custodian). Vendor-mediated access drops the grade to B or C depending on whether the vendor delivers on the official cadence.

The grade is part of the source's `last_verified_at` audit chain — if a source changes vendors mid-build, the grade must be re-evaluated and logged.

---

## Required evidence per lead

Every lead in `data/leads.json` must have at least one evidence object covering each of:
- Source event (the originating recording / filing / sale)
- Event date
- Source class (lead_generating vs enrichment)
- Property identifier (parcel ID, address, or legal description)
- Owner or party name (when source provides it)
- Source URL or source document reference
- Parser confidence
- Match confidence
- Lead pattern (which of the 11 patterns from `domain/01_lead_types.md` fired)
- Score reasons (the arithmetic chain from `domain/03_scoring_and_stacking.md`)
- Deal path reasons (the rationale chain from `domain/04_deal_path_classifier.md`)

A lead missing evidence for any required item routes to review queue with reason `evidence_incomplete` and does NOT export.

---

## Status rules

Six labels, used consistently across evidence objects, fields, and exports.

### `Confirmed`
The field is directly present in a verified source. The scraper log captured the value from a primary source. No inference.

Use when:
- Owner name appears in clerk grantee field
- Sale date appears in clerk recording
- Tax balance appears in tax collector portal

### `Estimated`
Derived from a proxy, model, calculation, or inferred logic. **Must include a `derivation` field** that shows the formula or proxy.

Use when:
- `high_equity` attribute fires from `assessed_value >= 2 * last_sale_price + 5_yr_owned`
- `senior_owner` fires from `years_owned >= 25` proxy
- `favorable_loan_era` fires from `last_sale_date in [2020-01-01, 2022-06-30]`

Derivation example:
```json
{
  "derivation": {
    "rule": "high_equity",
    "inputs": {"assessed_value": 510000, "last_sale_price": 125000, "years_owned": 33},
    "formula": "assessed_value >= 2 * last_sale_price AND years_owned >= 5",
    "result": true
  }
}
```

### `Possible`
The field pattern matches but is not verified enough to mark Confirmed. Used for fuzzy-match results, partial OCR captures, parser uncertainty.

### `Unknown`
The field is expected but missing. The framework looked, didn't find it, doesn't fabricate.

### `Needs Review`
The field may be correct but a human should look at it. Used for data conflicts, parser-confidence-low, ambiguous matches.

### `Unsupported`
**Temporary internal label only.** When the framework detects a field marked Confirmed that has no backing evidence, it relabels to Unsupported and routes through the Guardian process from `domain/06_hallucination_controls.md`.

The Guardian relabels Unsupported fields to Unknown or Needs Review before any output is written. **A record containing an Unsupported field cannot ship to dashboard or export.** This is a hard rule.

---

## Evidence rollup

Every matched lead carries an evidence summary alongside the per-field detail:

```json
{
  "evidence_summary": {
    "confirmed_fields": 14,
    "estimated_fields": 3,
    "possible_fields": 2,
    "unknown_fields": 1,
    "needs_review_fields": 0,
    "unsupported_fields": 0,
    "primary_sources": ["clerk_recordings", "tax_collector"],
    "last_verified_at": "2026-05-07T15:00:00Z"
  }
}
```

The dashboard renders this as a small evidence chip per lead: "14 Confirmed, 3 Estimated, 2 Possible, 1 Unknown" with a click-through to the full evidence drawer.

---

## Dashboard display rules

The dashboard must surface evidence in at least one of these ways:
- Evidence drawer per lead (click to expand, see every evidence object)
- Source chips per field (small icons next to non-Confirmed fields)
- Source URL button (opens the originating county page in a new tab)
- Status icon beside uncertain fields (yellow for Estimated, gray for Unknown, red for Needs Review)
- Raw document link when available (deep-link to clerk PDF or scanned page)

The dashboard does NOT need to show every raw evidence field by default. But the evidence MUST be accessible — at minimum via a "view evidence" action per lead.

---

## Export rule

CSV and CRM exports must include source and confidence fields per row. Minimum columns:
- `lead_id`
- `source_name`
- `source_url`
- `source_document_id`
- `lead_status` (overall record status, derived from worst per-field status)
- `match_confidence`
- `parser_confidence`
- `evidence_count`
- `review_flags`

When the operator's client imports the CSV into Go High Level, every lead they call carries its evidence forward. The client can verify any lead by clicking the source URL before dialing.
