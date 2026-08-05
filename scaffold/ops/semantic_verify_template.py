#!/usr/bin/env python3
"""semantic_verify_template.py — documentation-grade Semantic Verification template.

This file is a DOCUMENTATION-GRADE TEMPLATE. It implements the *surface* of the
§20 Semantic Verification Contract (knowledge_base/architecture/
20_semantic_verification_contract.md) in code form — the enums, the result
shapes, the twelve check signatures, and the verdict computation — so that a
county build has a copy-and-specialize starting point.

It is NOT a working production verifier. v5.3.0 ships the contract surface
only; eleven of the twelve checks raise NotImplementedError and must be
specialized per county. The one universal check (check_12, filer patterns)
carries a real implementation because its patterns are universal.

Counties copy this file to:
    runs/<county_slug>/build/semantic_verify_<county_slug>.py
and specialize the check implementations for their source taxonomy, browser
automation tooling, and CSV export format.

A working production semantic verifier — shared infrastructure, browser
automation, sampling harness — is deferred to v5.4.0 or later. This template
defines the contract; counties implement against it.

See knowledge_base/architecture/20_semantic_verification_contract.md §20.C for
the twelve check classes, §20.D for the three-state outcome model, and §20.F
for the deploy verdicts.
"""

from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


# --------------------------------------------------------------------------
# §20.D — three-state outcome model; §20.F — deploy verdicts.
# --------------------------------------------------------------------------

class CheckOutcome(Enum):
    """Outcome of a single semantic check (§20.D)."""
    VALID = "VALID"
    INVALID = "INVALID"
    AMBIGUOUS = "AMBIGUOUS"


class DeployVerdict(Enum):
    """Overall verdict of a semantic verification run (§20.F)."""
    DEPLOY_OK = "DEPLOY_OK"
    DEPLOY_BLOCKED = "DEPLOY_BLOCKED"
    NEEDS_OPERATOR_REVIEW = "NEEDS_OPERATOR_REVIEW"


# --------------------------------------------------------------------------
# Result shapes.
# --------------------------------------------------------------------------

@dataclass
class CheckResult:
    """The result of running one semantic check."""
    check_name: str
    outcome: CheckOutcome
    sampled_rows: List[Dict[str, Any]] = field(default_factory=list)
    failure_reason: Optional[str] = None
    ambiguous_reason: Optional[str] = None


@dataclass
class VerificationReport:
    """The full report of a semantic verification run."""
    county_slug: str
    matched_leads_count: int
    sampling_seed: int
    check_results: List[CheckResult] = field(default_factory=list)
    overall_verdict: DeployVerdict = DeployVerdict.DEPLOY_BLOCKED

    def to_markdown(self) -> str:
        """Render the report as operator-facing markdown.

        Specialize per county: the markdown layout, per-check sample tables,
        and ambiguous-row triage section are county-presentation concerns.
        """
        raise NotImplementedError("Specialize per county")


# --------------------------------------------------------------------------
# §20.C — the twelve check classes. Eleven are stubs to specialize per county;
# check_12 is universal and carries a real implementation.
# --------------------------------------------------------------------------

def check_01_debtor_attribution(matched_leads: List[Dict[str, Any]],
                                sample_size: int = 5) -> CheckResult:
    """Check 1 (§20.C) — debtor attribution sampling.

    Sample >=5 rows per canonical_doc_type and confirm owner_name is the
    expected debtor party per §17, not the filer.

    Specialize per county: the county's canonical_doc_type taxonomy and the
    per-doc-type expected-debtor name_type mapping.
    """
    raise NotImplementedError("Specialize per county")


def check_02_owner_type_classification(matched_leads: List[Dict[str, Any]],
                                       sample_size: int = 5) -> CheckResult:
    """Check 2 (§20.C) — owner type classification sampling.

    Sample >=5 rows per owner_type and confirm ENTITY/ESTATE/TRUST/INDIVIDUAL
    classification is correct; reject substring false positives.

    Specialize per county: nothing intrinsic — but the sampling source and
    the row-rendering for operator review are county-specific.
    """
    raise NotImplementedError("Specialize per county")


def check_03_parcel_resolution_plausibility(matched_leads: List[Dict[str, Any]],
                                            sample_size: int = 5) -> CheckResult:
    """Check 3 (§20.C) — parcel-resolution plausibility.

    Sample >=5 RESOLVED rows and confirm situs_address tokens overlap the
    debtor-name search key (Jaccard >=0.5 or >=2 shared significant tokens).

    Specialize per county: the county's parcel identifier form and the
    address-token normalization rules.
    """
    raise NotImplementedError("Specialize per county")


