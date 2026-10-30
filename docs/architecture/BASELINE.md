# R00 baseline and compatibility contract

> **Historical document / point-in-time snapshot:** This page preserves its original planning, inventory, findings or policy questions from its dated baseline. Some approvals, source values, lease wiring and stop integrations progressed afterward on `feature/live-activation-guardrails-20261030`. For **current branch status, approved R01 boundaries, integration coverage and activation blockers**, consult [the 2026-10-30 canonical release record](CURRENT_IMPLEMENTATION_STATUS_20261030.md). No recent R01/LIVE/unified-stop regression tests or supervised broker UAT have run; the feature flag remains disabled. Do not treat old “pending” or “passed” statements as new acceptance results.

**Captured:** 2026-10-29. **Scope:** repository source inspection; no code execution, tests, broker reads or credential access.  
**Reference:** `main` commit `92da61d2a5c5a1ae5d5e7477db0027f196fb7c5f`; master plan `plan/trading-engine-modernization-20261029` commit `eb574da98d9452f26c3169d5134e16d39579e36d`.  
**Independent unmerged OMS patch:** `refactor/trading-engine-architecture-20261029` commit `bc5a4b644041eae0ae5f51dfe1d0fabb2db92d17`. It has not been merged into this R00/R01 branch; tests were not executed for it.

## Application boundaries already present

| Responsibility | Existing entrypoint / implementation |
| --- | --- |
| CLI bootstrap | `nifty_trader_scheduler.py` delegates to `trading/application/scheduler.py` |
| Session control | `trading/application/workflows.py`, `trading/application/entry.py` |
| Strategy and signal selection | `trading/strategies/{registry,macd_momentum,radar,legacy}.py`, `trading/application/selection.py` |
| Decision risk, pricing and sizing | `entry_policy.py`, `trading/domain/{limits,sizing,prices}.py`, `ai_consultant.py` |
| OMS reconciliation/entry/exit | `position_lifecycle.py`, `trading/application/stop_manager.py`, `trading/application/position_monitor.py` |
| Durable state | `trading/adapters/position_store.py` and `trading/adapters/gateways/journal.py` |
| Broker execution | `execution_client.py` proxy, `trading/adapters/gateways/{base,kite,breeze}.py` |
| Market data | `trading/adapters/{market_data,market_sources,kite_stream}.py`, `trading/application/market_context.py` |
| Replay/research | `trading/replay.py`, `backtest_engine.py`, `trading/hybrid_research.py` |
| Infrastructure | `trading/{ports,models,bootstrap,configuration,audit,logging_setup}.py` |

See `SCRIPT_INVENTORY.md` for the root-script classification; names alone do not certify safety.

## Behavior and interfaces intentionally frozen

- Existing `AIConsultant.evaluate(dossier)` veto, expiration, identity and trap requirements; rules/playbook are deterministic, chat mode uses an external neural companion.
- `nifty_trader_scheduler.py` CLI flags; strategy names, input/output dictionaries, and broker method contracts.
- Existing order routes and mutation retries; broker tags, durable request IDs, verified partial fills, stop adjustment, pending exit recovery and record schemas.
- Position JSON schema-v2 and gateway-journal schema-v1; legacy singular order-ID aliases.
- Actual runtime cutoffs and sizing/affordability calculations **as implemented**; do not substitute nominal config values.
- Order book authority, stale-quote restrictions, mandatory square-off and no-new-exposure on uncertainty.
- No default to live execution based on a merely configured string; explicit native `--live` remains required.

### Contract references

See `tests/fixtures/oms_reference.json` (`filled`, `partial_cancelled`, `unknown_submit`), `tests/fixtures/staged_reference.json`, `staged_approved_reference.json`, `staged_extra_reference.json`, `indicators_reference.json`, `replay_example.json` and `tests/fixtures/PATH_A_POLICY.md`. These are existing reference artifacts, **not newly generated fixtures**. Baseline parity must be measured when tests are run later.

## R00 scope completed in this branch

1. Documented current architectural entrypoints and critical invariants.
2. Catalogued repository-owned top-level scripts and restricted imports in `SCRIPT_INVENTORY.md`.
3. Indexed existing golden fixtures and missing safety cases in `FIXTURE_MATRIX.md`.
4. Added ADR template, policy decision register, risk register and PR review checklist.
5. Added a **read-only** effective policy inspection command in R01, separate from runtime code.

## Scope not yet completed

- Owner approval of contradictory trading policies, broker-specific UAT, true process crash/fill traces, production-safe rollout and all full regression checks.
- The earlier OMS hardening branch is not merged here; choose a tested integration order before landing either branch on `main`.
- No policy change, migration, scheduler import or broker order call was performed.

## Next merge gate

Only merge the documentation/report increment after owner inspection, optional offline verification (`python -m tools.checks` and `python -m tools.quality`), and a comparison against current `main`. Preserve execution behavior. Structural and policy modifications require separate PRs.
