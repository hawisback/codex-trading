# R01 Unified Stop Loss — Integrated Execution Contract

**Branch:** `feature/live-activation-guardrails-20261030`
**Status:** Implementation reviewed by the owner; local regression and native fake-transport fixtures pass, not merged, enabled, deployed or broker-UAT validated.
**Activation:** `config/trading.json:r01_policy.enabled=false` remains unchanged.

Current implementation/release record: [CURRENT_IMPLEMENTATION_STATUS_20261030.md](CURRENT_IMPLEMENTATION_STATUS_20261030.md).

## End-to-end ownership

**For newly created R01 LIVE entries only**, `PositionLifecycle._submit_entry` persists `r01_policy_version=r01-owner-20261029-v1` and `r01_initial_stop_pct` before submitting the BUY. The frozen version—not the runtime strategy name or future enabled switch—chooses the stop policy through the life of the position.

- **Pure calculation:** `trading/domain/unified_stop_policy.py` calculates the loss floor and time-aware profit tiers. `trading/domain/unified_stop_workflow.py` composes the same calculation with persisted existing stop floors, quote freshness, upward NSE-tick rounding, mandatory close and a typed EXIT/RATCHET/HOLD outcome.
- **Broker protection:** `StopManager.ensure` creates the initial protective stop from that same R01 floor rather than any strategy's `initial_stop_pct`. `StopManager.floor` and `ratchet` apply the same floor to subsequent broker modifications. In-place modification limit, cancel-before-replace, fill reconciliation, pending acknowledgement and per-entry residual coverage stay owned by the existing OMS.
- **Monitoring:** `PositionMonitor.manage` routes *only stamped* R01 positions to `decide_unified_stop`, bypassing legacy strategy-dependent profit targets, fixed hold timers, runner thresholds, VWAP/EMA trailing and morning/late-day microtrailing. A verified floor breach requests an EXIT through the existing `exit_trade` coordinator; **never** submit a second SELL directly.
- **Independent safety exits remain:** hard 15:15 IST square-off, verified spot technical invalidation and active `risk_exit_required`/pending exits still use the existing protective and reconciliation path. They are not alternative profit-trailing strategies.
- **AI:** The existing `AIConsultant.evaluate` pre-entry consultation and veto remain mandatory. Strategy-dependent *post-fill* two-step AI stop overrides are skipped only for stamped R01 positions, to avoid competing stop authorities. Legacy positions retain their existing two-step procedure.

## Fixed R01 schedule (already introduced in earlier policy foundations)

- Initial loss: `risk.option_hard_stop_pct`, currently **25%** of entry premium, frozen on the position at BUY preparation.
- Peak gains of **15/20/30/40%** protect **0/10/20/30%** of entry premium.
- **09:15–11:30 IST:** peak gain of **5/10/15%** protects **-8/+1/+10%** of entry premium respectively, in addition to global tiers.
- **11:30–13:15 IST:** peak gain of **5%** protects **+3%** of entry premium, in addition to global tiers.
- **13:15–15:15 IST:** global profit tiers remain; no legacy strategy-based afternoon stop schedule.
- At every point the floor is max of the new proposal, previously desired/confirmed stop triggers, broker active-stop triggers and any retained stronger protective AI stop. Stop triggers are rounded **up** to the ₹0.05 exchange tick. **Never loosen.**

These values reproduce the prior R01 MACD-based opt-in baseline; this commit does not constitute independent owner approval or real-money verification of the exact percentages.

## Quote and order safety

- Only a quote with `quote_verified is True`, a timezone-aware `bid_timestamp` no older than 2 seconds and a positive executable option bid can authorize a profit ratchet or price-triggered exit. A stale/malformed quote yields HOLD for price-dependent decisions; the broker stop remains in place.
- A prior high bid is used for profit tiers only while the current quote is verified/fresh. A missing verified quote can still yield the initial unenhanced floor on stop creation.
- Initial stop and modifications share the single policy. The old strategy stop percentage, target, timer or session microtrail cannot override an R01 position. Existing legacy positions are never migrated merely because the runtime flag changes.
- A policy flag change does not switch already-stamped R01 positions back to legacy. For new LIVE R01 orders `unified_stop_enabled` must be true; incomplete opt-in configurations fail closed.
- Confirmed broker stop status/quantity/trigger is required to claim protection; R01 requires exact trigger-floor confirmation to tick precision. Lost mutation ACK remains unresolved and blocks duplicate submissions.
- If the requested floor is at or above the executable bid, the monitor initiates the standard broker-reconciled exit workflow rather than placing an invalid new stop. `risk_exit_required` remains the operator escalation path.

## What this work does NOT prove

- The unified stop, native workflow and process-ownership fixtures pass locally as part of [574 registered offline tests](OFFLINE_VALIDATION_20261030.md). The repair candidate remains uncommitted.
- Fake-transport crash/restart, partial-fill and replacement tests do not establish real broker UAT, real-time session monitoring, or LIVE order protection.
- Broker P&L, quantity limits, authoritative contract master, expiry source, and unrelated R02–R10 integration blockers still prevent activation.
- The current R01 flag is **off**; `main` and LIVE deployment are unchanged.

## Required verification before activation

Run the registered regression suite, including legacy runner tests and the new unified tests, under a no-order isolated transport. Verify no stop regression for stronger existing floors and no behavior changes for unstamped legacy positions. Exercise partial fills, stop creation/replacement races, stale and mismatched quotes, uncertain ACK, timestamp skew, after-hours square-off and restart with a previously stamped R01 position. Only then move to supervised broker UAT and separate production review.
