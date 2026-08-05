# 12 — Entity Resolution

Entity resolution decides when two records refer to the same person, company, estate, trust, parcel, case, or property.

This is one of the most important parts of the build. Bad entity resolution creates duplicate leads, wrong owner matches, mailers to the wrong address, and calls to the wrong person. The operator's client gets handed a list and starts dialing — every misresolved entity is a wasted call and a damaged reputation.

---

## Entity types

The framework supports these entity types:

```
individual
married_couple
estate
trust
LLC
corporation
partnership
government
lender
attorney
unknown_party
```

Every party name in a record gets typed. Ambiguous parties default to `unknown_party` and route to review.

---

## Normalization rules

### Names

Normalize for comparison; preserve the original for display.

- Uppercase for comparison
- Trim whitespace
- Remove punctuation for comparison only
- Standardize suffixes (`JR.` → `JR`, `III` → `III`, etc.)
- Standardize common company endings:

```
LLC = LIMITED LIABILITY COMPANY
INC = INCORPORATED
CO = COMPANY
CORP = CORPORATION
LP = LIMITED PARTNERSHIP
LLP = LIMITED LIABILITY PARTNERSHIP
TR = TRUST
EST = ESTATE
```

- Detect trust and estate phrases (`THE SMITH FAMILY TRUST`, `ESTATE OF JANE DOE`, `JOHN DOE TRUSTEE`)
- Preserve initials but lower confidence (`J SMITH` is weaker than `JOHN SMITH`)

### Addresses

- Standardize street suffixes (`Street` → `ST`, `Avenue` → `AVE`)
- Standardize directionals (`North` → `N`, `Southwest` → `SW`)
- Remove unit noise only when safe (`#5`, `APT 5`, `UNIT 5` → unit number stored separately)
- Preserve unit number as a separate field, not concatenated to street
- Compare house number, street name, city, ZIP, and parcel ID as separate fields

### Parcel IDs

- Remove spaces and separators for comparison (`123-456-789` and `123456789` compare equal)
- Preserve the original formatted value for display
- Store all alternate parcel IDs (historical, formatted variants)
- Detect when the same parcel has multiple ID formats across sources

### Legal descriptions

When parcel ID is missing or ambiguous, fall back to legal description. Compare:
- Subdivision name
- Block
- Lot
- Section, township, range (where applicable)
- Unit
- Plat reference

---

## Match confidence hierarchy

Auto-approval requires strong evidence. The hierarchy:

**Strong matches (auto-approve, confidence 90+):**
1. Parcel ID exact match
2. Instrument explicitly references both parcel ID and address
3. Court case explicitly references both parcel ID and owner
4. Exact normalized address + same owner
5. Exact normalized address + matching legal description

**Review-required matches (confidence 50–89, route to review):**
1. Address matches but owner conflict
2. Owner matches but address incomplete
3. Legal description partial match
4. Similar names with different mailing addresses
5. LLC with multiple possible parcels
6. Estate with missing decedent name
7. Trust with missing trustee
8. Spouse or heir name mismatch (one record shows "John Doe", another shows "John & Jane Doe")

**Weak matches (do NOT auto-approve, route to review with high severity):**
1. Owner name only, no parcel ID, no address
2. Address only with common owner name
3. Initials-based name matches
4. Cross-jurisdiction matches without state/county confirmation

The matcher emits `match_confidence` per record. Records below 80 route to review per `domain/05_review_queue_rules.md`.

---

## LLC logic

LLCs are tricky because the same beneficial owner can operate multiple LLCs with similar names, OR completely unrelated parties can pick similar names by coincidence.

For each LLC encountered:
- Preserve the full legal name as registered
- Create a normalized name for comparison
- Track the registered agent if available (often shared across LLCs run by the same operator)
- Track the mailing address (also often shared)
- Group obvious aliases only when evidence supports it (same agent + same mailing + sequential filing dates)
- **Do not assume two similar LLCs are the same.** When in doubt, route to review with `entity_merge_candidate` flag and let a human decide.

Example: `XCEREBRO HOLDINGS LLC` and `XCEREBRO INVESTMENTS LLC` share a normalized prefix. They might be the same beneficial owner running multiple entities, or they might be unrelated. Without registered-agent or address evidence, the framework keeps them as separate entities and surfaces the suggestive overlap to review.

---

## Trust logic

For trusts:
- Identify the trust name
- Identify the trustee if available
- Identify the grantor if available
- Identify the property reference
- Route to review when trustee or property reference is missing

A trust without an identifiable trustee is unactionable for the operator's client (you can't call a trust). The framework flags it but doesn't drop it — the trustee may be discoverable via downstream skip-trace or court records.

---

## Estate logic

