# 22. Doc-Type Namespace Bridge (v5.4.0 Session 8)

The v5.4.0 staged pipeline (§17 → §18 → §19 → §20) and the v5.1.2-beta monolith
run on the same data but speak different doc-type names. Three namespaces have
to agree before the staged engine can take over from the monolith. Session 8
builds the explicit, tested bridge between them; the cutover is a later session.

This file is the universal contract for the bridge. The bridge artifact is
`scaffold/pipeline/doc_type_bridge.py`; its tests are
`scaffold/tests/v5_4_0/test_doc_type_bridge.py`. The §17 rule-key reconciliation
(plural renames + broad-key fan-out) is recorded in
`knowledge_base/architecture/17_debtor_party_rules.md` §17.K Session 8.

---

## 22.0 Status and scope

- **Version:** v5.4.0 Session 8 (R1 / G1).
- **Date:** 2026-05-23.
- **Authoritative for:** the three-namespace reconciliation between §16's
  lead-type taxonomy, `canonical_doc_types.json`, and the monolith's
  `normalized_doc_type` output. The cutover from the v5.1.2-beta monolith to the
  v5.4.0 staged engine consumes this bridge as its doc-type seam.
- **Out of scope:** the cutover sequence itself, per-county doc-type synonyms
  (those layer on top via `normalize.normalize_doc_type`'s `county_synonyms`
  argument), and runtime debtor-party logic (that is §17).

---

## 22.A The three namespaces

1. **§16 — Source of Record Matrix
   (`knowledge_base/architecture/16_source_of_record_matrix.md`).** 27
   canonical Title-Case **lead_type** names (`Foreclosure`, `Trustee Sale`,
   `Tax Sale`, `Eviction`, …). The recon sweep guarantees a matrix entry per
   lead type per county; without a complete sweep no county enters Build Mode.
2. **`knowledge_base/domain/canonical_doc_types.json` — the registry.** 74
   UPPERCASE **canonical_doc_type** keys (`TAX_DEED`, `EVICTION_FILING`,
   `NOTICE_OF_SALE`, …) with subtype, lead_pattern, source_class, and
   common_abbreviations. The documented source of truth for doc-type
   normalization.
3. **`scaffold/pipeline/normalize.py` — the monolith's output.**
   `normalize_doc_type` reads a raw subtype string and returns one of the 74
   registry UPPERCASE keys (or `None` for unknown). The staged engine
   (`debtor_party_engine`, `aggregation_key_engine`, `aggregator`,
   `leads_base_writer`) consumes **lowercased** registry keys.

Until Session 8 the three names were aligned only by convention — no executable
artifact verified that the monolith's `normalized_doc_type` lowercased to a
registry-aligned value the staged engine understood, or that every registry
type traced back to a §16 lead type.

---

## 22.B The bridge contract

The bridge is the executable, tested artifact in
`scaffold/pipeline/doc_type_bridge.py`. It exposes:

- **`monolith_to_registry(NORMALIZED_DOC_TYPE) → str | None`** — lowercases an
  UPPERCASE monolith output to the registry-aligned canonical_doc_type the
  staged engine consumes. Returns `None` for an unknown input (no fuzzy
  fallback — the monolith's `normalize_doc_type` is the fuzzy layer; the
  bridge is strict).
- **`registry_to_lead_type(canonical_doc_type) → str | None`** — maps a
  lowercased registry canonical_doc_type to its §16 Title-Case lead_type, or
  `None` when the registry type has no §16 lead_type (enrichment, negative
  signal, sub-type — the reason is recorded in
  `REGISTRY_WITHOUT_LEAD_TYPE_REASONS`).
- **`lead_type_for_monolith_output(NORMALIZED_DOC_TYPE) → str | None`** —
  composes the two layers end-to-end.
- **`registry_types_for_broad_key(broad_key) → tuple[str, ...]`** — returns
  the registry canonical_doc_types a §17 broad-rule key fans out onto
  (Session 8 reconciliation; see 22.D below).
- **`bridge_totality_report() → dict`** — a structured report on bridge
  totality and gaps; consumed by the bridge totality test.

### Totality rule

- **Layer 1 totality.** Every UPPERCASE value `normalize.normalize_doc_type`
  can emit MUST bridge to a registry-aligned canonical_doc_type. The bridge
  test asserts `bridge_accepts == monolith_outputs` over the full set; adding
  a new entry to `canonical_doc_types.json` automatically grows both sides.
- **Layer 2 totality.** Every registry doc type MUST appear as a key in
  `REGISTRY_TO_LEAD_TYPE` — either with a §16 lead_type or with `None`.
  Adding a new registry entry without bridging it here is a build break.
- **Gap-log totality.** Every `None`-valued registry entry MUST have an
  entry in `REGISTRY_WITHOUT_LEAD_TYPE_REASONS`. Every §16 lead type that
  has no direct registry mapping MUST appear in
  `LEAD_TYPES_WITHOUT_REGISTRY_REASONS` or
  `LEAD_TYPES_SHARED_REGISTRY_MAPPING`. An unexplained gap is a build break.

### Determinism rule

The bridge is a static mapping module. No regex, no heuristic, no fuzzy
match. The same input produces the same output every call. The bridge
determinism test repeats five representative calls three times each and
asserts they agree.

### County-agnostic rule

The bridge contains no county / state / vendor literal. The county-agnostic
regression scanner enforces this against the module file.

