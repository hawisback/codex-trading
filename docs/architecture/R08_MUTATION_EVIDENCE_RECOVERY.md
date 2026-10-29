# R08 — Broker-evidence reconciliation for CANCEL / MODIFY / REPRICE

**Branch:** `refactor/r08-mutation-evidence-reconciliation-20261029`  
**Parent:** `refactor/oms-intent-recovery-consistency-20261029`  
**Status:** committed for review, **offline tests NOT run**, Kite/Breeze broker UAT NOT performed, NOT merged or deployed.

## Scope and change

The previous increment journaled existing-order mutations but left ACK/UNKNOWN/PREPARED outcomes unresolved. R08 adds a strict **read-only recovery pass** (`BaseBrokerGateway.reconcile_pending_mutations`):

- Reauthenticate/revalidate using the **existing broker session**, local one-process lease, and exact account identity; no additional login or distributed coordination is added.
- Fetch the latest broker order book via the native read-only order endpoint. A broker API reply is an observation, *not* a proof that the entire account is flat or the market is safe*.
- Match exactly one normalized broker order by original `order_id`, original journal `request_id`, broker account/mode, symbol, kind, regular variety and engine ownership. Missing, ambiguous or cross-account records are **never inferred away**.
- Mutations now durably record the original target quantity plus expected trigger and limit prices for STOP modification, and expected limit price for EXIT repricing. These fields cannot be rewritten after journal preparation. Historical MODIFY/REPRICE mutation records missing expected fields cannot be auto-cleared.
- `CANCEL` can become RECONCILED only if the broker order is genuinely `CANCELLED` **with zero filled quantity**. `FILLED`, `REJECTED`, `EXPIRED` and partially filled orders do not prove that the cancellation completed as intended.
- `MODIFY_STOP` requires broker `TRIGGER_PENDING`, zero fills and exact expected trigger **and** limit price. `REPRICE_EXIT` requires broker `OPEN`, zero fills and the exact expected limit price.
- PREPARED/SENT may have been transmitted before a crash. If broker evidence conclusively proves the requested current state, transition via UNKNOWN to RECONCILED with broker-verified evidence. UNKNOWN/ACKNOWLEDGED also require independent evidence before RECONCILED.
- The report includes IDs of resolved and unresolved intents and explicitly says `positions_verified=False`. No broker order mutations, journal deletion, forced flatness, or automatic resubmission occur in the recovery method.

The reconciliation pass is invoked before a native mutation and before a new BUY/STOP/EXIT intent. Consequently, a prior ACKNOWLEDGED existing-order mutation now **blocks further same-target mutation and new order preparation until its effect is verified**. This is intentionally conservative; it could delay protective responses if broker reads are stale, incomplete or unavailable. Operators must use the native authenticated broker console / established manual recovery runbook in those cases, not delete the journal to force more orders.

## Safety and availability trade-offs

- This release does **not** claim comprehensive emergency-exit liveness. Unresolved CANCELs with partial fills, missing broker order history, stop-trigger races or uncertain account inventory remain blocked for automatic retry. That is safer than accidentally submitting duplicate SELL orders, but may require operator intervention.
- The normal OMS still must reconcile actual positions, residual quantities, resting stops, STOP fill status, and the overall SELL book before placing or replacing protection. **RECONCILED mutation is not RECONCILED position**.
- Status fields in broker snapshots may lag the exchange. Even when a price or cancellation is observed, final order/fill and exposure verification remains separate.
- This increment is specifically for native Kite and Breeze adapters. External proxy services and ad hoc scripts remain outside this recovery gate; run only one approved local OMS writer.
- Profit trailing, initial-stop percentages, MACD candidate selection, Chat Companion veto, the ₹5,000 daily loss gate and broker-margin sizing have not been altered.

## Prepared but unexecuted verification

`tests/test_mutation_evidence_recovery.py` includes:
1. Exact-price STOP/EXIT evidence, wrong account/order/strategy identity failure, and old unparameterized mutation records.
2. CANCEL verification with zero fills; rejection of partial fills, missing records and non-CANCELLED terminal statuses.
3. Fresh mock broker order read after ACK/UNKNOWN/PREPARED; no second network DELETE/PUT is emitted during reconciliation.
4. Repeated same-order mutation denied when broker evidence does not yet prove a previous ACK or UNKNOWN operation.
5. Existing write-ahead mutation cases still registered under the offline regression suite.

**Before any live use:** run full regression suite, recovery replay with delayed/incomplete Kite/Breeze order books, mock stop replacement after partial fills, error-on-broker-GET cases, expired-session recovery, and manual emergency exit drills. Confirm the broker's exact status and price representations. Do not merge on the basis of syntax-only parsing.

## Next increment candidates

- Broker-position-verified handling of partial-fill cancel outcomes and protective-stop coverage with no competing SELLs.
- Clear operator-facing action reports for unresolved intents and emergency broker-console handoff.
- Validate that the trade lifecycle can manage emergency exits while mutation history is incomplete without bypassing broker identity, quantity or duplicate-SELL controls.


### R09 follow-up: position-verified partial cancellations

On `refactor/r09-partial-fill-emergency-recovery-20261029`, partially filled CANCELs can reconcile only after two stable, complete broker order books bracket an exact broker position read and account-wide same-instrument fills net to that position. Other active SELLs, mismatched or missing broker data and external fills remain unresolved. A read-only operator recovery inventory reports open orders, positions and unresolved mutation IDs without authorizing new SELLs or declaring the account flat. Tests are prepared but **not run**; emergency-exit liveness and broker UAT remain outstanding. See `docs/architecture/R09_PARTIAL_FILL_EMERGENCY_RECOVERY.md`.
