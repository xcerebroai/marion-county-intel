"""
Gate test for scaffold/pipeline/translators/ registry (v5.1.2-beta-r3+).

Verifies:
  - Built-in translators register at import time and are looked up by name.
  - register() refuses duplicate registration without force=True.
  - lookup() raises TranslatorNotFound for unknown names.
  - Each built-in translator returns a (signals, parcels, meta) tuple
    even on empty / malformed input (defensive shape).
  - The foreclosure_notices translator honors the cross-county-leak
    policy from county config (accepted_municipalities + unknown_city_action).
  - The foreclosure_notices translator dispatches to the named
    sale_date_rule from county config.
  - The parcel_master translator consumes normalized raw_payload with
    pre-parsed exempt_* booleans OR falls back to legacy string parsing.
  - The csv_static_list translator maps per-source doc_type_synonyms.
  - (r3) Both foreclosure_notices and parcel_master translators honor
    source_config.field_map for bridging non-canonical scraper field
    names to canonical names. Partial field_map (only some keys mapped,
    others default to identity) works correctly. This is a UNIVERSAL
    translator feature — the same pattern applies to all future
    translators (clerk_recordings, tax_collector, court, etc.).

CONTRACT (v5.1.2-beta-r2+): Translators consume the framework-canonical
WRAPPED RAW RECORD shape (MASTER_PROMPT §4.32):

    {
        "raw_record_id": "...",
        "source_id": "...",
        "source_url": "...",
        "raw_payload": {<normalized scraper-output fields, lowercase
                        framework-canonical names OR scraper-specific
                        names bridged via source_config.field_map>}
    }

Translators DO NOT consume raw vendor protocol attributes (UPPERCASE
REST attrs, portal-specific field labels, etc.). The scraper normalizes
BEFORE writing JSONL. This test uses lowercase normalized keys throughout.

Synthetic data only. No real county names or vendor portals.
"""

from __future__ import annotations

import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
SCAFFOLD_DIR = THIS_DIR.parent
FRAMEWORK_ROOT = SCAFFOLD_DIR.parent
sys.path.insert(0, str(FRAMEWORK_ROOT))

from scaffold.pipeline import translators  # noqa: E402
from scaffold.pipeline.translators import (  # noqa: E402
    register,
    lookup,
    registered_names,
    unregister,
    TranslatorNotFound,
    TranslatorAlreadyRegistered,
)


PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def case(name: str, passed: bool, detail: str = "") -> None:
    status = PASS if passed else FAIL
    results.append((status, name, detail))
    print(f"  [{status}] {name}" + (f" — {detail}" if detail else ""))


def test_builtins_registered():
    print("\n[builtin translators register at import time]")
    names = registered_names()
    case("foreclosure_notices registered", "foreclosure_notices" in names)
    case("parcel_master registered", "parcel_master" in names)
    case("csv_static_list registered", "csv_static_list" in names)
    case(
        "old arcgis_ names NOT registered",
        "arcgis_foreclosure_notices" not in names
        and "arcgis_parcel_master" not in names,
    )


def test_lookup_returns_callable():
    print("\n[lookup returns callables]")
    fn = lookup("foreclosure_notices")
    case("lookup returns callable", callable(fn))


def test_lookup_unknown_raises():
    print("\n[lookup raises TranslatorNotFound]")
    raised = False
    try:
        lookup("does_not_exist_zzz")
    except TranslatorNotFound:
        raised = True
    case("TranslatorNotFound raised for unknown name", raised)


def test_register_refuses_duplicate():
    print("\n[register refuses duplicate without force=True]")
    raised = False
    try:
        @register("foreclosure_notices")
        def _bad(*a, **k):
            return [], [], {}
    except TranslatorAlreadyRegistered:
        raised = True
    case("duplicate registration raises", raised)


