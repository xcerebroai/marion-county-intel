#!/usr/bin/env python3
"""v5.6.0 §01.14/§01.33 invariant — the recon protocol may permit a consolidated
recon document, but ONLY when it mandates a section-to-artifact index. This test
exists so the consolidated format can never degrade into a silent exception to
the eight-artifact content contract.

Run: python3 scaffold/tests/v5_6_0/test_recon_consolidated_requires_index.py
Exit 0 = pass, non-zero = fail.
"""
import sys
from pathlib import Path

PROTOCOL = (Path(__file__).resolve().parents[3]
            / "knowledge_base" / "protocols" / "01_county_recon.md")

# The eight §01.14 artifacts. A consolidated recon must still account for each.
ARTIFACTS = (
    "source_discovery.md",
    "source_verification.md",
    "portal_fingerprints.md",
    "access_classification.md",
    "source_role_classification.md",
    "document_type_discovery.md",
    "build_eligibility_handoff.md",
    "recon_summary.md",
)


def main() -> int:
    if not PROTOCOL.is_file():
        print(f"FAIL: protocol not found at {PROTOCOL}")
        return 1
    text = PROTOCOL.read_text(encoding="utf-8")
    low = text.lower()

    failures = []

    # Both permitted formats must be named explicitly.
    for needle in ("SPLIT_ARTIFACTS", "CONSOLIDATED"):
        if needle not in text:
            failures.append(f"missing permitted-format value: {needle!r}")

    # The content-vs-filesystem distinction is the basis of the amendment.
    if "CONTENT contract, not a filesystem contract" not in text:
        failures.append("protocol does not state that the eight artifacts are a "
                        "content contract rather than a filesystem contract")

    # The index must exist as a named, mandatory concept.
    if "section-to-artifact index" not in low:
        failures.append("missing 'section-to-artifact index' requirement")

    # A consolidated recon without the index must be explicitly non-compliant.
    if "is NOT compliant" not in text:
        failures.append("protocol does not state that a consolidated recon "
                        "without the index is non-compliant")

    # All eight artifacts must still be enumerated somewhere in the protocol,
    # so the index has a fixed checklist to map against.
    for artifact in ARTIFACTS:
        if artifact not in text:
            failures.append(f"artifact no longer enumerated in protocol: {artifact!r}")

    # A missing artifact must be a recorded gap, never a silent omission.
    if "NOT silently omitted" not in text:
        failures.append("protocol does not require that an absent artifact be "
                        "recorded as an explicit gap rather than omitted")

    # The index must point at locatable sections, not vague references.
    if "not a vague pointer" not in low:
        failures.append("protocol does not require concrete, locatable section "
                        "references in the index")

    if not any(k in text for k in ("MUST", "mandatory", "Required Step")):
        failures.append("index requirement present but not marked mandatory")

    if failures:
        print("FAIL: §01.14/§01.33 — consolidated recon index invariant")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("PASS: §01.14/§01.33 — consolidated recon permitted only with a "
          "mandatory section-to-artifact index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
