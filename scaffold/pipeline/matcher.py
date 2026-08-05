"""
Property matcher per architecture/12_entity_resolution.md.

Joins source records (e.g. foreclosure notices, court filings, code-
enforcement events) to a parcel master (e.g. an appraisal district's
records) using a confidence-tiered address-resolution hierarchy.

Match confidence tiers (framework-wide)
---------------------------------------

  100  parcel_id exact (source carries the parcel master's id directly)
   95  situs_address normalized + ZIP exact match, single candidate
   85  house_number + street_root + ZIP exact match, single candidate
   75  house_number + street_root + city exact match (no ZIP agreement)
   60  multi-candidate match (multiple parcels share the situs);
        primary candidate chosen by deterministic parcel_id order
   40  fuzzy match (city only, address-token overlap below threshold)
    0  no match found

The matcher returns one (source_signal, parcel, metadata) tuple per
source record. Metadata carries:
  - match_confidence (int)
  - match_method   (str)
  - candidate_parcel_ids (list[str]) — for multi-candidate cases
  - review_flags   (list[str]) — flags that the review-queue evaluator
                                 should preserve

Review-queue interactions
-------------------------

  match_confidence  -> review_flag
  100 / 95 / 85     -> none (clean match)
  75                -> address_match_uncertain
  60                -> multi_parcel_address
  40                -> address_match_uncertain
   0                -> parcel_not_found_in_bcad
"""

from __future__ import annotations

import re
from collections import defaultdict


_WHITESPACE = re.compile(r"\s+")
_NUM_RE = re.compile(r"^\s*([0-9]+[A-Z]?(?:\s*-\s*[0-9]+[A-Z]?)?)")
_DIRECTIONALS = frozenset({"N", "S", "E", "W", "NE", "NW", "SE", "SW"})
_STREET_SUFFIXES = frozenset({
    "ST", "STREET", "AVE", "AVENUE", "RD", "ROAD", "DR", "DRIVE",
    "LN", "LANE", "BLVD", "BOULEVARD", "CT", "COURT", "CIR", "CIRCLE",
    "PL", "PLACE", "PKWY", "PARKWAY", "WAY", "TRL", "TRAIL", "TER",
    "TERRACE", "HWY", "HIGHWAY", "LOOP", "PASS", "CV", "COVE",
    "SQ", "SQUARE", "RUN", "PATH", "PATHWAY", "RIDGE", "CRK", "CREEK",
})


def normalize_address(s: str) -> str:
    """Collapse whitespace, uppercase, strip trailing punctuation/space."""
    if not s:
        return ""
    out = _WHITESPACE.sub(" ", s.strip().upper())
    # Strip trailing punctuation then any whitespace that follows.
    return out.strip(",.;: \t")


def house_number(addr: str) -> str:
    m = _NUM_RE.match(addr.upper())
    return m.group(1).replace(" ", "") if m else ""


def address_tokens(addr: str) -> list:
    """Tokenize address into uppercase words, skipping the house number."""
    norm = normalize_address(addr)
    parts = norm.split()
    if not parts:
        return []
    # Drop leading house number.
    if _NUM_RE.match(parts[0]):
        parts = parts[1:]
    return parts


def street_root(addr: str) -> str:
    """Return the first significant street-name token (skip directionals)."""
    tokens = address_tokens(addr)
    while tokens and tokens[0] in _DIRECTIONALS:
        tokens = tokens[1:]
    return tokens[0] if tokens else ""


def street_body(addr: str) -> list:
    """Address tokens minus a leading directional and trailing suffix."""
    tokens = address_tokens(addr)
    while tokens and tokens[0] in _DIRECTIONALS:
        tokens = tokens[1:]
    while tokens and tokens[-1] in _STREET_SUFFIXES:
        tokens = tokens[:-1]
    return tokens


# ---------------------------------------------------------------------
# Index
# ---------------------------------------------------------------------

