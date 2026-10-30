# R01 configuration usage and effective-policy inspection

> **Historical document / point-in-time snapshot:** This page preserves its original planning, inventory, findings or policy questions from its dated baseline. Some approvals, source values, lease wiring and stop integrations progressed afterward on `feature/live-activation-guardrails-20261030`. For **current branch status, approved R01 boundaries, integration coverage and activation blockers**, consult [the 2026-10-30 canonical release record](CURRENT_IMPLEMENTATION_STATUS_20261030.md). No recent R01/LIVE/unified-stop regression tests or supervised broker UAT have run; the feature flag remains disabled. Do not treat old “pending” or “passed” statements as new acceptance results.

**Scope:** facts observed in source on 2026-10-29, based on original `main` code. The tool does not create a trader, read broker funds, consult an AI, inspect active positions, or authorize any orders.

## Read-only diagnostics (new)

Run later, from anywhere with this repository's Python environment:

```bash
python -m tools.policy_report
python -m tools.policy_report --format json
python -m tools.policy_report --validate-config --strategy macd_momentum
python -m tools.policy_report --format json --broker kite --ai-mode rules
```

`--validate-config` checks **only a documented subset of inventoried keys and selected CLI/JSON fields**. A zero exit status does **not** certify live trading safety, configuration completeness, broker correctness, or successful risk enforcement.

Report contains immutable `TradingPolicySnapshot` / `PolicyObservation` records, a stable SHA256 of **inspected nonsecret values only**, source/provenance, code-observed guardrails and caveats. It reports possible caps, not guaranteed effective live positions. The digest is **not** wired into OMS intents or live risk evaluation; future runtime integration requires an ADR and parity evidence. It writes nothing.

## Actual source precedence

| Subject | CLI | Environment | JSON | Code-observed behavior |
| --- | --- | --- | --- | --- |
| Strategy | `--strategy` | `STRATEGY_MODE` | `strategies.active_strategy` | `load_configuration()` picks the first truthy name; unknown profile fallback, with special requested missing MACD guard |
| Consultation mode | `--ai-mode` | `AI_CONSULTATION_MODE` | `strategies.ai_consultation.default_mode` | Disabled rejected; `rules`/`playbook` deterministic vs `chat` companion; gate mandatory |
| Execution adapter | `--broker` | `EXECUTION_BROKER` | — | default `proxy`, native Kite/Breeze require explicit `--live`, verified account + gateway arming |
| Data adapter | `--market-data-broker` | `MARKET_DATA_BROKER` | — | default Kite and independent of execution adapter |
| Entry quantity | `--quantity` / `--lots` | `MAX_ORDER_QUANTITY` low-priority fallback | `strategy.compounding.max_order_quantity` then `trading.risk.max_order_quantity` | `trading/domain/sizing.py` uses truthy precedence; `position_lifecycle._submit_entry` applies strategy/global cap, affordability and absolute 650 |
| Available capital | — | Broker authentication | `risk.account_equity` (also documented ₹10k) | `position_lifecycle._submit_entry` reads actual broker `available_margin` and subtracts ₹150; static equity is not verified purchasing power |
| Entry cutoff | — | — | `session.no_new_trade_after=14:45` | `position_lifecycle._submit_entry` enforces hard 14:15 and min(configured,hard) in LIVE; `MarketClock` has 14:15 trap |
| Force exit | — | — | `session.force_exit_time=15:20` | HARD_SQUARE_OFF=15:15, but broker outage can delay actual closure |
| Daily entries | — | — | `risk.max_trades_per_day=5` | `CycleWorkflow` uses MAX_DAILY_ENTRIES=10 and `PositionLifecycle` uses strategy `entry.max_daily_entries` (MACD=2) |
| Premium (existing behavior vs owner direction) | — | — | `option_selection.min_option_premium=15`, `max_option_premium=135` | EntryPolicy enforces price bounds and candidate selection uses the upper cap; `ai_consultant.py` has a sub-₹12 0DTE penny veto. **Owner has rejected penny-option/spot-level price-band bias for future policy. These old runtime gates still exist and must be reviewed separately before changing LIVE trading.** Affordability must still use the actual option execution price and verified broker purchasing power. |
| Maximum lots | — | — | `risk.max_lots_per_trade=1` vs active MACD `compounding.max_lots_cap=10` | `calculate_compounding_quantity` reads *strategy* lots cap, not global risk lots setting in this function |
| Arming and kill switch | `--live` | — | `mode=LIVE`, `system_armed=true`, `auto_trade_enabled=true`, `kill_switch=false` | Native mutation requires the CLI and broker/account checks; JSON flags alone are not proof of actual arming |
| Calendar/expiry | — | `MARKET_INSTRUMENTS_FILE` optional | `option_selection.exchange_holidays` | Market master and contract selectors also validate availability; calendar correctness not proven |
| Strategy trailing/stops | Strategy/profile | — | `strategies.*.exit`, `trading.risk.*` | Multiple active strategy paths; requires scenario-by-scenario characterization, no flattening yet |

## Important distinction: source evidence vs effective behavior

The command reports static source-backed rules, not the dynamic result of a live order. Example: active MACD strategy advertises a 650-contract compounding ceiling; the global config advertises 65. The selected strategy cap has truthy precedence in currently reviewed code, while buying power, requested quantity, available quotes, existing exposure, and the hard MAX_POSITION_QUANTITY further restrict submitted quantity. Calling “65” a universally enforced hard cap would be inaccurate.

**Do not change configured values in this structural increment.**

## R01 status

- R01.1 configuration map: **implemented for high-risk keys as this map + read-only inspection**; remainder of unreferenced JSON keys is still to be audited.
- R01.2 POL-01..08: **pending explicit owner approval**. See `POLICY_DECISIONS.md`.
- R01.3 typed immutable inspection view: **implemented in isolation**, NOT wired into live per-cycle policy or event hashes.
- R01.4 read-only `python -m tools.policy_report` with `--validate-config`: **implemented for inventoried keys only**; deliberately not a new scheduler flag.
- R01.5 runtime policy hash and live intent stamping: **deferred** pending owner policy and compatibility evidence.
- R01.6 safer boot validation: **deferred** because changing invalid-config runtime fallbacks would change trading behavior.

### Review and follow-up

Tests were added and registered, **but deliberately not run** per owner instruction. Revisit after approved policy ADRs and offline acceptance, then integrate typed policy and stronger validation behind a feature gate or compatibility adapter in separate PRs.
