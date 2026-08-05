"""
aggregation_key_engine — v5.4.0 staged pipeline, the §18 aggregation key.

STATUS: IMPLEMENTED in v5.4.0 Session 3. This module computes the §18.B
aggregation key — the tuple (parcel_id, canonical_doc_type, signal_type) — that
is the dedup boundary for signal aggregation. Records sharing the full key
collapse into one signal with a count badge; records differing in any component
stay distinct (the §18.F anti-collapse rule). The leads-base writer stamps each
base record with its key; the §19 aggregator (Session 4) groups by it.

Contract: knowledge_base/architecture/18_signal_aggregation_contract.md,
including the §18.J Session 3 amendment.

F-3 (resolved Session 3 — §18.J): §18.B assumes a non-null parcel_id, but
§13.14 emits UNRESOLVED leads with parcel_id = null. Grouping null-parcel
records by the key alone would over-collapse every distinct unresolved property
of the same doc type into ONE signal. `aggregation_key_tuple` therefore folds a
per-record `fallback_identity` (instrument_number, else raw_event_id — see
`null_parcel_fallback_identity`) into the grouping tuple for null-parcel
records, under a sentinel so it can never collide with a real parcel_id. A
null-parcel key offered for grouping with no fallback identity raises
ValueError — a loud failure beats a silent over-merge.

F-4 (resolved Session 3 — §18.J): signal_type is a many-to-one display label
derived from canonical_doc_type, so it carries no grouping information beyond
canonical_doc_type — `canonical_doc_type` is the authoritative grouping
discriminator. signal_type is retained in the key as the schema-required
display component; the §18.F anti-collapse guarantee is enforced by
canonical_doc_type.

This module is universal framework code: the aggregation-key shape, the F-3
fallback rule, and the §18.E instrument-union primitive are universal; the
per-county signal_type display labels are passed in at call time
(config/counties/<county_slug>.json `signal_type_labels`). No county / state /
vendor literal appears here.
"""

from __future__ import annotations

from typing import Optional

# F-3 sentinel — wraps a null-parcel fallback identity inside the grouping tuple
# so a fallback identity can never compare equal to a real string parcel_id.
_NULL_PARCEL_SENTINEL = "\x00NULL_PARCEL"


def resolve_signal_type(
    canonical_doc_type: str,
    *,
    signal_type_labels: dict,
) -> str:
    """Resolve the operator-facing signal_type for a canonical doc type (§18.B).

    §18.I locates the per-county display labels in
    config/counties/<county_slug>.json under `signal_type_labels`. When the map
    carries no label for `canonical_doc_type`, a deterministic default label is
    derived by title-casing the canonical doc type (e.g. `hospital_lien` ->
    "Hospital Lien"), so the engine never fails on an unlabelled doc type.

    F-4: the canonical_doc_type -> signal_type relationship is many-to-one;
    signal_type is a display label, not a grouping discriminator.

    Args:
        canonical_doc_type: The normalized doc type.
        signal_type_labels: The per-county canonical_doc_type -> display-label
            map.

    Returns:
        The resolved signal_type display label (always a non-empty string).
    """
    if not isinstance(canonical_doc_type, str) or not canonical_doc_type.strip():
        raise ValueError(
            "resolve_signal_type: canonical_doc_type must be a non-empty string"
        )
    label = (signal_type_labels or {}).get(canonical_doc_type)
    if isinstance(label, str) and label.strip():
        return label
    # F-4: no county-supplied label — deterministic title-cased fallback.
    return canonical_doc_type.replace("_", " ").strip().title()


def compute_aggregation_key(
    *,
    parcel_id: Optional[str],
    canonical_doc_type: str,
    signal_type: str,
) -> dict:
    """Compute the §18.B aggregation key for one record.

    The key is the dict {parcel_id, canonical_doc_type, signal_type}, conforming
    to the `aggregation_key` object in leads_base_record.schema.json. `parcel_id`
    is the resolved parcel id, or None when the lead is UNRESOLVED /
    REVIEW_REQUIRED (§13.14). The hashable grouping form is produced by
    `aggregation_key_tuple`.

    Args:
        parcel_id: The resolved parcel id, or None.
        canonical_doc_type: The normalized doc type.
        signal_type: The operator-facing signal type from `resolve_signal_type`.

    Returns:
        The aggregation-key dict.
    """
    if not isinstance(canonical_doc_type, str) or not canonical_doc_type.strip():
        raise ValueError(
            "compute_aggregation_key: canonical_doc_type must be a non-empty string"
        )
    if not isinstance(signal_type, str) or not signal_type.strip():
        raise ValueError(
            "compute_aggregation_key: signal_type must be a non-empty string"
        )
    return {
        "parcel_id": parcel_id,
        "canonical_doc_type": canonical_doc_type,
        "signal_type": signal_type,
    }


