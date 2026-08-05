# v5.4.0 pending behavioral specs

**All v5.4.0 behavioral specs have been promoted.** This directory holds no
pending specs — every executable behavioral spec for the v5.4.0 staged pipeline
engine now lives in `scaffold/tests/v5_4_0/` and runs in the default gate
(`scaffold/tests/run_all.py`).

## What these were

These were executable behavioral specs for the v5.4.0 staged pipeline engine —
each imports a real engine module, calls it on a real input, and asserts on the
real output. They are **not** doc-presence checks. (The doc-presence pattern in
`scaffold/tests/v5_3_0/` is exactly the gap escalation ESC-002 exposed: the
§16-§20 contracts shipped as documentation with passing doc-presence tests
while the executable pipeline behind them was never built. v5.4.0 built that
engine; these specs prove it behaves.)

Through Sessions 1-3 the specs were quarantined here, red, until the engine
stage each one binds was implemented — wiring a red spec into `run_all.py`
would have broken the default gate. Each session promoted its spec(s) once the
stage was implemented and the spec passed.

## Promotion schedule — complete

| Session | Implements | Spec(s) — all promoted to `scaffold/tests/v5_4_0/` |
|---|---|---|
| Session 2 ✅ | §17 debtor party engine | `test_debtor_party_engine_behavior.py`, `test_filer_suppression_behavior.py` |
| Session 3 ✅ | §18 aggregation key engine + leads-base writer | `test_aggregation_key_behavior.py` |
| Session 4 ✅ | §19 idempotent aggregator | `test_aggregator_idempotent_behavior.py` |
| Session 5 | cutover | (all specs promoted; monolith retired) |

The §17 / §18 / §19 engine behavior is now gated by those promoted specs plus
the per-stage unit tests in `scaffold/tests/v5_4_0/`. The Session 5 cutover
retires the monolith; no behavioral spec remains pending.