def check_04_enrichment_decoupling(matched_leads: List[Dict[str, Any]]) -> CheckResult:
    """Check 4 (§20.C) — enrichment status decoupling integrity.

    Confirm rows exist across the four valid (parcel_resolution_status,
    enrichment_status) combinations from §13.14, and that no row was dropped
    for enrichment failure.

    Specialize per county: the county's enrichment source set.
    """
    raise NotImplementedError("Specialize per county")


def check_05_signal_aggregation_integrity(matched_leads: List[Dict[str, Any]],
                                          sample_size: int = 3) -> CheckResult:
    """Check 5 (§20.C) — signal aggregation integrity.

    Sample >=3 rows with signal count > 1 and confirm count equals the number
    of distinct instrument_numbers (legitimate stacking vs dedup failure, §18).

    Specialize per county: the county's instrument_number format.
    """
    raise NotImplementedError("Specialize per county")


def check_06_cross_source_aggregation(matched_leads: List[Dict[str, Any]],
                                      sample_size: int = 3) -> CheckResult:
    """Check 6 (§20.C) — cross-source aggregation integrity.

    Sample >=3 multi-source leads and confirm the aggregation key
    (parcel_id, canonical_doc_type, signal_type) merges cross-source
    duplicates without collapsing distinct signal_types (§18).

    Specialize per county: the county's source set and signal_type labels.
    """
    raise NotImplementedError("Specialize per county")


def check_07_ocr_confidence_routing(matched_leads: List[Dict[str, Any]],
                                    sample_size: int = 5,
                                    ocr_confidence_floor: float = 0.85) -> CheckResult:
    """Check 7 (§20.C) — OCR confidence routing.

    For OCR-dependent sources, sample >=5 OCR'd records and confirm rows below
    the OCR confidence floor are flagged for review, not emitted as
    authoritative leads.

    Specialize per county: which sources are OCR-dependent and where the OCR
    confidence value is recorded.
    """
    raise NotImplementedError("Specialize per county")


def check_08_csv_output_schema(csv_path: Path,
                               dashboard_count: int) -> CheckResult:
    """Check 8 (§20.C) — CSV output schema validation.

    Confirm export column headers match the documented schema, row counts
    match dashboard counts, and no enrichment-only synthetic rows appear.

    Specialize per county: the county's documented CSV export schema.
    """
    raise NotImplementedError("Specialize per county")


def check_09_source_proof_links(matched_leads: List[Dict[str, Any]],
                                sample_size: int = 5) -> CheckResult:
    """Check 9 (§20.C) — source proof link validation.

    Sample >=5 leads per source and confirm source_urls resolve to a real
    document matching the lead's instrument_number and recorded_date.

    Specialize per county: the source URL/offline-path conventions and the
    online/offline fetch strategy.
    """
    raise NotImplementedError("Specialize per county")


def check_10_dashboard_row_integrity(dashboard_url: str) -> CheckResult:
    """Check 10 (§20.C) — dashboard row integrity (browser-rendered).

    With browser automation, confirm the header lead count matches the visible
    row count across >=5 filter states, and REVIEW_REQUIRED rows are visually
    distinct from RESOLVED rows.

    Specialize per county: the browser-automation tooling and the dashboard's
    filter-control selectors.
    """
    raise NotImplementedError("Specialize per county")


def check_11_methodology_consistency(matched_leads: List[Dict[str, Any]],
                                     build_report_path: Path) -> CheckResult:
    """Check 11 (§20.C) — methodology consistency.

    Confirm the build report's stated methodology (sources contributed,
    records ingested, enrichment hit rate, REVIEW_REQUIRED count) reconciles
    with the underlying matched_leads.json counts.

    Specialize per county: the build report's structure.
    """
    raise NotImplementedError("Specialize per county")