def test_register_force_overwrites():
    print("\n[register force=True overwrites]")
    marker = object()

    @register("test_temp_force_translator", force=True)
    def _stub(raw, cc, sc):
        return [marker], [], {}

    fn = lookup("test_temp_force_translator")
    out = fn([], {}, {})
    case("force=True registered new translator", out[0] == [marker])
    unregister("test_temp_force_translator")


def test_foreclosure_translator_empty():
    print("\n[foreclosure translator handles empty input]")
    fn = lookup("foreclosure_notices")
    sig, par, meta = fn([], {}, {})
    case("empty input returns ([], [], {})", sig == [] and par == [] and meta == {})


def test_foreclosure_translator_consumes_normalized_payload():
    print("\n[foreclosure translator reads NORMALIZED lowercase raw_payload]")
    fn = lookup("foreclosure_notices")
    raw = [{
        "raw_record_id": "raw_norm",
        "source_id": "foreclosure_notices",
        "raw_payload": {
            "address": "100 NORMAL ST",
            "doc_number": "DOC-N1",
            "recording_year": 2026,
            "recording_month": 6,
            "city": "ACCEPTEDTOWN",
            "zip": "00001",
            "layer_id": 0,
        },
        "source_url": "about:test/raw_norm",
        "parser_confidence": 95,
    }]
    county_config = {
        "geography": {
            "accepted_municipalities": [
                {"name": "ACCEPTEDTOWN", "kind": "incorporated"}
            ],
        }
    }
    source_config = {
        "translator": "foreclosure_notices",
        "translator_config": {
            "layer_doc_type_map": {
                "0": {
                    "canonical": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
                    "subtype_label": "NSTS",
                    "pattern": "foreclosure",
                }
            }
        },
        "parcel_id_prefix": "TST-",
    }
    sig, par, meta = fn(raw, county_config, source_config)
    case("normalized payload produces one signal", len(sig) == 1)
    case("normalized payload produces one parcel", len(par) == 1)
    if sig:
        case(
            "signal carries canonical doc_type",
            sig[0]["doc_type"] == "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
        )
    if par:
        case("parcel address preserved", par[0]["address"] == "100 NORMAL ST")


def test_foreclosure_translator_cross_county_drop():
    print("\n[foreclosure translator drops cross-county leaks when policy=drop]")
    fn = lookup("foreclosure_notices")
    raw = [{
        "raw_record_id": "raw_x",
        "raw_payload": {
            "address": "100 SYNTH ST",
            "doc_number": "DOC-001",
            "recording_year": 2026,
            "recording_month": 6,
            "city": "Anytown",
            "zip": "00000",
            "layer_id": 0,
        },
        "source_url": "about:test/raw_x",
        "parser_confidence": 95,
    }]
    county_config = {
        "geography": {
            "accepted_municipalities": [
                {"name": "OTHERCITY", "kind": "incorporated"}
            ],
            "cross_county_policy": {"unknown_city_action": "drop"},
        }
    }
    source_config = {
        "translator": "foreclosure_notices",
        "translator_config": {
            "layer_doc_type_map": {
                "0": {
                    "canonical": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
                    "subtype_label": "NSTS",
                    "pattern": "foreclosure",
                }
            }
        },
        "parcel_id_prefix": "TST-",
    }
    sig, par, meta = fn(raw, county_config, source_config)
    case("drop policy yields zero signals", len(sig) == 0)
    case("drop policy yields zero parcels", len(par) == 0)


