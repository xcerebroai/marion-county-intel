"""
Tests for scaffold/pipeline/owner_name_patterns.py.

Verifies the operator's authoritative regex spec (REVIEW_GATE_4
follow-up, 2026-05-14):

  - ESTATE_PATTERN matches `ESTATE OF | EST OF | ESTATE | HEIRS OF | HEIRS`
  - LIVING_TRUST_PATTERN matches `LIVING TRUST | FAMILY TRUST | REVOCABLE TRUST | REV TRUST | TRUST | TRUSTEE`
  - Both fire as proper framework signals (not attributes)

Run with: python3 scaffold/tests/test_owner_name_patterns.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scaffold.pipeline.owner_name_patterns import (  # noqa: E402
    ESTATE_PATTERN,
    LIVING_TRUST_PATTERN,
    emit_owner_name_signals_for_parcel,
)


passes = []
fails = []


def _assert(label, cond, detail=""):
    if cond:
        passes.append(label)
        print(f"  [PASS] {label}")
    else:
        fails.append((label, detail))
        print(f"  [FAIL] {label}  --  {detail}")


def _parcel(name, pid="BCAD-00100000") -> dict:
    return {"parcel_id": pid, "owner_name": name}


def _emit(parcel: dict) -> list:
    """Helper: emit with the defensive guard pre-satisfied for the parcel."""
    return emit_owner_name_signals_for_parcel(
        parcel,
        parcels_with_lead_signals={parcel["parcel_id"]},
        source_id="parcel_master",
    )


def _classes(name: str) -> set:
    """Mimic the legacy detect_owner_name_classes via the regex objects."""
    out = set()
    if ESTATE_PATTERN.search(name):
        out.add("estate_owner_name_pattern")
    if LIVING_TRUST_PATTERN.search(name):
        out.add("living_trust_owner_name_pattern")
    return out


# ---------------------------------------------------------------------
# Estate pattern
# ---------------------------------------------------------------------

def test_estate_explicit_phrase():
    print("[estate — explicit phrase]")
    _assert("ESTATE OF -> estate",
            "estate_owner_name_pattern" in _classes("ESTATE OF JOHN DOE"))


def test_estate_abbreviation():
    print("\n[estate — EST OF abbreviation]")
    _assert("EST OF -> estate",
            "estate_owner_name_pattern" in _classes("EST OF JOHN DOE"))


def test_estate_heirs_of():
    print("\n[estate — HEIRS OF]")
    _assert("HEIRS OF -> estate",
            "estate_owner_name_pattern" in _classes("HEIRS OF JANE SMITH"))


def test_estate_word_boundary():
    print("\n[estate — word-boundary correctness]")
    _assert("REALESTATE INC does NOT fire estate",
            "estate_owner_name_pattern" not in _classes("ALAMO REALESTATE INC"))
    _assert("HOMERS LLC does NOT fire estate",
            "estate_owner_name_pattern" not in _classes("HOMERS LLC"))


def test_estate_case_insensitive():
    print("\n[estate — case-insensitive]")
    _assert("lowercase 'estate of' matches",
            "estate_owner_name_pattern" in _classes("estate of jane doe"))


def test_estate_bare_word():
    print("\n[estate — bare 'ESTATE']")
    _assert("trailing 'ESTATE' matches",
            "estate_owner_name_pattern" in _classes("DOE ESTATE"))


# ---------------------------------------------------------------------
# Living-trust pattern
# ---------------------------------------------------------------------

def test_trust_family_trust():
    print("\n[trust — FAMILY TRUST]")
    _assert("FAMILY TRUST matches",
            "living_trust_owner_name_pattern" in _classes("DOE FAMILY TRUST"))


def test_trust_revocable():
    print("\n[trust — REVOCABLE TRUST]")
    _assert("REVOCABLE TRUST matches",
            "living_trust_owner_name_pattern" in _classes("DOE REVOCABLE TRUST"))


def test_trust_rev_trust_abbreviation():
    print("\n[trust — REV TRUST]")
    _assert("REV TRUST matches",
            "living_trust_owner_name_pattern" in _classes("DOE REV TRUST"))


def test_trust_bare_trust():
    print("\n[trust — bare TRUST]")
    _assert("bare TRUST matches",
            "living_trust_owner_name_pattern" in _classes("DOE TRUST"))


def test_trust_trustee():
    print("\n[trust — TRUSTEE]")
    _assert("TRUSTEE matches",
            "living_trust_owner_name_pattern" in _classes("DOE JANE TRUSTEE"))


def test_trust_word_boundary():
    print("\n[trust — word boundary]")
    _assert("ENTRUSTED does NOT fire trust",
            "living_trust_owner_name_pattern" not in _classes("ENTRUSTED CAPITAL LLC"))


# ---------------------------------------------------------------------
# Signal emission shape (canonical v5.1.2-beta-r3)
# ---------------------------------------------------------------------

def test_emit_estate_signal_shape():
    print("\n[emission — estate signal shape]")
    parcel = _parcel("ESTATE OF JOHN DOE", "BCAD-00200000")
    signals = _emit(parcel)
    _assert("emits 1 estate signal", len(signals) == 1)
    s = signals[0]
    _assert("signal.primary_parcel_id is the parcel's id",
            s["primary_parcel_id"] == "BCAD-00200000")
    _assert("signal.source_id identifies owner-name origin",
            s["source_id"] == "parcel_master")
    _assert("signal.doc_type == ESTATE_OWNER_NAME_PATTERN",
            s["doc_type"] == "ESTATE_OWNER_NAME_PATTERN")
    _assert("signal.doc_type_subtype_label is operator-readable",
            "Estate" in s["doc_type_subtype_label"])
    _assert("signal.parser_confidence == 75 (operator spec)",
            s["parser_confidence"] == 75)
    _assert("signal._owner_name_literal_match captured",
            s["_owner_name_literal_match"].upper() == "ESTATE OF")


def test_emit_trust_signal_shape():
    print("\n[emission — trust signal shape]")
    parcel = _parcel("DOE FAMILY REVOCABLE TRUST", "BCAD-00300000")
    signals = _emit(parcel)
    _assert("emits 1 trust signal", len(signals) == 1)
    s = signals[0]
    _assert("signal.doc_type == LIVING_TRUST_OWNER_NAME_PATTERN",
            s["doc_type"] == "LIVING_TRUST_OWNER_NAME_PATTERN")
    _assert("signal.parser_confidence == 70 (operator spec)",
            s["parser_confidence"] == 70)


def test_emit_no_match():
    print("\n[emission — no-match parcel]")
    parcel = _parcel("JOHN DOE")
    signals = _emit(parcel)
    _assert("emits 0 signals for plain owner name", len(signals) == 0)


def test_emit_entity_owner_does_not_fire_signal():
    print("\n[emission — entity-only owner emits no signal]")
    parcel = _parcel("FAMSACA LLC")
    signals = _emit(parcel)
    _assert("entity-only owner emits 0 signals (handled as attribute, not signal)",
            len(signals) == 0)


def test_emit_multi_match():
    print("\n[emission — multi-pattern parcel (estate + trust)]")
    parcel = _parcel("HEIRS OF JOHN DOE FAMILY TRUST")
    signals = _emit(parcel)
    doc_types = sorted([s["doc_type"] for s in signals])
    _assert("both estate and trust signals fire",
            doc_types == ["ESTATE_OWNER_NAME_PATTERN",
                          "LIVING_TRUST_OWNER_NAME_PATTERN"],
            f"got {doc_types}")


def test_emit_deterministic_ids():
    print("\n[emission — deterministic raw_record_id across runs]")
    parcel = _parcel("ESTATE OF JANE SMITH", "BCAD-00400000")
    a = _emit(parcel)[0]
    b = _emit(parcel)[0]
    _assert("identical inputs produce identical raw_record_id",
            a["raw_record_id"] == b["raw_record_id"])


def test_defensive_guard_blocks_emission():
    print("\n[emission — defensive guard blocks parcels without lead signals]")
    parcel = _parcel("ESTATE OF GUARD TEST", "BCAD-00500000")
    # parcels_with_lead_signals is empty -> guard fires -> 0 emissions.
    signals = emit_owner_name_signals_for_parcel(
        parcel,
        parcels_with_lead_signals=set(),
        source_id="parcel_master",
    )
    _assert("guard blocks emission when parcel has no lead signals",
            len(signals) == 0)


def main() -> int:
    print("[owner_name_patterns tests]\n")
    test_estate_explicit_phrase()
    test_estate_abbreviation()
    test_estate_heirs_of()
    test_estate_word_boundary()
    test_estate_case_insensitive()
    test_estate_bare_word()
    test_trust_family_trust()
    test_trust_revocable()
    test_trust_rev_trust_abbreviation()
    test_trust_bare_trust()
    test_trust_trustee()
    test_trust_word_boundary()
    test_emit_estate_signal_shape()
    test_emit_trust_signal_shape()
    test_emit_no_match()
    test_emit_entity_owner_does_not_fire_signal()
    test_emit_multi_match()
    test_emit_deterministic_ids()
    test_defensive_guard_blocks_emission()
    print(f"\npasses: {len(passes)}  fails: {len(fails)}")
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
