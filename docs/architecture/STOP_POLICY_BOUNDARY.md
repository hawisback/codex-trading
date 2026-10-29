# Shared stop-management boundary — POL-06 design checkpoint

**Current state:** Pure floor calculations extracted, actual broker-side stop decisions and all existing strategy-supplied stop values unchanged. No tests executed.

## Present module ownership

- `trading/domain/protection.py`: pure, deterministic stop references, existing stop floor and tick-rounded initial trigger.
- `trading/domain/stop_loss.py`: validation of existing explicit post-fill stop policies, pricing bands and structural invalidation.
- `trading/domain/trailing.py`: session windows, progressive floors, runner reference calculations (currently from selected strategy exit configuration).
- `trading/application/stop_manager.py`: write-ahead STOP/MODIFY/CANCEL intents, broker status confirmation, no-duplicate-SELL and reconnect protection.
- `trading/application/position_monitor.py`: look at approved price/market context, decide whether a trailing trigger is warranted; delegates mutation to OMS stop manager.
- `position_lifecycle.py`: scope, true residual exposure, entry/exit orchestration, monitor quote freshness and durable state.

## User-approved direction, numeric details still open

The owner wants **a single stop-loss and trailing policy across all strategies**. The policy may differ by *market time in IST*, but **must not depend on strategy name**. The owner has NOT yet approved a universal initial stop percentage, morning/midday/late-day thresholds, gain floors, pullback, protective sell price buffer or stop modification cadence. Existing per-strategy configs are not a valid automatic universal default.

Future solution should keep a versioned common `StopPolicySnapshot` identified on each newly opened position, with an explicit migration rule for open positions. Changes must not lower a confirmed trigger floor or permit competing exits. Initially validate against historical traces, then implement behind a compatibility mode with broker-specific stop UAT.

## Changes intentionally deferred

- Move legacy `strategy.exit` values out of `config/strategies.json` after owner signs a single schedule and trace/rollback matrix.
- Change initial stop %, trailing activation %, time-window boundaries, stale-quote timeouts, tick buffer and modification limits.
- Inject blanket “always live” mode or bypass consultation.
- Move `position_lifecycle.py` while recovery/state-path dependencies remain ambiguous.

**Safety rule:** structural extraction may relocate the *calculation* but must not authorize a new network mutation or relax an existing preflight.