def test_foreclosure_translator_cross_county_flag():
    print("\n[foreclosure translator flags cross-county leaks when policy=flag_for_review]")
    fn = lookup("foreclosure_notices")
    raw = [{
        "raw_record_id": "raw_y",
        "raw_payload": {
            "address": "200 SYNTH AVE",
            "doc_number": "DOC-002",
            "recording_year": 2026,
            "recording_month": 6,
            "city": "Outsidetown",
            "zip": "11111",
            "layer_id": 0,
        },
        "source_url": "about:test/raw_y",
        "parser_confidence": 95,
    }]
    county_config = {
        "geography": {
            "accepted_municipalities": [
                {"name": "OTHERCITY", "kind": "incorporated"}
            ],
            "cross_county_policy": {"unknown_city_action": "flag_for_review"},
        }
    }
    source_config = {
        "translator": "foreclosure_notices",
        "translator_config": {
            "layer_doc_type_map": {
                "0": {
                    "canonical": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
                    "subtype_label": "NSTS",
                    "pattern": "foreclosure",
                }
            }
        },
        "parcel_id_prefix": "TST-",
    }
    sig, par, meta = fn(raw, county_config, source_config)
    case("flag policy yields one signal", len(sig) == 1)
    case("flag policy yields one parcel", len(par) == 1)
    flags_seen = []
    for url, m in meta.items():
        flags_seen.extend(m.get("preset_review_flags", []))
    case(
        "potential_cross_county_leak flag set",
        "potential_cross_county_leak" in flags_seen,
    )


def test_foreclosure_translator_sale_date_rule():
    print("\n[foreclosure translator dispatches to sale_date_rule]")
    fn = lookup("foreclosure_notices")
    raw = [{
        "raw_record_id": "raw_z",
        "raw_payload": {
            "address": "300 SYNTH BLVD",
            "doc_number": "DOC-003",
            "recording_year": 2026,
            "recording_month": 7,
            "city": "ACCEPTEDTOWN",
            "zip": "22222",
            "layer_id": 0,
        },
        "source_url": "about:test/raw_z",
        "parser_confidence": 95,
    }]
    county_config = {
        "geography": {
            "accepted_municipalities": [
                {"name": "ACCEPTEDTOWN", "kind": "incorporated"}
            ],
            "sale_date_rule": {
                "rule_name": "first_tuesday_of_month",
                "holiday_shift": {
                    "shift_dates": ["07-04"],
                    "shift_to": "next_wednesday",
                },
            },
        }
    }
    source_config = {
        "translator": "foreclosure_notices",
        "translator_config": {
            "layer_doc_type_map": {
                "0": {
                    "canonical": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
                    "subtype_label": "NSTS",
                    "pattern": "foreclosure",
                }
            }
        },
        "parcel_id_prefix": "TST-",
    }
    sig, par, meta = fn(raw, county_config, source_config)
    case("signal produced", len(sig) == 1)
    if sig:
        case("filing_date populated", sig[0]["filing_date"] is not None)


def test_parcel_master_translator_normalized_booleans():
    print("\n[parcel_master translator consumes pre-parsed exempt_* booleans]")
    fn = lookup("parcel_master")
    raw = [{
        "raw_record_id": "p_norm",
        "source_id": "parcel_master",
        "raw_payload": {
            "parcel_id": "CAD-12345",
            "address": "300 SYNTH BLVD",
            "owner_name": "DOE JOHN",
            "city": "ACCEPTEDTOWN",
            "zip": "22222",
            "assessed_value": 250000,
            "land_value": 50000,
            "improvement_value": 200000,
            "year_built": 1995,
            "exempt_homestead": True,
            "exempt_over_65": True,
            "exempt_disabled": False,
            "exempt_veteran": False,
            "property_use": "A1",
            "acres": 0.15,
            "legal_description": "LOT 1 BLOCK 1",
        },
    }]
    source_config = {"translator": "parcel_master"}
    sig, par, meta = fn(raw, {}, source_config)
    case("returns no signals", len(sig) == 0)
    case("returns one parcel", len(par) == 1)
    if par:
        p = par[0]
        case("parcel_id preserved verbatim", p["parcel_id"] == "CAD-12345")
        case("address mapped", p["address"] == "300 SYNTH BLVD")
        case("owner_name mapped", p["owner_name"] == "DOE JOHN")
        case("homestead boolean preserved", p["exempt_homestead"] is True)
        case("over_65 boolean preserved", p["exempt_over_65"] is True)
        case("disabled boolean preserved", p["exempt_disabled"] is False)
        case("assessed_value parsed", p["assessed_value"] == 250000)
        case("year_built parsed", p["year_built"] == 1995)


