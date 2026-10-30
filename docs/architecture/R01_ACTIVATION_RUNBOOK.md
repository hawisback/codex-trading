# R01 opt-in implementation and activation contract

**Original R01 branch:** `feature/r01-approved-policy-contracts-20261029`
**Current integrated branch:** `feature/live-activation-guardrails-20261030`
**Status:** Implemented behind `config/trading.json:r01_policy.enabled=false`. **NOT activated, merged, broker-validated or deployed.**
**Tests:** The owner authorized testing and repairs. The local quality wrapper and **574 registered offline tests pass**; see [validation and candidate identity](OFFLINE_VALIDATION_20261030.md). Real broker UAT and review of the final committed repair candidate remain required. See [current status](CURRENT_IMPLEMENTATION_STATUS_20261030.md).

## Implemented behavioral contracts (only if explicitly enabled)

1. **Capital ladder (owner revision, 2026-10-30):** Verified available margin below INR 40k permits up to 2 lots; INR 40k/60k/80k/100k permits up to 4/6/8/10 respectively. Thus INR 20k permits 2, INR 40k permits 4 and INR 100k permits 10. Recompute at each entry and de-escalate immediately below a milestone. Actual option entry-limit premium, the INR 150 reserve, exchange freeze and the 650-contract hard cap can reduce quantity, including to one lot. No guessed quantity limit or order splitting.
2. **Daily trades/loss:** Up to ten reconciled filled entries per IST day. For each proposed new entry, compare verified account-wide realized + unrealized P&L against **INR 3,000 x its actual affordable lot count**, capped by ten lots. Equality at the negative threshold blocks entry. The budget recalculates for every new entry; it is not anchored to the first trade. The legacy `risk.max_daily_loss_pct` and opening equity are not used by this R01 gate. A breach **only blocks new entries**; existing stops, trailing and ordinary OMS exits continue. Missing, stale or mismatched books block new entries.
3. **No penny/price bias (POL-03):** Within the opt-in policy only,
   the fixed sub-₹12 0DTE price-label veto in deterministic
   `AIConsultant._evaluate_playbook` is disabled; the fixed
   ₹15/₹135 option premium floor/cap in `EntryPolicy.band` and
   candidate selection are also disabled. The **real consultation
   still runs** with all other vetoes; quote identity, timestamps,
   bid/ask liquidity, spread, time-bound reference/slippage bands,
   actual option cost, margin, and expiry checks remain active.
   No trading decisions are based on arbitrary NIFTY spot price bands
   introduced by R01; underlying spot remains context for technical
   analysis/contract choice and independent stop invalidation.
4. **Unified stop (POL-06):** New R01-stamped positions use one
   strategy-independent policy in `trading/domain/unified_stop_policy.py`
   and `trading/domain/unified_stop_workflow.py` across **both**
   `StopManager.ensure/floor` (broker initial and trailing protection)
   and `PositionMonitor.manage` (hold/ratchet/breached-floor exits).
   The entry persists `r01_policy_version=r01-owner-20261029-v1`
   and the initial loss percentage (currently **25%**) for restart
   and configuration-reload continuity. Global +15/20/30/40%-peak
   gain tiers protect 0/10/20/30%; morning 09:15–11:30 and midday
   11:30–13:15 IST proposals compete by strongest floor.
   R01 triggers round upward to ₹0.05 and never loosen verified stronger
   broker stops. A fresh verified executable bid is required for
   price-driven actions. Legacy profile targets, timers, EMA/VWAP and
   separate microtrails are bypassed **only for stamped R01 positions**;
   independent technical invalidation, unresolved risk exits, and
   15:15 square-off still apply. The OMS still owns actual broker
   modification, cancel, replacement and fill reconciliation.
   Post-fill strategy-specific AI stop overrides are skipped for R01;
   **mandatory pre-entry consultant evaluation and veto remain**.
   New R01 orders reject a configuration without the unified-stop flag.
   Full contract: [R01_UNIFIED_STOP_EXECUTION.md](R01_UNIFIED_STOP_EXECUTION.md).
