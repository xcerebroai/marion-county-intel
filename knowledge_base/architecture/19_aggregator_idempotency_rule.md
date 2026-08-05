# 19. Aggregator Idempotency Rule (v5.3.0+)

The aggregator idempotency rule prevents a class of bug where the aggregator writes to a
file it later reads from, causing inputs to grow on each run. Repeated aggregation must
produce identical output given identical inputs.

This file is the universal contract. The per-county base-file inventory lives in
`config/counties/<county_slug>.json`.

---

## 19.0 Status and scope

- **Version:** v5.3.0 (Session A2 — Gap 8).
- **Date:** 2026-05-18.
- **Authoritative for:** every build-phase aggregator that combines translator outputs
  into a single matched-leads artifact.
- **Scope:** universal — the bug pattern, the read-source rule, the idempotency
  invariant, and the self-check requirement. The per-county base-file inventory lives in
  the county config.

---

## 19.A Purpose

The aggregator idempotency rule prevents a class of bug where the aggregator writes to a
file it later reads from, causing inputs to grow on each run. Repeated aggregation must
produce identical output given identical inputs — i.e. the aggregation must be
idempotent.

---

## 19.B The bug pattern this rule prevents

An aggregator combines outputs from multiple translator pipelines into a single
`matched_leads.json`. If the aggregator reads its own previous output as input on the
next run, leads from the previous run get re-aggregated with the current run's leads,
inflating the total. The inflation may be partial (some leads duplicate) or full (counts
double each run).

The bug is subtle because:

- initial runs produce correct output;
- inflation appears only on the second run and beyond;
- diff-checking against the prior run's output looks like "more leads were ingested,"
  which is plausible;
- the bug compounds — each run adds another layer of duplication.

---

## 19.C The rule

Aggregators MUST read only from stable per-source base files (e.g.
`clerk_leads_base.json`, `foreclosure_notices_leads_base.json`) that are written by
upstream translators. Aggregators MUST NEVER read from their own output
(`matched_leads.json` or `dashboard/data.json`).

The pipeline contract:

    Translators write to *_base.json. The aggregator reads only from *_base.json files,
    never from matched_leads.json. Each aggregation run starts from the stable base
    files, not from the previous aggregate.

    [translator pipelines]  ->  <source>_leads_base.json   (stable per-source base files)
                                        |
                                        v
                            [aggregator]  reads base files only
                                        |
                                        v
                            matched_leads.json              (the aggregate output)
                                        |
                                        v
                            [dashboard build]  reads the aggregate

The aggregator's output is never used as input to itself.

---

## 19.D Idempotency invariant

Running the aggregator twice in succession on the same set of `*_base.json` inputs MUST
produce identical `matched_leads.json` output. If output differs between runs without
intervening base-file changes, the aggregator is non-idempotent and violates this rule.

---

## 19.E Detection

The aggregator implementation MUST include a self-check: after writing
`matched_leads.json`, the aggregator runs once more in dry-run mode and compares output
byte-for-byte. If outputs differ, the aggregator emits an error and refuses to deploy.

---

## 19.F Cross-reference

This rule applies to the build pipeline (§4.39 Build Mode Protocol, Session A4). The
aggregator is a build-phase component; the rule's enforcement happens during build, not
recon.

---

## 19.G Universal versus county-specific separation

- **Universal** — the rule, the pipeline contract, and the self-check requirement. They
  live in this file.
- The `*_base.json` filename pattern is a county-agnostic convention: any county
  pipeline must follow the `<source>_leads_base.json` naming.
- **County-specific** — the per-county base-file inventory lives in
  `config/counties/<county_slug>.json` under `pipeline.base_files`.

This file contains no county name, no state name, and no county-specific example. The
county-agnostic regression scanner enforces this.
