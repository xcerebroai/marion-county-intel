#!/usr/bin/env python3
"""v5.4.0 unit tests — §17 debtor party engine.

Added in v5.4.0 Session 2; extended in v5.4.0 Session 7. Wired into run_all.py
via scaffold/tests/v5_4_0/. Exercises debtor_party_engine across the full §17
surface:

  - all 29 §17.C mapped doc types resolve to a real debtor (17 from Session 2
    plus the 12 Session-7 doc types: tax_deed, tax_foreclosure_notice,
    tax_sale_certificate, sheriff_sale_surplus, eviction_filing,
    writ_of_possession, divorce_filing, final_decree_of_divorce,
    marital_property_division, bankruptcy_petition, condemnation_notice,
    demolition_order);
  - the F-5 default rule routes an unmapped doc type to REVIEW_REQUIRED with
    review_reason "no_debtor_rule_for_doc_type";
  - the §17.F owner-type classifier across all 5 outputs;
  - the §17.D filer-suppression groups — the 7 Session-2 groups and the 9
    Session-7 groups added for the operator-supplied debtor rules.
  - the Session-7 document-only-resolution path: when a record carries only a
    parcel / address / case number / tenant — but no debtor — the engine
    routes to REVIEW_REQUIRED "owner_not_on_document" (§17 must NOT attempt
    parcel / assessor / tax-roll / GIS resolution; that is §13.14).
  - Rule 7 — bankruptcy: a petition with no real-property hook routes to
    REVIEW_REQUIRED "no_property_connection". The lead is NOT dropped.
  - Rule 6 — divorce: both spouses go in the multi-owner block. A clear
    awarded-to spouse → MULTIPLE_OWNERS_PRIMARY_CLEAR; otherwise
    MULTIPLE_OWNERS_PRIMARY_UNCLEAR + debtor_resolution_status REVIEW_REQUIRED.

Every resolve_debtor_party call self-validates its output against
debtor_resolved_record.schema.json (the engine raises ValueError on a
non-conforming record), so a clean return is also a schema-conformance check.

Run: python3 scaffold/tests/v5_4_0/test_debtor_party_engine_units.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.pipeline import debtor_party_engine as engine


def _party(name: str, name_type: str) -> dict:
    return {"name": name, "name_type": name_type, "raw_role": name_type}


def _raw_event(doc_type, *, parties=None, document_body_text=None,
               property_refs=None) -> dict:
    """Build a schema-complete raw_event_record for one canonical doc type."""
    return {
        "raw_event_id": f"raw_{doc_type}_0001",
        "source_id": "unit_test_source",
        "source_role": "PRIMARY_EVENT_SOURCE",
        "canonical_doc_type": doc_type,
        "raw_doc_type": doc_type.upper(),
        "instrument_number": f"INST-{doc_type}-0001",
        "recorded_date": "2026-04-01",
        "event_date": None,
        "source_url": f"https://example.test/{doc_type}/0001",
        "parties": parties or [],
        "document_body_text": document_body_text,
        "property_refs": property_refs or {
            "parcel_id": None,
            "situs_address": "100 EXAMPLE WAY",
            "legal_description": None,
            "case_number": None,
        },
        "amounts": [],
        "evidence_ids": [f"ev_{doc_type}_0001"],
        "parser_name": "unit_test",
        "parser_version": "1.0.0",
        "parser_confidence": 90,
        "captured_at": "2026-04-05T12:00:00Z",
    }


# A neutral individual debtor name — not a known filer, classifies INDIVIDUAL.
DEBTOR = "DOE, MARGARET R"

# §17.C STRUCTURED doc types: (doc_type, debtor name_type to tag the party).
# v5.4.0 Session 8 — three keys renamed to the plural / possessive registry
# forms (mechanic_lien → mechanics_lien, executor_deed → executors_deed,
# administrator_deed → administrators_deed). The rule logic is unchanged.
STRUCTURED_CASES = [
    ("hospital_lien", "TP"),
    ("code_lien", "TP"),
    ("administrative_lien", "TP"),
    ("federal_tax_lien", "TP"),
    ("state_tax_lien", "TP"),
    ("mechanics_lien", "GR"),
    ("construction_lien", "GR"),
    ("lis_pendens", "DF"),
    ("civil_judgment", "DF"),
    ("abstract_of_judgment", "DF"),
    ("executors_deed", "GR"),
    ("administrators_deed", "GR"),
    ("sheriff_sale", "DF"),
]

# v5.4.0 Session 7 — the 12 new registry doc types and the lead's NAME_TYPE.
# tax_deed / tax_foreclosure_notice / tax_sale_certificate / sheriff_sale_surplus
# → TP (the former owner / delinquent taxpayer / claimant entitled to surplus).
# eviction_filing / writ_of_possession → PL (the landlord / property owner).
# condemnation_notice / demolition_order → DF (the owner being acted against).
# bankruptcy_petition → TP (the bankruptcy debtor).
# The three divorce doc types use the multi-owner DIVORCE_MULTI_OWNER path,
# tested separately further down.
SESSION_7_STRUCTURED_CASES = [
    ("tax_deed", "TP"),
    ("tax_foreclosure_notice", "TP"),
    ("tax_sale_certificate", "TP"),
    ("sheriff_sale_surplus", "TP"),
    ("eviction_filing", "PL"),
    ("writ_of_possession", "PL"),
    ("condemnation_notice", "DF"),
    ("demolition_order", "DF"),
    ("bankruptcy_petition", "TP"),
]

SESSION_7_DIVORCE_TYPES = (
    "divorce_filing",
    "final_decree_of_divorce",
    "marital_property_division",
)

# §17.C DOCUMENT_BODY doc types: (doc_type, document body carrying the debtor).
BODY_CASES = [
    ("affidavit_of_heirship", "AFFIDAVIT OF HEIRSHIP\nDECEDENT: DOE, MARGARET R\n"),
    ("foreclosure_notice", "NOTICE OF FORECLOSURE SALE\nMORTGAGOR: DOE, MARGARET R\n"),
    ("trustee_sale", "NOTICE OF TRUSTEE'S SALE\nGRANTOR: DOE, MARGARET R\n"),
    ("probate", "IN THE ESTATE OF MARGARET R DOE\nPENDING IN PROBATE COURT\n"),
]

# (name, expected §17.F owner type).
OWNER_TYPE_CASES = [
    ("ACME HOLDINGS LLC", "ENTITY"),
    ("ESTATE OF JOHN DOE", "ESTATE"),
    ("DOE FAMILY TRUST", "TRUST"),
    ("DOE, JANE A", "INDIVIDUAL"),
    ("—", "UNKNOWN"),
]

# (name, §17.D group the match label must start with).
SUPPRESSION_CASES = [
    ("CITY OF EXAMPLE", "government_entity"),
    ("EXAMPLE COMPTROLLER", "state_agency"),
    ("EXAMPLE GENERAL HOSPITAL", "hospital_entity"),
    ("EXAMPLE MORTGAGE COMPANY", "mortgage_lender"),
    ("FREDDIE MAC", "federal_mortgage_agency"),
    ("NATIONSTAR", "servicer"),
    ("SUBSTITUTE TRUSTEE", "trustee"),
]


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    # --- structural: the §17.C table and §17.D groups -----------------------
    rules = engine.UNIVERSAL_DEBTOR_PARTY_RULES
    # v5.4.0 Session 8 added 13 registry-keyed fan-out rule rows on top of
    # Session 7's 29 (17 Session-2 + 12 Session-7), so the §17 table now
    # carries 42 keys. The fan-out is sourced from BROAD_KEY_REGISTRY_ALIASES
    # and is tested in detail by test_doc_type_bridge.py; here we pin the count
    # so a future row addition surfaces in the gate.
    check("§17.C UNIVERSAL_DEBTOR_PARTY_RULES covers 42 mapped doc types "
          "(17 from Session 2 + 12 from Session 7 + 13 from Session 8 "
          "broad-key → registry fan-out)",
          len(rules) == 42)
    check("§17.C table maps `probate` (Session 2 row 17)", "probate" in rules)
    # The 12 Session-7 registry doc types are all present.
    for new_doc_type in (
        "tax_deed", "tax_foreclosure_notice", "tax_sale_certificate",
        "sheriff_sale_surplus", "eviction_filing", "writ_of_possession",
        "divorce_filing", "final_decree_of_divorce",
        "marital_property_division", "bankruptcy_petition",
        "condemnation_notice", "demolition_order",
    ):
        check(f"§17.C maps Session-7 registry doc type `{new_doc_type}`",
              new_doc_type in rules)
    # tax_delinquency is deliberately NOT a §17 doc type — it is a tax-roll
    # status (enrichment), not a recorded document (§17.K).
    check("§17.C does NOT map `tax_delinquency` (tax-roll status, "
          "enrichment, not a recorded document — §17.K)",
          "tax_delinquency" not in rules)
    check("§17.D defines 16 filer-suppression groups "
          "(7 from Session 2 + 9 from Session 7)",
          len(engine._FILER_SUPPRESSION_PATTERNS) == 16)

    # --- the 17 §17.C mapped doc types resolve to a real debtor -------------
    for doc_type, name_type in STRUCTURED_CASES:
        try:
            out = engine.resolve_debtor_party(
                _raw_event(doc_type, parties=[_party(DEBTOR, name_type)])
            )
            ok = (out.get("debtor_resolution_status") == "RESOLVED"
                  and "DOE" in str(out.get("owner_name", "")).upper())
        except Exception as exc:  # noqa: BLE001 — surface engine errors as fails
            ok = False
            print(f"  (exception for {doc_type}: {exc})")
        check(f"§17.C {doc_type} → RESOLVED to the debtor", ok)

    for doc_type, body in BODY_CASES:
        try:
            out = engine.resolve_debtor_party(
                _raw_event(doc_type, document_body_text=body)
            )
            ok = (out.get("debtor_resolution_status") == "RESOLVED"
                  and "DOE" in str(out.get("owner_name", "")).upper())
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  (exception for {doc_type}: {exc})")
        check(f"§17.C {doc_type} (document-body) → RESOLVED to the debtor", ok)

    # --- F-5 default rule: an unmapped doc type routes to REVIEW_REQUIRED ----
    try:
        f5 = engine.resolve_debtor_party(_raw_event("tax_sale"))
        f5_ok = (
            f5.get("debtor_resolution_status") == "REVIEW_REQUIRED"
            and f5.get("review_reason") == "no_debtor_rule_for_doc_type"
            and f5.get("debtor_extraction_method") == "REVIEW_ROUTED"
            and "unidentified party" in str(f5.get("owner_name", "")).lower()
        )
    except Exception as exc:  # noqa: BLE001
        f5_ok = False
        print(f"  (exception for F-5 default: {exc})")
    check("F-5 default: unmapped `tax_sale` → REVIEW_REQUIRED, "
          "review_reason 'no_debtor_rule_for_doc_type'", f5_ok)

    # --- §17.F owner-type classification, all 5 outputs ---------------------
    for name, expected in OWNER_TYPE_CASES:
        got = engine.classify_owner_type(name)
        check(f"§17.F classify_owner_type({name!r}) == {expected}",
              got == expected)

    # --- §17.D filer suppression, all 7 groups ------------------------------
    for name, group in SUPPRESSION_CASES:
        label = engine.match_known_filer(name)
        check(f"§17.D match_known_filer({name!r}) → {group}",
              isinstance(label, str) and label.startswith(group))

    # an individual name is NOT flagged as a filer
    check("§17.D match_known_filer does not flag an individual name",
          engine.match_known_filer(DEBTOR) is None)

    # =======================================================================
    # v5.4.0 Session 7 — the 9 operator-supplied debtor rules, 12 doc types.
    # =======================================================================

    # --- Rule 1, 3, 4, 5, 8, 9 — the 8 STRUCTURED Session-7 doc types --------
    # (bankruptcy_petition is also STRUCTURED but has its own property-
    # connection branch; tested below.)
    for doc_type, lead_name_type in SESSION_7_STRUCTURED_CASES:
        try:
            out = engine.resolve_debtor_party(
                _raw_event(doc_type, parties=[_party(DEBTOR, lead_name_type)]),
            )
            ok = (out.get("debtor_resolution_status") == "RESOLVED"
                  and "DOE" in str(out.get("owner_name", "")).upper()
                  and out.get("expected_debtor_name_type") == lead_name_type)
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"  (exception for {doc_type}: {exc})")
        check(f"§17 Rule-Session-7 {doc_type} ({lead_name_type}) → RESOLVED "
              f"to the lead debtor", ok)

    # --- the document-only-resolution rule (§17.K): owner_not_on_document ----
    # For tax_foreclosure_notice / eviction_filing / writ_of_possession /
    # condemnation_notice / demolition_order, the owner is frequently NOT named
    # on the record. With no qualifying parties on the document, the engine
    # routes to REVIEW_REQUIRED "owner_not_on_document" — NOT a guess via
    # parcel / assessor / tax-roll resolution (that is §13.14, not §17).
    for doc_type in ("tax_foreclosure_notice", "eviction_filing",
                     "writ_of_possession", "condemnation_notice",
                     "demolition_order"):
        out = engine.resolve_debtor_party(
            _raw_event(doc_type, parties=[],
                       property_refs={
                           "parcel_id": "PARCEL-XYZ",
                           "situs_address": "100 EXAMPLE WAY",
                           "legal_description": None,
                           "case_number": "C-2026-0001",
                       }),
        )
        ok = (out.get("debtor_resolution_status") == "REVIEW_REQUIRED"
              and out.get("review_reason") == "owner_not_on_document"
              and "unidentified party" in str(out.get("owner_name", "")).lower())
        check(f"§17 document-only-resolution: {doc_type} with no debtor on "
              f"document → REVIEW_REQUIRED 'owner_not_on_document'", ok)

    # --- Rule 5 suppression coverage — a tenant-only eviction record routes --
    # An eviction with only the DF-tagged tenant party (no PL landlord) does
    # not pick the tenant — name_type selection excludes DF from the lead.
    out = engine.resolve_debtor_party(
        _raw_event("eviction_filing",
                   parties=[_party("DOE, JOHN", "DF")]),
    )
    check("§17 Rule 5 suppression: tenant-only eviction record routes to "
          "REVIEW_REQUIRED (the tenant is never the lead)",
          out.get("debtor_resolution_status") == "REVIEW_REQUIRED"
          and out.get("review_reason") == "owner_not_on_document"
          and "DOE, JOHN" not in str(out.get("owner_name", "")).upper())

    # --- Rule 1 suppression coverage — a tax deed whose only TP-party name is
    # the auction company / tax authority routes to REVIEW_REQUIRED.
    out = engine.resolve_debtor_party(
        _raw_event("tax_deed", parties=[_party("ACME AUCTION COMPANY", "TP")]),
    )
    check("§17 Rule 1 suppression: a §17.D 'auction company' candidate is "
          "never emitted as owner on a tax_deed",
          out.get("debtor_resolution_status") == "REVIEW_REQUIRED"
          and "AUCTION" not in str(out.get("owner_name", "")).upper())

    # --- Rule 8 suppression coverage — a condemnation DF that is the
    # condemning authority (transportation department) routes to REVIEW.
    out = engine.resolve_debtor_party(
        _raw_event("condemnation_notice",
                   parties=[_party("EXAMPLE TRANSPORTATION DEPARTMENT", "DF")]),
    )
    check("§17 Rule 8 suppression: a 'transportation department' candidate "
          "is never emitted as owner on a condemnation_notice",
          out.get("debtor_resolution_status") == "REVIEW_REQUIRED"
          and "TRANSPORTATION" not in str(out.get("owner_name", "")).upper())

    # --- Rule 9 suppression coverage — a demolition DF named "BUILDING
    # DEPARTMENT" routes to REVIEW.
    out = engine.resolve_debtor_party(
        _raw_event("demolition_order",
                   parties=[_party("EXAMPLE BUILDING DEPARTMENT", "DF")]),
    )
    check("§17 Rule 9 suppression: a 'building department' candidate is "
          "never emitted as owner on a demolition_order",
          out.get("debtor_resolution_status") == "REVIEW_REQUIRED"
          and "BUILDING DEPARTMENT" not in str(
              out.get("owner_name", "")).upper())

    # --- Rule 7 — bankruptcy 'no_property_connection' path ------------------
    # With a property identifier present, RESOLVE.
    bk_with_property = engine.resolve_debtor_party(
        _raw_event("bankruptcy_petition",
                   parties=[_party(DEBTOR, "TP")],
                   property_refs={
                       "parcel_id": "PARCEL-100",
                       "situs_address": None,
                       "legal_description": None,
                       "case_number": "BK-2026-0001",
                   }),
    )
    check("§17 Rule 7: bankruptcy_petition WITH a property connection "
          "resolves the TP debtor",
          bk_with_property.get("debtor_resolution_status") == "RESOLVED"
          and "DOE" in str(bk_with_property.get("owner_name", "")).upper())

    # Without parcel / situs / legal description (case_number alone is the BK
    # case, not a property identifier), route to REVIEW_REQUIRED with
    # review_reason "no_property_connection". The lead is NOT hard-excluded.
    bk_no_property = engine.resolve_debtor_party(
        _raw_event("bankruptcy_petition",
                   parties=[_party(DEBTOR, "TP")],
                   property_refs={
                       "parcel_id": None,
                       "situs_address": None,
                       "legal_description": None,
                       "case_number": "BK-2026-0002",
                   }),
    )
    check("§17 Rule 7: bankruptcy_petition with NO property connection "
          "routes to REVIEW_REQUIRED 'no_property_connection' (NOT dropped)",
          bk_no_property.get("debtor_resolution_status") == "REVIEW_REQUIRED"
          and bk_no_property.get("review_reason") == "no_property_connection"
          and isinstance(bk_no_property, dict))

    # An entity-debtor bankruptcy with property connection classifies ENTITY.
    bk_entity = engine.resolve_debtor_party(
        _raw_event("bankruptcy_petition",
                   parties=[_party("ACME HOLDINGS LLC", "TP")],
                   property_refs={
                       "parcel_id": "PARCEL-200",
                       "situs_address": None,
                       "legal_description": None,
                       "case_number": "BK-2026-0003",
                   }),
    )
    check("§17 Rule 7: business-debtor bankruptcy resolves to the entity "
          "(owner_type ENTITY)",
          bk_entity.get("debtor_resolution_status") == "RESOLVED"
          and bk_entity.get("owner_type") == "ENTITY")

    # --- Rule 6 — divorce multi-owner: PRIMARY_UNCLEAR -----------------------
    # Two spouses on the decree but no award language → both preserved, none
    # is_primary, multi_owner_status MULTIPLE_OWNERS_PRIMARY_UNCLEAR, and the
    # debtor_resolution_status verdict field is independently REVIEW_REQUIRED
    # — the Session 7A no-contradiction guarantee.
    for doc_type in SESSION_7_DIVORCE_TYPES:
        out = engine.resolve_debtor_party(
            _raw_event(doc_type, parties=[
                _party("DOE, MARY", "PL"),
                _party("DOE, JOHN", "DF"),
            ]),
        )
        owners = out.get("owners") or []
        ok = (out.get("multi_owner_status") == "MULTIPLE_OWNERS_PRIMARY_UNCLEAR"
              and out.get("debtor_resolution_status") == "REVIEW_REQUIRED"
              and len(owners) == 2
              and out.get("owner_count") == 2
              and not any(o.get("is_primary") for o in owners)
              and "unidentified party" in str(out.get("owner_name", "")).lower())
        check(f"§17 Rule 6: {doc_type} with two spouses + no award language → "
              f"MULTIPLE_OWNERS_PRIMARY_UNCLEAR + REVIEW_REQUIRED, both "
              f"spouses preserved (co-owners never dropped)", ok)

    # --- Rule 6 — divorce multi-owner: PRIMARY_CLEAR -------------------------
    # The decree clearly awards the property to one spouse — that spouse is
    # is_primary; multi_owner_status MULTIPLE_OWNERS_PRIMARY_CLEAR; the
    # debtor_resolution_status verdict is RESOLVED.
    out = engine.resolve_debtor_party(
        _raw_event("final_decree_of_divorce",
                   parties=[
                       _party("DOE, MARY", "PL"),
                       _party("DOE, JOHN", "DF"),
                   ],
                   document_body_text=(
                       "IT IS THEREFORE ORDERED THAT THE MARITAL HOMESTEAD "
                       "BE AWARDED TO DOE, MARY AS HER SOLE AND SEPARATE "
                       "PROPERTY.")),
    )
    owners = out.get("owners") or []
    primary_owners = [o for o in owners if o.get("is_primary")]
    check("§17 Rule 6: decree awarding the homestead to one spouse → "
          "MULTIPLE_OWNERS_PRIMARY_CLEAR, that spouse is_primary",
          out.get("multi_owner_status") == "MULTIPLE_OWNERS_PRIMARY_CLEAR"
          and out.get("debtor_resolution_status") == "RESOLVED"
          and len(primary_owners) == 1
          and primary_owners[0].get("name") == "DOE, MARY"
          and out.get("primary_owner_name") == "DOE, MARY"
          and out.get("owner_name") == "DOE, MARY")

    # --- Rule 6 — divorce with NO spouses on the document --------------------
    out = engine.resolve_debtor_party(
        _raw_event("divorce_filing", parties=[]),
    )
    check("§17 Rule 6: divorce with no spouses on the document → "
          "REVIEW_REQUIRED 'owner_not_on_document'",
          out.get("debtor_resolution_status") == "REVIEW_REQUIRED"
          and out.get("review_reason") == "owner_not_on_document")

    # --- §17.F owner-type classification across the Session-7 doc types -----
    # An LLC tax-deed lead (delinquent corporate owner) is ENTITY.
    ent = engine.resolve_debtor_party(
        _raw_event("tax_deed",
                   parties=[_party("ACME HOLDINGS LLC", "TP")]),
    )
    check("§17.F: tax_deed with an LLC delinquent-owner debtor → ENTITY",
          ent.get("owner_type") == "ENTITY")
    # An estate-titled property under demolition is ESTATE.
    est = engine.resolve_debtor_party(
        _raw_event("demolition_order",
                   parties=[_party("ESTATE OF HAROLD DOE", "DF")]),
    )
    check("§17.F: demolition_order with an estate debtor → ESTATE",
          est.get("owner_type") == "ESTATE")

    # --- §17.D Session-7 suppression groups: each has a recognisable pattern -
    SESSION_7_SUPPRESSION_PROBES = [
        ("ACME TAX COLLECTOR", "tax_authority"),
        ("ACME AUCTION COMPANY", "auction_party"),
        ("SMITH LAW FIRM", "law_firm"),
        ("EXAMPLE MUNICIPAL COURT", "court_role"),
        ("CONSTABLE", "law_enforcement"),
        ("SURPLUS RECOVERY GROUP", "surplus_recovery"),
        ("U.S. TRUSTEE", "bankruptcy_official"),
        ("EXAMPLE BUILDING DEPARTMENT", "code_enforcement_role"),
        ("EXAMPLE PROPERTY MANAGEMENT GROUP", "property_manager"),
    ]
    for name, group in SESSION_7_SUPPRESSION_PROBES:
        label = engine.match_known_filer(name)
        check(f"§17.D Session-7 group `{group}` flags {name!r}",
              isinstance(label, str) and label.startswith(group))

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: §17 debtor party engine unit tests — "
              f"{len(failed)} of {len(checks)} checks failed")
        return 1

    print(f"PASS: §17 debtor party engine unit tests — "
          f"all {len(checks)} checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
