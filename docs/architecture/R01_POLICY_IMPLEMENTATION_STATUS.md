# R01 policy implementation status — feature branch

**Original implementation:** 2026-10-29, `feature/r01-approved-policy-contracts-20261029`  
**Current integration:** 2026-10-30, `feature/live-activation-guardrails-20261030`  
**Default:** `config/trading.json:r01_policy.enabled=false`  
**Verification:** Python syntax-only inspection performed; tests authored but **not executed**. No broker UAT or LIVE orders. No deployment or merge to `main`.

## Owner decisions implemented in code (explicit opt-in only)

| Policy | R01 implementation |
| --- | --- |
| POL-01 | Available broker margin selects 2/4/6/8/10-lot tiers at ₹20k/₹40k/₹60k/₹80k inclusive bands. Broker-confirmed single-order cap, fresh approved option price, margin, ₹150 reserve, lot size and 650-position hard limit also bound quantity. |
| POL-02 | `config/trading.json` aligned to 14:15 IST no-new-entry and 15:15 IST force-exit trigger, matching existing hard runtime constants. |
| POL-03 | No ₹12/₹30 penny-option veto in opted-in deterministic consultation; absolute ₹15/₹135 premium price bands ignored when enabled. Other AI consultation vetoes, approved entry envelope, quote/spread/expiry/broker affordability stay intact. |
| POL-04 | New opt-in LIVE entries require verified broker margin and matching account identity. Static equity cannot authorize quantity. |
| POL-05 | Reconciled filled entry count ceiling 10 (including MACD); new entries require broker-reconciled session P&L with realized+unrealized loss strictly below existing configured 1.5% of verified start-of-day equity. Missing/mismatched/stale P&L blocks entries. |
| POL-06 | **Integrated** unified calculation through `unified_stop_workflow.py`, `PositionMonitor.manage` and `StopManager.ensure/floor`: a version-stamped R01 position uses one time-aware stop across strategy profiles, freeze-on-entry 25% initial risk and monotonic upward-tick floors. Stamped positions remain on R01 across config reloads; legacy unstamped positions retain previous strategies. Stop/exits still use existing OMS; no regression/UAT pass has been established. |
| POL-07 | Keep explicit native `--live`; Kite/Breeze now also require a verified account-scoped OS owner lease at arming and mutation transport. This local lease is not distributed fencing; no broker UAT. |
| POL-08 | Calendar and broker-master cross-source verification remains the later R05 market data/expiry deliverable; no unsupported calendar-refresh promise or change made in R01. |

## Critical activation limitation

**Do not turn on this flag in production yet.** Current native broker `get_funds()` adapters attach authenticated account/source/local receipt metadata but **do not** provide
`max_single_order_quantity`, account-verified `pnl_asof`,
`pnl_session_date`, `pnl_account_id`,
`start_of_day_equity`, `realized_pnl_today` and
`unrealized_pnl_today`. R01 deliberately denies new LIVE entries
until those broker-side contract fields are present, correct and fresh.

See [current status](CURRENT_IMPLEMENTATION_STATUS_20261030.md), [unified stop contract](R01_UNIFIED_STOP_EXECUTION.md) and [R01_ACTIVATION_RUNBOOK.md](R01_ACTIVATION_RUNBOOK.md) for exact
fields and rollout / rollback constraints; [ADR-0001](../adr/ADR-0001-OWNER-LOT-LADDER.md)
and [ADR-0002](../adr/ADR-0002-NO-PENNY-OPTION-PRICE-BIAS.md)
for the supporting policy direction and legacy filter inventory.

## What is deliberately unchanged

- `main` branch and the currently deployed/live engine.
- The default `enabled=false` sizing, OMS execution, AI veto and stop management.
- Broker order submission/retry/cancel semantics, durable intent IDs,
  unknown outcome reconciliation, current open position treatment.
- The risk of nonfill or outage during square-off remains real.

## Review gates remaining

- Broker P&L and per-order quantity normalized against actual authenticated account.
- Offline test/replay and adverse-order scenario evidence, including boundary capital,
  daily loss, opt-in price-neutral consultation and persistent stop monotonicity.
- Review of old open positions and OMS policy-version continuity.
- Separate reviewed approval to turn the flag on, supervised broker UAT and staged rollout.

The code was committed and syntax inspected. **It has not been proven safe
to activate or merged**. No tests were run at the owner's request.