For estates:
- Identify the decedent name
- Identify the personal representative (executor or administrator) if available
- Identify the heirs if available
- Identify the probate case number if available
- Link recorded estate instruments only when property evidence supports it

An estate may span multiple parcels. The framework tracks the estate as one entity and links each parcel separately, so the operator's client can see all properties associated with one decedent.

---

## Married name logic

For married couples and name changes:
- Detect `and`, `&`, `husband and wife`, `H/W`, `j/t`, and similar phrases
- Preserve both names as separate party entries
- Create a `married_couple` entity only when evidence supports the connection
- Route to review when only one spouse appears on one record and both appear on another (possible separation, possible death, possible recording error)

---

## Dedupe rules

Dedupe runs before any export. The framework refuses to ship duplicate leads — but it refuses even harder to merge two leads incorrectly. Bad merges corrupt the record store. When in doubt, do not merge. Route to review.

### Strong identifier requirement

A merge requires **at least two strong identifiers** matching across records. A single matching field — even a strong one — is not enough. Strong identifiers, ranked:

1. `parcel_id` (county-canonical form)
2. `legal_description` (normalized)
3. `situs_address` (normalized, including street + city + state)
4. `mailing_address` (normalized)
5. `document_number` / `instrument_number`
6. `case_number`
7. `owner_name + situs_address`
8. `owner_name + parcel_id`

Note that `owner_name` alone is **never** a strong identifier. Common names ("John Smith", "Maria Garcia"), corporate-name variants ("ABC LLC" vs "ABC Holdings LLC"), trust names, and trade names produce false matches at scale. Owner name only counts as part of a compound identifier (rows 7 and 8 above).

### Auto-merge keys (in priority order)

The framework auto-merges only when one of these compound keys matches exactly:

1. `parcel_id + signal_id` — exact match, auto-merge
2. `source_document_id + parcel_id` — same recording, same property, auto-merge
3. `case_number + parcel_id` — same court case affecting same parcel, auto-merge
4. `normalized_address + event_date + pattern` — likely the same event reported by two sources
5. `owner_entity_id + normalized_address + event_date` — possible duplicate, lower confidence

### When in doubt, route to review

If no auto-merge key is strong enough AND the records share at least one strong identifier (suggesting they might be duplicates but not provably so), route to review with `possible_duplicate` flag. The reviewer sees both records side-by-side and decides.

If records share fewer than one strong identifier, they are not candidate duplicates — leave them separate. Two different leads on two different parcels with the same owner name are two leads, not one.

### Anti-patterns the framework refuses

- **Merge by owner-name fuzzy match alone.** "John Smith Jr." and "John Smith" might be the same person or might be father and son. Without a second identifier, the framework will not merge.
- **Merge by mailing-address alone when owner names differ.** Multiple parties can use the same PO Box, attorney's office, or commercial mail receiver.
- **Merge by partial parcel-ID match.** "1234.05" and "1234.06" are adjacent parcels, not the same parcel.
- **Cross-county merges based on name + city.** Even if two counties report what looks like the same owner, no merge happens unless a state-canonical identifier (SSN, FEIN, state ID number) is available — and the framework does not capture those.

The cost of a bad merge is corruption that propagates: scoring, deal-path classification, evidence rollup, and CRM export all read merged records. A bad merge ships a lead the operator can't act on. Better to over-route to review.

---

## Entity record schema

```json
{
  "entity_id": "ent_<uuid>",
  "entity_type": "LLC",
  "display_name": "Example Owner LLC",
  "normalized_name": "EXAMPLE OWNER LIMITED LIABILITY COMPANY",
  "aliases": [],
  "mailing_addresses": [],
  "related_entities": [],
  "evidence_ids": [],
  "confidence": 0,
  "review_flags": []
}
```

`aliases` carries known alternate names. `mailing_addresses` is the deduplicated list across all records that touched this entity. `related_entities` carries soft-linked entity IDs (same registered agent, same mailing, same trustee, etc.) — the matcher proposes; humans confirm via review queue.

Stored at `data/entities.jsonl` (static mode) or `entities` table (Supabase mode).

---

## Why entity resolution matters more than scoring

Scoring is reversible. If a lead is scored 70 and should be 80, the next refresh recomputes and corrects. Entity resolution is sticky. If two parcels get incorrectly merged into one entity, the framework will keep treating them as one until a human intervenes.

This is why the framework defaults to NOT merging when evidence is weak. The cost of an unmerged duplicate is one extra lead in the review queue. The cost of an incorrect merge is data corruption that propagates across every downstream artifact — score, deal-path classification, exports, audit log.

When in doubt, do not merge. Surface the candidate to the operator's review queue with the suggestive evidence attached. Let the human decide.
