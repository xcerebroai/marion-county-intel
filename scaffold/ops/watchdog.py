#!/usr/bin/env python3
"""
watchdog.py — Production health watchdog

v5.3.0 status: STUB (CLI surface only). v5.3.0 does NOT ship a production
watchdog, alert dispatch, or rollback execution. Earlier docstrings stated the
full implementation would ship "in v5.2.0"; v5.2.0 shipped without it. This
disclosure corrects the record.

A working production watchdog — health checks, alert dispatch, last-known-good
rollback — is deferred to a future harness release. The §20 Semantic
Verification Contract defines the verification surface a future watchdog
enforces; production watchdog infrastructure is a per-county responsibility
until universal production tooling lands.

This stub exists so the framework's contract is honest: the CLI is wired up,
the schema fields are reserved, the calling pattern is documented — but NO
watchdog logic runs here. It returns a non-zero WATCHDOG_STUB_MODE status so
callers never mistake it for a pass.

Usage:
    python scaffold/ops/watchdog.py \\
        --county-slug <slug> \\
        --dashboard-url https://xcerebroai.github.io/<slug>-intel \\
        --data-path data/leads.json \\
        --heartbeat-path data/source_heartbeat.json

Returns:
    0 — all checks pass (build healthy)
    1 — one or more checks failed (build unhealthy)
    2 — usage error
    3 — watchdog stub mode (stub — not yet implemented; see status note above)

Copyright (c) 2026 Xcerebro LLC. All rights reserved.
Proprietary VIP license. See LICENSE.md.
"""

import argparse
import sys
from pathlib import Path


def parse_args(argv):
    parser = argparse.ArgumentParser(
        prog="watchdog.py",
        description=(
            "Production health watchdog. "
            "v5.1.0-beta: CLI stub only. Full implementation in v5.2.0."
        ),
    )
    parser.add_argument("--county-slug", required=True)
    parser.add_argument("--dashboard-url")
    parser.add_argument("--data-path", default="data/leads.json")
    parser.add_argument("--heartbeat-path", default="data/source_heartbeat.json")
    parser.add_argument("--repo-root", default=None)
    parser.add_argument(
        "--rollback-on-failure",
        action="store_true",
        help="If checks fail, restore last-known-good (v5.2.0+)",
    )
    return parser.parse_args(argv)


def resolve_repo_root(explicit_root):
    if explicit_root:
        return Path(explicit_root).resolve()
    return Path(__file__).resolve().parent.parent.parent


def main(argv=None):
    args = parse_args(argv if argv is not None else sys.argv[1:])

    repo_root = resolve_repo_root(args.repo_root)

    print("=" * 72)
    print("Watchdog (v5.1.0-beta STUB)")
    print("=" * 72)
    print(f"Repo root: {repo_root}")
    print(f"County: {args.county_slug}")
    print(f"Dashboard: {args.dashboard_url or '(local)'}")
    print(f"Data path: {args.data_path}")
    print(f"Heartbeat path: {args.heartbeat_path}")
    print(f"Rollback on failure: {args.rollback_on_failure}")
    print()
    print("STATUS: WATCHDOG_STUB_MODE")
    print()
    print("Reason: v5.1.0-beta ships watchdog.py as a CLI stub.")
    print("The full watchdog is deferred to v5.2.0 because watchdog rules")
    print("depend on real failure modes observed in real production runs.")
    print()
    print("v5.2.0 implementation will check:")
    print()
    print("  - Dashboard live (HTTP 200 + content sanity)")
    print("  - Data file live (parses as JSON, has expected shape)")
    print("  - Heartbeat freshness (last_attempted_at within tolerance)")
    print("  - Console errors (Playwright render, capture console)")
    print("  - Record count anomaly (vs prior run, ±50% threshold)")
    print("  - Source failure (any source_freshness_status FAILED/OVERDUE)")
    print("  - CSV export works")
    print("  - Critical source freshness (P0 sources FRESH or PAUSED)")
    print("  - Build manifest status (run_manifest.json parses)")
    print()
    print("On failure:")
    print("  - Mark build unhealthy in deployment.production_verification_status")
    print("  - Dispatch alert to configured channel(s)")
    print("  - If --rollback-on-failure: restore last-known-good")
    print("  - If issue is source-specific: quarantine the offending source")
    print("  - Write watchdog report to runs/<slug>/reports/watchdog_<ts>.md")
    print()

    return 3


if __name__ == "__main__":
    sys.exit(main())
