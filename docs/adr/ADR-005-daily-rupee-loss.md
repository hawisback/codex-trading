# ADR-005 — ₹5,000 daily loss gate, ₹2,000 planned trade risk, 10 entries

- **Owner:** approved ₹5,000 daily loss and up to 10 trades; implementation judgment delegated to assistant.
- **Branch:** `refactor/r05-pol03-pol05-pol06-safety-20261029`
- **Status:** implemented for review; **NO TESTS RUN**, no broker UAT, unmerged and not live.
- **Change class:** RISK POLICY; deliberate change from legacy MACD two-entry cap and prior risk settings.

## Authority and limits

- `risk.max_daily_loss_rupees=5000`: block **new BUYs** once the observed intraday net loss including a conservative fee cushion reaches or exceeds ₹5,000.
- `risk.max_planned_loss_per_trade_rupees=2000`: planned maximum per position, using the final approved executable option limit price, **20% maximum initial premium stop distance** and ₹150 entry cost cushion. This is a limit on *planned* risk, not worst-case guaranteed realized loss.
- `risk.max_trades_per_day=10`: global daily filled ENTRY-order count. The active MACD profile's legacy cap is aligned to 10; its independent completed-bar cooldown remains operative. One active position at a time is unchanged.
- `risk.daily_loss_fee_cushion_per_entry_rupees=150`: a conservative **estimate**, not broker-confirmed actual charges or a fee statement. True brokerage, taxes and slippage can exceed the reserve, and therefore actual losses can exceed the daily cap.
- Existing authenticated broker-available-margin 2/4/6/8/10 tier and affordability remain **additional ceilings**, not target order sizes.

## Pre-entry enforcement and failure policy

`PositionLifecycle._submit_entry`, after actual broker funds/quote verification, calls a newly added pure `trading/domain/daily_risk.py` calculator against a **fresh complete** `get_orders` result. It requires prior OMS flat-book verification, filled quantities, positive execution average prices, unique order IDs, account/mode identity, and settled round-trip position quantities. It does not infer P&L from last-traded prices, assumed equity, absent fills or static research balances.

When verified flat, the sum of actual filled SELL proceeds minus BUY fill costs provides **realized intraday P&L**. Because no open position is permitted for a new entry, current unrealized exposure is zero at that decision point. Unknown or other-account/foreign fills, incomplete broker order history, unmatched buy/sell quantities, missing avg prices or invalid risk config fail closed for **new entries**. The estimate subtracts ₹150 per filled ENTRY order in place of unexposed broker fee details.

For open positions, regular stop management continues independent of this entry-only loss gate; there is no new forced liquidation or disabling of protective STOP/EXIT. The calculation assumes supported intraday contracts and cannot verify a full-day broker P&L after out-of-band transfers, overnight carry, missing pagination or external trades. A later broker-backed P&L endpoint is preferable if one becomes available with trustworthy realized, unrealized and fee fields.

## Loss budgeting

At each entry, usable planned risk is
`min(₹2,000, ₹5,000 - max(0, -verified_day_pnl)) - ₹150`.
If this is insufficient to cover one whole lot at 20% of the final option limit premium, block the BUY. Today's profits do **not** increase the risk budget. A position's broker-available margin lot tier can be higher than the order size permitted by this additional risk budget.

Any stop-limit order can fail to fill during a gap, rapid price move, broker/API outage or session transition. This implementation cannot guarantee the realized daily loss is capped at ₹5,000, or that broker execution quantity limits accept larger NIFTY orders.

## Deferred work

- Integrate broker-certified actual charges if supported; reconcile any unrelated trades and prior-day inventory rather than guessing.
- Test complete/partial fills, fees, gap-through loss, 0-fill order statuses, overnight exposure, order-book pagination and fresh-account-session restarts with redacted broker evidence.
- Review user-requested structural invalidation policy separately from level selection and time-dependent trailing.
- Do **not** merge or run against live funds before offline tests, native Kite/Breeze UAT and supervision.