def test_parcel_master_translator_legacy_exemption_string():
    print("\n[parcel_master translator falls back to legacy exemption-string parsing]")
    fn = lookup("parcel_master")
    raw = [{
        "raw_record_id": "p_legacy",
        "source_id": "parcel_master",
        "raw_payload": {
            "parcel_id": "CAD-LEGACY",
            "address": "400 LEGACY ST",
            "owner_name": "SMITH JANE",
            "exemptions": "HS, OV65",
            "assessed_value": 180000,
        },
    }]
    source_config = {
        "translator": "parcel_master",
        "translator_config": {
            "exemption_codes": {
                "homestead": ["HS"],
                "over_65": ["OV65", "O65"],
                "disabled": ["DV"],
                "veteran": ["VET"],
            }
        },
    }
    sig, par, meta = fn(raw, {}, source_config)
    case("returns one parcel via legacy path", len(par) == 1)
    if par:
        p = par[0]
        case(
            "legacy: homestead parsed from string",
            p["exempt_homestead"] is True,
        )
        case(
            "legacy: over_65 parsed from string",
            p["exempt_over_65"] is True,
        )
        case(
            "legacy: disabled not present in string",
            p["exempt_disabled"] is False,
        )


def test_parcel_master_translator_empty_parcel_id_skipped():
    print("\n[parcel_master translator skips records missing parcel_id]")
    fn = lookup("parcel_master")
    raw = [
        {"raw_record_id": "p_skip1", "raw_payload": {}},
        {"raw_record_id": "p_skip2", "raw_payload": {"parcel_id": ""}},
        {
            "raw_record_id": "p_ok",
            "raw_payload": {"parcel_id": "CAD-OK", "address": "1 X"},
        },
    ]
    sig, par, meta = fn(raw, {}, {"translator": "parcel_master"})
    case("two records with empty parcel_id skipped", len(par) == 1)
    if par:
        case("surviving parcel has correct id", par[0]["parcel_id"] == "CAD-OK")


def test_csv_static_list_doc_type_synonyms():
    print("\n[csv_static_list translator maps per-source doc_type_synonyms]")
    fn = lookup("csv_static_list")
    raw = [{
        "raw_record_id": "csv_1",
        "raw_payload": {
            "address": "500 LIST ST",
            "doc_num": "L-001",
            "doc_type": "tax sale",
            "filing_date": "2026-06-01",
        },
        "source_url": "about:test/csv_1",
        "parser_confidence": 80,
    }]
    source_config = {
        "translator": "csv_static_list",
        "translator_config": {
            "doc_number_field": "doc_num",
            "doc_type_synonyms": {
                "tax sale": "TAX_FORECLOSURE_NOTICE",
            }
        },
        "parcel_id_prefix": "CSV-",
    }
    sig, par, meta = fn(raw, {}, source_config)
    case("CSV translator produces signal", len(sig) == 1)
    if sig:
        case(
            "doc_type mapped from synonym",
            sig[0]["doc_type"] == "TAX_FORECLOSURE_NOTICE",
        )


def test_csv_static_list_unknown_doc_type_skipped():
    print("\n[csv_static_list skips records with unmapped doc-type]")
    fn = lookup("csv_static_list")
    raw = [{
        "raw_record_id": "csv_skip",
        "raw_payload": {
            "address": "600 LIST AVE",
            "doc_num": "L-002",
            "doc_type": "totally_unknown_type",
            "filing_date": "2026-06-01",
        },
        "source_url": "about:test/csv_skip",
        "parser_confidence": 80,
    }]
    source_config = {
        "translator": "csv_static_list",
        "translator_config": {
            "doc_type_synonyms": {"some other thing": "QUITCLAIM_DEED"}
        },
    }
    sig, par, meta = fn(raw, {}, source_config)
    case("unknown doc_type is skipped", len(sig) == 0)


