# Trailing stops and uncapped runners

The active `ai_opportunity_radar` profile has no fixed profit target. Existing AI
approval/veto rules, entry sizing, structural wick and EMA9 exits, initial stop,
holding limit, and mandatory 15:15 IST square-off still apply. Other profiles keep
their configured target behaviour.

## Strategy

The initial trigger is 30% below entry. Normal runner trailing activates when the
highest observed fresh option bid reaches +20% from entry. The trigger is the
higher of the applicable profit floor and 90% of that peak bid. Once the peak gain
reaches +50%, the trigger becomes the higher of the existing floor and 95% of the
peak bid. Because the peak persists, a subsequent pullback never restores the
looser 10% allowance. There is no upper profit cap.

For an illustrative entry at Rs 50:

| Peak gain | Peak bid | Calculated trigger |
| --- | --- | --- |
| +20% | 60 | 55 |
| +30% | 65 | 60 |
| +40% | 70 | 65 |
| +50% | 75 | 71.25 |
| +60% | 80 | 76 |
| +100% | 100 | 95 |

All triggers use the existing nearest-0.05 tick rounding. The strongest persisted
desired/confirmed floor also participates in exit decisions. Normal broker
modifications require more than Rs 0.50 improvement, configurable through
`stop_min_improvement_points`; unchanged peaks do not cause repeated successful
modifications. The after-14:00 micro-trail still sets a +1% trigger floor when the
peak gain reaches +4%.

The morning micro-trail applies to the first filled entry of the IST trading day
when its entry time is 09:15-09:45 and its peak gain reaches +10%. Entry submission
persists the daily ordinal from the verified broker order book; restarts retain
it, and older position files recover it during reconciliation. Missing ordinal
evidence does not qualify as the first trade. Setting
`morning_micro_trail_first_trade_only` to false permits later morning entries.

Five percent means five percent of the peak premium, not five percentage points
of entry profit. These are trigger levels, not guaranteed execution prices. The
existing stop-limit price is 2% below the trigger; gaps, empty depth and exchange
limits can prevent a fill. Fees and execution prices affect realised profit.

`trading/domain/trailing.py` owns the runner calculation. The active historical
configuration also disables the target and uses the same aggressive calculation.
No historical backtest or live orders were run for this change. Candle simulations
cannot certify five-second execution or intrabar ordering.

## Modification and replacement recovery

Every modification records its desired trigger, request time and reserved
modification attempt before transmission. Only a broker snapshot showing the
requested or stronger trigger in `TRIGGER_PENDING` confirms the change. An
acknowledgement showing the old trigger, `MODIFY_PENDING`, or an unknown network
outcome remains pending and prevents another modification of that order. After
the configurable ten-second confirmation deadline, the OMS requests a verified
exit rather than treating an old trigger as newly confirmed protection.

Each stop has its own 25-attempt budget. On the next meaningful improvement after
that budget is exhausted, the OMS persists `stop_replacement`, cancels that stop,
and verifies its terminal outcome. It reconciles broker quantity and all linked
fills before creating one replacement for the remaining entry quantity. The new
order starts with zero modifications; entry identity, entry price, peak and floor
survive. No fixed sleep is inserted. A delayed cancellation resumes on a later
cycle; fills during cancellation can reduce or eliminate the replacement.

Replacement state and the new order intent are durable before their respective
writes. A lost creation acknowledgement is recovered by its request ID and never
blindly retransmitted. If recovery discovers an existing related stop, the OMS
adopts and raises that stop instead of adding a competing SELL. Rejection,
expired confirmation, a breached floor, or invalid coverage requests risk exit.
An unknown order that cannot be identified remains blocked for reconciliation.

## Prices and exits

Active monitoring uses contract identity, exchange timestamp, positive bid depth
and a valid bid, not the positions API's LTP. Invalid/stale quotes preserve the
last valid peak and resting stops; they cannot initiate new price-driven
modifications. Quotes are revalidated before stop writes. The default maximum
quote age is two seconds and request budget is 1.5 seconds. Reconciliation and
broker delays can still overrun a five-second scheduler target.

An `OPEN` protective stop is a triggered, unfilled SELL, not confirmed resting
protection. It requests the exit workflow, which verifies cancellation and fills
before selling the residual. Fresh exit limits cross the bid with a configurable
0.5% buffer (at least one tick). Native Kite can reprice the same open exit ID,
tracking uncertain reprices instead of creating duplicate SELLs; exhausted exit
modification budgets use verified cancellation before another residual exit.
Separate verified entry references can each receive an exit without waiting for
the first reference's accepted order to fill.
Each entry reference receives at most one OMS exit submission per call; a
broker-side rejection resumes on a later cycle rather than recursively retrying.
The proxy retains its existing bounded retries for definitive HTTP rejections.

Definitive cancellation failures record the error and permit another attempt on
the next verified cycle. Acknowledged or uncertain cancellations wait for the
confirmation timeout; if a fresh broker snapshot still shows the same exit as
`OPEN`, cancellation can be retried against that order ID. No replacement SELL is
submitted until terminal cancellation/fill status and residual exposure have
been reconciled, including across restarts.

Exit owns protection transitions locally. A fresh stop discovered after
cancellation blocks a competing SELL and reports `STOPS_REAPPEARED_DURING_EXIT`.
The local execution proxy is a passive request/response service. Order requests
originate in this engine; the proxy does not independently initiate them. Our
reconciliation, recovery and exit calls must therefore respect the persisted
exit/replacement state. Unexpected stop records require tracing our requests and
their broker outcomes; they do not establish autonomous activity in the backend.
Cancel-and-create remains a sequence of broker operations, not an atomic exchange
transaction. The proxy's documented API has no generic exit cancellation/repricing operation;
when those capabilities are absent, pending exits remain recorded and explicitly
require operator reconciliation. Native Kite implements those operations.

No path promises fills or zero time without resting protection. Do not delete
recovery state to clear an uncertain order, and do not run competing execution
owners. Restart the scheduler to load these changes; no running process or broker
session is changed by editing this repository.

## Verification

Run `python -m tools.quality` from this repository. Offline tests include actual AI
approval with simulated Kite HTTP, repeated stop generations beyond +50%, a 5%
pullback exit, restarts, lost acknowledgements, partial fills, cancellation races,
stale quote rejection, pending modifications and pending exit repricing. Real
network connections are blocked. No AI gate is replaced or bypassed.
