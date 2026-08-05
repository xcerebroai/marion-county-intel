# 17. Debtor Party Rules (v5.3.0+)

The debtor party rules contract defines, per canonical doc type, which party in a source
record is the debtor / owner — the lead subject — versus which party is the filer,
lienholder, or claimant. Getting this wrong inverts the identity of a lead.

This file is the universal contract. The per-county doc-type taxonomy that maps raw
document codes to canonical doc types lives in `config/counties/<county_slug>.json`.

---

## 17.0 Status and scope

- **Version:** v5.3.0 (Session A2 — Gap 5).
- **Date:** 2026-05-18.
- **Authoritative for:** every translator that produces a `matched_lead` from an
  event-based source record. The `owner_name` on a matched lead MUST be derived per this
  contract.
- **Scope:** universal — the per-doc-type debtor/filer rules, the filer-suppression
  patterns, the REVIEW_REQUIRED routing contract, and the owner-type classifier. The
  county-specific doc-type taxonomy and any county-specific suppression additions live
  in the county config.

---

## 17.A Purpose

The debtor party rules contract defines, per `canonical_doc_type`, which party in the
source record is the debtor / owner (the lead subject), versus which party is the filer,
lienholder, or claimant. The contract is universal; the per-county doc-type taxonomy
lives in `config/counties/<county_slug>.json`.

---

## 17.B Why this contract exists

A naive translator that uses column order, or the first-named party, as "owner" produces
filer-as-owner inversions. Different doc types invert party roles differently:

- **Hospital lien** — the hospital is the filer; the patient is the debtor.
- **Code / administrative lien** — the agency is the filer; the property owner is the
  debtor.
- **Federal / state tax lien** — the taxing authority is the filer; the taxpayer is the
  debtor.
- **Mechanic / construction lien** — the contractor is the filer; the property owner is
  the debtor.
- **Lis pendens** — the plaintiff is the filer; the defendant is the lead subject.
- **Judgment lien** — the judgment creditor is the filer; the debtor is the lead
  subject.
- **Executor / administrator deed** — the estate is the grantor and a grantee receives,
  but the LEAD SUBJECT is the estate / decedent (the property is estate-titled).
- **Foreclosure notice** — the lender / trustee files; the debtor is the property owner
  being foreclosed on.
- **Affidavit of heirship** — the heirs file; the decedent's estate is the lead subject.

Without explicit per-doc-type rules, the translator defaults to a positional or
first-name heuristic and produces wrong-party leads.

---

## 17.C The debtor_party_rules mapping

For each `canonical_doc_type`, the contract specifies:

- **`expected_debtor_name_type`** — which `name_type` role in the raw record carries the
  debtor identity (e.g. TP / taxpayer, DF / defendant, GR / grantor, GE / grantee).
- **`fallback_debtor_name_type`** — the secondary role used if the primary is missing.
- **`filer_name_types`** — the `name_type` roles that are KNOWN FILERS and must NEVER be
  promoted to `owner_name`.
- **`missing_debtor_behavior`** — `REVIEW_REQUIRED`: route to operator review with the
  `filer_entity` captured separately.

Required mapping (universal, doc-type-centric, county-agnostic):

    canonical_doc_type     expected_debtor   fallback   known_filers                              if missing
    ---------------------  ----------------  ---------  ----------------------------------------  ---------------
    hospital_lien          TP                GE         hospital entity patterns                  REVIEW_REQUIRED
    code_lien              TP                GE         municipal agency patterns                 REVIEW_REQUIRED
    administrative_lien    TP                GE         state agency patterns                     REVIEW_REQUIRED
    federal_tax_lien       TP                GE         IRS, United States, USA                   REVIEW_REQUIRED
    state_tax_lien         TP                GE         state revenue/comptroller, state-name      REVIEW_REQUIRED
    mechanic_lien          GR                DF         contractor/construction entity patterns   REVIEW_REQUIRED
    construction_lien      GR                DF         contractor/construction entity patterns   REVIEW_REQUIRED
    lis_pendens            DF                TP         plaintiff patterns                        REVIEW_REQUIRED
    civil_judgment         DF                TP         judgment creditor patterns                REVIEW_REQUIRED
    abstract_of_judgment   DF                TP         judgment creditor patterns                REVIEW_REQUIRED
    executor_deed          GR                --         (none -- the estate IS the lead)          REVIEW_REQUIRED
    administrator_deed     GR                --         (none -- the estate IS the lead)          REVIEW_REQUIRED
    affidavit_of_heirship  decedent from     --         heir-affiant patterns                     REVIEW_REQUIRED
                           document body
    foreclosure_notice     debtor from       --         mortgagee, trustee, lender patterns       REVIEW_REQUIRED
                           notice body
    trustee_sale           debtor from       --         trustee, mortgagee patterns               REVIEW_REQUIRED
                           notice body
    sheriff_sale           DF                --         sheriff, marshal patterns                 REVIEW_REQUIRED
    probate                decedent from     --         executor/administrator patterns           REVIEW_REQUIRED
                           document body

