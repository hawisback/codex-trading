# Production readiness — R01 / LIVE guardrails (2026-10-30)

**Release gate: BLOCKED.** This file provides the production-readiness pointer expected by the earlier modernization plan. It is a release checklist, **not a certification or a command to activate LIVE**.

**Code under review:** `hawisback/codex-trading` · `feature/live-activation-guardrails-20261030`. Current `r01_policy.enabled=true` with `auto_trade_enabled=false` prepares a paused start; `main` has not received this increment and no production rollout has been established.

**Current release scope: Kite only.** The owner deferred Breeze; its HTTP 401
issue is outside this release's acceptance gates. Kite account/API reads and
live read-only market conformance pass. Kite R01 risk/contract/calendar source acceptance also passes; actual order UAT
remains pending. The deployment target is this Windows machine; no CI or
additional deployment/security project is required.

| Gate | Status as of 2026-10-30 | Evidence still required |
| --- | --- | --- |
| Owner implementation review | **Reviewed** | Review of exact final release commit after all integration fixes |
| Kite account and market read conformance | **PASS** | Authenticated funds/positions/orders and live market checks passed; this does not establish R01 risk evidence or order execution acceptance |
| R01 unified stop integration | **OFFLINE PASS** | Real broker acceptance of initial protection, ratchets, restart and amendments; see [validation record](architecture/OFFLINE_VALIDATION_20261030.md) |
| Account-day P&L and buying power | **READ-ONLY PASS** | Account-matched margins plus net/day positions reconciled with daily fills; cash cap uses each new entry's actual lots, not opening equity |
| Contract-specific order freeze | **READ-ONLY PASS** | Exact Kite NIFTY master lot/tick and current published NSE freeze feed with source hashes; broker RMS acceptance remains part of UAT |
| Expiry / market master | **READ-ONLY PASS** | Current Kite listed expiry, NSE FO holiday calendar and R05 entry resolver; conservative regular weekday sessions only, matching calendar year required |
| OMS single-writer and recovery | **NATIVE OFFLINE PASS / UAT OPEN** | Native process exclusion, crash release and recovery fixtures pass; proxy/distributed boundary and actual broker recovery remain unverified |
| Registered offline tests and replay | **PASS LOCALLY: 574 tests** | Windows/Python 3.14.6 quality wrapper passed; base repairs were committed as `23df96f`; subsequent paused-configuration/reporting changes require their own validation; other environments are outside scope |
| Codex companion | **OFFLINE + CANARY PASS** | Explicit CLI invocation, request-bound application publication and failure tests pass; actual broker chat-mode acceptance remains pending |
| Operator entry pause | **OFFLINE PASS** | Fresh control reads and BUY-boundary enforcement; protective stop/exit paths remain active |
| Supervised broker UAT | **NOT RUN** | Verified protected order lifecycle, actual broker response semantics and supervised incident/rollback drills |
| Local startup/rollback | **PROCEDURE PREPARED** | [Operator-run acceptance and recovery](operations/KITE_LOCAL_ACCEPTANCE_20261030.md); actual broker acceptance is still pending |

## Safe review sequence

1. Review [current branch status](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md), [LIVE blockers](architecture/LIVE_ACTIVATION_HOLD_20261030.md), [R01 activation contract](architecture/R01_ACTIVATION_RUNBOOK.md) and [unified stops](architecture/R01_UNIFIED_STOP_EXECUTION.md).
2. Recheck current-session Kite P&L/order-freeze/expiry evidence. Read-only integration passes; existing broker account identity, risk and single-writer protections remain mandatory.
3. Review the [executed offline validation](architecture/OFFLINE_VALIDATION_20261030.md). The owner authorized these tests; revalidate changes to the final release candidate and record its source fingerprint.
4. Conduct controlled broker conformance/UAT and restart/rollback drills with approved operator controls. Never infer a fill or flatness from an API acknowledgement alone.
5. After broker acceptance passes, the operator can perform the controlled local activation. R01 is configured on with new entries paused; the assistant has not armed a gateway or started the scheduler.

`python -m tools.refactor_readiness` is a **read-only, deliberately BLOCKED** preflight and does not check broker authorization or place trades. An optimistic JSON flag or passing syntax check cannot replace any gate.

**Offline tests passed for the local repair candidate. No real broker orders or supervised UAT were executed.**
