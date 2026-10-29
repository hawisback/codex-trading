# R09 — Partial-fill cancellation recovery and emergency inventory

**Branch:** `refactor/r09-partial-fill-emergency-recovery-20261029`  
**Parent:** `refactor/r08-mutation-evidence-reconciliation-20261029`  
**Status:** review-only; **tests NOT run**, no broker orders/sessions or UAT, not merged into main.

## Scope

This increment addresses an important R08 availability gap. A CANCEL that
partially filled could not be proven complete from its terminal order status
alone, so its durable intent stayed UNKNOWN and blocked subsequent
order preparation. Marking it RECONCILED without checking the account's
remaining long exposure could create duplicate or excessive protective SELLs.

### Verified partial-cancel path

`trading/domain/mutation_evidence.py` contains pure
`verified_partial_cancel_exposure` and `stable_order_fingerprint`.
`BaseBrokerGateway.reconcile_pending_mutations` uses them when a CANCEL
of a known ENTRY/STOP/EXIT is **CANCELLED with a positive partial fill**.
It performs read-only broker operations (no POST, PUT, DELETE):

1. Require the authenticated LIVE broker account and held local OMS lease, plus
   the original durable order identity and immutable target quantity.
2. Obtain a complete current normalized broker order book; verify the target
   and same-origin request, instrument, kind, account and status.
3. Read broker positions; then read broker orders again. **Only** continue if
   the full order/quantity/fill/price snapshot fingerprints agree. Changing
   orders leave the cancellation unresolved.
4. Account for every same-instrument ENTRY fill minus linked STOP/EXIT SELL
   fills. Refuse negative residuals, mismatched positions, unowned/foreign
   executed orders, extra active orders, conflicting instruments or missing
   order allocation identities. Require an exact positive long or flat
   broker position match.
5. Only then advance PREPARED/UNKNOWN/ACKNOWLEDGED cancellation to
   RECONCILED with an evidence record naming filled quantity and reconciled
   residual. **Never** infer that the remaining position is protected, that
   another SELL can safely be submitted, or that a new order is authorized.
   The normal stop/exit OMS must perform its own fresh residual, resting SELL,
   quote and authorization preflights.

This path is intentionally conservative. Historical carry, incomplete broker
order history/pagination, outstanding second stops, stale position books and
unowned fills block automatic resolution. Such cases require the operator and
broker console rather than journal deletion or a blind SELL retry.

### Emergency recovery inventory

`BaseBrokerGateway.emergency_recovery_report()` is a new read-only operator
helper. With the existing live session and local lease, it reports:
- nonzero broker position quantities by contract;
- active orders, their filled and unfilled quantities and ownership;
- unresolved CANCEL/MODIFY/REPRICE durable mutation IDs and targets;
- explicit `safe_to_resubmit_sell=False`,
  `account_flat_confirmed=False` and `protective_stop_confirmed=False`.

It cannot approve orders, settle journal phases, override account authentication
or bypass normal OMS duplicate-SELL prevention. On unavailable/stale/mismatched
broker evidence, it returns an error and continues to deny automatic SELL
resubmission. A report is an observation, *not* a proof of live coverage.

## Operator recovery procedure

When a protective stop, cancellation or exit is uncertain:

1. Prevent fresh BUY entries; do not launch another scheduler process.
2. Use the broker's **existing authenticated session/official console** to
   inspect account positions and the full entry/stop/exit order book.
3. Record order IDs, current status, filled and pending contracts, the exact
   NIFTY option instrument and any resting protective SELLs.
4. Confirm whether exposure is flat or remains open. If a protective stop
   is absent or SELL state is ambiguous, perform supervised manual
   broker-console recovery in accordance with actual broker capabilities.
5. Do not manually clear JSON journal entries merely to get an order through.
   Reconcile journal intent and broker positions/orders before restarting.
6. Re-run verified recovery and confirm held local execution lease on restart.
   A new Kite/Breeze daily token is *not* evidence that old exposure disappeared.

The code in this increment **does not automatically bypass** journal
blocks for emergency exits. That would require proof that no competing SELL is
working at the exchange, and remains a pre-live validation item.
No new authentication, distributed lease, vault or multi-host execution added.

## Acceptance and remaining work

Prepared but **not executed**:
- Partial STOP cancellation with 15 sold of 65: 50 remaining, exact broker
  position and stable order books, no new broker mutation.
- Broker position disagreement, second resting stop, unowned fill, stale
  order-copy mismatch, duplicate IDs, and dynamic book changes: no clearance.
- Read-only emergency report never claims authorization to resubmit SELL.
- Historical R08 fixture repairs to create a real zero-fill STOP before tests.

**Before LIVE:** run full offline regression and broker-specific mock tests,
simulate partial fills/cancel races and delayed position updates, validate
truncated order history behavior, operator emergency drills, and protected
exit liveness with Kite/Breeze. This implementation remains untested and
**not approved for live capital**.