For the rows whose `expected_debtor` is "extracted from the document body" (affidavit of
heirship, foreclosure notice, trustee sale, probate), the debtor identity is not carried
in a structured `name_type` field and must be extracted from the document text; absence
of an extractable debtor routes to `REVIEW_REQUIRED`.

---

## 17.D Known filer suppression patterns (universal)

Patterns that MUST NEVER appear as `owner_name`, regardless of where they appear in the
raw record:

- **Government entities** — `CITY OF <*>`, `COUNTY OF <*>`, `STATE OF <*>`,
  `UNITED STATES OF AMERICA`, `UNITED STATES`, `IRS`, `INTERNAL REVENUE SERVICE`.
- **State agencies** — `<STATE> COMPTROLLER`, `<STATE> WORKFORCE COMMISSION`,
  `<STATE> DEPARTMENT OF <*>`.
- **Hospital entities by suffix** — name contains `HOSPITAL`, `HEALTH SYSTEM`,
  `MEDICAL CENTER`, `HOSPITALS OF <*>`.
- **Mortgage / lender entities by suffix** — name contains `MORTGAGE COMPANY`,
  `MORTGAGE CORP`, `MORTGAGE LLC`, `BANK N.A.`, `BANK NATIONAL ASSOCIATION`.
- **Federal mortgage agencies** — `FREDDIE MAC`, `FANNIE MAE`,
  `FEDERAL HOME LOAN MORTGAGE CORPORATION`, `FEDERAL NATIONAL MORTGAGE ASSOCIATION`,
  `GINNIE MAE`, `GOVERNMENT NATIONAL MORTGAGE ASSOCIATION`.
- **Servicers** — `NATIONSTAR`, `MR. COOPER`, `PHH MORTGAGE`, `NEWREZ`, `SHELLPOINT`,
  `RUSHMORE`, `SERVBANK`.
- **Trustee patterns** — `SUBSTITUTE TRUSTEE`, `TRUSTEE SERVICES`.

The suppression list is universal pattern matching. County-specific suppression entries
(local hospital systems, local government name variants) belong in
`config/counties/<county_slug>.json` under `debtor_party_rules.additional_suppressions`,
not in this contract.

---

## 17.E REVIEW_REQUIRED routing contract

When the expected debtor `name_type` is missing, OR a known filer pattern matches the
proposed owner:

- The `matched_lead` is emitted with `parcel_resolution_status = REVIEW_REQUIRED`.
- `owner_name` is set to a placeholder: `"<canonical_doc_type> against unidentified
  party"`.
- A separate field `filer_entity` captures the original filer name from the raw record.
- The lead is **NOT dropped** — it remains in the dashboard, visually distinct, as a
  research-pile entry for operator triage.
- A separate field `review_reason` captures the rule that triggered the routing — e.g.
  `"expected_debtor_name_type TP missing"`, or
  `"known_filer_pattern match on STATE OF <*>"`.

A wrong-party lead is worse than a flagged-for-review lead — review routing preserves the
record for an operator instead of asserting a false owner.

---

## 17.F Owner type classification

Classifier rules for `owner_type`:

- **ENTITY** — the name contains a corporate suffix: `LLC`, `INC`, `CORP`, `LP`, `LTD`,
  `P.A.` (professional association), `P.C.` (professional corporation), `PLLC`,
  `COMPANY`, `CO.`, `GROUP`, `ASSOCIATES`, `ENTERPRISES`, `PARTNERS`, `SERVICES`,
  `AUTHORITY`, `COMMISSION`, `DISTRICT`.
- **ESTATE** — the name matches a decedent pattern (word-boundary regex):
  `ESTATE OF <name>`, `EST OF <name>`, `<name> ESTATE`, `<name> EST OF`,
  `HEIRS OF <name>`. It MUST NOT match if `REAL ESTATE` precedes `ESTATE`, or if
  `ESTATE` appears as a substring inside a corporate name (`REAL ESTATE GROUP LLC` is
  ENTITY, not ESTATE).
- **TRUST** — the name matches `<name> TRUST`, `<name> REVOCABLE TRUST`,
  `<name> FAMILY TRUST`, `<name> LIVING TRUST` by word boundary. It MUST NOT match
  corporate names that merely contain `TRUST` (`TRUST COMPANY OF <*>` is ENTITY).
- **INDIVIDUAL** — the default when no other rule matches.
- **UNKNOWN** — only when the name is empty, `—`, or pure punctuation.

**Classifier precedence:** ENTITY beats ESTATE beats TRUST beats INDIVIDUAL. Word-boundary
and position rules MUST be enforced — substring matching alone produces false positives.

---

## 17.G Cross-reference to §13

This contract supplements §13, the Lead Origination Contract
(`13_lead_origination_contract.md`). §13 governs WHICH sources originate leads. §17
governs HOW debtor identity is extracted from a source record once it is recognized as
lead-originating. Together the two contracts define the integrity of `owner_name` on
matched leads.

---

## 17.H Universal versus county-specific separation

- **Universal** — the debtor_party_rules table, the filer-suppression patterns, and the
  classifier precedence. They live in this file.
- **County-specific** — the per-county doc-type taxonomy (mapping raw document codes to
  `canonical_doc_type` values) lives in `config/counties/<county_slug>.json`. Per-county
  additional suppression entries — county-specific hospital systems, local government
  name variants — live in `config/counties/<county_slug>.json` under
  `debtor_party_rules.additional_suppressions`.

This file therefore contains no county name, no state name, and no county-specific
example. The county-agnostic regression scanner enforces this.

---

## 17.K Amendment note — v5.4.0 Session 2 reconciliations

v5.4.0 Session 2 implemented the §17 debtor party engine
(`scaffold/pipeline/debtor_party_engine.py`). Three findings were ratified and
reconciled against this contract during that build. The sections above are left
unchanged for history; this note records the deltas and is authoritative where
it supersedes them.

### F-1 — `parcel_resolution_status` is out of scope for the §17 engine

§17.E above expresses REVIEW_REQUIRED routing by emitting
`parcel_resolution_status = REVIEW_REQUIRED`. Ratified finding F-1 supersedes
that wording: the §17 debtor party engine records its verdict ONLY in its own
field, `debtor_resolution_status` (`RESOLVED` / `REVIEW_REQUIRED`), and MUST NOT
write `parcel_resolution_status` or any other parcel-stage field. Each pipeline
stage owns its own fields — `parcel_resolution_status` is owned by the
downstream §13.14 parcel-resolution stage and first appears on the leads-base
record, where the leads-base writer propagates the REVIEW_REQUIRED verdict. The
inter-stage schema `debtor_resolved_record.schema.json`, its dataclass mirror in
`contracts/records.py`, and the behavioral spec
`test_filer_suppression_behavior.py` were reconciled to F-1 in Session 2: the
`parcel_resolution_status` property, its `required` entry, the `allOf` clause
constraining it, and the spec assertion on it were removed.

### F-5 — `probate` is a mapped doc type; nine doc types remain unmapped

The §17.C table maps 17 canonical doc types, and all 17 are implemented —
`probate` included (row 17; debtor extracted from the document body). A
`canonical_doc_type` with no §17.C rule row is never guessed: the engine applies
a default rule that routes it to `REVIEW_REQUIRED` with
`review_reason = "no_debtor_rule_for_doc_type"`, and never silently passes it
through as resolved. Nine doc types are known to be unmapped and are a
documented operator-input follow-up — they require operator-supplied debtor
logic and no rule is invented for them: `tax_sale`, `tax_delinquency`,
`tax_certificate`, `surplus`, `eviction`, `divorce`, `bankruptcy`,
`condemnation`, `demolition`.

