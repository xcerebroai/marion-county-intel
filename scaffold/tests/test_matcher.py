"""
Tests for scaffold/pipeline/matcher.py.

Covers the address-resolution confidence tiers per
architecture/12_entity_resolution.md and the conservative
out-of-state validator that gates `out_of_state` attribute firing
against BCAD-style data-entry artifacts.

Run with: python3 scaffold/tests/test_matcher.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.pipeline.matcher import (  # noqa: E402
    ParcelIndex,
    house_number,
    looks_like_out_of_state,
    match_signals_to_parcels,
    normalize_address,
    street_root,
)


def _bcad(**overrides) -> dict:
    """Fixture parcel in canonical (post-translator) field-name shape."""
    base = {
        "parcel_id": "BCAD-00100000",
        "address": "100 SYNTHETIC LN",
        "city": "SYNTHTOWN",
        "situs_state": "TX",
        "zip": "78001",
        "owner_name": "SAMPLE OWNER",
        "owner_mailing_address": "100 SYNTHETIC LN",
        "owner_mailing_city": "SYNTHTOWN",
        "owner_mailing_state": "TX",
        "owner_mailing_zip": "78001",
        "year_built": 1990,
        "assessed_value": 300000.0,
        "exempt_homestead": False,
        "exempt_over_65": False,
        "exempt_disabled": False,
    }
    # Back-compat: accept legacy field names in test calls and route them
    # to canonical names so existing test cases keep working.
    legacy_map = {
        "situs_address": "address",
        "situs_city": "city",
        "situs_zip": "zip",
        "owner_mailing_addr1": "owner_mailing_address",
    }
    for k, v in list(overrides.items()):
        if k in legacy_map:
            overrides[legacy_map[k]] = v
            overrides.pop(k)
        elif k == "bcad_prop_id":
            # legacy fixture field; no longer used by matcher
            overrides.pop(k)
    base.update(overrides)
    return base


def _signal(**overrides) -> dict:
    base = {
        "signal_id": "test_sig_1",
        "_record_address": "100 SYNTHETIC LN",
        "_record_city": "SYNTHTOWN",
        "_record_zip": "78001",
    }
    base.update(overrides)
    return base


passes = []
fails = []


def _assert(label, cond, detail=""):
    if cond:
        passes.append(label)
        print(f"  [PASS] {label}")
    else:
        fails.append((label, detail))
        print(f"  [FAIL] {label}  --  {detail}")


# ---------------------------------------------------------------------
# Address normalization
# ---------------------------------------------------------------------

def test_normalization():
    print("[normalize]")
    _assert("collapses double-space",
            normalize_address("3795  MOUNT OLIVE RD ") == "3795 MOUNT OLIVE RD")
    _assert("uppercases input",
            normalize_address("3795 Mount Olive Rd") == "3795 MOUNT OLIVE RD")
    _assert("trims trailing punctuation",
            normalize_address("3795 MOUNT OLIVE RD ,") == "3795 MOUNT OLIVE RD")
    _assert("house_number extracts number+suffix",
            house_number("123A MAIN ST") == "123A")
    _assert("street_root skips directional",
            street_root("100 N HOLLY ST") == "HOLLY")
    _assert("street_root returns first token when no directional",
            street_root("100 MAIN ST") == "MAIN")


# ---------------------------------------------------------------------
# Match-confidence tiers
# ---------------------------------------------------------------------

def test_single_exact_match():
    print("\n[single_exact_match]")
    parcels = [_bcad()]
    matched, meta = match_signals_to_parcels([_signal()], parcels)
    m = meta["test_sig_1"]
    _assert("exact match confidence == 95", m["match_confidence"] == 95)
    _assert("primary_parcel_id is the BCAD record",
            m["primary_parcel_id"] == "BCAD-00100000")
    _assert("no review flags on clean match",
            m["review_flags"] == [])


def test_multi_parcel_address():
    print("\n[multi_parcel_address]")
    parcels = [
        _bcad(parcel_id="BCAD-00100001", bcad_prop_id=100001,
              owner_name="OWNER A"),
        _bcad(parcel_id="BCAD-00100002", bcad_prop_id=100002,
              owner_name="OWNER B"),
    ]
    matched, meta = match_signals_to_parcels([_signal()], parcels)
    m = meta["test_sig_1"]
    _assert("multi-candidate confidence == 60",
            m["match_confidence"] == 60)
    _assert("review_flags carries multi_parcel_address",
            "multi_parcel_address" in m["review_flags"])
    _assert("candidate_parcel_ids has both",
            len(m["candidate_parcel_ids"]) == 2)
    _assert("primary picked deterministically (lowest bcad_prop_id)",
            m["primary_parcel_id"] == "BCAD-00100001")


def test_zip_mismatch_falls_back_to_housenum_root_zip():
    print("\n[zip_mismatch fallback]")
    # Foreclosure record's address differs slightly from BCAD ("LN" vs "LANE").
    parcels = [_bcad(situs_address="100 SYNTHETIC LANE", situs_zip="78001")]
    sig = _signal(_record_address="100 SYNTHETIC LN", _record_zip="78001")
    matched, meta = match_signals_to_parcels([sig], parcels)
    m = meta["test_sig_1"]
    _assert("housenum+root+zip match confidence == 85",
            m["match_confidence"] == 85,
            f"got {m['match_confidence']}")
    _assert("method records housenum_root_zip path",
            "housenum_root_zip" in m["match_method"])


def test_address_with_doublespace_situs():
    print("\n[double-space Situs normalization]")
    parcels = [_bcad(situs_address="3795  MOUNT OLIVE RD ")]
    sig = _signal(_record_address="3795 MOUNT OLIVE RD")
    matched, meta = match_signals_to_parcels([sig], parcels)
    _assert("double-space Situs normalizes to single-space for exact match",
            meta["test_sig_1"]["match_confidence"] == 95)


def test_no_match():
    print("\n[no_match]")
    parcels = [_bcad(situs_address="999 OTHER ST", situs_zip="78999")]
    matched, meta = match_signals_to_parcels([_signal()], parcels)
    m = meta["test_sig_1"]
    _assert("no match yields confidence 0", m["match_confidence"] == 0)
    _assert("review_flags carries parcel_not_found_in_bcad",
            "parcel_not_found_in_bcad" in m["review_flags"])
    _assert("primary_parcel_id is None", m["primary_parcel_id"] is None)


def test_fuzzy_housenum_only():
    print("\n[fuzzy housenum-only]")
    # BCAD has a parcel at house 13926 but on a different street.
    parcels = [_bcad(situs_address="13926 MOONCREST", situs_zip="78247")]
    sig = _signal(_record_address="13926 WOOL PARK", _record_zip="78247")
    matched, meta = match_signals_to_parcels([sig], parcels)
    m = meta["test_sig_1"]
    _assert("fuzzy match confidence == 40", m["match_confidence"] == 40,
            f"got {m['match_confidence']}")
    _assert("review_flags carries address_match_uncertain",
            "address_match_uncertain" in m["review_flags"])


def test_city_match_when_zip_disagrees():
    print("\n[city match when ZIP disagrees]")
    parcels = [_bcad(situs_zip="78002", situs_city="SYNTHTOWN")]
    sig = _signal(_record_zip="78001", _record_city="SYNTHTOWN")
    matched, meta = match_signals_to_parcels([sig], parcels)
    m = meta["test_sig_1"]
    _assert("city-only match confidence == 75",
            m["match_confidence"] == 75,
            f"got {m['match_confidence']}")
    _assert("review_flags carries address_match_uncertain",
            "address_match_uncertain" in m["review_flags"])


# ---------------------------------------------------------------------
# Out-of-state validator
# ---------------------------------------------------------------------

_BEXAR_OOS_KWARGS = {"in_state_zip_prefixes": ["7"], "in_state_code": "TX"}


def test_oos_clean_california():
    print("\n[out_of_state — clean California]")
    p = _bcad(owner_mailing_state="CA", owner_mailing_zip="94105",
              situs_state="TX")
    _assert("CA mailing with CA-style ZIP fires out_of_state",
            looks_like_out_of_state(p, **_BEXAR_OOS_KWARGS) is True)


def test_oos_data_entry_artifact():
    print("\n[out_of_state — data entry artifact 'OH' with in-state ZIP]")
    # Real parcel-master data: typo state code paired with in-state ZIP.
    p = _bcad(owner_mailing_state="OH", owner_mailing_zip="78252",
              situs_state="TX")
    _assert("OH mailing with in-state ZIP does NOT fire out_of_state",
            looks_like_out_of_state(p, **_BEXAR_OOS_KWARGS) is False)


def test_oos_invalid_state_code():
    print("\n[out_of_state — invalid state code]")
    p = _bcad(owner_mailing_state="ZZ", owner_mailing_zip="00000",
              situs_state="TX")
    _assert("ZZ mailing state does NOT fire out_of_state",
            looks_like_out_of_state(p, **_BEXAR_OOS_KWARGS) is False)


def test_oos_same_state():
    print("\n[out_of_state — same-state mailing]")
    p = _bcad(owner_mailing_state="TX", owner_mailing_zip="78001",
              situs_state="TX")
    _assert("same-state does NOT fire out_of_state",
            looks_like_out_of_state(p, **_BEXAR_OOS_KWARGS) is False)


def main() -> int:
    print("[matcher tests]\n")
    test_normalization()
    test_single_exact_match()
    test_multi_parcel_address()
    test_zip_mismatch_falls_back_to_housenum_root_zip()
    test_address_with_doublespace_situs()
    test_no_match()
    test_fuzzy_housenum_only()
    test_city_match_when_zip_disagrees()
    test_oos_clean_california()
    test_oos_data_entry_artifact()
    test_oos_invalid_state_code()
    test_oos_same_state()
    print(f"\npasses: {len(passes)}  fails: {len(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