def aggregation_key_tuple(
    aggregation_key: dict,
    *,
    fallback_identity: Optional[str] = None,
) -> tuple:
    """Return the hashable grouping tuple for an aggregation key (§18.B / F-3).

    The §19 aggregator groups base records by this tuple; two records are in the
    same signal group iff their tuples are equal.

      - non-null parcel_id -> (parcel_id, canonical_doc_type, signal_type), the
        §18.B tuple;
      - null parcel_id (F-3) -> the per-record `fallback_identity` is folded in
        under a sentinel: ((sentinel, fallback_identity), canonical_doc_type,
        signal_type). Two distinct unresolved properties carry distinct fallback
        identities, so they never collapse into one signal.

    A null-parcel key passed with no `fallback_identity` raises ValueError:
    grouping it on the bare key would silently merge every distinct unresolved
    property of the doc type (contract finding F-3). Callers derive the fallback
    with `null_parcel_fallback_identity`.

    Args:
        aggregation_key: An aggregation-key dict from `compute_aggregation_key`.
        fallback_identity: The per-record identity used for null-parcel records.

    Returns:
        A hashable tuple usable as a grouping key.
    """
    if not isinstance(aggregation_key, dict):
        raise ValueError("aggregation_key_tuple: aggregation_key must be a dict")
    parcel_id = aggregation_key.get("parcel_id")
    canonical_doc_type = aggregation_key.get("canonical_doc_type")
    signal_type = aggregation_key.get("signal_type")
    if not canonical_doc_type or not signal_type:
        raise ValueError(
            "aggregation_key_tuple: aggregation_key is missing "
            "canonical_doc_type or signal_type"
        )

    if parcel_id is not None:
        return (parcel_id, canonical_doc_type, signal_type)

    # F-3: a null parcel_id must group by a per-record fallback identity.
    if fallback_identity is None or not str(fallback_identity).strip():
        raise ValueError(
            "aggregation_key_tuple: a null-parcel aggregation key cannot be "
            "grouped without a fallback_identity (contract finding F-3) — "
            "distinct unresolved properties would silently collapse into one "
            "signal. Pass fallback_identity=null_parcel_fallback_identity(record)."
        )
    return (
        (_NULL_PARCEL_SENTINEL, str(fallback_identity)),
        canonical_doc_type,
        signal_type,
    )


def null_parcel_fallback_identity(record: dict) -> str:
    """Derive the F-3 null-parcel fallback grouping identity for a record.

    Priority: `instrument_number`, else `raw_event_id`, else `base_record_id`.
    A distinct unresolved property carries a distinct recording instrument, so
    `instrument_number` keeps distinct properties distinct; `raw_event_id` /
    `base_record_id` are the always-present per-record backstops (both are
    required, non-empty id fields on their respective records).

    Args:
        record: A raw-event / debtor-resolved / leads-base record dict.

    Returns:
        A non-empty fallback identity string.
    """
    for field in ("instrument_number", "raw_event_id", "base_record_id"):
        value = record.get(field)
        if value is not None and str(value).strip():
            return str(value)
    raise ValueError(
        "null_parcel_fallback_identity: record carries none of "
        "instrument_number / raw_event_id / base_record_id — cannot derive an "
        "F-3 fallback identity for a null-parcel record."
    )


def distinct_instrument_numbers(records) -> tuple:
    """Return the §18.E union of distinct instrument numbers across a group.

    §18.E: within a signal group the aggregator unions records by
    `instrument_number`. When the union count is below the record count, the
    difference is a dedup failure — the same event ingested twice; true
    duplicates collapse. When the union count equals the record count, every
    record is a distinct distress event — legitimate signal stacking, which is
    NOT deduplicated.

    Only non-null instrument numbers participate in the union (a null
    instrument cannot be deduped by value — such records are kept distinct).

    Args:
        records: An iterable of records each carrying `instrument_number`.

    Returns:
        The sorted tuple of distinct non-null instrument numbers.
    """
    seen: list[str] = []
    for record in records or []:
        instrument = record.get("instrument_number")
        if instrument is not None and str(instrument).strip():
            text = str(instrument)
            if text not in seen:
                seen.append(text)
    return tuple(sorted(seen))