### F-6 — §17.D defines seven filer-suppression groups; all are implemented

§17.D concretely enumerates seven filer-suppression groups: government
entities, state agencies, hospital entities, mortgage / lender entities, federal
mortgage agencies, servicers, and trustee patterns. All seven are implemented in
the engine. The filer pattern-sets that §17.C references but §17.D never
concretely defines — contractor / construction, plaintiff, judgment-creditor,
heir-affiant, sheriff / marshal, and executor / administrator patterns — remain
a documented gap: they are flagged here, and no patterns are invented for them.

### v5.4.0 Session 7A — the multi-owner contract extension

Co-ownership is the norm in distressed property — married couples, heirs,
siblings, partners, LLC members, probate, partition, divorce. A single
`owner_name` string silently drops real co-owners. Session 7A extends three
inter-stage records — `debtor_resolved_record`, `leads_base_record`,
`matched_lead_record` (the JSON Schemas and their `records.py` dataclass
mirrors) — to represent multiple distressed owners. This is a GENERAL
multi-owner extension, not divorce-specific.

**Shape.** `owner_name` is unchanged — it stays the required PRIMARY display
owner, so all pre-7A single-owner code and records remain valid. Each of the
three records additionally carries the **multi-owner block**: an `owners`
array (each owner: `name`, `role`, `name_type`, `is_primary`, `confidence`,
`source_field`, `resolution_status`, `notes` — `name_type` uses the existing
unextended `TP/DF/GR/GE/PL/OTHER` enum) plus the scalars `primary_owner_name`,
`additional_owner_names`, `owner_count`, and `multi_owner_status`. The block is
schema-optional for backward compatibility; the staged engine always emits it.

**`multi_owner_status` is descriptive, never a verdict.** It has exactly three
values — `SINGLE_OWNER`, `MULTIPLE_OWNERS_PRIMARY_CLEAR`,
`MULTIPLE_OWNERS_PRIMARY_UNCLEAR` — and describes owner cardinality and
primary-clarity ONLY. It deliberately has no `REVIEW_REQUIRED` value. The single
source of truth for "needs review" remains `debtor_resolution_status` (the
F-1-ratified field on the debtor-resolved record; `parcel_resolution_status`
REVIEW_REQUIRED downstream) — unchanged. When the primary owner is unclear,
`multi_owner_status` is `MULTIPLE_OWNERS_PRIMARY_UNCLEAR` AND the existing review
mechanic independently sets the verdict field to `REVIEW_REQUIRED`. One field
describes, the other decides; the schema's `allOf` consistency rules make it
impossible for them to contradict.

**Consistency, enforced.** The schemas (`allOf` + `dependentRequired`) and the
`records.py` dataclasses (`__post_init__` + `multi_owner_consistency_errors`)
jointly enforce: `SINGLE_OWNER` → exactly one owner, marked primary,
`owner_count` 1, `additional_owner_names` empty, `primary_owner_name` ==
`owner_name`; `MULTIPLE_OWNERS_PRIMARY_CLEAR` → more than one owner, exactly one
primary; `MULTIPLE_OWNERS_PRIMARY_UNCLEAR` → more than one owner, NONE marked
primary, verdict field REVIEW_REQUIRED. `owner_count` always equals
`len(owners)` — every identified owner is counted; **co-owners are never
dropped**. **Ownership priority is never invented** — if the source document
does not make a primary clear, the status is `MULTIPLE_OWNERS_PRIMARY_UNCLEAR`,
not a guess, and `owner_name` / `primary_owner_name` take the §17.E
unidentified-party placeholder (the existing review-placeholder mechanic, not a
new one).

**Engine adaptation.** The §17 engine resolves one owner per record today, so it
emits a `SINGLE_OWNER` block (the resolved debtor, or the §17.E placeholder on a
review-routed record). The leads-base writer and the §19 aggregator carry the
block forward unchanged — co-owners survive every stage. Multi-owner *resolution*
(populating `owners` with co-owners for the 9 deferred doc types) is Session 7,
which keys off this contract. Session 7A is contract + schema + thin
backward-compatible adaptation only — no debtor-rule logic.