def check_12_universal_filer_patterns(matched_leads: List[Dict[str, Any]]) -> CheckResult:
    """Check 12 (§20.C) — universal filer-as-owner spot check.

    UNIVERSAL — no per-county specialization. The filer patterns below are
    universal regex patterns (governments, hospitals, mortgage entities,
    federal mortgage agencies, servicers, trustees). None may appear as
    owner_name on any row; such an entity may appear only as filer_entity on a
    REVIEW_REQUIRED row.
    """
    import re

    universal_filer_patterns = [
        # Government entities.
        r"CITY OF .+", r"COUNTY OF .+", r"STATE OF .+",
        r"UNITED STATES OF AMERICA", r"UNITED STATES",
        r"IRS", r"INTERNAL REVENUE SERVICE",
        # Hospital entities.
        r".+HOSPITAL$", r".+HOSPITALS$", r".+HEALTH SYSTEM$",
        r".+MEDICAL CENTER$", r"THE HOSPITALS OF .+",
        # Mortgage entities.
        r".+ MORTGAGE COMPANY$", r".+ MORTGAGE CORP$", r".+ MORTGAGE LLC$",
        r".+ BANK N\.A\.$",
        # Federal mortgage agencies.
        r"FREDDIE MAC", r"FANNIE MAE", r"FEDERAL HOME LOAN MORTGAGE CORPORATION",
        r"FEDERAL NATIONAL MORTGAGE ASSOCIATION", r"GINNIE MAE",
        # Servicers.
        r"NATIONSTAR", r"MR\. COOPER", r"PHH MORTGAGE", r"NEWREZ", r"SHELLPOINT",
        # Trustees.
        r"SUBSTITUTE TRUSTEE", r"TRUSTEE SERVICES",
    ]
    compiled = [re.compile(p, re.IGNORECASE) for p in universal_filer_patterns]

    violations: List[Dict[str, Any]] = []
    for lead in matched_leads:
        # REVIEW_REQUIRED rows are allowed to carry the filer in filer_entity;
        # they are not owner_name violations.
        if lead.get("parcel_resolution_status") == "REVIEW_REQUIRED":
            continue
        owner_name = (lead.get("owner_name") or "").strip()
        if not owner_name:
            continue
        for pattern in compiled:
            if pattern.match(owner_name):
                violations.append({
                    "lead_id": lead.get("lead_id"),
                    "owner_name": owner_name,
                    "matched_pattern": pattern.pattern,
                })
                break

    if violations:
        return CheckResult(
            check_name="check_12_universal_filer_patterns",
            outcome=CheckOutcome.INVALID,
            sampled_rows=violations,
            failure_reason=(
                f"{len(violations)} row(s) emit a universal filer pattern as "
                f"owner_name; a filer may appear only as filer_entity on a "
                f"REVIEW_REQUIRED row"
            ),
        )
    return CheckResult(
        check_name="check_12_universal_filer_patterns",
        outcome=CheckOutcome.VALID,
        sampled_rows=[],
    )


# --------------------------------------------------------------------------
# §20.F — verdict computation.
# --------------------------------------------------------------------------

def compute_verdict(check_results: List[CheckResult]) -> DeployVerdict:
    """Compute the overall deploy verdict from the per-check results (§20.F).

    DEPLOY_BLOCKED if any check is INVALID; NEEDS_OPERATOR_REVIEW if any is
    AMBIGUOUS and none INVALID; DEPLOY_OK otherwise.
    """
    outcomes = [r.outcome for r in check_results]
    if CheckOutcome.INVALID in outcomes:
        return DeployVerdict.DEPLOY_BLOCKED
    if CheckOutcome.AMBIGUOUS in outcomes:
        return DeployVerdict.NEEDS_OPERATOR_REVIEW
    return DeployVerdict.DEPLOY_OK


# --------------------------------------------------------------------------
# Template entry point.
# --------------------------------------------------------------------------

def main(county_slug: str,
         matched_leads_path: Path,
         dashboard_url: str,
         csv_path: Path,
         build_report_path: Path) -> int:
    """Run semantic verification for a county build (template).

    Specialize per county: uncomment the specialized checks once their
    NotImplementedError stubs have been implemented for this county.
    """
    # §20.E — random sampling with a recorded seed for reproducibility.
    # The actual seed used MUST be recorded in the VerificationReport; 42 is a
    # placeholder default for the template.
    sampling_seed = 42
    random.seed(sampling_seed)

    matched_leads: List[Dict[str, Any]] = json.loads(
        Path(matched_leads_path).read_text(encoding="utf-8")
    )

    check_results: List[CheckResult] = []
    # Uncomment each check after it has been specialized for this county:
    # check_results.append(check_01_debtor_attribution(matched_leads))
    # check_results.append(check_02_owner_type_classification(matched_leads))
    # check_results.append(check_03_parcel_resolution_plausibility(matched_leads))
    # check_results.append(check_04_enrichment_decoupling(matched_leads))
    # check_results.append(check_05_signal_aggregation_integrity(matched_leads))
    # check_results.append(check_06_cross_source_aggregation(matched_leads))
    # check_results.append(check_07_ocr_confidence_routing(matched_leads))
    # check_results.append(check_08_csv_output_schema(csv_path, 0))
    # check_results.append(check_09_source_proof_links(matched_leads))
    # check_results.append(check_10_dashboard_row_integrity(dashboard_url))
    # check_results.append(check_11_methodology_consistency(
    #     matched_leads, build_report_path))
    # check_12 is universal — active without specialization:
    check_results.append(check_12_universal_filer_patterns(matched_leads))

    verdict = compute_verdict(check_results)

    report = VerificationReport(
        county_slug=county_slug,
        matched_leads_count=len(matched_leads),
        sampling_seed=sampling_seed,
        check_results=check_results,
        overall_verdict=verdict,
    )
    _ = report  # report.to_markdown() is specialized per county.

    print(f"VERDICT: {verdict.value}")
    return 0 if verdict is DeployVerdict.DEPLOY_OK else 1


if __name__ == "__main__":
    # Template — does nothing when invoked directly.
    sys.exit(0)
