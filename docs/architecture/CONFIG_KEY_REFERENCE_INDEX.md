# R01.1 — Static configuration key reference index

> **Historical document / point-in-time snapshot:** This page preserves its original planning, inventory, findings or policy questions from its dated baseline. Some approvals, source values, lease wiring and stop integrations progressed afterward on `feature/live-activation-guardrails-20261030`. For **current branch status, approved R01 boundaries, integration coverage and activation blockers**, consult [the 2026-10-30 canonical release record](CURRENT_IMPLEMENTATION_STATUS_20261030.md). No recent R01/LIVE/unified-stop regression tests or supervised broker UAT have run; the feature flag remains disabled. Do not treat old “pending” or “passed” statements as new acceptance results.

**Source:** `config/trading.json`, baseline `92da61d`. **Method:** quoted-string search in 10 high-relevance runtime modules. This is **not** proof that a key is enforced; indirect uses and other files are not included. No modules were imported or run.

## risk (27 keys)

| Config key | JSON value | Literal references in inspected sources |
| --- | --- | --- |
| `max_lots_per_trade` | `1` | *Not found in inspected sources* |
| `max_order_quantity` | `65` | `position_lifecycle.py:669`, `position_lifecycle.py:670`, `trading/domain/sizing.py:26`, `trading/domain/sizing.py:27` |
| `entry_order_timeout_sec` | `10` | `entry_policy.py:87` |
| `breakeven_buffer_points` | `2` | *Not found in inspected sources* |
| `max_trades_per_strategy_per_day` | `5` | *Not found in inspected sources* |
| `max_trade_capital` | `50000` | *Not found in inspected sources* |
| `risk_per_trade_pct_of_account` | `0.5` | *Not found in inspected sources* |
| `max_daily_loss_r` | `2` | *Not found in inspected sources* |
| `max_daily_loss_pct` | `1.5` | *Not found in inspected sources* |
| `max_failed_trades_per_strategy` | `2` | *Not found in inspected sources* |
| `max_trades_per_day` | `5` | *Not found in inspected sources* |
| `max_concurrent_positions` | `1` | *Not found in inspected sources* |
| `cooldown_after_loss_min` | `10` | *Not found in inspected sources* |
| `option_hard_stop_pct` | `25` | *Not found in inspected sources* |
| `broker_protective_stop_limit_buffer_pct` | `10` | *Not found in inspected sources* |
| `broker_protective_stop_max_failures` | `2` | *Not found in inspected sources* |
| `broker_protective_stop_cancel_timeout_sec` | `5` | *Not found in inspected sources* |
| `broker_protective_stop_cancel_max_attempts` | `3` | *Not found in inspected sources* |
| `account_equity` | `500000` | *Not found in inspected sources* |
| `paper_slippage_points` | `0` | *Not found in inspected sources* |
| `paper_brokerage_per_order` | `20` | *Not found in inspected sources* |
| `paper_exchange_charge_rate` | `0.0003503` | *Not found in inspected sources* |
| `paper_stt_sell_rate` | `0.001` | *Not found in inspected sources* |
| `paper_gst_rate` | `0.18` | *Not found in inspected sources* |
| `paper_sebi_charge_rate` | `0.000001` | *Not found in inspected sources* |
| `paper_stamp_buy_rate` | `0.00003` | *Not found in inspected sources* |
| `paper_cost_assumption_version` | `"paper_options_costs_v1"` | *Not found in inspected sources* |

## session (4 keys)

| Config key | JSON value | Literal references in inspected sources |
| --- | --- | --- |
| `strategy_b_no_new_trade_before` | `"09:25"` | *Not found in inspected sources* |
| `no_new_trade_before` | `"09:20"` | `position_lifecycle.py:621`, `trading/application/entry.py:16` |
| `no_new_trade_after` | `"14:45"` | `position_lifecycle.py:622`, `trading/application/entry.py:17` |
| `force_exit_time` | `"15:20"` | *Not found in inspected sources* |

## execution (9 keys)

| Config key | JSON value | Literal references in inspected sources |
| --- | --- | --- |
| `entry_buffer_pct` | `5` | `entry_policy.py:75` |
| `climax_entry_buffer_pct` | `3` | `entry_policy.py:76` |
| `entry_downside_buffer_pct` | `8` | `entry_policy.py:77` |
| `marketable_limit_ticks` | `1` | `entry_policy.py:79` |
| `max_slippage_ceiling_pts` | `4` | `entry_policy.py:78` |
| `max_entry_quote_age_seconds` | `3` | `entry_policy.py:80` |
| `entry_quote_timeout_sec` | `3` | `entry_policy.py:81` |
| `ai_approval_ttl_seconds` | `15` | `entry_policy.py:82` |
| `max_entry_candidate_age_seconds` | `60` | `entry_policy.py:83` |

## option_selection (15 keys)

| Config key | JSON value | Literal references in inspected sources |
| --- | --- | --- |
| `max_option_premium` | `135` | `entry_policy.py:85`, `trading/application/selection.py:106` |
| `min_option_premium` | `15` | `entry_policy.py:84` |
| `max_otm_strikes` | `4` | `trading/application/selection.py:147` |
| `min_open_interest` | `10000` | *Not found in inspected sources* |
| `max_bid_ask_spread_pct` | `3` | `entry_policy.py:86` |
| `prefer_premium_closest_to_cap` | `true` | *Not found in inspected sources* |
| `use_current_expiry_on_0dte` | `false` | *Not found in inspected sources* |
| `preferred_delta_min` | `0.6` | *Not found in inspected sources* |
| `preferred_delta_max` | `0.65` | *Not found in inspected sources* |
| `allowed_delta_min` | `0.55` | *Not found in inspected sources* |
| `allowed_delta_max` | `0.7` | *Not found in inspected sources* |
| `minimum_expiry_sessions_remaining` | `2` | *Not found in inspected sources* |
| `max_quote_age_seconds` | `30` | *Not found in inspected sources* |
| `minimum_volume` | `0` | *Not found in inspected sources* |
| `exchange_holidays` | `list (1)` | `market_clock.py:108`, `nifty_trader_scheduler.py:130`, `nifty_trader_scheduler.py:138` |

## How to interpret this inventory

- Presence means a literal source reference, **not** actual runtime effect, enforcement, or correct precedence.
- Absence means **not found among the inspected modules**, not unused globally. Review adapters, research, transitive readers and dynamic key access before concluding.
- The verified-by-reading effective paths for high-risk settings are documented in `POLICY_USAGE_MAP.md`; values requiring owner sign-off remain in `POLICY_DECISIONS.md`.
- Do not treat configured daily loss, failed-trade or cooldown limits as live protections without tracing enforcement.
- All policy configuration values remain unchanged. No tests or live code were executed.