### v5.4.0 Session 7 — the 9 deferred debtor rules implemented (12 doc types)

Session 7 implements the nine operator-supplied debtor rules deferred from
F-5 (Session 2). The rules are keyed onto the lowercased
`canonical_doc_types.json` registry names; nine logic rules map onto twelve
registry doc types. After Session 7, §17 covers **29 canonical doc types**
(17 from Session 2 + 12 from Session 7), and the engine never silently passes
a recognised distress doc type through with a wrong-party owner.

**Registry doc types newly mapped (12).** `tax_deed` and
`tax_foreclosure_notice` (Rule 1 — tax sale / deed); `tax_sale_certificate`
(Rule 3); `sheriff_sale_surplus` (Rule 4); `eviction_filing` and
`writ_of_possession` (Rule 5); `divorce_filing`, `final_decree_of_divorce`,
and `marital_property_division` (Rule 6); `bankruptcy_petition` (Rule 7);
`condemnation_notice` (Rule 8); `demolition_order` (Rule 9).

**NAME_TYPE assignments (the existing TP/DF/GR/GE/PL/OTHER enum, unextended).**
Rule 1 / 3 / 4 → `TP` (delinquent former owner / claimant entitled to
surplus). Rule 5 → `PL` (the landlord — NOT the tenant). Rule 8 / 9 → `DF`
(the owner being condemned / ordered demolished). Rule 7 → `TP` (the
bankruptcy debtor). Rule 6 — the divorce types — uses the Session 7A
multi-owner contract: both spouses go in the owners[] array.

**Document-only resolution — the new §17 invariant.** §17 resolves the
debtor solely from parties named on the document. Five of the new doc types
(`tax_foreclosure_notice`, `eviction_filing`, `writ_of_possession`,
`condemnation_notice`, `demolition_order`) and the divorce types frequently
carry no owner name on the record — only a parcel, address, case number, or
tenant. When the owner is not resolvable from document parties, the engine
routes to `REVIEW_REQUIRED` with `review_reason = "owner_not_on_document"`.
**§17 must NOT attempt parcel / assessor / tax-roll / GIS resolution itself
— that is the downstream §13.14 parcel-resolution stage.** §17 is a
debtor-from-document-parties contract, period; promoting an enrichment lookup
into §17 would re-couple the stages F-1 and §13.14 deliberately separated.

**Rule 6 — divorce multi-owner.** The Session 7A multi-owner contract is the
wire format. Both spouses tied to the property go in the `owners[]` array
(co-owners are never dropped). When the decree clearly awards / orders sold
by / transfers / vests the property in one named spouse (the document body
carries one of the recognised award labels — `AWARDED TO`,
`ORDERED TO SELL BY`, `TO BE TRANSFERRED TO`, `VESTED IN`, `OBLIGATED TO`,
`SOLE OWNERSHIP TO`), that spouse is `is_primary` and `multi_owner_status`
is `MULTIPLE_OWNERS_PRIMARY_CLEAR`. Otherwise both spouses are preserved
with no `is_primary`, `multi_owner_status` is
`MULTIPLE_OWNERS_PRIMARY_UNCLEAR`, `debtor_resolution_status` is
`REVIEW_REQUIRED`, and `review_reason` is `"divorce_primary_owner_unclear"`
— ownership priority is never guessed. The schema's `allOf` rules enforce
the Session 7A no-contradiction guarantee.

**Rule 7 — bankruptcy `"no_property_connection"`.** The bankruptcy debtor
(individual or business entity) is the lead — IF the petition has a real-
property hook. When `property_refs` carries no `parcel_id`, no
`situs_address`, and no `legal_description`, the engine routes to
`REVIEW_REQUIRED` with `review_reason = "no_property_connection"`. The lead
is **NOT hard-excluded** — exclusion is a downstream decision; §17 only
records that the record is not §17-actionable. `case_number` alone does NOT
count for the property-connection check — on a bankruptcy record it is
almost always the bankruptcy case number, not a property identifier. Contact
context (signer / managing member / registered agent / principal) is
ENRICHMENT, NOT §17 — it is deliberately not added here.

