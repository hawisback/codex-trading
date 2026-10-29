# AI entry bands and just-in-time quotes

The scheduler still calls the actual AI consultant before any entry. A successful
evaluation now authorizes a price band for one contract, setup, reference price,
candidate timestamp, and optional structural invalidation level. Vetoes, traps,
errors, missing envelopes, and expired approvals block entries. Execution can
tighten the authorized bounds but cannot widen them.

## Defaults

`config/trading.json` contains the execution settings:

| Setting | Default |
| --- | --- |
| Trend/other approved setup upside allowance | 5% |
| Explicit `CLIMAX_SPRING` upside allowance | 3% |
| Downside allowance | 8% |
| Absolute upside allowance | ₹4 |
| Marketable limit buffer | 1 tick (₹0.05) |
| Maximum quote age, including request elapsed time | 1 second |
| Quote socket-operation timeout, without retry | 1 second |
| Approval validity after evaluation returns | 5 seconds |
| Maximum age of the original candidate | 15 seconds |

The existing selection limits also apply at execution: ₹15 minimum premium,
₹70 maximum premium, and 3% maximum bid/ask spread, measured against best bid.
These are configurable policy starting values, not empirically validated claims
about profitable execution or risk/reward. Raising execution tolerances does not
change the AI's institutional trap rules or authorize 0DTE contracts excluded by
the existing selection configuration.

For reference price `P`, the policy ceiling is the minimum of the percentage cap,
`P + ₹4`, and the premium cap. The ceiling rounds down and the floor rounds up to
₹0.05 ticks. A reference of ₹67 therefore gives a normal band of ₹61.65–₹70.00
with the current premium cap; a climax spring gives ₹61.65–₹69.00.

Chat approvals may supply narrower `min_entry_price`/`max_entry_price` fields.
The pending consultation JSON publishes the proposed policy band. Both chat and
interactive approvals receive the same identity binding and execution deadlines
as playbook evaluations. A consultation exceeding the AI timeout cannot produce
an executable approval. A slow consultation may also exhaust the candidate's
shorter lifetime, requiring a new candidate and actual AI evaluation.

## Submission sequence

1. Reconcile the account under the existing singleton/OMS locks. Verify flatness.
2. Verify the approval and available broker margin.
3. For setups with an approved invalidation level, fetch a fresh NIFTY index quote
   and reject a crossed structural boundary.
4. Fetch the selected contract through the existing local gateway endpoint,
   `GET /api/v1/market/quote/{instrument_id}`. No paid API is introduced.
5. Validate identity, dated exchange timestamp, elapsed request age, positive
   bid/ask quantities, valid ticks, spread, and the entire approved entry band.
   Missing or failed quotes never fall back to the candidate's old LTP.
6. Compute `min(best_ask + ₹0.05, effective_ceiling)` and size using that final
   limit, verified margin less ₹150, and existing lot/quantity caps.
7. Persist the request ID, quote, verdict, limit, quantity, and cancellation
   deadline before submission. Recheck immediately after persistence and again
   after client logging, before the POST is attempted.

The gateway's read-only OpenAPI route and an index quote were checked during
implementation. Its observed flat response contains `instrument_id`,
`best_bid`, `best_ask`, `best_bid_qty`, `best_ask_qty`, and an ISO `timestamp`.
An index legitimately has zero depth; depth validation applies to the option,
while index validation uses its `last_price`. A malformed/unsupported response
blocks entry rather than guessing a schema. Only dated timestamps are accepted;
naive exchange timestamps are interpreted as IST.
Freshness depends on the gateway timestamp describing its market-data snapshot
accurately. The client cannot independently detect a gateway that republishes
old depth with a newly generated timestamp; the read-only response check verifies
field shape, not that provider guarantee.

## Fills, cancellation, and recovery

The configured `risk.entry_order_timeout_sec` is a maximum resting lifetime,
including acknowledgement latency. Approval expiry, candidate expiry, or the
14:15 entry cutoff shortens it. Partial fills end polling immediately so the
remaining BUY can be cancelled and confirmed fills protected. Position and order
snapshots are refreshed after cancellation to account for racing fills.

Confirmed partial exposure is protected even when cancellation is still pending,
provided broker positions and fill quantities agree. New entries remain blocked.
Additional fills or conflicting protection quantities require reconciliation and
the existing safe-exit path. No automatic upward repricing or blind POST retry is
introduced. Unknown outcomes retain durable intent for request-ID recovery.

`active_position.json` retains `entry_execution` evidence and order fill details;
initial protective stops use the reconciled actual broker entry price. Logs
record rejection reasons, the band, ask, final limit, and quantity.

Limits cap the buy price; they do not guarantee fills or exchange acceptance.
The client cannot enforce a server-side expiry while disconnected or prevent a
fill racing cancellation. Network, gateway, and cancellation delays can exceed
client timing targets. This change does not move general broker calls into a
background worker or guarantee a five-second scheduler cadence. No gateway files
outside this repository were changed.

## Offline verification

```powershell
python -m unittest test_entry_execution test_market_intelligence test_self_healing_exit -q
```

These tests use simulated market/broker transports and actual AI evaluation, with
temporary state inside the repository. They do not start the live scheduler,
place orders, or alter live position state. Restart the scheduler to load changes.