class ParcelIndex:
    """In-memory index over parcel-master records, keyed for fast match."""

    def __init__(self, parcels: list):
        self._by_norm_address: dict = defaultdict(list)
        self._by_zip_housenum_root: dict = defaultdict(list)
        self._by_city_housenum_root: dict = defaultdict(list)
        self._by_zip_housenum: dict = defaultdict(list)
        for p in parcels:
            situs = normalize_address(p.get("address") or "")
            zip_code = (p.get("zip") or "").strip()
            city = (p.get("city") or "").strip().upper()
            num = house_number(situs)
            root = street_root(situs)
            if situs and zip_code:
                self._by_norm_address[(situs, zip_code)].append(p)
            if num and root and zip_code:
                self._by_zip_housenum_root[(zip_code, num, root)].append(p)
                self._by_zip_housenum[(zip_code, num)].append(p)
            if num and root and city:
                self._by_city_housenum_root[(city, num, root)].append(p)

    def find(self, address: str, zip_code: str, city: str) -> tuple:
        """Return (match_method, match_confidence, candidates list)."""
        addr = normalize_address(address)
        zip_code = (zip_code or "").strip()
        city = (city or "").strip().upper()

        # Tier 1: exact normalized address + ZIP.
        candidates = self._by_norm_address.get((addr, zip_code))
        if candidates:
            confidence = 95 if len(candidates) == 1 else 60
            method = "situs_normalized_zip_exact" if len(candidates) == 1 else "situs_normalized_zip_multi"
            return method, confidence, candidates

        # Tier 2: house number + street root + ZIP.
        num = house_number(addr)
        root = street_root(addr)
        if num and root and zip_code:
            candidates = self._by_zip_housenum_root.get((zip_code, num, root))
            if candidates:
                # Within this tier require body-token agreement to avoid
                # false-positive single-letter root collisions.
                body_source = street_body(addr)
                tightened = [
                    p for p in candidates
                    if _body_overlap(street_body(p.get("address") or ""), body_source)
                ]
                if tightened:
                    confidence = 85 if len(tightened) == 1 else 60
                    method = "housenum_root_zip" if len(tightened) == 1 else "housenum_root_zip_multi"
                    return method, confidence, tightened

        # Tier 3: house number + street root + city.
        if num and root and city:
            candidates = self._by_city_housenum_root.get((city, num, root))
            if candidates:
                confidence = 75 if len(candidates) == 1 else 60
                method = "housenum_root_city" if len(candidates) == 1 else "housenum_root_city_multi"
                return method, confidence, candidates

        # Tier 4: fuzzy — house number + ZIP, any street.
        if num and zip_code:
            candidates = self._by_zip_housenum.get((zip_code, num))
            if candidates:
                return "housenum_zip_fuzzy", 40, candidates

        return "no_match", 0, []


def _body_overlap(a: list, b: list, *, min_overlap: int = 1) -> bool:
    if not a or not b:
        return False
    return len(set(a) & set(b)) >= min_overlap


# ---------------------------------------------------------------------
# Match
# ---------------------------------------------------------------------

def match_signals_to_parcels(signals: list, parcels: list,
                              *, source_address_field: str = "_record_address",
                              source_zip_field: str = "_record_zip",
                              source_city_field: str = "_record_city") -> tuple:
    """
    Match a list of signals (with translator-supplied address metadata)
    against a parcel master. Returns (matched_parcels_by_id, signal_match_meta).

    matched_parcels_by_id  : dict[parcel_id -> parcel record from `parcels`]
    signal_match_meta      : dict[signal_id -> match metadata]
    """
    index = ParcelIndex(parcels)
    matched: dict = {}
    meta: dict = {}

    for sig in signals:
        addr = sig.get(source_address_field) or ""
        zip_code = sig.get(source_zip_field) or ""
        city = sig.get(source_city_field) or ""
        method, confidence, candidates = index.find(addr, zip_code, city)
        candidate_ids = [c.get("parcel_id") for c in candidates if c.get("parcel_id")]
        review_flags: list = []
        if confidence >= 85:
            primary = candidates[0]
        elif confidence == 75:
            primary = candidates[0]
            review_flags.append("address_match_uncertain")
        elif confidence == 60:
            # Multi-parcel address — pick deterministically by parcel_id,
            # flag for operator review.
            primary = sorted(
                candidates,
                key=lambda p: p.get("parcel_id") or "~",
            )[0]
            review_flags.append("multi_parcel_address")
        elif confidence == 40:
            primary = candidates[0]
            review_flags.append("address_match_uncertain")
        else:
            primary = None
            review_flags.append("parcel_not_found_in_bcad")

        if primary and primary.get("parcel_id"):
            matched[primary["parcel_id"]] = primary

        meta[sig.get("signal_id") or sig.get("parcel_id")] = {
            "match_method": method,
            "match_confidence": confidence,
            "primary_parcel_id": primary.get("parcel_id") if primary else None,
            "candidate_parcel_ids": candidate_ids,
            "candidate_count": len(candidates),
            "review_flags": review_flags,
        }

    return matched, meta


# ---------------------------------------------------------------------
# Owner-name analysis for attribute derivation
# ---------------------------------------------------------------------

_VALID_US_STATE_CODES = frozenset({
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY","DC","PR","VI","GU","AS","MP",
    "AE","AP","AA",
})


def looks_like_out_of_state(
    parcel: dict,
    *,
    in_state_zip_prefixes: list | None = None,
    in_state_code: str | None = None,
) -> bool:
    """
    Conservative out-of-state check: fire only when the mailing state
    is a valid US 2-letter code, disagrees with the situs state, and
    the mailing ZIP doesn't contradict the mailing state. The in-state
    ZIP-prefix guard catches the case where a parcel-master row carries
    an in-state ZIP under a typo state code; for those rows the ZIP
    wins and the row is treated as in-state.
    """
    mail_st = (parcel.get("owner_mailing_state") or "").strip().upper()
    situs_st = (parcel.get("situs_state") or "").strip().upper()
    if not mail_st or not situs_st:
        return False
    if mail_st == situs_st:
        return False
    if mail_st not in _VALID_US_STATE_CODES:
        return False
    mail_zip = (parcel.get("owner_mailing_zip") or "").strip()
    in_state_code = (in_state_code or "").upper()
    prefixes = in_state_zip_prefixes or []
    if (
        mail_zip
        and prefixes
        and in_state_code
        and any(mail_zip.startswith(p) for p in prefixes)
        and mail_st != in_state_code
    ):
        return False
    return True
