# R01 policy decision register (unapproved)

These are **review items, not instructions to change runtime trading behavior**. Compare `docs/TRADING_ENGINE_REFACTOR_MASTER_PLAN.md` and `docs/ARCHITECTURE_REVIEW.md`.

| ID | Conflicting or incomplete evidence | Owner decision | Interim treatment |
| --- | --- | --- | --- |
| POL-01 | `AGENTS.md` step ladder 2–10 lots; global `risk.max_order_quantity=65`; active `macd_momentum.compounding.max_order_quantity=650` and `max_lots_cap=10`; `position_lifecycle.py` gives strategy cap precedence | Approve strategy-by-strategy maximum and whether global cap is actually hard | Do not change precedence or increase size silently |
| POL-02 | `config/trading.json` 14:45 entry / 15:20 force exit; `trading/domain/limits.py` 14:15 / 15:15; `MarketClock` has further lockout | Explicit hard session policy and cutoff ownership | Keep current sequence and thresholds |
| POL-03 | `config/trading.json` ₹135 max option premium, `EntryPolicy` default ₹70 when missing config, `AGENTS.md`/playbook ₹12/₹30 penny-trap text | Approve per-strategy premium/0DTE veto rules | Report each source, do not flatten |
| POL-04 | ₹10,000 baseline in `AGENTS.md`, ₹500,000 `risk.account_equity`, broker margin checked by `position_lifecycle.py` | Separate paper equity assumptions from live purchasing-power evidence | Preserve broker-funded limit |
| POL-05 | `risk.max_trades_per_day=5`, shared `MAX_DAILY_ENTRIES=10`, active strategy `entry.max_daily_entries=2` | Approve global, strategy and actual order-count definitions | Preserve all existing gates |
| POL-06 | Configurable trailing, stop floors and optional stop consultation; different strategy behavior | Approve policy semantics and safety invariants | No stop/target tuning |
| POL-07 | JSON `mode=LIVE`, `system_armed=true`, `auto_trade_enabled=true`, `kill_switch=false`; native CLI `--live` and broker authorization | Define independent operator arming and kill switch contract | No arming change |
| POL-08 | Static `exchange_holidays` vs instrument-master expiry and session rules | Confirm authoritative exchange calendar and validation | Preserve current data checks |

**Status:** all proposed, **none approved**. Complete an ADR using `docs/adr/ADR_TEMPLATE.md` before any business-rule change. Owner decision and signed-off before/after scenarios required.

## Source precedence currently observed

- Strategy selection: CLI `--strategy` → `STRATEGY_MODE` environment → `config/strategies.json.active_strategy` → fallback; unknown profile falls back except specifically requested missing `macd_momentum` raises.
- AI consultation mode: CLI `--ai-mode` → `AI_CONSULTATION_MODE` environment → `config/strategies.json.ai_consultation.default_mode` → playbook fallback; disabled is rejected.
- Execution broker: CLI `--broker` → `EXECUTION_BROKER` → proxy; native Kite/Breeze require `--live` and account verification.
- Market-data broker: CLI `--market-data-broker` → `MARKET_DATA_BROKER` → kite; independent of execution broker.
- Entry quantity: strategy compounding `max_order_quantity` truthy value → trading `risk.max_order_quantity` truthy value → env/default; then affordability and `MAX_POSITION_QUANTITY`; explicit CLI quantity affects baseline calculation.
- **Trading JSON errors:** `trading/configuration.py` currently logs and falls back to an empty dict; changing to startup-fatal is a POLICY/OPERATIONS behavior change, not an automatic structural cleanup.

Further key-by-key analysis and the read-only report are documented in `docs/architecture/POLICY_USAGE_MAP.md`.