**`tax_delinquency` is enrichment, NOT a §17 doc type.** `tax_delinquency`
is a **tax-roll STATUS** (the assessor's flag that a parcel is delinquent on
taxes for the current cycle), not a recorded document. §17 governs how the
debtor is extracted from a recorded document's party block; a tax-roll
status carries no document and no parties — it is parcel-keyed enrichment
that joins to a parcel via the §13.14 stage, not via §17. `tax_delinquency`
is therefore intentionally NOT a §17.C rule row; the F-5 default rule never
fires on it because translators do not produce raw events of that type — it
is consumed by enrichment.

**Suppression — by name_type first, by name pattern second.** The engine
picks the lead party by its assigned name_type, so role-descriptor parties
(tenant on an eviction, bidder on a tax deed, certificate buyer on a tax
sale certificate) are never selected because they do not hold the lead's
name_type. The Session-7 §17.D additions add organizational-name suppression
groups that complement name_type selection: `tax_authority`, `auction_party`,
`law_firm`, `court_role`, `law_enforcement`, `surplus_recovery`,
`bankruptcy_official`, `code_enforcement_role`, `property_manager` — nine
new groups, bringing §17.D to 16 universal suppression groups. A candidate
matching any of these patterns is routed to `REVIEW_REQUIRED` with
`review_reason = "known_filer_pattern match: <category>:<label>"` rather
than emitted as `owner_name`. County-specific suppression entries continue
to layer on top via the existing `additional_suppressions` argument.

**The §04 deal-path classifier is downstream.** §17 tags
`sheriff_sale_surplus` as a §17.C-mapped doc type and resolves the former
owner / claimant; it does NOT implement deal-path logic. The downstream §04
classifier treats it as a surplus-recovery lead — that lives in §04, not
here.

**Schemas, dataclasses, and writers — no schema-level changes in Session 7.**
The Session 7A multi-owner contract is the wire format Session 7's divorce
path uses. The `debtor_resolved_record` / `leads_base_record` /
`matched_lead_record` schemas, their `records.py` dataclass mirrors, the
`leads_base_writer`, and the §19 aggregator are unchanged — they already
carry the multi-owner block forward unchanged. Session 7 is engine logic
only.

### v5.4.0 Session 8 — doc-type namespace bridge (R1 / G1)

Session 8 reconciles the three doc-type namespaces the v5.4.0 cutover has to
keep in sync — §16's 27 Title-Case `lead_type` taxonomy, the
`canonical_doc_types.json` registry's 74 UPPERCASE keys, and the monolith's
UPPERCASE `normalized_doc_type` output — and builds the explicit, tested
bridge between them (`scaffold/pipeline/doc_type_bridge.py`, design note
`knowledge_base/architecture/22_doc_type_bridge.md`). The cutover is a later
session; Session 8 only builds the bridge.

**Three plural-key fixes — §17 keys aligned to the registry.** Session 2
keyed three rule rows under the singular forms `mechanic_lien`,
`executor_deed`, `administrator_deed`. The corresponding registry entries
are plural / possessive (`MECHANICS_LIEN`, `EXECUTORS_DEED`,
`ADMINISTRATORS_DEED`). The §17 rule rows are renamed to match the
lowercased registry names so the staged engine resolves them after cutover;
the rule logic is unchanged. The Session-2 §17.C contract table above is
LEFT unchanged (history); this amendment records the rename.

**Seven broad-key reconciliations — option (a) for all 7.** Seven Session-2
§17 rule keys did not match any single registry entry. Each was reconciled
per the Session-8 bridge rule "option (a) — the broad key maps to one or
more finer registry doc types; implement the mapping so the §17 rule fires
for each registry alias". No registry gap (option (b) — operator decision)
surfaced. The fan-out is recorded in
`debtor_party_engine.BROAD_KEY_REGISTRY_ALIASES` and replayed at module
import (`_fan_out_broad_rules` / `_fan_out_body_labels`):

