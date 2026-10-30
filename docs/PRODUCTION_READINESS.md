# Production readiness — R01 / LIVE guardrails (2026-10-30)

**Release gate: BLOCKED.** This file provides the production-readiness pointer expected by the earlier modernization plan. It is a release checklist, **not a certification or a command to activate LIVE**.

**Code under review:** `hawisback/codex-trading` · `feature/live-activation-guardrails-20261030`. Current `r01_policy.enabled=false`; `main` has not received this increment and no production rollout has been established.

| Gate | Status as of 2026-10-30 | Evidence still required |
| --- | --- | --- |
| Owner implementation review | **Reviewed** | Review of exact final release commit after all integration fixes |
| R01 unified stop integration | **Coded, not verified** | Offline scenario parity for all strategies, tick/quote/IST boundaries, stronger floors, recovery, restart and broker stop amendments |
| Account-day P&L and buying power | **BLOCKED** | Authenticated verified start-of-day equity, realized/unrealized P&L, correct account/session/time and actual available funds |
| Contract-specific order freeze | **BLOCKED** | Current contract-specific broker/exchange quantity maximum with provenance; no guessed 65/650 |
| Expiry / market master | **BLOCKED** | Authoritative current exchange calendar and account-specific broker instrument master integrated with R05 |
| OMS single-writer and recovery | **PARTIAL / UNVERIFIED** | Native per-account OS lease coded; verify multi-process/native/proxy boundary, unknown ACK, partial fill, crash, cancel/replacement/exit and restart |
| Complete offline tests and replay | **NOT RUN** | Owner changes prior no-tests direction, then runs offline suite and records results without broker orders |
| Supervised broker UAT | **NOT RUN** | Verified protected order lifecycle, actual broker response semantics and supervised incident/rollback drills |
| Deployment/rollback sign-off | **NOT APPROVED** | Exact commit, named authorized operator and account, kill switch, risk bounds, monitoring, rollback procedure and broker flatness criteria |

## Safe review sequence

1. Review [current branch status](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md), [LIVE blockers](architecture/LIVE_ACTIVATION_HOLD_20261030.md), [R01 activation contract](architecture/R01_ACTIVATION_RUNBOOK.md) and [unified stops](architecture/R01_UNIFIED_STOP_EXECUTION.md).
2. Complete source integration for genuine broker P&L/order-freeze/expiry evidence and reconcile every OMS LIVE entrypoint without assuming other processes are fenced.
3. Only after explicit separate authorization, execute the **offline** regression suite under isolated no-order transports; record failures/fixes and the validated commit SHA.
4. Conduct controlled broker conformance/UAT and restart/rollback drills with approved operator controls. Never infer a fill or flatness from an API acknowledgement alone.
5. Obtain distinct final go-live approval. Only then consider merging, enabling `r01_policy` and controlled native `--live` arming.

`python -m tools.refactor_readiness` is a **read-only, deliberately BLOCKED** preflight and does not check broker authorization or place trades. An optimistic JSON flag or passing syntax check cannot replace any gate.

**No tests or broker orders were run in this documentation update.**