def test_foreclosure_translator_field_map_bridges_non_canonical_names():
    print("\n[foreclosure translator: field_map bridges non-canonical scraper names (r3)]")
    fn = lookup("foreclosure_notices")
    # Scraper writes "situs_addr", "rec_doc", "rec_yr", "rec_mo" instead of
    # the canonical lowercase names. field_map bridges them.
    raw = [{
        "raw_record_id": "raw_fm",
        "raw_payload": {
            "situs_addr": "400 FIELDMAP DR",
            "rec_doc": "DOC-FM",
            "rec_yr": 2026,
            "rec_mo": 8,
            "situs_city": "ACCEPTEDTOWN",
            "situs_zip": "33333",
            "lyr": 0,
        },
        "source_url": "about:test/raw_fm",
        "parser_confidence": 95,
    }]
    county_config = {
        "geography": {
            "accepted_municipalities": [
                {"name": "ACCEPTEDTOWN", "kind": "incorporated"}
            ],
        }
    }
    source_config = {
        "translator": "foreclosure_notices",
        "translator_config": {
            "layer_doc_type_map": {
                "0": {
                    "canonical": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
                    "subtype_label": "NSTS",
                    "pattern": "foreclosure",
                }
            }
        },
        "field_map": {
            "address": "situs_addr",
            "doc_number": "rec_doc",
            "recording_year": "rec_yr",
            "recording_month": "rec_mo",
            "city": "situs_city",
            "zip": "situs_zip",
            "layer_id": "lyr",
        },
        "parcel_id_prefix": "TST-",
    }
    sig, par, meta = fn(raw, county_config, source_config)
    case("field_map bridges yields one signal", len(sig) == 1)
    case("field_map bridges yields one parcel", len(par) == 1)
    if par:
        case(
            "parcel address resolved via field_map",
            par[0]["address"] == "400 FIELDMAP DR",
        )


def test_foreclosure_translator_partial_field_map():
    print("\n[foreclosure translator: partial field_map uses identity for missing keys (r3)]")
    fn = lookup("foreclosure_notices")
    # Scraper writes 'situs_addr' but other fields are already canonical.
    raw = [{
        "raw_record_id": "raw_partial",
        "raw_payload": {
            "situs_addr": "500 PARTIAL ST",
            "doc_number": "DOC-PRT",
            "recording_year": 2026,
            "recording_month": 9,
            "city": "ACCEPTEDTOWN",
            "zip": "44444",
            "layer_id": 0,
        },
        "source_url": "about:test/raw_partial",
        "parser_confidence": 95,
    }]
    county_config = {
        "geography": {
            "accepted_municipalities": [
                {"name": "ACCEPTEDTOWN", "kind": "incorporated"}
            ],
        }
    }
    source_config = {
        "translator": "foreclosure_notices",
        "translator_config": {
            "layer_doc_type_map": {
                "0": {
                    "canonical": "NOTICE_OF_SUBSTITUTE_TRUSTEE_SALE",
                    "subtype_label": "NSTS",
                    "pattern": "foreclosure",
                }
            }
        },
        "field_map": {"address": "situs_addr"},
        "parcel_id_prefix": "TST-",
    }
    sig, par, meta = fn(raw, county_config, source_config)
    case("partial field_map yields one signal", len(sig) == 1)
    if par:
        case(
            "mapped field resolves",
            par[0]["address"] == "500 PARTIAL ST",
        )


