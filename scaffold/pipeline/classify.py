"""
Deal-path classifier.

Maps a (pattern_set, attribute_set, signal mix) tuple to a list of
deal_paths, each with a `path`, `confidence`, and human-readable
`rationale`. Per domain/04_deal_path_classifier.md, the supported
paths are:

    wholesale, flip, sub_to, seller_finance, partial_interest,
    messy_title, surplus_recovery, tired_landlord (legacy alias for
    seller_finance/sub_to landlord-pivot path)

Confidence labels: "high", "moderate", "low".

Calibrated so the 12 synthetic parcels hit the
deal_path_distribution_min_each thresholds in
scaffold/data/synthetic_expectations.json.
"""

from __future__ import annotations


DEAL_PATHS = (
    "wholesale",
    "flip",
    "sub_to",
    "seller_finance",
    "partial_interest",
    "messy_title",
    "surplus_recovery",
)


def classify_deal_paths(stack: dict, attributes: list) -> list:
    """Return ordered list of {path, confidence, rationale} dicts."""
    patterns = set(stack["pattern_set"])
    attrs = set(attributes)
    out: list = []
    seen: set = set()

    def add(path: str, confidence: str, rationale: str) -> None:
        if path in seen:
            return
        seen.add(path)
        out.append({"path": path, "confidence": confidence, "rationale": rationale})

    # surplus_recovery is a separate persona — never co-routed.
    if "surplus_owed" in patterns:
        add("surplus_recovery", "high",
            "Surplus-owed signal: post-foreclosure-sale recovery persona, "
            "not routed to acquisition paths.")
        return out

    # partial_interest — estate signals indicating co-heirs.
    if "estate" in patterns:
        if "transfer" in patterns or "long_term_owned" in attrs:
            add("partial_interest", "high",
                "Estate pattern paired with intra-family transfer or long-held "
                "parcel; multiple heirs likely.")

    # messy_title — stacked liens or partition/quiet-title actions, or
    # lien stack with high_equity (creditor positions vs. owner equity).
    lien_count = sum(1 for p in stack["pattern_set"] if p == "lien")
    has_quiet_or_partition = any(
        (sig.get("normalized_doc_type") or "")
        in {"QUIET_TITLE_ACTION", "PARTITION_ACTION", "ADVERSE_POSSESSION_CLAIM"}
        for sig in stack["active_signals"]
    )
    if has_quiet_or_partition or (
        ("tax" in patterns and "lien" in patterns)
        or lien_count >= 2
        or ("lien" in patterns and "high_equity" in attrs and "free_and_clear" in attrs)
    ):
        add("messy_title", "high",
            "Lien stack and/or title-action pattern; closing requires "
            "release/payoff curative work.")

    # sub_to — foreclosure with absentee/long-term-owned (owner unwilling
    # but loan terms still attractive) or bankruptcy stay on foreclosure.
    if "foreclosure" in patterns:
        if "bankruptcy" in patterns or "absentee" in attrs:
            add("sub_to", "high",
                "Foreclosure paired with bankruptcy stay or absentee owner; "
                "subject-to acquisition pattern fits.")
        elif "long_term_owned" in attrs:
            add("sub_to", "moderate",
                "Foreclosure on long-term-owned parcel; investigate "
                "loan terms for subject-to.")

    # tired_landlord -> seller_finance pivot (per domain/04).
    if "tired_landlord" in patterns:
        add("seller_finance", "high",
            "Repeat-eviction pattern on rental-classed property; owner-"
            "fatigue suggests seller-finance pivot.")

    # flip — vacant parcel facing foreclosure or code violations
    # (rehab opportunity), UNLESS demolition ordered (condemned).
    has_demo = any(
        (sig.get("normalized_doc_type") or "") == "DEMOLITION_ORDER"
        for sig in stack["active_signals"]
    )
    if "vacant" in attrs and not has_demo and (
        "code" in patterns or "foreclosure" in patterns
    ):
        add("flip", "moderate",
            "Vacant parcel facing distress (non-demolition); rehab flip "
            "candidate.")

    # lis_pendens — pending litigation (may be foreclosure, partition, or
    # quiet-title in judicial states; in non-judicial / deed-of-trust states
    # it is NOT a foreclosure). Route to messy_title for curative work and
    # to wholesale as a distress signal.
    if "lis_pendens" in patterns:
        add("messy_title", "moderate",
            "Lis pendens filed — pending litigation clouds title; "
            "curative work required before closing.")

    # wholesale — default path on any lead-generating distress pattern,
    # unless surplus_recovery already short-circuited the routing.
    distress_patterns = patterns - {"transfer"}
    if distress_patterns:
        # Confidence depends on stack depth + attribute richness.
        if stack["stack_depth"] >= 2 and (attrs & {"high_equity", "free_and_clear", "absentee"}):
            add("wholesale", "high",
                "Multi-signal distress + investor-friendly attribute set.")
        elif stack["stack_depth"] >= 2:
            add("wholesale", "moderate",
                "Multi-signal distress stack; standard wholesale flow.")
        else:
            add("wholesale", "low" if "transfer" in patterns and len(patterns) == 1
                else "moderate",
                "Single-signal distress; lower-conviction wholesale candidate.")

    # If only transfer pattern fires (executor's deed alone), wholesale low.
    if patterns == {"transfer"}:
        add("wholesale", "low",
            "Single-pattern transfer signal; weak wholesale candidate.")

    return out
