"""
debtor_party_engine — v5.4.0 staged pipeline, stage 2 (the §17 engine).

STATUS: IMPLEMENTED in v5.4.0 Session 2. This module resolves the debtor /
lead subject for one raw event record per the §17 Debtor Party Rules. The
behavioral spec is scaffold/tests/v5_4_0/test_debtor_party_engine_behavior.py,
test_filer_suppression_behavior.py, and test_debtor_party_engine_units.py.

Contract: knowledge_base/architecture/17_debtor_party_rules.md.

This engine takes a raw event record (raw_event_record.schema.json) and
resolves the debtor / lead subject — the party in the source record that is
the property owner being acted against — distinct from the filer, lienholder,
or claimant. It emits a debtor-resolved record
(debtor_resolved_record.schema.json), which it validates before returning.

Why this engine exists (§17.B): different doc types invert party roles
differently. A naive translator that takes the first-named party as "owner"
produces filer-as-owner inversions — it would name the hospital as the owner
of a hospital lien, the IRS as the owner of a federal tax lien, the lender as
the owner of a foreclosure. §17 specifies, per canonical_doc_type, which party
is the debtor.

v5.4.0 finding F-1, RATIFIED Session 2 (see §17.K): this engine records its
verdict in `debtor_resolution_status` only. It MUST NOT write
`parcel_resolution_status` — that is a downstream parcel-stage field.

v5.4.0 finding F-5, resolved for Session 2 and extended in Session 7: the §17.C
table covers 29 canonical doc types — 17 mapped in Session 2 plus 12 added in
Session 7 (the 9 operator-supplied debtor rules: tax sale/deed, tax certificate,
surplus, eviction, divorce, bankruptcy, condemnation, demolition, keyed onto
the canonical_doc_types.json registry's lowercased names — tax_deed,
tax_foreclosure_notice, tax_sale_certificate, sheriff_sale_surplus,
eviction_filing, writ_of_possession, divorce_filing, final_decree_of_divorce,
marital_property_division, bankruptcy_petition, condemnation_notice,
demolition_order). A canonical_doc_type with NO §17.C rule row hits the DEFAULT
rule — route to REVIEW_REQUIRED with review_reason
"no_debtor_rule_for_doc_type". The engine NEVER guesses a debtor for an unmapped
doc type and NEVER silently passes it through. tax_delinquency is intentionally
NOT a §17 doc type — it is a tax-roll STATUS, not a recorded document; it is
enrichment, not §17.

Session 7 also formalises DOCUMENT-ONLY RESOLUTION (§17.K): the §17 engine
resolves the debtor solely from parties NAMED ON THE DOCUMENT. Several of the
new doc types (tax_foreclosure_notice, eviction_filing, writ_of_possession,
condemnation_notice, demolition_order, and the divorce types) frequently carry
no owner name on the record — only a parcel / address / case number / tenant —
and the engine MUST route such records to REVIEW_REQUIRED with review_reason
"owner_not_on_document" rather than attempt parcel / assessor / tax-roll / GIS
resolution itself (that is the downstream §13.14 parcel-resolution stage).

This module is universal framework code: the §17.C debtor_party_rules table
and the §17.D filer-suppression patterns are universal; the per-county
doc-type taxonomy and any county-specific suppression additions are passed in
at call time. No county / state / vendor literal appears here.
"""

from __future__ import annotations

import functools
import json
import re
from typing import Optional

from jsonschema import Draft202012Validator

from scaffold.pipeline.contracts import schema_path
from scaffold.pipeline.contracts.records import single_owner_block

# ---------------------------------------------------------------------------
# §17.C — the universal debtor_party_rules table.
#
# Rule row shape:
#   expected_debtor_name_type  the name_type carrying the debtor identity
#   fallback_debtor_name_type  secondary name_type if the primary is absent
#   filer_name_types           name_type(s) whose parties are filers (used to
#                              populate filer_entity — best-effort, see F-6)
#   debtor_source              "STRUCTURED" (name_type fields) or
#                              "DOCUMENT_BODY" (extracted from document text)
#   known_filer_role           descriptive label of the filer's role. §17.C
#                              names filer pattern-sets ("plaintiff patterns",
#                              "contractor patterns", "executor/administrator
#                              patterns", "heir-affiant patterns", "sheriff/
#                              marshal patterns") that §17.D does NOT
#                              enumerate — finding F-6, an open gap. This
#                              engine implements only the concretely-defined
#                              §17.D patterns; known_filer_role is descriptive
#                              metadata, not an executable pattern set.
# ---------------------------------------------------------------------------

# Session 7 extension fields a rule row MAY carry:
#   missing_debtor_review_reason  override for the REVIEW_REQUIRED review_reason
#                                 when the structured debtor is absent. The 12
#                                 Session-7 rules all use "owner_not_on_document"
#                                 (the document-only-resolution rule); the
#                                 pre-Session-7 rules keep the default message
#                                 "expected_debtor_name_type <X> missing".
#   debtor_source values added in Session 7:
#     BANKRUPTCY_STRUCTURED       Rule 7 — TP is the debtor, but the engine
#                                 first checks for a real-property connection on
#                                 property_refs and routes to REVIEW_REQUIRED
#                                 "no_property_connection" when none is present.
#                                 Contact context (signer / managing-member /
#                                 registered-agent / principal) is ENRICHMENT,
#                                 NOT §17 — it is deliberately not added here.
#     DIVORCE_MULTI_OWNER         Rule 6 — both spouses go in the Session 7A
#                                 multi-owner block. The decree's document body
#                                 may "AWARD" / "ORDER TO SELL" / "TRANSFER" the
#                                 property to one named spouse — when so, that
#                                 spouse is_primary and multi_owner_status is
#                                 MULTIPLE_OWNERS_PRIMARY_CLEAR. Otherwise both
#                                 spouses are preserved with no is_primary,
#                                 multi_owner_status MULTIPLE_OWNERS_PRIMARY_UNCLEAR
#                                 and debtor_resolution_status REVIEW_REQUIRED —
#                                 ownership priority is never guessed.

