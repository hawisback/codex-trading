# R01 opt-in implementation and activation contract

**Implementation branch:** `feature/r01-approved-policy-contracts-20261029`  
**Status:** Implemented behind `config/trading.json:r01_policy.enabled=false`. **NOT activated, merged, broker-validated or deployed.**  
**Tests:** Authored/registered only. No tests were run, per owner instruction.

## Implemented behavioral contracts (only if explicitly enabled)

1. **Capital ladder (POL-01/04):** The owner-approved 2/4/6/8/10 NIFTY
   lot tiers at inclusive upper boundaries ₹20k/₹40k/₹60k/₹80k.
   `trading/domain/sizing.py` uses the tier for candidate-side preview.
   `position_lifecycle._submit_entry` independently recomputes the
   submitted quantity from **broker available margin**, a verified fresh
   option entry limit, current lot size (currently 65), the ₹150 reserve,
   broker-provided single-order quantity ceiling, and existing absolute
   position hard cap. Tiers are maxima, not a minimum lot count.
   No inferred brokerage freeze quantity and no automatic order splitting.
2. **Daily trades/loss (POL-05):** Up to ten reconciled filled ENTRY
   orders per IST session, including MACD (formerly two); existing MACD
   spacing still applies. For LIVE entries the gate requires a matching
   account/day broker P&L ledger, at most 60 seconds old, containing
   authenticated start-of-day equity, realized and unrealized P&L.
   Stop NEW entries once their sum is a loss of **1.5% or more** of
   verified start-of-day equity, using the pre-existing configured
   `risk.max_daily_loss_pct=1.5`. Incomplete P&L means *block entry*.
   Position exits and protective actions are NOT gated on P&L.
   A split BUY yielding multiple filled entry orders counts
   conservatively in the present order-ledger gate. No new trading
   opportunities are guaranteed by the ceiling.
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
4. **Unified stop (POL-06):** The same strategy-name-independent
   protective stop floor is calculated in
   `trading/domain/unified_stop_policy.py` and consumed by the existing
   `StopManager.floor`. The starting common floor uses the existing
   configured **25% option hard stop**, while retaining any stronger
   pre-existing/confirmed stop. The common profit tiers and
   morning/midday schedules are based on the current active MACD
   configuration (15/20/30/40% gains -> 0/10/20/30% protected;
   morning 09:15–11:30, midday 11:30–13:15).
   No stop can be lowered by this helper; updates still use the
   existing OMS stop-modify/cancel/verify/recovery logic.
   A position is eligible only if its entry state carries
   `r01_policy_version=r01-owner-20261029-v1`: no retroactive
   conversion of already-open legacy positions.
5. **Session and authorization (POL-02/07):** JSON now records
   no-entry-after **14:15 IST** and forced exit **15:15 IST** to
   match the already-hard-coded runtime limits. Broker fills and a
   verified flat position are not guaranteed during an outage.
   LIVE still requires explicit `--live`, account/mode authorization,
   an armed gateway, and all existing consultation, OMS and kill
   switch protections. `main` and production deployment are untouched.

## Gateway contract still required before enabling

The existing gateway may not supply this entire schema. If
`r01_policy.enabled=true` is used without the required verified data,
**NEW LIVE entries fail closed**. Do not populate missing fields with
static estimates, placeholder values, guessed ₹10k/₹500k account equity,
or zero P&L.

An authenticated `get_funds()` response must provide:

| Field | Required provenance |
| --- | --- |
| `account_id` | Same verified account as `execution_scope.account_id` |
| `available_margin` | Finite actual broker purchasing power |
| `pnl_account_id` | Same account as the execution session |
| `pnl_session_date` | Current IST session date YYYY-MM-DD |
| `pnl_asof` | Aware timestamp, not future, no older than 60 seconds |
| `start_of_day_equity` | Broker-reconciled positive actual account-day opening equity |
| `realized_pnl_today` | Verified current-session realized P&L |
| `unrealized_pnl_today` | Verified current-session current mark-to-market P&L |
| `max_single_order_quantity` | Authenticated, instrument-appropriate broker order freeze limit as integer |

The broker adapter must reconcile these fields with the correct account,
date, current NIFTY instrument master, and broker reporting semantics.
A generic funds endpoint may not contain all these fields; that is a
**known integration gap, not permission to use a fabricated fallback**.

## Change activation and rollback

- The branch intentionally ships with **`enabled: false`**. Existing
  production order sizing/consultation/stops continue through legacy
  paths by default, except that repository session JSON now matches
  existing effective hard cutoffs.
- Before a separate supervised activation: implement/verify broker
  field normalization; record risk/stop/price envelope parity in
  fixtures; run the full offline suite; inspect OMS unknown-ACK,
  partial-fill, cancel and broker-outage behavior; conduct supervised
  broker UAT. This work was intentionally **not performed here**.
- Never enable the new policy mid-position to retroactively rewrite
  a legacy stop. The policy version is persisted on new R01 entries.
- Rolling back the branch is a code/config change only; always reconcile
  and continue protecting existing positions before replacing an
  active process. Do not restart blindly into LIVE mode.
- Any missing verification blocks NEW exposure but does not suppress
  managing existing broker-side stops and exits.

**This document is an implementation record, not certification that the
feature is safe to turn on or that LIVE orders have been executed.**
