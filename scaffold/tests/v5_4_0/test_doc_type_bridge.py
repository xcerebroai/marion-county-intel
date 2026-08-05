#!/usr/bin/env python3
"""v5.4.0 Session 8 unit tests — the doc-type bridge.

Wired into run_all.py via scaffold/tests/v5_4_0/. Exercises three things:

  1. The 3 plural-key fixes — administrator_deed → administrators_deed,
     executor_deed → executors_deed, mechanic_lien → mechanics_lien — are
     present as §17 rule rows and the obsolete singular keys are gone.
  2. The 7 §17 broad-key reconciliations — abstract_of_judgment,
     administrative_lien, civil_judgment, code_lien, foreclosure_notice,
     probate, trustee_sale — fire on every registry doc type they fan out
     onto. The fan-out is non-empty for the 5 broad keys with finer-grained
     registry equivalents; intentionally empty for civil_judgment (whose
     judgment_lien target is already provided by abstract_of_judgment's
     fan-out) and administrative_lien (a broad bucket whose children carry
     their own §17 rules).
  3. The bridge artifact (scaffold/pipeline/doc_type_bridge.py) — totality
     over normalize.py's output, determinism, the registry → §16 lead_type
     mapping coverage, and the bridge end-to-end composition.

Run: python3 scaffold/tests/v5_4_0/test_doc_type_bridge.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.pipeline import debtor_party_engine as engine
from scaffold.pipeline import doc_type_bridge as bridge
from scaffold.pipeline import normalize


def _party(name: str, name_type: str) -> dict:
    return {"name": name, "name_type": name_type, "raw_role": name_type}


def _raw_event(doc_type, *, parties=None, document_body_text=None,
               property_refs=None) -> dict:
    """A minimal schema-valid raw_event_record for one canonical doc type."""
    return {
        "raw_event_id": f"raw_{doc_type}_0001",
        "source_id": "bridge_unit_test",
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
            "parcel_id": "PARCEL-EX",
            "situs_address": "100 EXAMPLE WAY",
            "legal_description": None,
            "case_number": None,
        },
        "amounts": [],
        "evidence_ids": [f"ev_{doc_type}_0001"],
        "parser_name": "bridge_unit_test",
        "parser_version": "1.0.0",
        "parser_confidence": 90,
        "captured_at": "2026-04-05T12:00:00Z",
    }


DEBTOR = "DOE, MARGARET R"

# Fan-out cases: (broad_key, alias_registry_key, debtor_name_type | None for
# document-body extraction).
STRUCTURED_FAN_OUT = [
    ("abstract_of_judgment", "judgment_lien", "DF"),
    ("code_lien", "code_violation_notice", "TP"),
    ("code_lien", "municipal_lien", "TP"),
]
BODY_FAN_OUT = [
    ("foreclosure_notice", "notice_of_sale",
     "NOTICE OF FORECLOSURE SALE\nMORTGAGOR: DOE, MARGARET R\n"),
    ("foreclosure_notice", "notice_of_default",
     "NOTICE OF DEFAULT\nDEBTOR: DOE, MARGARET R\n"),
    ("foreclosure_notice", "notice_of_substitute_trustee_sale",
     "NOTICE OF SUBSTITUTE TRUSTEE'S SALE\nMORTGAGOR: DOE, MARGARET R\n"),
    ("foreclosure_notice", "final_judgment_of_foreclosure",
     "FINAL JUDGMENT OF FORECLOSURE\nMORTGAGOR: DOE, MARGARET R\n"),
    ("foreclosure_notice", "appointment_of_substitute_trustee",
     "APPOINTMENT OF SUBSTITUTE TRUSTEE\nMORTGAGOR: DOE, MARGARET R\n"),
    ("trustee_sale", "trustees_deed_upon_sale",
     "TRUSTEE'S DEED UPON SALE\nGRANTOR: DOE, MARGARET R\n"),
    ("probate", "letters_testamentary",
     "ESTATE OF MARGARET R DOE"),
    ("probate", "letters_of_administration",
     "ESTATE OF MARGARET R DOE"),
    ("probate", "determination_of_heirship",
     "ESTATE OF MARGARET R DOE"),
    ("probate", "muniment_of_title",
     "ESTATE OF MARGARET R DOE"),
]


def main() -> int:
    checks: list[tuple[str, bool]] = []

    def check(desc: str, ok: bool) -> None:
        checks.append((desc, bool(ok)))

    # =======================================================================
    # Part 1 — the 3 plural-key fixes.
    # =======================================================================
    rules = engine.UNIVERSAL_DEBTOR_PARTY_RULES
    for new_key, old_key in [
        ("administrators_deed", "administrator_deed"),
        ("executors_deed", "executor_deed"),
        ("mechanics_lien", "mechanic_lien"),
    ]:
        check(f"§17 plural-key fix: `{new_key}` is registered "
              f"(matches the canonical_doc_types.json registry name)",
              new_key in rules)
        check(f"§17 plural-key fix: obsolete singular key `{old_key}` is GONE "
              f"(prevents a stale-name regression)",
              old_key not in rules)

    # Each renamed key resolves a real debtor on a sample raw event.
    for new_key in ("administrators_deed", "executors_deed", "mechanics_lien"):
        rule = rules.get(new_key)
        nt = rule.get("expected_debtor_name_type") if rule else None
        out = engine.resolve_debtor_party(
            _raw_event(new_key, parties=[_party(DEBTOR, nt)]),
        )
        check(f"§17 plural-key fix: `{new_key}` resolves to the real debtor "
              f"(name_type {nt})",
              out.get("debtor_resolution_status") == "RESOLVED"
              and DEBTOR in str(out.get("owner_name", "")))

    # =======================================================================
    # Part 2 — the 7 §17 broad-key reconciliations.
    # =======================================================================
    # The 7 broad keys are all still present (backward-compatible aliases).
    broad_keys = (
        "abstract_of_judgment", "administrative_lien", "civil_judgment",
        "code_lien", "foreclosure_notice", "probate", "trustee_sale",
    )
    for broad_key in broad_keys:
        check(f"§17 broad key `{broad_key}` retained as a backward-compat "
              f"rule row", broad_key in rules)

    # BROAD_KEY_REGISTRY_ALIASES covers all 7 broad keys, with the
    # documented empty-tuple entries for civil_judgment and administrative_lien.
    aliases = engine.BROAD_KEY_REGISTRY_ALIASES
    check("BROAD_KEY_REGISTRY_ALIASES enumerates exactly the 7 broad keys",
          set(aliases.keys()) == set(broad_keys))
    check("administrative_lien is intentionally empty in the fan-out "
          "(broad bucket — children federal_tax_lien / state_tax_lien / "
          "municipal_lien each carry their own §17 rule)",
          aliases["administrative_lien"] == ())
    check("civil_judgment is intentionally empty in the fan-out "
          "(judgment_lien is already provided by abstract_of_judgment)",
          aliases["civil_judgment"] == ())

    # Every fan-out alias key exists in the registry (the lowercased
    # canonical_doc_types.json registry — the staged engine's namespace).
    for broad_key, alias_keys in aliases.items():
        for alias in alias_keys:
            check(f"fan-out: `{alias}` (from broad `{broad_key}`) is a real "
                  f"registry-aligned canonical_doc_type",
                  alias in bridge.REGISTRY_LOWER_KEYS)
            check(f"fan-out: `{alias}` (from broad `{broad_key}`) is "
                  f"registered as a §17 rule row",
                  alias in rules)

    # STRUCTURED fan-outs RESOLVE on a sample raw event.
    for broad_key, alias, nt in STRUCTURED_FAN_OUT:
        out = engine.resolve_debtor_party(
            _raw_event(alias, parties=[_party(DEBTOR, nt)]),
        )
        check(f"§17 fan-out: `{alias}` (from `{broad_key}`) RESOLVES the "
              f"{nt} party as the lead debtor",
              out.get("debtor_resolution_status") == "RESOLVED"
              and DEBTOR in str(out.get("owner_name", "")))

    # DOCUMENT_BODY fan-outs RESOLVE on a sample raw event with body text.
    for broad_key, alias, body in BODY_FAN_OUT:
        out = engine.resolve_debtor_party(
            _raw_event(alias, document_body_text=body),
        )
        ok = (out.get("debtor_resolution_status") == "RESOLVED"
              and "DOE" in str(out.get("owner_name", "")).upper())
        check(f"§17 fan-out: `{alias}` (from `{broad_key}`) RESOLVES via "
              f"document-body extraction", ok)

    # =======================================================================
    # Part 3 — the bridge artifact: totality, determinism, mapping coverage.
    # =======================================================================

    # Layer 1 — every UPPERCASE registry key bridges to its lowercase form.
    check("bridge layer 1: every UPPERCASE registry key maps to its "
          "lowercased registry equivalent",
          all(bridge.monolith_to_registry(k) == k.lower()
              for k in bridge.REGISTRY_UPPER_KEYS))

    # Layer 1 — the bridge is total over normalize.py's output. The monolith's
    # normalize_doc_type emits exactly REGISTRY_UPPER_KEYS (verified by
    # introspecting _BY_KEY); the bridge accepts every one of them.
    monolith_outputs = set(normalize._BY_KEY.values())
    bridge_accepts = {
        m for m in monolith_outputs if bridge.monolith_to_registry(m) is not None
    }
    check("bridge totality: every normalize.py UPPERCASE output bridges to a "
          "registry-aligned canonical_doc_type (no monolith output dropped)",
          bridge_accepts == monolith_outputs)

    # Layer 1 — unknown inputs map to None (no silent invention).
    check("bridge layer 1: an unknown input maps to None "
          "(no fuzzy fallback)",
          bridge.monolith_to_registry("NOT_A_REAL_DOC_TYPE_0001") is None
          and bridge.monolith_to_registry(None) is None
          and bridge.monolith_to_registry("") is None)

    # Determinism — the bridge is a static mapping; repeated calls are equal.
    sample_inputs = [
        "TAX_DEED", "EVICTION_FILING", "BANKRUPTCY_PETITION",
        "HOSPITAL_LIEN", "NOT_REAL_X",
    ]
    for s in sample_inputs:
        first = bridge.monolith_to_registry(s)
        second = bridge.monolith_to_registry(s)
        third = bridge.monolith_to_registry(s)
        check(f"bridge determinism: monolith_to_registry({s!r}) returns the "
              f"same value across three calls",
              first == second == third)

    # Layer 2 — REGISTRY_TO_LEAD_TYPE covers every registry key.
    missing_from_bridge = (
        bridge.REGISTRY_LOWER_KEYS - set(bridge.REGISTRY_TO_LEAD_TYPE.keys())
    )
    check("bridge layer 2 totality: every registry doc type appears in "
          "REGISTRY_TO_LEAD_TYPE (either with a §16 lead_type or None)",
          not missing_from_bridge)

    # Every None-valued registry key has a documented reason.
    none_keys = {
        k for k, v in bridge.REGISTRY_TO_LEAD_TYPE.items() if v is None
    }
    unexplained_none = none_keys - set(
        bridge.REGISTRY_WITHOUT_LEAD_TYPE_REASONS.keys()
    )
    check("bridge gap-log totality: every registry doc type bridged to None "
          "has a documented reason in REGISTRY_WITHOUT_LEAD_TYPE_REASONS",
          not unexplained_none)

    # Every §16 Title-Case lead type appearing in REGISTRY_TO_LEAD_TYPE values
    # is one of the 27 canonical §16 lead types (no typos / no extras).
    bridged_lead_types = {
        v for v in bridge.REGISTRY_TO_LEAD_TYPE.values() if v is not None
    }
    extra_lead_types = bridged_lead_types - set(bridge.LEAD_TYPES_16)
    check("bridge §16 alignment: every bridged §16 lead_type value is one of "
          "the 27 canonical §16 lead types",
          not extra_lead_types)

    # §16 lead types without a registry mapping are explained (Tax Delinquency
    # in LEAD_TYPES_WITHOUT_REGISTRY_REASONS; Abstract of Judgment in
    # LEAD_TYPES_SHARED_REGISTRY_MAPPING).
    without = set(bridge.LEAD_TYPES_16) - bridged_lead_types
    explained = (
        set(bridge.LEAD_TYPES_WITHOUT_REGISTRY_REASONS.keys())
        | set(bridge.LEAD_TYPES_SHARED_REGISTRY_MAPPING.keys())
    )
    unexplained_lead = without - explained
    check("bridge gap-log totality: every §16 lead type with no direct "
          "registry mapping is documented (Tax Delinquency / Abstract of "
          "Judgment shared via judgment_lien)",
          not unexplained_lead)

    # Layer 3 — the bridge composes end-to-end.
    end_to_end_cases = [
        ("EVICTION_FILING", "Eviction"),
        ("BANKRUPTCY_PETITION", "Bankruptcy"),
        ("TAX_DEED", "Tax Sale"),
        ("SHERIFF_SALE_SURPLUS", "Surplus"),
        ("EXECUTORS_DEED", "Executor Deed"),
        ("ADMINISTRATORS_DEED", "Administrator Deed"),
        ("MECHANICS_LIEN", "Mechanic Lien"),
        # Registry types intentionally without a §16 lead type → None.
        ("HOSPITAL_LIEN", None),
        ("MORTGAGE", None),
        ("RECONVEYANCE", None),
    ]
    for monolith_value, expected_lead_type in end_to_end_cases:
        got = bridge.lead_type_for_monolith_output(monolith_value)
        check(f"bridge end-to-end: {monolith_value!r} → §16 lead_type "
              f"{expected_lead_type!r}", got == expected_lead_type)

    # The totality report itself is structured and free of unmapped values.
    report = bridge.bridge_totality_report()
    check("bridge_totality_report: registry_missing_from_bridge is empty",
          report["registry_missing_from_bridge"] == [])
    check("bridge_totality_report: registry_missing_reason is empty",
          report["registry_missing_reason"] == [])
    check("bridge_totality_report: lead_types_unexplained is empty",
          report["lead_types_unexplained"] == [])
    check("bridge_totality_report: registry_total == 74 (the registry size)",
          report["registry_total"] == 74)
    check("bridge_totality_report: lead_types_total == 27 (the §16 sweep size)",
          report["lead_types_total"] == 27)

    # registry_types_for_broad_key matches BROAD_KEY_REGISTRY_ALIASES.
    for broad_key in broad_keys:
        rts = bridge.registry_types_for_broad_key(broad_key)
        check(f"registry_types_for_broad_key({broad_key!r}) returns the "
              f"expected fan-out tuple",
              rts == tuple(engine.BROAD_KEY_REGISTRY_ALIASES[broad_key]))

    # --- report -------------------------------------------------------------
    failed = [d for d, ok in checks if not ok]
    for desc, ok in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {desc}")

    if failed:
        print(f"FAIL: doc-type bridge — {len(failed)} of {len(checks)} "
              f"checks failed")
        return 1

    print(f"PASS: doc-type bridge (v5.4.0 Session 8) — all {len(checks)} "
          f"checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