UNIVERSAL_DEBTOR_PARTY_RULES: dict[str, dict] = {
    "hospital_lien": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "GE",
        "filer_name_types": ["GR"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "hospital entity",
    },
    "code_lien": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "GE",
        "filer_name_types": ["GR"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "municipal agency",
    },
    "administrative_lien": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "GE",
        "filer_name_types": ["GR"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "state agency",
    },
    "federal_tax_lien": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "GE",
        "filer_name_types": ["GR"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "federal taxing authority",
    },
    "state_tax_lien": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "GE",
        "filer_name_types": ["GR"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "state taxing authority",
    },
    # v5.4.0 Session 8 — plural-key fix. The registry key is MECHANICS_LIEN
    # (plural). The §17 rule is keyed on the lowercased registry name so the
    # staged engine resolves it on cutover; the engine's logic is unchanged.
    "mechanics_lien": {
        "expected_debtor_name_type": "GR",
        "fallback_debtor_name_type": "DF",
        "filer_name_types": ["GE"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "contractor / construction entity",
    },
    "construction_lien": {
        "expected_debtor_name_type": "GR",
        "fallback_debtor_name_type": "DF",
        "filer_name_types": ["GE"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "contractor / construction entity",
    },
    "lis_pendens": {
        "expected_debtor_name_type": "DF",
        "fallback_debtor_name_type": "TP",
        "filer_name_types": ["PL"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "plaintiff",
    },
    "civil_judgment": {
        "expected_debtor_name_type": "DF",
        "fallback_debtor_name_type": "TP",
        "filer_name_types": ["PL"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "judgment creditor",
    },
    "abstract_of_judgment": {
        "expected_debtor_name_type": "DF",
        "fallback_debtor_name_type": "TP",
        "filer_name_types": ["PL"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "judgment creditor",
    },
    # v5.4.0 Session 8 — plural-key fixes. Registry keys are EXECUTORS_DEED
    # and ADMINISTRATORS_DEED (plural / possessive). Same §17 logic; the rule
    # rows are renamed so the staged engine resolves them after cutover.
    "executors_deed": {
        "expected_debtor_name_type": "GR",
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "none (the estate is the lead subject)",
    },
    "administrators_deed": {
        "expected_debtor_name_type": "GR",
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "none (the estate is the lead subject)",
    },
    "sheriff_sale": {
        "expected_debtor_name_type": "DF",
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "sheriff / marshal",
    },
    "affidavit_of_heirship": {
        "expected_debtor_name_type": None,
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "DOCUMENT_BODY",
        "known_filer_role": "heir-affiant",
    },
    "foreclosure_notice": {
        "expected_debtor_name_type": None,
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "DOCUMENT_BODY",
        "known_filer_role": "mortgagee / trustee / lender",
    },
    "trustee_sale": {
        "expected_debtor_name_type": None,
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "DOCUMENT_BODY",
        "known_filer_role": "trustee / mortgagee",
    },
    "probate": {
        "expected_debtor_name_type": None,
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "DOCUMENT_BODY",
        "known_filer_role": "executor / administrator",
    },
    # -----------------------------------------------------------------------
    # v5.4.0 Session 7 — the 9 operator-supplied debtor rules. 12 new registry
    # doc types (the rules with multiple registry mappings count once per
    # mapped name). Keyed on the lowercased canonical_doc_types.json registry
    # name. tax_delinquency is intentionally NOT a rule — it is a tax-roll
    # STATUS, not a recorded document; it is enrichment, not §17 (§17.K).
    # -----------------------------------------------------------------------
    # Rule 1 — tax sale / deed. Lead: the delinquent former owner whose
    # property was sold for taxes (the TP). The grantor on a tax deed is the
    # taxing authority / sheriff; the grantee is the certificate buyer or
    # successful bidder. The TP-tagged delinquent owner is the lead subject.
    "tax_deed": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": None,
        "filer_name_types": ["GR"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "taxing authority / sheriff / certificate buyer / "
                            "auction company / law firm",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    # Rule 1 — tax sale / deed (notice variant). The pre-sale notice itself.
    # Frequently carries only a parcel / address / case number — the owner is
    # NOT named on the document. Document-only resolution: route to
    # REVIEW_REQUIRED "owner_not_on_document" when the structured debtor is
    # absent. §17 must NOT attempt parcel / assessor / tax-roll resolution.
    "tax_foreclosure_notice": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "DF",
        "filer_name_types": ["GR", "PL"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "taxing authority / tax collector / treasurer / "
                            "sheriff / trustee / law firm",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    # Rule 3 — tax certificate. Lead: the property owner whose taxes were sold
    # / assigned into a certificate (the TP). The grantee is the certificate
    # buyer / investor / assignee.
    "tax_sale_certificate": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": None,
        "filer_name_types": ["GE"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "certificate buyer / investor / assignee / "
                            "taxing authority / treasurer / tax collector / "
                            "auction platform",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    # Rule 4 — surplus. Lead: the former owner or claimant entitled to excess
    # proceeds from a sheriff sale. The auction buyer, court clerk, surplus
    # recovery company, lender, and plaintiff are all suppressed by name_type
    # selection. §17 emits the doc-type tag and stops — §04 deal-path
    # classification of "surplus-recovery lead" is downstream; §17 does NOT
    # implement deal-path logic.
    "sheriff_sale_surplus": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "DF",
        "filer_name_types": ["GE"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "auction buyer / court clerk / surplus recovery "
                            "company / law firm / lender / plaintiff",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    # Rule 5 — eviction / writ of possession. Lead: the LANDLORD / property
    # owner — the PL (plaintiff) — NOT the tenant. The DF tenant, occupant,
    # defendant tenant, constable, sheriff, court, property manager (when
    # clearly only an agent), and law firm are suppressed by name_type
    # selection.
    "eviction_filing": {
        "expected_debtor_name_type": "PL",
        "fallback_debtor_name_type": None,
        "filer_name_types": ["DF"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "tenant / occupant / constable / sheriff / "
                            "court / property manager / law firm",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    "writ_of_possession": {
        "expected_debtor_name_type": "PL",
        "fallback_debtor_name_type": None,
        "filer_name_types": ["DF"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "tenant / occupant / constable / sheriff / "
                            "court / property manager / law firm",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    # Rule 6 — divorce. Lead: the titled property owner(s) whose property is
    # divided / awarded / ordered sold / transferred. The Session 7A
    # multi-owner contract is the wire format: both spouses go in owners[];
    # the decree's document body may make one spouse the clear primary
    # (MULTIPLE_OWNERS_PRIMARY_CLEAR) or not (MULTIPLE_OWNERS_PRIMARY_UNCLEAR
    # + REVIEW_REQUIRED — ownership priority is never guessed).
    "divorce_filing": {
        "expected_debtor_name_type": None,
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "DIVORCE_MULTI_OWNER",
        "known_filer_role": "attorneys / court / judge / mediator / "
                            "child support office",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    "final_decree_of_divorce": {
        "expected_debtor_name_type": None,
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "DIVORCE_MULTI_OWNER",
        "known_filer_role": "attorneys / court / judge / mediator / "
                            "child support office",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    "marital_property_division": {
        "expected_debtor_name_type": None,
        "fallback_debtor_name_type": None,
        "filer_name_types": [],
        "debtor_source": "DIVORCE_MULTI_OWNER",
        "known_filer_role": "attorneys / court / judge / mediator / "
                            "child support office",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    # Rule 7 — bankruptcy. Lead: the bankruptcy debtor when tied to a real
    # property asset. The TP-tagged debtor is the lead — individual or entity.
    # When the petition has no real-property connection (no parcel_id, no
    # situs_address, no legal_description), the engine routes to
    # REVIEW_REQUIRED "no_property_connection" — do NOT hard-exclude
    # (exclusion is a downstream decision). Contact context (signer / managing
    # member / registered agent / principal) is ENRICHMENT, NOT §17.
    "bankruptcy_petition": {
        "expected_debtor_name_type": "TP",
        "fallback_debtor_name_type": "DF",
        "filer_name_types": ["GE", "PL"],
        "debtor_source": "BANKRUPTCY_STRUCTURED",
        "known_filer_role": "trustee / creditors / secured lender / servicer "
                            "/ attorney / court / US trustee / bankruptcy "
                            "administrator",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    # Rule 8 — condemnation. Lead: the property owner whose property is
    # condemned / taken — the DF (defendant / respondent). The condemning
    # authority, city, county, state, transportation department, utility
    # authority, redevelopment authority, court, law firm, and appraiser are
    # all suppressed.
    "condemnation_notice": {
        "expected_debtor_name_type": "DF",
        "fallback_debtor_name_type": "TP",
        "filer_name_types": ["PL", "GR"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "condemning authority / city / county / state / "
                            "transportation department / utility authority / "
                            "redevelopment authority / court / law firm / "
                            "appraiser",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
    # Rule 9 — demolition. Lead: the owner of the structure / parcel subject
    # to demolition — the DF. The city, county, building department, code
    # enforcement, demolition contractor, inspector, municipal court, and
    # hearing officer are all suppressed.
    "demolition_order": {
        "expected_debtor_name_type": "DF",
        "fallback_debtor_name_type": "TP",
        "filer_name_types": ["PL", "GR"],
        "debtor_source": "STRUCTURED",
        "known_filer_role": "city / county / building department / code "
                            "enforcement / demolition contractor / inspector "
                            "/ municipal court / hearing officer",
        "missing_debtor_review_reason": "owner_not_on_document",
    },
}

# ---------------------------------------------------------------------------
# v5.4.0 Session 8 — broad-key → registry-doc-type fan-out.
#
# The §17.C contract (Session 2) defined several BROAD doc-type rule keys
# (`abstract_of_judgment`, `civil_judgment`, `code_lien`, `foreclosure_notice`,
# `probate`, `trustee_sale`) that do not match any single canonical_doc_types.json
# registry key. After the v5.4.0 cutover, the staged engine consumes lowercased
# REGISTRY keys (the monolith's normalize_doc_type emits registry UPPERCASE
# values; the bridge lowercases them). Session 8 reconciles the two namespaces:
# for each broad key, the SAME §17 rule is registered under every fine-grained
# registry doc type it covers, so the staged engine resolves correctly after
# cutover. The broad keys are retained as backward-compat aliases.
#
# `administrative_lien` is a broad CATEGORY whose registry-aligned children
# (`federal_tax_lien`, `state_tax_lien`, `municipal_lien`) each carry their own
# §17 rule rows already; the broad rule has no further fan-out and remains as
# documentation.
#
# Where two broad keys cover the same registry doc type (e.g. `foreclosure_notice`
# and `trustee_sale` both cover `notice_of_substitute_trustee_sale`), the alias
# is assigned to one canonical broad key (here, the foreclosure_notice fan-out)
# so the registry-keyed rule row is defined exactly once. The two broad rules'
# logic is identical (DOCUMENT_BODY extraction, mortgagor / grantor / debtor
# labels) so the assignment is operationally neutral.
# ---------------------------------------------------------------------------

BROAD_KEY_REGISTRY_ALIASES: dict[str, tuple[str, ...]] = {
    "abstract_of_judgment": ("judgment_lien",),
    "civil_judgment": (),  # judgment_lien already covered by abstract_of_judgment
    "administrative_lien": (),  # broad bucket — children carry their own rows
    "code_lien": ("code_violation_notice", "municipal_lien"),
    "foreclosure_notice": (
        "notice_of_sale",
        "notice_of_default",
        "notice_of_substitute_trustee_sale",
        "final_judgment_of_foreclosure",
        "appointment_of_substitute_trustee",
    ),
    "probate": (
        "letters_testamentary",
        "letters_of_administration",
        "determination_of_heirship",
        "muniment_of_title",
    ),
    "trustee_sale": ("trustees_deed_upon_sale",),
}
"""v5.4.0 Session 8 — for each broad §17 rule key, the registry-aligned
canonical_doc_type values the same rule must fire on after the cutover. Empty
tuple = broad bucket with no registry-fan-out (its children carry their own
rule rows separately, or no further registry match exists)."""


def _fan_out_broad_rules() -> None:
    """Register each broad rule under every registry alias in BROAD_KEY_REGISTRY_ALIASES.

    Identity by reference is fine — the rule dict is read, never mutated, by the
    engine. Existing registry-keyed rule rows are never overwritten: an explicit
    Session-7 rule (e.g. condemnation_notice) wins over a fan-out alias collision.
    """
    for broad_key, aliases in BROAD_KEY_REGISTRY_ALIASES.items():
        base_rule = UNIVERSAL_DEBTOR_PARTY_RULES.get(broad_key)
        if not base_rule:
            continue
        for alias in aliases:
            if alias not in UNIVERSAL_DEBTOR_PARTY_RULES:
                UNIVERSAL_DEBTOR_PARTY_RULES[alias] = base_rule


# ---------------------------------------------------------------------------
# §17.D — universal known-filer suppression patterns.
#
# A name matching any of these MUST NEVER be returned as owner_name. The
# patterns are grouped by category for review_reason reporting. Each entry is
# a compiled, case-insensitive regex; multi-word patterns tolerate flexible
# whitespace. <*> wildcards in §17.D become "match the marker phrase anywhere
# in the name".
# ---------------------------------------------------------------------------

def _ci(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.IGNORECASE)


_FILER_SUPPRESSION_PATTERNS: dict[str, list[tuple[str, re.Pattern]]] = {
    "government_entity": [
        ("CITY OF <*>", _ci(r"\bCITY\s+OF\b")),
        ("COUNTY OF <*>", _ci(r"\bCOUNTY\s+OF\b")),
        ("STATE OF <*>", _ci(r"\bSTATE\s+OF\b")),
        ("UNITED STATES OF AMERICA", _ci(r"\bUNITED\s+STATES(\s+OF\s+AMERICA)?\b")),
        ("IRS", _ci(r"\bIRS\b")),
        ("INTERNAL REVENUE SERVICE", _ci(r"\bINTERNAL\s+REVENUE\s+SERVICE\b")),
    ],
    "state_agency": [
        ("<STATE> COMPTROLLER", _ci(r"\bCOMPTROLLER\b")),
        ("<STATE> WORKFORCE COMMISSION", _ci(r"\bWORKFORCE\s+COMMISSION\b")),
        ("<STATE> DEPARTMENT OF <*>", _ci(r"\bDEPARTMENT\s+OF\b")),
    ],
    "hospital_entity": [
        ("HOSPITAL", _ci(r"\bHOSPITALS?\b")),
        ("HEALTH SYSTEM", _ci(r"\bHEALTH\s+SYSTEM\b")),
        ("MEDICAL CENTER", _ci(r"\bMEDICAL\s+CENTER\b")),
    ],
    "mortgage_lender": [
        ("MORTGAGE COMPANY", _ci(r"\bMORTGAGE\s+COMPANY\b")),
        ("MORTGAGE CORP", _ci(r"\bMORTGAGE\s+CORP(ORATION)?\b")),
        ("MORTGAGE LLC", _ci(r"\bMORTGAGE\s+L\.?L\.?C\.?\b")),
        ("BANK N.A.", _ci(r"\bBANK\s+N\.?\s*A\.?\b")),
        ("BANK NATIONAL ASSOCIATION", _ci(r"\bBANK\s+NATIONAL\s+ASSOCIATION\b")),
    ],
    "federal_mortgage_agency": [
        ("FREDDIE MAC", _ci(r"\bFREDDIE\s+MAC\b")),
        ("FANNIE MAE", _ci(r"\bFANNIE\s+MAE\b")),
        ("FEDERAL HOME LOAN MORTGAGE CORPORATION",
         _ci(r"\bFEDERAL\s+HOME\s+LOAN\s+MORTGAGE\s+CORPORATION\b")),
        ("FEDERAL NATIONAL MORTGAGE ASSOCIATION",
         _ci(r"\bFEDERAL\s+NATIONAL\s+MORTGAGE\s+ASSOCIATION\b")),
        ("GINNIE MAE", _ci(r"\bGINNIE\s+MAE\b")),
        ("GOVERNMENT NATIONAL MORTGAGE ASSOCIATION",
         _ci(r"\bGOVERNMENT\s+NATIONAL\s+MORTGAGE\s+ASSOCIATION\b")),
    ],
    "servicer": [
        ("NATIONSTAR", _ci(r"\bNATIONSTAR\b")),
        ("MR. COOPER", _ci(r"\bMR\.?\s+COOPER\b")),
        ("PHH MORTGAGE", _ci(r"\bPHH\s+MORTGAGE\b")),
        ("NEWREZ", _ci(r"\bNEWREZ\b")),
        ("SHELLPOINT", _ci(r"\bSHELLPOINT\b")),
        ("RUSHMORE", _ci(r"\bRUSHMORE\b")),
        ("SERVBANK", _ci(r"\bSERVBANK\b")),
    ],
    "trustee": [
        ("SUBSTITUTE TRUSTEE", _ci(r"\bSUBSTITUTE\s+TRUSTEE\b")),
        ("TRUSTEE SERVICES", _ci(r"\bTRUSTEE\s+SERVICES\b")),
    ],
    # -----------------------------------------------------------------------
    # v5.4.0 Session 7 — additional universal name-pattern suppression groups
    # supporting the 9 operator-supplied debtor rules. Role-descriptor parties
    # (tenant, bidder, certificate buyer) are filtered out by name_type
    # selection itself — they never carry the lead's name_type, so they are
    # never picked as owner_name. These pattern groups add organizational-name
    # suppression that complements name_type selection: a record where the
    # only candidate carries one of these names is routed to REVIEW_REQUIRED
    # rather than emitted as the owner. Patterns are conservative (operator-
    # supplied role labels, regulated office names) so they don't false-
    # positive against real person names.
    # -----------------------------------------------------------------------
    "tax_authority": [
        ("TAX COLLECTOR", _ci(r"\bTAX\s+COLLECTOR\b")),
        ("TAX ASSESSOR", _ci(r"\bTAX\s+ASSESSOR\b")),
        ("TAX OFFICE", _ci(r"\bTAX\s+OFFICE\b")),
        ("TREASURER", _ci(r"\bTREASURER\b")),
        ("TAXING AUTHORITY", _ci(r"\bTAXING\s+AUTHORITY\b")),
    ],
    "auction_party": [
        ("AUCTION COMPANY", _ci(r"\bAUCTION\s+COMPANY\b")),
        ("AUCTION SERVICES", _ci(r"\bAUCTION\s+SERVICES\b")),
        ("AUCTION PLATFORM", _ci(r"\bAUCTION\s+PLATFORM\b")),
        ("FORECLOSURE AUCTIONS", _ci(r"\bFORECLOSURE\s+AUCTIONS?\b")),
    ],
    "law_firm": [
        ("LAW FIRM", _ci(r"\bLAW\s+FIRM\b")),
        ("LAW OFFICES", _ci(r"\bLAW\s+OFFICES?\b")),
        ("ATTORNEYS AT LAW", _ci(r"\bATTORNEYS?\s+AT\s+LAW\b")),
    ],
    "court_role": [
        ("MUNICIPAL COURT", _ci(r"\bMUNICIPAL\s+COURT\b")),
        ("FAMILY COURT", _ci(r"\bFAMILY\s+COURT\b")),
        ("PROBATE COURT", _ci(r"\bPROBATE\s+COURT\b")),
        ("BANKRUPTCY COURT", _ci(r"\bBANKRUPTCY\s+COURT\b")),
        ("DISTRICT COURT", _ci(r"\bDISTRICT\s+COURT\b")),
        ("COURT CLERK", _ci(r"\bCOURT\s+CLERK\b")),
        ("CLERK OF THE COURT", _ci(r"\bCLERK\s+OF\s+THE\s+COURT\b")),
        ("HEARING OFFICER", _ci(r"\bHEARING\s+OFFICER\b")),
        ("MEDIATOR", _ci(r"\bMEDIATOR\b")),
        ("CHILD SUPPORT OFFICE", _ci(r"\bCHILD\s+SUPPORT\s+OFFICE\b")),
    ],
    "law_enforcement": [
        ("SHERIFF", _ci(r"\bSHERIFF\b")),
        ("CONSTABLE", _ci(r"\bCONSTABLE\b")),
        ("MARSHAL", _ci(r"\bMARSHALL?\b")),
    ],
    "surplus_recovery": [
        ("SURPLUS RECOVERY", _ci(r"\bSURPLUS\s+RECOVERY\b")),
        ("SURPLUS FUNDS RECOVERY", _ci(r"\bSURPLUS\s+FUNDS\s+RECOVERY\b")),
        ("FUND RECOVERY", _ci(r"\bFUND\s+RECOVERY\b")),
    ],
    "bankruptcy_official": [
        ("U.S. TRUSTEE", _ci(r"\bU\.?\s*S\.?\s+TRUSTEE\b")),
        ("UNITED STATES TRUSTEE", _ci(r"\bUNITED\s+STATES\s+TRUSTEE\b")),
        ("BANKRUPTCY ADMINISTRATOR",
         _ci(r"\bBANKRUPTCY\s+ADMINISTRATOR\b")),
        ("OFFICE OF THE TRUSTEE", _ci(r"\bOFFICE\s+OF\s+THE\s+TRUSTEE\b")),
    ],
    "code_enforcement_role": [
        ("BUILDING DEPARTMENT", _ci(r"\bBUILDING\s+DEPARTMENT\b")),
        ("BUILDING INSPECTOR", _ci(r"\bBUILDING\s+INSPECTOR\b")),
        ("CODE ENFORCEMENT", _ci(r"\bCODE\s+ENFORCEMENT\b")),
        ("CODE COMPLIANCE", _ci(r"\bCODE\s+COMPLIANCE\b")),
        ("HOUSING AUTHORITY", _ci(r"\bHOUSING\s+AUTHORITY\b")),
        ("REDEVELOPMENT AUTHORITY",
         _ci(r"\bREDEVELOPMENT\s+AUTHORITY\b")),
        ("TRANSPORTATION DEPARTMENT",
         _ci(r"\bTRANSPORTATION\s+DEPARTMENT\b")),
        ("UTILITY AUTHORITY", _ci(r"\bUTILITY\s+AUTHORITY\b")),
        ("PORT AUTHORITY", _ci(r"\bPORT\s+AUTHORITY\b")),
        ("APPRAISAL DISTRICT", _ci(r"\bAPPRAISAL\s+DISTRICT\b")),
    ],
    "property_manager": [
        ("PROPERTY MANAGEMENT",
         _ci(r"\bPROPERTY\s+MANAGEMENT(\s+(GROUP|COMPANY|SERVICES|LLC))?\b")),
    ],
}

# ---------------------------------------------------------------------------
# §17.F — owner-type classifier patterns.
# ---------------------------------------------------------------------------

# Corporate-suffix tokens (§17.F ENTITY). Word-boundary guarded so a suffix is
# matched only as a standalone token, never as a substring inside a longer
# word. Dotted abbreviations tolerate optional periods.
_ENTITY_RE = re.compile(
    r"(?<![A-Za-z])(?:"
    r"L\.?L\.?C\.?|L\.?L\.?P\.?|L\.?P\.?|"
    r"INCORPORATED|INC\.?|"
    r"CORPORATION|CORP\.?|"
    r"P\.?L\.?L\.?C\.?|"
    r"P\.?C\.?|P\.?A\.?|"
    r"LTD\.?|"
    r"COMPANY|CO\.?|"
    r"GROUP|ASSOCIATES|ENTERPRISES|PARTNERS|SERVICES|"
    r"AUTHORITY|COMMISSION|DISTRICT"
    r")(?![A-Za-z])",
    re.IGNORECASE,
)

# Decedent patterns (§17.F ESTATE). "REAL ESTATE" is stripped before testing.
_ESTATE_RE = re.compile(
    r"\b(?:EST(?:ATE)?\.?\s+OF\b|HEIRS?\s+OF\b|ESTATE\b)",
    re.IGNORECASE,
)
_REAL_ESTATE_RE = re.compile(r"\bREAL\s+ESTATE\b", re.IGNORECASE)

# Family/decedent trust patterns (§17.F TRUST). Corporate "TRUST COMPANY"
# names are caught by _ENTITY_RE first (ENTITY precedence).
_TRUST_RE = re.compile(
    r"\b(?:REVOCABLE|FAMILY|LIVING|REV)\s+TRUST\b|\bTRUST\b",
    re.IGNORECASE,
)
_ALNUM_RE = re.compile(r"[A-Za-z0-9]")

# ---------------------------------------------------------------------------
# §17.C document-body extraction labels, per doc type.
# ---------------------------------------------------------------------------

_BODY_DEBTOR_LABELS: dict[str, list[str]] = {
    "foreclosure_notice": [
        "ORIGINAL MORTGAGOR", "MORTGAGOR", "GRANTOR", "DEBTOR", "BORROWER",
        "PROPERTY OWNER", "RECORD OWNER", "OWNER OF RECORD",
    ],
    "trustee_sale": [
        "ORIGINAL MORTGAGOR", "MORTGAGOR", "GRANTOR", "DEBTOR", "BORROWER",
        "PROPERTY OWNER", "RECORD OWNER",
    ],
    "probate": ["NAME OF DECEDENT", "DECEDENT", "DECEASED"],
    "affidavit_of_heirship": ["NAME OF DECEDENT", "DECEDENT", "DECEASED"],
}


def _fan_out_body_labels() -> None:
    """Share each broad body-label set into every registry-alias key.

    A registry-keyed rule fanned out from `foreclosure_notice` / `trustee_sale` /
    `probate` reaches the document-body extractor under its own canonical_doc_type
    value; the label set must be accessible by that name. Existing label entries
    are never overwritten.
    """
    for broad_key, aliases in BROAD_KEY_REGISTRY_ALIASES.items():
        labels = _BODY_DEBTOR_LABELS.get(broad_key)
        if not labels:
            continue
        for alias in aliases:
            if alias not in _BODY_DEBTOR_LABELS:
                _BODY_DEBTOR_LABELS[alias] = list(labels)


# Apply the Session 8 fan-out at module-import time. Registering both the rule
# table and the body-label table here makes the staged engine resolve every
# fanned-out registry doc type without any further wiring at the call site.
_fan_out_broad_rules()
_fan_out_body_labels()

# Doc types whose document body may carry "ESTATE OF <name>" / "HEIRS OF <name>"
# without a colon. The `probate` broad key and `affidavit_of_heirship`, plus
# every Session-8 probate-family registry alias (letters_testamentary,
# letters_of_administration, determination_of_heirship, muniment_of_title).
_PROBATE_BODY_DOC_TYPES: frozenset[str] = frozenset(
    {"probate", "affidavit_of_heirship"}
    | set(BROAD_KEY_REGISTRY_ALIASES.get("probate", ()))
)

# v5.4.0 Session 7 — Rule 6 divorce: award-language labels the engine reads
# from a divorce decree / property-division order's document_body_text to make
# one spouse the clear primary (multi_owner_status MULTIPLE_OWNERS_PRIMARY_CLEAR).
# Each label is followed by a name. Absence of a recognised label keeps the
# record MULTIPLE_OWNERS_PRIMARY_UNCLEAR (REVIEW_REQUIRED) — ownership priority
# is never guessed.
_DIVORCE_AWARD_LABELS: tuple[str, ...] = (
    "PROPERTY AWARDED TO",
    "AWARDED TO",
    "ORDERED TO SELL BY",
    "TO BE TRANSFERRED TO",
    "TRANSFERRED TO",
    "VESTED IN",
    "OBLIGATED TO",
    "SOLE OWNERSHIP TO",
)

# v5.4.0 Session 7 — Rule 6 divorce: the spouse name_types gathered into the
# multi-owner block when the rule's debtor_source is DIVORCE_MULTI_OWNER. PL
# and DF are the standard petitioner / respondent name_types for a divorce
# action; GR catches deed-shaped marital_property_division records that name
# both spouses as grantors.
_DIVORCE_SPOUSE_NAME_TYPES: tuple[str, ...] = ("PL", "DF", "GR")

# The §17.E placeholder owner_name for a REVIEW_REQUIRED record.
_PLACEHOLDER = "{doc_type} against unidentified party"


@functools.lru_cache(maxsize=1)
def _output_validator() -> Draft202012Validator:
    """Lazy-load the debtor_resolved_record JSON Schema validator."""
    schema = json.loads(
        schema_path("debtor_resolved_record").read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


def _validate_output(record: dict) -> dict:
    """Validate an engine output record against debtor_resolved_record.schema.json.

    Raises ValueError when the engine produced a non-conforming record — that
    is an engine bug, not a data problem, and must fail loudly.
    """
    errors = sorted(
        _output_validator().iter_errors(record), key=lambda e: list(e.path)
    )
    if errors:
        detail = "; ".join(
            f"{list(e.path) or '<root>'}: {e.message}" for e in errors
        )
        raise ValueError(
            "debtor_party_engine produced a record that violates "
            f"debtor_resolved_record.schema.json: {detail}"
        )
    return record


# ---------------------------------------------------------------------------
# Public engine functions.
# ---------------------------------------------------------------------------

def classify_owner_type(name: str) -> str:
    """Classify an owner name into one of the §17.F owner types.

    Returns one of ENTITY, ESTATE, TRUST, INDIVIDUAL, UNKNOWN.

    Precedence ENTITY > ESTATE > TRUST > INDIVIDUAL (§17.F). Word-boundary and
    position rules are enforced: a corporate suffix is matched only as a
    standalone token, "REAL ESTATE" is stripped before the ESTATE test, and a
    corporate "TRUST COMPANY" is caught as ENTITY first. UNKNOWN is returned
    only when the name is empty or carries no alphanumeric character.

    Args:
        name: The owner name to classify.

    Returns:
        One of the §17.F owner-type strings.
    """
    if not isinstance(name, str):
        return "UNKNOWN"
    stripped = name.strip()
    if not stripped or not _ALNUM_RE.search(stripped):
        return "UNKNOWN"
    if _ENTITY_RE.search(stripped):
        return "ENTITY"
    estate_text = _REAL_ESTATE_RE.sub(" ", stripped)
    if _ESTATE_RE.search(estate_text):
        return "ESTATE"
    if _TRUST_RE.search(stripped):
        return "TRUST"
    return "INDIVIDUAL"


def match_known_filer(
    name: str,
    *,
    additional_suppressions: tuple[str, ...] = (),
) -> Optional[str]:
    """Test whether a name matches a known-filer suppression pattern (§17.D).

    Government entities, state agencies, hospital entities, mortgage/lender
    entities, federal mortgage agencies, servicers, and trustee patterns must
    never appear as owner_name. County-specific suppression entries are
    layered on top as case-insensitive substring patterns.

    Args:
        name: The candidate owner name to test.
        additional_suppressions: County-specific suppression patterns.

    Returns:
        A "<category>:<pattern>" label when `name` is a known filer, or None
        when it is not.
    """
    if not isinstance(name, str) or not name.strip():
        return None
    for category, patterns in _FILER_SUPPRESSION_PATTERNS.items():
        for label, regex in patterns:
            if regex.search(name):
                return f"{category}:{label}"
    upper = name.upper()
    for entry in additional_suppressions:
        if entry and str(entry).upper() in upper:
            return f"county_suppression:{entry}"
    return None


def extract_debtor_from_document_body(
    document_body_text: str,
    canonical_doc_type: str,
) -> Optional[str]:
    """Extract the debtor name from unstructured document text (§17.C).

    For the doc types whose §17.C expected_debtor is "extracted from the
    document body" — foreclosure_notice, trustee_sale, probate,
    affidavit_of_heirship — the debtor identity is read from labelled fields
    in the document text ("DEBTOR: ...", "MORTGAGOR: ...", "DECEDENT: ...",
    "ESTATE OF ...", etc.). Absence of an extractable debtor returns None,
    which routes the record to REVIEW_REQUIRED (§17.E).

    This is a deterministic labelled-field extractor — it does not infer a
    debtor from free prose. A source whose document text does not carry a
    recognised debtor label is routed for operator review rather than guessed.

    Args:
        document_body_text: The full document text from the raw event record.
        canonical_doc_type: The canonical doc type, selecting the label set.

    Returns:
        The extracted debtor name, or None when no debtor can be extracted.
    """
    if not isinstance(document_body_text, str) or not document_body_text.strip():
        return None
    text = document_body_text

    labels = _BODY_DEBTOR_LABELS.get(canonical_doc_type, [])
    for label in labels:
        pattern = re.compile(
            r"\b" + re.escape(label).replace(r"\ ", r"\s+") + r"\b\s*[:\-]\s*([^\n;]+)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            value = _clean_extracted_name(match.group(1))
            if value:
                return value

    # "ESTATE OF <name>" / "HEIRS OF <name>" appear without a colon in the
    # probate and affidavit-of-heirship body text. After the Session 8 fan-out,
    # every probate-family registry doc type (letters_testamentary,
    # letters_of_administration, determination_of_heirship, muniment_of_title)
    # uses the same body-label set, so the no-colon estate-of branch must
    # cover them too.
    if canonical_doc_type in _PROBATE_BODY_DOC_TYPES:
        match = re.search(
            r"\b(ESTATE\s+OF|HEIRS?\s+OF)\s+([^\n;,]+)", text, re.IGNORECASE
        )
        if match:
            value = _clean_extracted_name(
                f"{match.group(1)} {match.group(2)}"
            )
            if value:
                return value

    return None


def route_to_review(
    raw_event: dict,
    *,
    review_reason: str,
    filer_entity: Optional[str],
) -> dict:
    """Build a REVIEW_REQUIRED debtor-resolved record (§17.E routing contract).

    The §17.E contract: the record is NOT dropped. It is emitted with
    `debtor_resolution_status = REVIEW_REQUIRED`,
    `owner_name = "<canonical_doc_type> against unidentified party"`,
    `owner_type = UNKNOWN` (the owner is genuinely unidentified — see §17
    implementation note in the Session 2 report), `filer_entity` set to the
    original filer name when one was identified (None otherwise — e.g. the
    F-5 default rule), and `review_reason` set to the rule that triggered
    routing. Per ratified finding F-1, no parcel-stage field is written.

    Args:
        raw_event: The raw event record that could not be debtor-resolved.
        review_reason: The §17.E rule that triggered routing.
        filer_entity: The original filer name, or None when none was found.

    Returns:
        A debtor-resolved record with REVIEW_REQUIRED routing applied,
        conforming to debtor_resolved_record.schema.json.
    """
    doc_type = raw_event.get("canonical_doc_type") or "unknown_doc_type"
    placeholder = _PLACEHOLDER.format(doc_type=doc_type)
    record = _carry_forward(raw_event)
    record.update({
        "owner_name": placeholder,
        "owner_type": "UNKNOWN",
        "filer_entity": filer_entity,
        "debtor_resolution_status": "REVIEW_REQUIRED",
        "review_reason": review_reason,
        "expected_debtor_name_type": None,
        "debtor_extraction_method": "REVIEW_ROUTED",
    })
    # v5.4.0 Session 7A — a review-routed record has one (unidentified) owner
    # slot: the 17.E placeholder. multi_owner_status SINGLE_OWNER is descriptive
    # cardinality only; the needs-review verdict stays debtor_resolution_status.
    record.update(single_owner_block(
        placeholder,
        name_type=None,
        role="unresolved",
        resolution_status="REVIEW_REQUIRED",
        source_field=None,
    ))
    return record


def resolve_debtor_party(
    raw_event: dict,
    *,
    debtor_party_rules: Optional[dict] = None,
    additional_suppressions: tuple[str, ...] = (),
) -> dict:
    """Resolve the debtor party for one raw event record (§17.C / §17.E).

    The contract (§17.C, §17.E, §17.F):

      1. Look up the §17.C rule for `raw_event["canonical_doc_type"]`. With no
         rule (finding F-5), apply the DEFAULT rule: route to REVIEW_REQUIRED
         with review_reason "no_debtor_rule_for_doc_type".
      2. Extract the debtor by `debtor_source`:
         - STRUCTURED — take the party whose `name_type` matches the rule's
           `expected_debtor_name_type`; if absent, the fallback name_type;
         - DOCUMENT_BODY — call `extract_debtor_from_document_body`;
         - BANKRUPTCY_STRUCTURED — Rule 7. First check for a real-property
           connection on `property_refs`; route to REVIEW_REQUIRED
           "no_property_connection" when none exists, otherwise resolve like
           STRUCTURED. Do NOT hard-exclude — exclusion is a downstream
           decision.
         - DIVORCE_MULTI_OWNER — Rule 6. Gather both spouses (PL / DF / GR)
           into the Session 7A multi-owner block. If the decree's document
           body clearly awards / obligates / vests / orders-sold-by one
           spouse, that spouse is `is_primary`
           (MULTIPLE_OWNERS_PRIMARY_CLEAR); otherwise both spouses are
           preserved with no `is_primary`, multi_owner_status is
           MULTIPLE_OWNERS_PRIMARY_UNCLEAR, and debtor_resolution_status is
           REVIEW_REQUIRED — ownership priority is never guessed.
      3. Route to review (§17.E) when the expected debtor is missing, the
         document-body debtor is not extractable, OR a known-filer pattern
         (§17.D) matches the proposed owner. The lead is NEVER dropped. For
         the 12 Session 7 doc types, a missing structured debtor uses the
         document-only-resolution review_reason "owner_not_on_document"
         (§17.K) — §17 must NOT attempt parcel / assessor / tax-roll / GIS
         resolution; that is the downstream §13.14 stage.
      4. Classify `owner_type` via `classify_owner_type` (§17.F).
      5. The output is validated against debtor_resolved_record.schema.json.

    Per ratified finding F-1, the verdict is recorded in
    `debtor_resolution_status`; this engine writes no parcel-stage field.

    Args:
        raw_event: A raw event record conforming to
            raw_event_record.schema.json.
        debtor_party_rules: The §17.C debtor_party_rules mapping. When None,
            UNIVERSAL_DEBTOR_PARTY_RULES is used.
        additional_suppressions: County-specific filer-suppression patterns.

    Returns:
        A debtor-resolved record conforming to
        debtor_resolved_record.schema.json.

    Raises:
        ValueError: if the engine produces a non-conforming record.
    """
    rules = (
        debtor_party_rules
        if debtor_party_rules is not None
        else UNIVERSAL_DEBTOR_PARTY_RULES
    )
    doc_type = raw_event.get("canonical_doc_type")
    rule = rules.get(doc_type) if isinstance(rules, dict) else None

    # F-5 default rule — no §17.C rule for this canonical_doc_type.
    if rule is None:
        return _validate_output(
            route_to_review(
                raw_event,
                review_reason="no_debtor_rule_for_doc_type",
                filer_entity=None,
            )
        )

    parties = raw_event.get("parties") or []
    filer_name_types = set(rule.get("filer_name_types") or [])
    filer_entity = _first_party_name(parties, filer_name_types)
    debtor_source = rule.get("debtor_source", "STRUCTURED")

    if debtor_source == "DOCUMENT_BODY":
        debtor = extract_debtor_from_document_body(
            raw_event.get("document_body_text") or "", doc_type
        )
        if not debtor:
            return _validate_output(
                route_to_review(
                    raw_event,
                    review_reason="document_body_debtor_not_extractable",
                    filer_entity=filer_entity,
                )
            )
        filer_hit = match_known_filer(
            debtor, additional_suppressions=additional_suppressions
        )
        if filer_hit:
            return _validate_output(
                route_to_review(
                    raw_event,
                    review_reason=f"known_filer_pattern match: {filer_hit}",
                    filer_entity=debtor,
                )
            )
        return _validate_output(
            _build_resolved(
                raw_event,
                owner_name=debtor,
                filer_entity=filer_entity,
                method="DOCUMENT_BODY",
                expected_name_type=None,
            )
        )

    if debtor_source == "DIVORCE_MULTI_OWNER":
        return _validate_output(
            _resolve_divorce_multi_owner(
                raw_event,
                rule=rule,
                filer_entity=filer_entity,
                additional_suppressions=additional_suppressions,
            )
        )

    if debtor_source == "BANKRUPTCY_STRUCTURED":
        # Rule 7 — bankruptcy must have a real-property connection. The §17
        # engine resolves only on document parties; if there is no parcel
        # identifier, situs address, or legal description on the record, the
        # bankruptcy has no property hook for §17 and is routed to review with
        # "no_property_connection". The bankruptcy is NOT hard-excluded — an
        # operator may still choose to pursue it for non-§17 reasons.
        if not _has_property_connection(raw_event):
            return _validate_output(
                route_to_review(
                    raw_event,
                    review_reason="no_property_connection",
                    filer_entity=filer_entity,
                )
            )
        # Property connection present — fall through to the STRUCTURED path.

    # STRUCTURED (and BANKRUPTCY_STRUCTURED with property connection) debtor
    # extraction.
    expected = rule.get("expected_debtor_name_type")
    fallback = rule.get("fallback_debtor_name_type")

    candidate = _first_party_name(parties, {expected}) if expected else None
    method = "STRUCTURED_NAME_TYPE"
    used_name_type = expected
    if not candidate and fallback:
        fallback_candidate = _first_party_name(parties, {fallback})
        if fallback_candidate:
            candidate = fallback_candidate
            method = "FALLBACK_NAME_TYPE"
            used_name_type = fallback

    if not candidate:
        # The 12 Session 7 rules carry `missing_debtor_review_reason =
        # "owner_not_on_document"` — the document-only-resolution review_reason
        # (§17.K). The pre-Session 7 rules keep the default message
        # "expected_debtor_name_type <X> missing".
        review_reason = rule.get("missing_debtor_review_reason") or (
            f"expected_debtor_name_type {expected} missing"
        )
        return _validate_output(
            route_to_review(
                raw_event,
                review_reason=review_reason,
                filer_entity=filer_entity,
            )
        )

    filer_hit = match_known_filer(
        candidate, additional_suppressions=additional_suppressions
    )
    if filer_hit:
        return _validate_output(
            route_to_review(
                raw_event,
                review_reason=f"known_filer_pattern match: {filer_hit}",
                filer_entity=candidate,
            )
        )

    return _validate_output(
        _build_resolved(
            raw_event,
            owner_name=candidate,
            filer_entity=filer_entity,
            method=method,
            expected_name_type=used_name_type,
        )
    )


# ---------------------------------------------------------------------------
# Internal helpers.
# ---------------------------------------------------------------------------

def _carry_forward(raw_event: dict) -> dict:
    """Copy the fields a debtor-resolved record carries from the raw event."""
    property_refs = raw_event.get("property_refs") or {}
    return {
        "raw_event_id": raw_event.get("raw_event_id"),
        "source_id": raw_event.get("source_id"),
        "source_role": raw_event.get("source_role"),
        "canonical_doc_type": raw_event.get("canonical_doc_type"),
        "source_url": raw_event.get("source_url"),
        "recorded_date": raw_event.get("recorded_date"),
        "instrument_number": raw_event.get("instrument_number"),
        "event_date": raw_event.get("event_date"),
        "property_refs": {
            "parcel_id": property_refs.get("parcel_id"),
            "situs_address": property_refs.get("situs_address"),
            "legal_description": property_refs.get("legal_description"),
            "case_number": property_refs.get("case_number"),
        },
        "evidence_ids": list(raw_event.get("evidence_ids") or []),
    }


def _build_resolved(
    raw_event: dict,
    *,
    owner_name: str,
    filer_entity: Optional[str],
    method: str,
    expected_name_type: Optional[str],
) -> dict:
    """Build a RESOLVED debtor-resolved record."""
    record = _carry_forward(raw_event)
    record.update({
        "owner_name": owner_name,
        "owner_type": classify_owner_type(owner_name),
        "filer_entity": filer_entity,
        "debtor_resolution_status": "RESOLVED",
        "review_reason": None,
        "expected_debtor_name_type": expected_name_type,
        "debtor_extraction_method": method,
    })
    # v5.4.0 Session 7A — the 17 engine resolves one owner per record; wrap it
    # as the SINGLE_OWNER multi-owner block. Multi-owner resolution (the 9
    # deferred rules) is Session 7, which keys off this same block.
    record.update(single_owner_block(
        owner_name,
        name_type=expected_name_type,
        role="debtor",
        resolution_status="RESOLVED",
        source_field=expected_name_type or "document_body",
    ))
    return record


def _first_party_name(parties: list, name_types: set) -> Optional[str]:
    """Return the first non-empty party name whose name_type is in name_types."""
    if not name_types:
        return None
    for party in parties or []:
        if not isinstance(party, dict):
            continue
        if party.get("name_type") in name_types:
            name = (party.get("name") or "").strip()
            if name:
                return name
    return None


def _clean_extracted_name(value: str) -> str:
    """Trim a document-body-extracted name of surrounding noise."""
    cleaned = re.sub(r"\s+", " ", value).strip()
    cleaned = cleaned.strip("\"'")
    cleaned = cleaned.rstrip(".,;:- ").strip()
    return cleaned


# ---------------------------------------------------------------------------
# v5.4.0 Session 7 — internal helpers for Rule 6 (divorce multi-owner) and
# Rule 7 (bankruptcy property connection).
# ---------------------------------------------------------------------------

def _has_property_connection(raw_event: dict) -> bool:
    """Return True when the raw event carries a real-property identifier.

    Rule 7 — bankruptcy: a petition with no real-property hook (no parcel_id,
    no situs_address, no legal_description) is routed to REVIEW_REQUIRED
    "no_property_connection". `case_number` alone does NOT count for the
    property-connection check — on a bankruptcy record `case_number` is
    almost always the bankruptcy case number, not a property identifier.
    """
    property_refs = raw_event.get("property_refs") or {}
    for field in ("parcel_id", "situs_address", "legal_description"):
        value = property_refs.get(field)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _all_party_names(parties: list, name_types: tuple[str, ...]) -> list[dict]:
    """Return every party whose name_type is in name_types, in order.

    Each entry preserves the original `name` and `name_type` so the caller can
    populate the Session 7A multi-owner block's owners[] without losing the
    party role-code provenance. Empty / non-dict / blank-name parties are
    skipped.
    """
    out: list[dict] = []
    allowed = set(name_types)
    for party in parties or []:
        if not isinstance(party, dict):
            continue
        if party.get("name_type") not in allowed:
            continue
        name = (party.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "name_type": party.get("name_type"),
            "raw_role": party.get("raw_role"),
        })
    return out


def _extract_divorce_award_target(document_body_text: Optional[str]) -> Optional[str]:
    """Extract the name a divorce decree clearly awards / orders / vests the
    property in (Rule 6 — multi_owner_status MULTIPLE_OWNERS_PRIMARY_CLEAR).

    The extractor is a deterministic labelled-field scan over
    `_DIVORCE_AWARD_LABELS`. It returns the candidate name string (cleaned),
    or None when no recognised award label is present — keeping the record
    MULTIPLE_OWNERS_PRIMARY_UNCLEAR. Ownership priority is NEVER guessed.
    """
    if not isinstance(document_body_text, str) or not document_body_text.strip():
        return None
    text = document_body_text
    for label in _DIVORCE_AWARD_LABELS:
        pattern = re.compile(
            r"\b" + re.escape(label).replace(r"\ ", r"\s+")
            + r"\b\s*[:\-]?\s*([^\n;\.]+)",
            re.IGNORECASE,
        )
        match = pattern.search(text)
        if match:
            value = _clean_extracted_name(match.group(1))
            if value:
                return value
    return None


def _match_spouse_by_award(
    award_target: str, spouses: list[dict]
) -> Optional[dict]:
    """Return the spouse entry whose name overlaps the award-target string.

    Matching is case-insensitive and works on whichever direction is longer —
    either the spouse name appears in the award string, or the award string
    appears in the spouse name. This tolerates "MARY DOE" vs "DOE, MARY" and
    "MARY M DOE" vs "MARY DOE". When two spouses both overlap (e.g. partial
    last-name collision), no match is returned and the record falls to
    MULTIPLE_OWNERS_PRIMARY_UNCLEAR rather than guess.
    """
    award_u = award_target.upper()
    matches: list[dict] = []
    for spouse in spouses:
        name_u = (spouse.get("name") or "").upper()
        if not name_u:
            continue
        if award_u in name_u or name_u in award_u:
            matches.append(spouse)
        else:
            # Try token-set overlap on rough family-name fragments
            tokens_award = {t for t in re.split(r"[\s,]+", award_u) if len(t) > 2}
            tokens_name = {t for t in re.split(r"[\s,]+", name_u) if len(t) > 2}
            if tokens_award and tokens_name and tokens_award.issubset(tokens_name):
                matches.append(spouse)
    if len(matches) == 1:
        return matches[0]
    return None


def _build_divorce_multi_owner_record(
    raw_event: dict,
    *,
    spouses: list[dict],
    primary_name: Optional[str],
    filer_entity: Optional[str],
) -> dict:
    """Build a Rule-6 divorce debtor-resolved record from a list of spouses.

    `primary_name` is the spouse the engine resolved as primary (case-
    insensitive match against one of `spouses["name"]`); when None, both
    spouses are preserved with `is_primary` False, multi_owner_status
    MULTIPLE_OWNERS_PRIMARY_UNCLEAR, and debtor_resolution_status
    REVIEW_REQUIRED — the schema's allOf consistency rules enforce the
    no-contradiction guarantee.
    """
    doc_type = raw_event.get("canonical_doc_type") or "unknown_doc_type"
    placeholder = _PLACEHOLDER.format(doc_type=doc_type)
    record = _carry_forward(raw_event)

    primary_clear = primary_name is not None
    owners: list[dict] = []
    primary_owner = None
    additional: list[str] = []
    for spouse in spouses:
        is_primary = primary_clear and (
            spouse.get("name", "").upper() == primary_name.upper()
        )
        owners.append({
            "name": spouse.get("name"),
            "role": "spouse",
            "name_type": spouse.get("name_type"),
            "is_primary": is_primary,
            "confidence": None,
            "source_field": spouse.get("name_type"),
            "resolution_status": (
                "RESOLVED" if primary_clear else "REVIEW_REQUIRED"
            ),
            "notes": None,
        })
        if is_primary:
            primary_owner = spouse.get("name")
        else:
            additional.append(spouse.get("name"))

    if primary_clear and primary_owner is not None:
        owner_name = primary_owner
        owner_type = classify_owner_type(owner_name)
        debtor_resolution_status = "RESOLVED"
        review_reason: Optional[str] = None
        extraction_method = "STRUCTURED_NAME_TYPE"
        multi_owner_status = "MULTIPLE_OWNERS_PRIMARY_CLEAR"
        primary_owner_name: Optional[str] = primary_owner
        expected_name_type: Optional[str] = "PL"
    else:
        # Ownership priority is never invented — the placeholder owner_name
        # is the §17.E unidentified-party placeholder; primary_owner_name
        # mirrors it (Session 7A contract). additional_owner_names lists
        # every preserved spouse, so co-owners are never dropped.
        owner_name = placeholder
        owner_type = "UNKNOWN"
        debtor_resolution_status = "REVIEW_REQUIRED"
        review_reason = "divorce_primary_owner_unclear"
        extraction_method = "REVIEW_ROUTED"
        multi_owner_status = "MULTIPLE_OWNERS_PRIMARY_UNCLEAR"
        primary_owner_name = placeholder
        additional = [s.get("name") for s in spouses if s.get("name")]
        expected_name_type = None

    record.update({
        "owner_name": owner_name,
        "owner_type": owner_type,
        "filer_entity": filer_entity,
        "debtor_resolution_status": debtor_resolution_status,
        "review_reason": review_reason,
        "expected_debtor_name_type": expected_name_type,
        "debtor_extraction_method": extraction_method,
        "owners": owners,
        "primary_owner_name": primary_owner_name,
        "additional_owner_names": additional,
        "owner_count": len(owners),
        "multi_owner_status": multi_owner_status,
    })
    return record


def _resolve_divorce_multi_owner(
    raw_event: dict,
    *,
    rule: dict,
    filer_entity: Optional[str],
    additional_suppressions: tuple[str, ...] = (),
) -> dict:
    """Resolve a Rule 6 divorce record into a multi-owner debtor-resolved record.

    The contract (Rule 6 / Session 7A):

      1. Gather every PL / DF / GR-tagged spouse party into a list.
      2. With NO spouses on the record → REVIEW_REQUIRED
         "owner_not_on_document" (document-only resolution; §17 never
         attempts parcel / assessor / tax-roll resolution).
      3. With exactly ONE spouse → resolve them as a SINGLE_OWNER record
         (the document only carries one spouse; nothing to dispute).
      4. With TWO+ spouses → scan `document_body_text` for an award label
         (AWARDED TO / ORDERED TO SELL BY / TRANSFERRED TO / VESTED IN /
         OBLIGATED TO / SOLE OWNERSHIP TO). When a recognised label matches
         exactly one of the spouses, mark that spouse `is_primary` →
         MULTIPLE_OWNERS_PRIMARY_CLEAR. Otherwise both spouses are
         preserved with no `is_primary` → MULTIPLE_OWNERS_PRIMARY_UNCLEAR
         and debtor_resolution_status REVIEW_REQUIRED.
      5. A spouse-name that matches a known-filer pattern (§17.D) — e.g.
         a "LAW FIRM" appearing as a PL — is suppressed from the owners[]
         list before the spouse-count branch.
    """
    parties = raw_event.get("parties") or []
    spouses_raw = _all_party_names(parties, _DIVORCE_SPOUSE_NAME_TYPES)
    # Suppress §17.D-flagged candidates from the owners[] list — a law firm or
    # court entity is never an owner. additional_suppressions layer on top.
    spouses: list[dict] = []
    for spouse in spouses_raw:
        if match_known_filer(
            spouse.get("name") or "",
            additional_suppressions=additional_suppressions,
        ):
            continue
        spouses.append(spouse)

    if len(spouses) == 0:
        return route_to_review(
            raw_event,
            review_reason=(
                rule.get("missing_debtor_review_reason")
                or "owner_not_on_document"
            ),
            filer_entity=filer_entity,
        )

    if len(spouses) == 1:
        # One spouse on the record → SINGLE_OWNER resolution.
        only = spouses[0]
        return _build_resolved(
            raw_event,
            owner_name=only.get("name"),
            filer_entity=filer_entity,
            method="STRUCTURED_NAME_TYPE",
            expected_name_type=only.get("name_type"),
        )

    award_target = _extract_divorce_award_target(
        raw_event.get("document_body_text")
    )
    primary_spouse = None
    if award_target:
        primary_spouse = _match_spouse_by_award(award_target, spouses)

    return _build_divorce_multi_owner_record(
        raw_event,
        spouses=spouses,
        primary_name=primary_spouse.get("name") if primary_spouse else None,
        filer_entity=filer_entity,
    )
