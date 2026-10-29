# ADR-001 — Broker-funded account-wide 2/4/6/8/10 lot ladder

- **Date:** 2026-10-29
- **Owner intent:** confirmed in chat, including broker available margin
- **Change class:** POLICY
- **Implementation:** on unmerged branch; tests and broker UAT NOT RUN
- **Related IDs:** POL-01, POL-04

## Approved decision

Every strategy gets the same maximum lot tier based on **authenticated broker available margin** (not static account equity or presumed starting capital):

| Available margin in INR | Max lots | Max quantity (currently 65 per lot) |
| --- | ---: | ---: |
| Positive through 20,000 inclusive | 2 | 130 |
| Above 20,000 through 40,000 inclusive | 4 | 260 |
| Above 40,000 through 60,000 inclusive | 6 | 390 |
| Above 60,000 through 80,000 inclusive | 8 | 520 |
| Above 80,000 | 10 | 650 |

**Tiers are ceilings, not order targets.** Actual quantity is the lesser of the tier ceiling, what the broker available margin can pay for at the executable *option* limit price after the existing ₹150 reserve, and broker/order limits. Underlying NIFTY spot still determines eligible strike and never substitutes for the option premium.

Account scope, stale/faulty funds, quote health, existing exposure, price band, AI consultant vetoes, entry time, durable intents and stop protection remain mandatory.

## Technical design

- The canonical 5-tier policy lives in `config/trading.json:risk.available_margin_lot_tiers`, with exact values validated by `trading/domain/lot_policy.py`.
- `risk.max_lots_per_trade` is now 10 and `risk.max_order_quantity` is now 650. Both are hard configuration validations; missing or inconsistent configuration blocks sizing.
- `trading/domain/sizing.py:calculate_compounding_quantity` keeps its public function signature, but ignores obsolete per-strategy compounding policy and uses the shared account policy.
- `position_lifecycle.py:_submit_entry` continues to request current broker funds, validates the final approved option limit price and calculates quantity a second time before persisting/submitting an order.
- No automatic order splitting or broker POST retries were introduced. Validate broker per-order quantity constraints in broker-specific UAT; the broker may reject 650 as a single order.
- The legacy strategy-local `compounding` blocks remain in `config/strategies.json` for historic research compatibility, but are no longer authoritative for live sizing. Remove only after independent compatibility review.

## Intended behavior differences and risks

The old active MACD floor milestones 0/20k/40k/70k/100k are superseded by **inclusive upper** bounds 20k/40k/60k/80k and 10 thereafter; other strategies are no longer limited by their one-lot strategy-specific caps. This can **increase nominal exposure**. Size changes therefore require broker validation, stop-loss review, and daily loss gate decisions before production activation.

Do not equate available capital with index spot, initial backtest equity, or the current persisted position value. Broker returned available margin must be account verified and fresh. Missing or bad funds data yields zero-size/no-new-entry.

The current 65-contract lot constant is retained; any exchange contract size changes require a separate audited update.

## Rollback and acceptance

Do not deploy this untested sizing code to the live scheduler. Before merge: run prepared offline tests, golden signal/OMS traces, broker-specific order limits and quote validation, cash shortfall and near-boundary scenarios, restart reconciliation, and explicit operator acceptance.

Rollback requires broker position/order reconciliation and state compatibility; merely swapping binaries does not prove zero exposure.

**Test suite not run at owner request; no live broker orders placed.**
