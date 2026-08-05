#!/usr/bin/env python3
"""v5.4.0 Group A (green) — contract dataclasses present; engine stubs retired.

This is a SHAPE / SCAFFOLDING test, not a behavioral test. Through Sessions 1-3
it asserted that the not-yet-implemented engine modules exposed the declared
function signatures and were still `raise NotImplementedError` stubs; each
session removed its module once implemented (Session 2 — §17 debtor_party_engine;
Session 3 — §18 aggregation_key_engine and leads_base_writer; Session 4 — §19
aggregator). As of Session 4 ALL v5.4.0 engine stages are implemented and no
stub remains, so ENGINE_SPEC is empty. The test now guards only that the
contracts package and its inter-stage dataclasses import — engine behavior is
gated by the §17 / §18 / §19 specs in scaffold/tests/v5_4_0/.

This test is wired into scaffold/tests/run_all.py and must stay green.

Run: python3 scaffold/tests/v5_4_0/test_engine_stubs.py
Exit 0 = pass, non-zero = fail.
"""
import importlib
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# module path -> {function name -> expected parameter names (in order)}.
# Empty as of Session 4 — all v5.4.0 engine stages are implemented; their
# behavior is gated by the §17 / §18 / §19 specs, not by this stub test.
ENGINE_SPEC: dict[str, dict] = {}

# How to invoke each stub so it reaches its `raise NotImplementedError`.
CALL_THUNKS: dict = {}

# The contract dataclasses that must exist alongside the engine stubs.
EXPECTED_DATACLASSES = [
    "RawEventRecord", "DebtorResolvedRecord", "LeadsBaseRecord",
    "SignalGroup", "MatchedLeadRecord", "EvidenceLedgerEntry",
    "Party", "PropertyRefs", "AggregationKey",
]


def main() -> int:
    failures = []
    stub_count = 0

    # The contracts package and its dataclasses must import.
    try:
        contracts = importlib.import_module("scaffold.pipeline.contracts")
        for dc in EXPECTED_DATACLASSES:
            if not hasattr(contracts, dc):
                failures.append(f"contracts package missing dataclass: {dc}")
    except Exception as exc:
        failures.append(f"scaffold.pipeline.contracts not importable — {exc}")

    for module_path, funcs in ENGINE_SPEC.items():
        try:
            module = importlib.import_module(module_path)
        except Exception as exc:
            failures.append(f"engine module not importable: {module_path} — {exc}")
            continue

        for func_name, expected_params in funcs.items():
            fn = getattr(module, func_name, None)
            if fn is None:
                failures.append(f"{module_path}.{func_name} — function missing")
                continue
            if not callable(fn):
                failures.append(f"{module_path}.{func_name} — not callable")
                continue

            # Signature: parameter names match the declared contract.
            actual_params = list(inspect.signature(fn).parameters.keys())
            if actual_params != expected_params:
                failures.append(
                    f"{module_path}.{func_name} — signature mismatch: "
                    f"expected {expected_params}, got {actual_params}"
                )

            # Behavior expected of a Session 1 stub: raise NotImplementedError.
            thunk = CALL_THUNKS.get((module_path, func_name))
            if thunk is None:
                failures.append(
                    f"{module_path}.{func_name} — test has no call thunk"
                )
                continue
            try:
                thunk(module)
                failures.append(
                    f"{module_path}.{func_name} — did not raise "
                    f"NotImplementedError (Session 1 stubs must)"
                )
            except NotImplementedError:
                stub_count += 1
            except Exception as exc:
                failures.append(
                    f"{module_path}.{func_name} — raised {type(exc).__name__} "
                    f"instead of NotImplementedError: {exc}"
                )

    if failures:
        print("FAIL: v5.4.0 engine-stub shape test")
        for f in failures:
            print(f"  - {f}")
        return 1

    if ENGINE_SPEC:
        print("PASS: v5.4.0 engine module stubs present and well-formed")
        print(f"  {len(ENGINE_SPEC)} engine modules importable; {stub_count} "
              f"stub functions, all raising NotImplementedError")
    else:
        print("PASS: all v5.4.0 engine stages implemented — no stubs remain; "
              "contract package and inter-stage dataclasses import cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
