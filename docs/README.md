# Documentation index — NIFTY options engine

> **Current as of 2026-10-30 on** `feature/live-activation-guardrails-20261030`. This index is the entry point for engineering decisions and the release gate. **The branch is not merged or deployed; R01 is disabled and the new LIVE/stop integration has not been tested or broker-UAT verified.** Retain the owner's standing prohibition on running tests until explicitly lifted.

## Read these first (current working-branch facts)

| Purpose | Document | What it establishes |
| --- | --- | --- |
| Branch and release truth | [Current implementation status](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md) | New R01/guardrail/unified stop implementation versus remaining verification and broker contracts |
| Real-money release blockers | [LIVE activation hold](architecture/LIVE_ACTIVATION_HOLD_20261030.md) | Missing authenticated day P&L, instrument freeze limits, source-of-truth calendar/master, tests and UAT |
| R01 policy activation contract | [R01 activation runbook](architecture/R01_ACTIVATION_RUNBOOK.md) | Exact broker fields, lot and risk policy, enabled flag and rollback constraints |
| Unified position stops | [R01 unified stop execution](architecture/R01_UNIFIED_STOP_EXECUTION.md) | Stamped per-position policy, strategy-neutral stop schedule, broker OMS and freshness |
| Human operations | [R02–R10 operator runbook](operations/REFACTOR_OPERATOR_RUNBOOK.md) | Single-writer ownership, unknown orders, uncovered residuals, startup/rollback/square-off; **draft, untested** |
| Broker setup and limitations | [Broker integrations](BROKER_INTEGRATIONS.md), [native safety](NATIVE_GATEWAY_SAFETY.md) | Authenticated session, account lease, funds provenance, exclusions from P&L/freeze data |
| Persistence and order recovery | [OMS recovery](OMS_RECOVERY.md) | Position/state, stop and exit reconciliation; adverse-event validation still open |
| Behavior of **legacy** positions | [Trailing stops](TRAILING_STOPS.md), [MACD session rules](MACD_SESSION_RULES.md) | Original strategy-specific paths and the R01 difference |
| Engineering quality procedure | [CONTRIBUTING.md](../CONTRIBUTING.md), [fixture matrix](architecture/FIXTURE_MATRIX.md), [change review checklist](architecture/CHANGE_REVIEW_CHECKLIST.md) | Exact offline suite, case coverage, validation-before-merge; no new suite executed |

## Historical/baseline material (do not use as a current release verdict)

- [2026-10-29 R02–R10 implementation snapshot](architecture/REFACTOR_DELIVERY_STATUS_20261029.md), [R01 policy status snapshot](architecture/R01_POLICY_IMPLEMENTATION_STATUS.md), [original owner directions](architecture/OWNER_POLICY_DIRECTIONS_20261029.md), [R01 policy decision register](architecture/POLICY_DECISIONS.md).
- [Original master modernization plan](TRADING_ENGINE_REFACTOR_MASTER_PLAN.md), [R00 baseline](architecture/BASELINE.md), [read-only policy usage map](architecture/POLICY_USAGE_MAP.md), [configuration inventory](architecture/CONFIG_KEY_REFERENCE_INDEX.md) and [engineering risk register](architecture/RISK_REGISTER.md).
- [Staged refactor record](STAGED_REFACTOR.md), [original architecture review](ARCHITECTURE_REVIEW.md) and [first OMS boundary change](OMS_BOUNDARY_REFACTOR.md).
- Historical performance/backtest narratives and AI operating descriptions elsewhere under `docs/` reflect the circumstances of their captures; they are **not** evidence that the later R01 logic, live broker execution or stop recovery has been verified.

## Additional focused reference

- [Entry execution and price bands](ENTRY_EXECUTION.md) — includes a warning about older examples versus current JSON and R01 opt-in behavior.
- [Market data](MARKET_DATA.md), [news worker](NEWS_WORKER.md) and [daily logs](DAILY_LOGS.md) — subsystem descriptions, not release certificates.
- [AI architecture directive](AI_ARCHITECTURE_AND_DIRECTIVE.md), [AI companion pair trading](AI_COMPANION_PAIR_TRADING.md) — consultation and mode descriptions, not authorization to bypass approval/veto or launch `--live`.

**Source code, authenticated broker books, and executed acceptance evidence take precedence over an old document's claims of activation or safety.** Never infer LIVE status from `mode: LIVE` or `system_armed: true` alone.