| Broad §17 key (Session 2)  | Registry alias(es) the same §17 rule fires on                                                                                                |
|----------------------------|----------------------------------------------------------------------------------------------------------------------------------------------|
| `abstract_of_judgment`     | `judgment_lien`                                                                                                                              |
| `civil_judgment`           | (empty — `judgment_lien` already covered by `abstract_of_judgment`)                                                                          |
| `administrative_lien`      | (empty — broad bucket; children `federal_tax_lien` / `state_tax_lien` / `municipal_lien` each carry their own §17 rule rows)                 |
| `code_lien`                | `code_violation_notice`, `municipal_lien`                                                                                                    |
| `foreclosure_notice`       | `notice_of_sale`, `notice_of_default`, `notice_of_substitute_trustee_sale`, `final_judgment_of_foreclosure`, `appointment_of_substitute_trustee` |
| `probate`                  | `letters_testamentary`, `letters_of_administration`, `determination_of_heirship`, `muniment_of_title`                                        |
| `trustee_sale`             | `trustees_deed_upon_sale`                                                                                                                    |

The broad keys themselves remain as backward-compatible rule rows (the
Session-2 §17.C historical contract refers to them, and the v5.3.0 invariant
test pins their names in this file). After cutover, only the registry-aligned
aliases will see traffic; the broad keys are documentation. The fan-out adds
13 new rule rows, bringing §17.C to 42 total (17 Session-2 + 12 Session-7 +
13 Session-8 aliases).

**Probate body-label fan-out generalized.** The probate-specific "ESTATE OF
<name>" / "HEIRS OF <name>" no-colon body branch was hardcoded to the
`probate` and `affidavit_of_heirship` keys. Session 8 generalises it via
`_PROBATE_BODY_DOC_TYPES` so the four probate fan-out aliases
(`letters_testamentary`, `letters_of_administration`,
`determination_of_heirship`, `muniment_of_title`) all read the body the same
way.

**The doc-type bridge — `scaffold/pipeline/doc_type_bridge.py`.** A static,
deterministic, county-agnostic module:

- `monolith_to_registry(NORMALIZED_DOC_TYPE) → registry canonical_doc_type`
  (lowercased). Total over `normalize.py`'s 74 outputs (verified by the
  bridge totality test); an unknown input maps to `None` rather than a
  fuzzy guess.
- `registry_to_lead_type(canonical_doc_type) → §16 Title-Case lead_type` or
  `None`. The mapping is exhaustive over the 74 registry types — 36 bridge
  to one of the 25 §16 lead types the registry covers (some many-to-one,
  e.g. `letters_testamentary` / `letters_of_administration` /
  `determination_of_heirship` / `muniment_of_title` all → "Probate"); the
  remaining 38 map to `None` and the reason is recorded in
  `REGISTRY_WITHOUT_LEAD_TYPE_REASONS`.
- `lead_type_for_monolith_output(NORMALIZED_DOC_TYPE)` composes the two
  layers end-to-end.
- `bridge_totality_report()` returns a structured report on totality and
  gaps; the bridge test consumes it.

**Documented gaps — no operator decision required.** Two §16 lead types
have no direct registry equivalent:

- `Tax Delinquency` — a tax-roll STATUS (assessor flag), not a recorded
  document. Recorded in `LEAD_TYPES_WITHOUT_REGISTRY_REASONS`. The closest
  recorded-document analogue, `tax_foreclosure_notice`, is bridged
  separately to the distinct §16 lead type "Tax Lien Foreclosure".
- `Abstract of Judgment` — the registry carries one instrument
  (`judgment_lien`) for both this and "Civil Judgment"; the bridge maps to
  the broader "Civil Judgment" §16 category, and `Abstract of Judgment` is
  recorded in `LEAD_TYPES_SHARED_REGISTRY_MAPPING` as a known shared
  mapping.

Both are explicit decisions, not silent gaps — no registry entry is being
proposed, no §16 lead type is being dropped. The cutover proceeds against
the bridge as documented.

**No schema / writer / aggregator changes.** Session 8 only renames §17 rule
keys, adds fan-out rule rows that share existing logic, and builds the
bridge module. The staged-pipeline engines, schemas, dataclasses, and writers
are unchanged.