---

## 22.C The current bridge state — totals

Built and gated as of v5.4.0 Session 8:

| Layer                                       | Total | Bridged                                   | Explicitly unbridged                                 |
|---------------------------------------------|-------|-------------------------------------------|------------------------------------------------------|
| Registry → §16                              | 74    | 36 (→ 25 distinct §16 lead types)         | 38 (None, each with a documented reason)             |
| §16 → registry                              | 27    | 25 (one or more registry doc types each)  | 2 — `Tax Delinquency`, `Abstract of Judgment` (both documented) |
| Monolith UPPERCASE → registry (lowercased)  | 74    | 74 (the identity-lowercase map; total)    | 0                                                    |

The two §16 lead types without a direct registry mapping:

- **`Tax Delinquency`** — a tax-roll STATUS (the assessor flag that a parcel is
  delinquent on taxes for the current cycle), not a recorded document. The
  framework consumes it as enrichment (§17.K Session 7). The closest
  recorded-document analogue `tax_foreclosure_notice` is bridged separately
  to the distinct §16 lead type "Tax Lien Foreclosure".
- **`Abstract of Judgment`** — the registry carries one instrument
  (`judgment_lien`) for both this and "Civil Judgment". The common
  abbreviation "ABSTRACT OF JUDGMENT" is listed on the `JUDGMENT_LIEN`
  registry entry. The bridge maps `judgment_lien` to the broader "Civil
  Judgment" §16 category; the shared mapping is recorded in
  `LEAD_TYPES_SHARED_REGISTRY_MAPPING`.

Neither is an operator decision — they are recorded as documented behavior of
the bridge and gated by tests.

---

## 22.D The §17 reconciliation — three plural fixes + seven broad-key fan-outs

Session 8 reconciled ten Session-2 §17 rule keys to the registry. The
reconciliation is recorded in
`knowledge_base/architecture/17_debtor_party_rules.md` §17.K Session 8 and
mirrored in `debtor_party_engine.BROAD_KEY_REGISTRY_ALIASES`.

**Three plural renames (registry-aligned keys for the same §17 rules):**

| Session-2 key (singular) | Session-8 key (registry-aligned plural / possessive) |
|--------------------------|------------------------------------------------------|
| `mechanic_lien`          | `mechanics_lien`                                     |
| `executor_deed`          | `executors_deed`                                     |
| `administrator_deed`     | `administrators_deed`                                |

**Seven broad-key fan-outs (every broad rule fires on its registry aliases):**

| Broad §17 key (Session 2) | Registry alias(es)                                                                                                                          | Bridge decision |
|---------------------------|---------------------------------------------------------------------------------------------------------------------------------------------|----------------|
| `abstract_of_judgment`    | `judgment_lien`                                                                                                                             | option (a) — map |
| `civil_judgment`          | (empty — `judgment_lien` already provided by `abstract_of_judgment`)                                                                        | option (a) — map (shared) |
| `administrative_lien`     | (empty — broad bucket; children `federal_tax_lien` / `state_tax_lien` / `municipal_lien` each carry their own §17 rule rows)                | option (a) — map (children) |
| `code_lien`               | `code_violation_notice`, `municipal_lien`                                                                                                   | option (a) — map |
| `foreclosure_notice`      | `notice_of_sale`, `notice_of_default`, `notice_of_substitute_trustee_sale`, `final_judgment_of_foreclosure`, `appointment_of_substitute_trustee` | option (a) — map |
| `probate`                 | `letters_testamentary`, `letters_of_administration`, `determination_of_heirship`, `muniment_of_title`                                       | option (a) — map |
| `trustee_sale`            | `trustees_deed_upon_sale`                                                                                                                   | option (a) — map |

No reconciliation surfaced option (b) — no registry entry was proposed, no
operator decision is required. The broad keys remain as backward-compat rule
rows; after cutover only the registry-aligned aliases see traffic.

---

## 22.E What the bridge is NOT

- **Not the cutover.** The bridge is the seam the cutover will use; the
  cutover itself (rewiring `run_pipeline` to feed the staged engine through
  this bridge) is a later session.
- **Not a normalizer.** The fuzzy / heuristic layer that turns a raw source
  subtype string into a registry key is `normalize.normalize_doc_type`. The
  bridge accepts only known registry keys and rejects unknowns.
- **Not a per-county taxonomy.** County-specific synonyms layer into
  `normalize.normalize_doc_type` via its `county_synonyms` argument. The
  bridge is universal.
- **Not §17 logic.** The bridge knows nothing about debtor parties, filers,
  or owner names; that is §17. The §17 fan-out tables are sourced from
  `debtor_party_engine.BROAD_KEY_REGISTRY_ALIASES` for documentation; the
  engine wiring lives in §17, not here.

---

## 22.F Universal versus county-specific separation

The three taxonomies are universal:

- §16's 27 lead types are the universal recon sweep.
- `canonical_doc_types.json` is the universal document-type registry.
- The bridge is universal — same mapping, same totality rules, every county.

County-specific entries (per-county synonyms, per-county doc-type aliases)
layer through `normalize.normalize_doc_type`'s `county_synonyms` argument and
the `doc_type_synonyms` block in `config/counties/<county_slug>.json`. None of
that touches this bridge.

The county-agnostic regression scanner enforces that this file and
`scaffold/pipeline/doc_type_bridge.py` contain no county / state / vendor
literal.
