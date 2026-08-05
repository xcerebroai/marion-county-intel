#!/usr/bin/env python3
"""
verify_live.py — Production self-verification (Phase 6.5)

v5.3.0 status: STUB (CLI surface only). v5.3.0 does NOT ship a production
self-verifier. Earlier docstrings stated the full implementation would ship
"in v5.2.0"; v5.2.0 shipped without it. This disclosure corrects the record.

What v5.3.0 DOES ship: the §20 Semantic Verification Contract
(knowledge_base/architecture/20_semantic_verification_contract.md) defines the
verification contract surface — the twelve check classes, the three-state
outcome model, the deploy verdicts — and scaffold/ops/semantic_verify_template.py
provides a documentation-grade, county-agnostic reference template. A working
production verify_live.py is deferred to a future harness release.

This stub exists so the framework's contract is honest: the CLI is wired up,
the schema fields are reserved, the calling pattern is documented — but NO
verification logic runs here. It returns a non-zero
PRODUCTION_VERIFICATION_BLOCKED status so callers never mistake it for a pass.

Usage:
    python scaffold/ops/verify_live.py \\
        --dashboard-url https://xcerebroai.github.io/<slug>-intel \\
        --county-slug <slug> \\
        --data-path data/leads.json \\
        --expected-status PRIMARY_BUILD

Or for local pre-deploy testing:
    python scaffold/ops/verify_live.py \\
        --local-dashboard-path ./index.html \\
        --county-slug <slug> \\
        --data-path data/leads.json

Returns non-zero exit on failure or when verification is blocked.

Copyright (c) 2026 Xcerebro LLC. All rights reserved.
Proprietary VIP license. See LICENSE.md.
"""

import argparse
import sys
from pathlib import Path


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="verify_live.py",
        description=(
            "Production self-verification (Phase 6.5). "
            "v5.1.0-beta: CLI stub only. Full implementation in v5.2.0."
        ),
    )
    parser.add_argument(
        "--dashboard-url",
        help="URL of the live deployed dashboard (e.g. https://xcerebroai.github.io/<slug>-intel)",
    )
    parser.add_argument(
        "--local-dashboard-path",
        help="Local path to index.html for pre-deploy testing",
    )
    parser.add_argument(
        "--county-slug",
        required=True,
        help="County slug (e.g. bexar_tx)",
    )
    parser.add_argument(
        "--data-path",
        default="data/leads.json",
        help="Path to leads.json (relative to repo root)",
    )
    parser.add_argument(
        "--expected-status",
        choices=["FULL_BUILD", "PARTIAL_BUILD", "SOURCE_LIMITED", "PRIMARY_SOURCE_PENDING"],
        default="FULL_BUILD",
        help="Expected dashboard build label",
    )
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Path to framework repo root (defaults to script's grandparent)",
    )
    return parser.parse_args(argv)


def resolve_repo_root(explicit_root):
    if explicit_root:
        return Path(explicit_root).resolve()
    return Path(__file__).resolve().parent.parent.parent


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    if not args.dashboard_url and not args.local_dashboard_path:
        print(
            "ERROR: must specify --dashboard-url OR --local-dashboard-path",
            file=sys.stderr,
        )
        return 2

    repo_root = resolve_repo_root(args.repo_root)
    target = args.dashboard_url or args.local_dashboard_path

    print("=" * 72)
    print("Phase 6.5 — Production self-verification (v5.1.0-beta STUB)")
    print("=" * 72)
    print(f"Repo root: {repo_root}")
    print(f"County: {args.county_slug}")
    print(f"Target: {target}")
    print(f"Data path: {args.data_path}")
    print(f"Expected status: {args.expected_status}")
    print()
    print("STATUS: PRODUCTION_VERIFICATION_BLOCKED")
    print()
    print("Reason: v5.1.0-beta ships verify_live.py as a CLI stub.")
    print("The full Playwright-based dashboard verification is deferred to v5.2.0.")
    print()
    print("v5.2.0 implementation will run the following checks:")
    print()
    print("  1. Dashboard loads without console errors")
    print("  2. Data payload (leads.json) loads")
    print("  3. At least one event-based lead row renders if lead data exists")
    print("  4. Empty state renders correctly if no leads exist")
    print("  5. Filter count matches table row count (Two-Truths)")
    print("  6. CSV export works")
    print("  7. Source proof links render")
    print("  8. No enrichment-only rows shown as leads")
    print("  9. Client View renders")
    print(" 10. Operator View renders")
    print(" 11. Dashboard status banner displays for partial builds")
    print(" 12. Build manifest present")
    print(" 13. Heartbeat file present")
    print(" 14. No broken static asset paths")
    print(" 15. No uncaught JavaScript errors")
    print()
    print("Next step: record `deployment.production_verification_status = ")
    print("PRODUCTION_VERIFICATION_BLOCKED` in the county config and DO NOT")
    print("declare the build complete until v5.2.0 ships or operator approves")
    print("manual verification.")
    print()

    # Return non-zero so callers treat this as not-yet-verified
    return 3


if __name__ == "__main__":
    sys.exit(main())