def test_parcel_master_translator_field_map_bridges_non_canonical_names():
    print("\n[parcel_master translator: field_map bridges non-canonical scraper names (r3)]")
    fn = lookup("parcel_master")
    # Scraper writes situs_*/property_class instead of canonical names.
    raw = [{
        "raw_record_id": "p_fm",
        "source_id": "parcel_master",
        "raw_payload": {
            "parcel_id": "CAD-FM",
            "situs_address": "600 PARCELMAP CT",
            "situs_city": "BOERNE",
            "situs_zip": "78006",
            "owner_name": "FIELDMAP OWNER",
            "owner_mailing_addr1": "PO BOX 1",
            "owner_mailing_city": "AUSTIN",
            "owner_mailing_state": "ZZ",
            "owner_mailing_zip": "78701",
            "assessed_value": 300000,
            "land_value": 60000,
            "improvement_value": 240000,
            "year_built": 1985,
            "property_class": "A1",
            "acres": 0.25,
            "legal_description": "LOT 5 BLOCK 9",
            "exempt_homestead": True,
            "exempt_over_65": False,
            "exempt_disabled": False,
        },
    }]
    source_config = {
        "translator": "parcel_master",
        "field_map": {
            "address": "situs_address",
            "city": "situs_city",
            "zip": "situs_zip",
            "owner_mailing_address": "owner_mailing_addr1",
            "property_use": "property_class",
        },
    }
    sig, par, meta = fn(raw, {}, source_config)
    case("field_map bridges yields one parcel", len(par) == 1)
    if par:
        p = par[0]
        case("parcel_id preserved", p["parcel_id"] == "CAD-FM")
        case(
            "address resolved via field_map",
            p["address"] == "600 PARCELMAP CT",
        )
        case(
            "city resolved via field_map",
            p["city"] == "BOERNE",
        )
        case(
            "zip resolved via field_map",
            p["zip"] == "78006",
        )
        case(
            "owner_mailing_address resolved via field_map",
            p["owner_mailing_address"] == "PO BOX 1",
        )
        case(
            "property_use resolved via field_map",
            p["property_use"] == "A1",
        )
        case(
            "owner_name still resolves via identity (no field_map entry)",
            p["owner_name"] == "FIELDMAP OWNER",
        )
        case(
            "assessed_value parses correctly through identity",
            p["assessed_value"] == 300000,
        )
        case(
            "exempt_homestead boolean preserved",
            p["exempt_homestead"] is True,
        )


def test_parcel_master_translator_no_field_map_identity():
    print("\n[parcel_master translator: no field_map = identity mapping (r3 backward-compat)]")
    fn = lookup("parcel_master")
    # Scraper writes canonical names; no field_map needed.
    raw = [{
        "raw_record_id": "p_identity",
        "raw_payload": {
            "parcel_id": "CAD-ID",
            "address": "800 IDENTITY ST",
            "owner_name": "IDENTITY OWNER",
            "city": "ACCEPTEDTOWN",
            "exempt_homestead": True,
        },
    }]
    source_config = {"translator": "parcel_master"}
    sig, par, meta = fn(raw, {}, source_config)
    case("identity: one parcel produced", len(par) == 1)
    if par:
        case(
            "identity: address read directly without field_map",
            par[0]["address"] == "800 IDENTITY ST",
        )


def main() -> int:
    print("=" * 72)
    print("TRANSLATOR REGISTRY TEST — v5.1.2-beta-r3")
    print("=" * 72)
    test_builtins_registered()
    test_lookup_returns_callable()
    test_lookup_unknown_raises()
    test_register_refuses_duplicate()
    test_register_force_overwrites()
    test_foreclosure_translator_empty()
    test_foreclosure_translator_consumes_normalized_payload()
    test_foreclosure_translator_cross_county_drop()
    test_foreclosure_translator_cross_county_flag()
    test_foreclosure_translator_sale_date_rule()
    test_parcel_master_translator_normalized_booleans()
    test_parcel_master_translator_legacy_exemption_string()
    test_parcel_master_translator_empty_parcel_id_skipped()
    test_csv_static_list_doc_type_synonyms()
    test_csv_static_list_unknown_doc_type_skipped()
    # r3 additions: field_map support (universal translator feature)
    test_foreclosure_translator_field_map_bridges_non_canonical_names()
    test_foreclosure_translator_partial_field_map()
    test_parcel_master_translator_field_map_bridges_non_canonical_names()
    test_parcel_master_translator_no_field_map_identity()

    passed = sum(1 for r in results if r[0] == PASS)
    failed = sum(1 for r in results if r[0] == FAIL)
    print()
    print(f"RESULT: {passed} pass, {failed} fail")
    print("=" * 72)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
