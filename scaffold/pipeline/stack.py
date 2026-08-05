"""
Multi-property owner detection helper.

v5.4.0 Session 10 — the monolith's `stack_signals` (per-parcel lifecycle /
TTL / negative-signal suppression / eviction-collapse stacking) was retired
in the cutover. The §18 aggregation key engine + §19 idempotent aggregator
replace its grouping role; the §17 debtor party engine + the doc_type
registry's `source_class` and the seam's stack adaptation replace its
lifecycle role. The only piece this module still owns is the cross-parcel
owner-name grouping helper, which is parcel-master-shape input and is
orthogonal to the per-parcel staged pipeline — it produces the
`multi_properties` attribute hint the seam's enrichment-derived attributes
key off (via normalize.derive_attributes).
"""

from __future__ import annotations

from collections import defaultdict


# Owner-name sentinels that should NOT be grouped for multi-property
# detection. Production-mode placeholder parcels carry an "Unknown" owner
# name pending parcel-master enrichment; treating them all as the same
# owner produces a false multiple_properties attribute on every parcel.
_NON_GROUPABLE_OWNER_TOKENS = (
    "UNKNOWN",
    "PENDING",
    "PLACEHOLDER",
    "TBD",
)


def detect_multi_property_owners(parcels: list) -> set:
    """Return the set of parcel_ids belonging to owners with >1 parcel in
    the dataset. Skips placeholder parcels and non-groupable owner sentinels
    so a missing-enrichment row never inflates the multi_properties signal."""
    by_owner = defaultdict(list)
    for p in parcels:
        if p.get("_placeholder"):
            continue
        owner = (p.get("owner_name") or "").strip().upper()
        if not owner:
            continue
        if any(t in owner for t in _NON_GROUPABLE_OWNER_TOKENS):
            continue
        by_owner[owner].append(p.get("parcel_id"))
    out: set = set()
    for owner, ids in by_owner.items():
        if len(ids) >= 2:
            out.update(ids)
    return out