5. **Session and authorization (POL-02/07):** JSON now records
   no-entry-after **14:15 IST** and forced exit **15:15 IST** to
   match the already-hard-coded runtime limits. Broker fills and a
   verified flat position are not guaranteed during an outage.
   LIVE still requires explicit `--live`, account/mode authorization,
   an armed gateway, and all existing consultation, OMS and kill
   switch protections. `main` and production deployment are untouched.

## Kite entry evidence contract

R01 calls `KiteExecutionGateway.get_entry_funds(instrument_id)`. Legacy `get_funds()` remains a margin-only read. The entry method combines independent sources and does not arm the gateway:

| Field | Required source |
| --- | --- |
| `account_id`, `funds_asof`, `available_margin`, `source` | Account-verified Kite margins; aware local response receipt time, maximum 60-second age |
| `pnl_account_id`, `pnl_session_date`, `pnl_asof` | Same verified account/current IST day; bounded read window and at most 60-second receipt age |
| `realized_pnl_today`, `unrealized_pnl_today` | Raw Kite net positions, retaining closed rows, reconciled against net/day quantities and values and unique current-day fills from `/trades` |
| `max_single_order_quantity` | Current published NSE NIFTY quantity-freeze CSV, bound to the selected NIFTY option in the current Kite master |
| `expiry_sessions_remaining` | Future regular sessions through the exact listed expiry, excluding NSE FO holidays; minimum configured session budget enforced at entry |
| `contract_evidence` | Exact instrument/symbol, listed expiry, lot/tick, master/freeze/calendar URLs, SHA-256s and conservative local receipt timestamps |

The margin and P&L receipt timestamps are not exchange-origin timestamps. Broker-reported P&L is gross of subsequently posted charges. Missing/invalid/partial books never become zero; genuinely complete authenticated empty books may establish zero. Positions with overnight quantities are unsupported for this intraday aggregation and block new entries. Existing exposure management remains independent.

The master/calendar cache is current-session only; the freeze feed refreshes after five minutes. A changed lot/tick, ambiguous symbol, mismatched internal instrument, stale calendar year, closed regular session or expiry absent from verified regular sessions blocks entry. Next-year expiries require the matching year's calendar; special weekend/Muhurat sessions are intentionally unsupported. Broker RMS may impose additional limits; a published exchange ceiling is not a guarantee of broker order acceptance.

Sources: [Kite portfolio](https://kite.trade/docs/connect/v3/portfolio/), [daily trades](https://kite.trade/docs/connect/v3/orders/#retrieving-all-trades), [instrument master](https://kite.trade/docs/connect/v3/market-quotes/#instruments), [NSE contract information](https://www.nseindia.com/static/products-services/equity-derivatives-contract-information), [NSE holidays](https://www.nseindia.com/resources/exchange-communication-holidays).

Read-only acceptance of these sources passed on the refreshed Kite session; see [validation record](OFFLINE_VALIDATION_20261030.md). Breeze remains deferred and does not provide this entry-evidence integration.

## Change activation and rollback

- The branch intentionally ships with **`enabled: false`**. Existing
  production order sizing/consultation/stops continue through legacy
  paths by default, except that repository session JSON now matches
  existing effective hard cutoffs.
- Before supervised activation: verify current-session broker
  evidence; record risk/stop/price envelope parity in
  fixtures; run the full offline suite; inspect OMS unknown-ACK,
  partial-fill, cancel and broker-outage behavior; conduct supervised
  broker UAT. Offline and read-only checks pass; real broker order UAT is still pending.
- Never enable the new policy mid-position to retroactively rewrite a legacy stop. A stamped R01 position retains the unified stop authority and its entry-frozen loss setting even if the new-entry feature switch is disabled later; continue protecting it through the existing OMS.
- Rolling back the branch is a code/config change only; always reconcile
  and continue protecting existing positions before replacing an
  active process. Do not restart blindly into LIVE mode.
- Any missing verification blocks NEW exposure but does not suppress
  managing existing broker-side stops and exits.

**This document is an implementation record, not certification that the
feature is safe to turn on or that LIVE orders have been executed.**
