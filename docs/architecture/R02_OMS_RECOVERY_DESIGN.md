# R02 — Durable OMS recovery and shared stop-boundary refactor

**Branch:** `refactor/r02-oms-recovery-stop-boundaries-20261029`  
**Parent:** `refactor/pol01-sizing-and-layout-20261029` at `80d1cebde1460641f97202051b0684cfc45e6312`.  
**Status:** Source changes committed for review; **tests NOT RUN**, no broker UAT or live orders. Main unaffected.  
**Change class:** STRUCTURAL / recovery safety (not POL-06 strategy tuning).

## What was integrated from the earlier independent OMS patch

The unmerged `refactor/trading-engine-architecture-20261029` contains a position codec, defensive journal validation, rate-limiter input hardening and prepared offline tests. These were **ported as file content** (not merged through git), and `tests/test_regression.py` was updated while preserving modules added in the ancestor R00/R01/POL01 branches.

- `trading/adapters/position_codec.py`: schema-v2 aliases, v1 legacy hydration, strict collection shape checking. Missing/corrupt collections do not become empty positions.
- `trading/adapters/position_store.py`: filesystem duties only; codec handles schema conversion.
- `trading/adapters/gateways/journal.py`: hardened request identity/tag/account correlation and immutable snapshots.
- `trading/adapters/gateways/rate_limiter.py`: stable token budgeting with validation.
- `tests/test_boundary_safety.py`: unexecuted offline cases from the previous branch.

Do **not** merge the old independent branch after this migration without checking for duplicate changes and tests.

## New R02 implementation

### 1. Cross-process JSON journal writer coordination

`GatewayJournal.put` acquires an OS-level advisory writer lock at the sibling path `<intents.json>.writer.lock` through `execution_safety.SchedulerLock`. The lock encloses:
1. Mandatory force reload of the latest persisted journal, **under** the lock.
2. Account/request ID/tag uniqueness validation.
3. Update to a deep-copied document and existing atomic JSON save.
4. Release when the journal transaction is committed.

This closes the former lost-update window between two **cooperating, same-path** journal writers. The OS lock is authoritative rather than lock-file existence. Lock acquisition failure raises, preventing the mutation. Holding the mutex briefly does not provide broker-order idempotency.

**Explicit limits:** this is not a distributed lock, not a transactional database, and not a per-account execution lease. A second process with a separate journal path could still place an order; even two processes that share the journal could independently assess stale exposure. Therefore only one authorized OMS process may write orders for a broker account. Recheck account identity and persisted/reconciled orders before every network mutation. Non-cooperating old binaries must not write the same journal at the same time.

### 2. Pure fill-accounting boundary

`trading/application/reconciliation.py:reconciled_entry_balances` now owns the existing `filled BUY - filled STOP - filled EXIT` computation **per entry reference**, preserving the exact legacy branch semantics, aliases, messages and reconciliation failures. `PositionLifecycle._entry_balances` delegates to it. Unknown SELL parent or a negative residual still raises `ReconciliationError`; the method does NOT determine broker-side flatness without a verified position snapshot.

### 3. Pure protective stop-floor boundary

`trading/domain/protection.py` owns three side-effect-free helpers:
- `entry_reference(stop)` resolves the existing entry/parent-order ID.
- `existing_stop_floor(state)` calculates the highest in-scope floor, including `desired_stop_trigger`, unchanged.
- `initial_stop_trigger(entry_price, initial_loss_pct, floor)` rounds the maximum of the historical initial stop and established floor exactly as before.

`StopManager.ref`, `.floor` and the initial placement path delegate. All actual `StopManager` placement/replacement/ratchet/acknowledgement logic is unchanged. **Current strategy-specific stop percentages and time-of-day rules remain authoritative temporarily**; POL-06 will require an explicitly approved unified schedule, before/after trace inventory, and safe migration of active positions. Do not weaken existing protection in the name of unification.

## Reconciliation lifecycle and failure decisions

| Observation | Existing / intended result | Do not do |
| --- | --- | --- |
| Local state malformed, missing intent IDs or an unknown order response | Deny new entry; retain evidence and require broker reconciliation | Assume rejected or delete an unresolved request |
| Order has an unknown SELL parent | Raise reconciliation error | Discard unknown SELL fill |
| SELL fills exceed tracked BUY fills | Raise reconciliation error | Clamp negative residual to zero |
| Partial fill during entry cancellation | Re-read broker positions and orders, reconcile residual before protection | Rely on initial fill snapshot |
| Protective stop ACK without verified trigger-pending status | Keep protection unconfirmed | Treat ACK as coverage |
| STOP cancellation pending/unknown | Persist intent and reconcile before replacement | Submit competing SELL |
| Journal cannot obtain writer lock / disk write fails | Reject intent mutation; new BUY path must not proceed | Retry POST blindly |
| 15:15 IST reached while broker unreachable | Continue management and raise incident; never claim verified flat | Delete state or infer zero exposure |

## Candidate acceptance evidence (not yet executed)

`tests/test_boundary_safety.py` includes codec/journal/rate limiter regressions. `tests/test_oms_recovery_boundaries.py` adds pure fill, legacy parent, existing stop floor, initial tick calculation, two-journal interleaving and held lock cases. Registered via `tests/test_regression.py`; these are **not asserted passing**.

Before merge: run `python -m tools.checks`, `python -m tools.quality`, dedicated boundary tests and manual source/golden trace parity; record real results. Before live: broker account ownership, 65/130/260/390/520/650 order quantity limits, interrupted journal writes, crash-restart events, pending partial fills, cancel/replace races, actual stop-book reconciliation, and operator UAT. The POL-01 sizing ancestor also remains untested.

## Next R02/R03 work packages

1. Enforce **single execution writer per authenticated broker account** across *all* entrypoints, including alternative root/manual scripts, not just one scheduler lock path.
2. Specify the durable request-id state machine and cross-file crash points for every mutation.
3. Review persistence durability (directory fsync, disk failures, atomic rename) and account-scoped state backups/recovery; never delete live recovery files for cleanup.
4. Separate pure broker normalization and reconciliation from cancellation, protection and exits in smaller adapter-level PRs.
5. Approve POL-06 shared stop percentages/time windows and POL-05 loss gating before changing their live behavior.

**The current branch is NOT production-certified.**
