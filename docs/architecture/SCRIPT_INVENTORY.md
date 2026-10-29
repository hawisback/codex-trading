# R00 repository script inventory

**Source:** tracked root .py files on main at `92da61d`; filename classification only. **No scripts were imported or run.**

Production execution may be reachable from additional imported modules. An audit must inspect import-time effects, network I/O, broker writes, historical DB access and CLI flags before reclassifying any manual script as safe.

### Production/bootstrap and compatibility (9)
- `ai_consultant.py`
- `ai_context_dossier.py`
- `ai_opportunity_radar.py`
- `entry_policy.py`
- `execution_client.py`
- `market_clock.py`
- `market_intelligence.py`
- `nifty_trader_scheduler.py`
- `position_lifecycle.py`

### Research/backtesting/audits (28)
- `audit_60_sessions_ai.py`
- `audit_detailed.py`
- `audit_grand_10weeks.py`
- `audit_june_3weeks.py`
- `audit_last_week_deep.py`
- `audit_pullback_itm.py`
- `audit_sep21_week.py`
- `audit_sep28_week.py`
- `audit_summer_stress_test.py`
- `audit_trade_dossier.py`
- `backtest_ai_opportunity_radar.py`
- `backtest_engine.py`
- `calc_10k_compound.py`
- `calc_50k_oct05_week.py`
- `diagnose_deep_dive.py`
- `fetch_option_candles.py`
- `inspect_oct05.py`
- `run_30_sessions_swing_audit.py`
- `run_60_sessions_official.py`
- `run_backtest_today.py`
- `run_expiry_backtest_3weeks.py`
- `run_last_week_all_strategies.py`
- `run_last_week_spot_fix_backtest.py`
- `run_market_context.py`
- `run_multiweek_audit.py`
- `run_recent_backtest.py`
- `run_today_all_strategies.py`
- `run_today_full_ai_backtest.py`

### Diagnostics/manual test scripts (11)
- `check_kite_transactions.py`
- `check_live_apis.py`
- `test_api_endpoints.py`
- `test_diagnose_trades.py`
- `test_entry_execution.py`
- `test_incremental_trailing.py`
- `test_market_intelligence.py`
- `test_self_healing_exit.py`
- `test_trailing_ladder.py`
- `test_trailing_options.py`
- `verify_data_parity.py`

### Other root Python (1)
- `execution_safety.py`

## Package entrypoints and tool modules

- Application services: `trading/application/*.py`; broker and market adapters: `trading/adapters/**/*.py`; domain logic: `trading/domain/*.py`.
- Explicit standard-library offline check: `python -m tools.checks` (uses `tests/test_regression.py` and `tests/test_architecture.py`).
- Optional quality wrapper: `python -m tools.quality`; read-only market verification: `tools.market_data`, `tools.verify_market_data`, `tools.brokers` (may contact brokers; never call as part of offline checks).
- Replay commands: `tools.replay` / `tools.replay_hybrid`; review their data/AI contracts before execution.
- `start_scheduler.ps1` starts the application; it is not a test.

## Risk categories

| Kind | Default treatment | Next action |
| --- | --- | --- |
| Production boot/compatibility | Characterize calls and startup side effects | Maintain import and CLI compatibility |
| Manual `test_*.py` at repo root | Potential network, filesystem, historical-data or mutation side effects | Do not broad-discover root tests |
| Root audit/backtest/research | May read historical data outside the repository | Identify data sources and archive into `research/` later |
| `tools/*` | Explicitly classify read-only vs network-capable vs mutation-capable | Keep safety opt-in explicit |

**Operator caution:** No evidence of actual production usage is inferred from a filename. The only currently documented production CLI is `nifty_trader_scheduler.py`; retained legacy scripts are **unverified**.
