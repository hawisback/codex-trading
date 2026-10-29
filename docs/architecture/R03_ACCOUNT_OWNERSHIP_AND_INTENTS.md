# R03 — Account-scoped scheduler ownership and typed intent phases

**Branch:** `refactor/r03-account-ownership-intent-model-20261029`  
**Parent:** `refactor/r02-oms-recovery-stop-boundaries-20261029` at `8e11657db335c2c2c9dcf8ac33b47a62cc61ee2e`.  
**Change class:** execution safety and phased structural refactoring.  
**Verification:** new test cases prepared; **no tests, live broker sessions or orders executed**. This branch is not production-certified.

## 1. Account-scoped single-writer lease for live scheduler

The existing `nifty_trader_scheduler.main` acquires a workspace-wide `logs/scheduler.lock`; R02 protects individual journal updates with another OS lock. These do not prevent a second Git checkout from independently starting with the **same broker account**.

Now `trading/application/scheduler.py` does the following for **`--live` only**:

1. Construct the trader and complete existing read-only warmup.
2. Run the existing broker `client.set_mode("LIVE")` authorization, requiring mode/live_authorized.
3. Re-read broker status and demand that it is `LIVE`, `connected`, `live_authorized`, and includes a verified `account_id`. If the initial mode response contained an account ID, the two must agree.
4. Acquire `AccountExecutionLease(broker, account_id)` **before** any `--once` cycle, account reconciliation or repeated scheduler cycle.
5. Hold the OS ownership handle across the entire scheduler lifetime, including market-open waits and worker shutdown. Release it in `finally`, even on cycle failure or operator interruption.

A competing cooperating scheduler with the same verified broker/account and local lock-directory cannot acquire the lease and **will not start another order-capable loop**. The existing `logs/scheduler.lock` remains in place.

Implementation: `trading/adapters/account_lease.py` uses the established OS advisory `SchedulerLock` primitive; hashes broker and verified account into a filename so the account string is not written into the filename. Default cross-checkout lock directory is `~/.codex-trading/account-locks/`. Administrators can set a common absolute `TRADING_ACCOUNT_LOCK_DIR` for services using a shared host filesystem. Every cooperating process must use the same directory, OS ownership context and broker identity.

**Limits that are NOT solved by this increment:**
- This is a **local-host advisory filesystem lease**, not a distributed/remote lock, and not broker-backed fencing. Containers, different hosts or different OS users using different lock paths can still write the same broker account.
- Direct imports, one-off gateway commands and the existing proxy REST server are **not yet forced** through this scheduler lease. They must be disabled or integrated before claiming account-wide execution exclusivity.
- There is no automatic broker order cancellation or emergency flatten if ownership cannot be acquired. Operator must reconcile/manage exposure through the already-authorized owner or broker console. NEVER delete an existing journal or state to seize ownership.
- The current gateway `set_mode("LIVE")` is authorization only and does not transmit a trade; the lease is acquired after authorization but before any scheduler order-capable operation.
- The lease does not prove broker order idempotency, account flatness, complete order books, enough margin, fresh quotes or consultation approval.
- The lock is **nonblocking**. Failure to obtain ownership or write the lock raises and prevents a live scheduler cycle.

## 2. Typed, fail-closed intent phase model

`trading/domain/intent_state.py` defines `IntentPhase`: `PREPARED`, `SENT` (reserved), `UNKNOWN`, `ACKNOWLEDGED`, `REJECTED` and `RECONCILED` (reserved). Definitions:

| Phase | Meaning | Can new submission assume no order? |
| --- | --- | --- |
| PREPARED | Durable intent created; a mutation may be attempted | No |
| SENT | Reserved optional persisted pre-send marker | No |
| UNKNOWN | Transmission outcome uncertain | No |
| ACKNOWLEDGED | Broker returned an order ID; a fill is **not** proven | Broker reconciliation still required |
| REJECTED | Definitive failure, not an ambiguous timeout | Subject to normal risk/position checks |
| RECONCILED | Independently confirmed broker state (reserved for migration) | Subject to real exposure and account checks |

A pure `proposed_transition` validates allowed transitions and requires explicit broker-evidence flag to resolve an UNKNOWN outcome to a definitive phase, or to mark an ACKNOWLEDGED order reconciled. This function does NOT itself query a broker or approve a trade, and is not yet wired to journal writes.

`BaseBrokerGateway._prepare` now uses the pure `needs_reconciliation` function when searching existing journal intents. PREPARED, SENT, UNKNOWN, **missing** or **unrecognized** phases are treated conservatively: new submissions are blocked. ACKNOWLEDGED and REJECTED preserve their existing guard treatment; exposure must still be reconciled independently.

This is intentional fail-closed behavior for malformed/incomplete historic journal entries. The journal remains **schema-v1**; the position file remains **schema-v2**. No silent migration or rewritten past intents.

## 3. What is unchanged

- No changes to broker HTTP POST payloads, stop modification calculations, percent/trailing windows, strategy signals, session cutoffs or approved 2/4/6/8/10 sizing thresholds.
- No changes to `AIConsultant.evaluate`, chat/playbook distinction, true consultation veto, broker status authority or price band checks.
- No changed write-ahead journal format, persistence request identity, state/OMS recovery method or order retry policy.
- Existing fallback entry management, partial fill protection and pending exit suppression remain owned by the real OMS.

## 4. Prepared tests / required review

New `tests/test_intent_states.py`, registered in `tests/test_regression.py`, covers:
- Canonical lock-key hashing and case normalized broker identity.
- Duplicate same-account/same-broker lease rejection, release/reacquire and invalid identities.
- Explicit intent transition rules, unrecognized phases, broker-proof requirements.
- No direct broker connections or writes during these cases.

**Tests have not been run.** Before merge and especially before any LIVE deployment:
1. Run `python -m tools.checks`, `python -m tools.quality` and dedicated offline cases, recording actual results.
2. Test full scheduler `--live` authorization and account acquisition with mocked credentials/account status, including exit/exception cleanup.
3. Verify no account-lock bypass across supported entrypoints, both broker adapters, all process identities and proxy deployment topologies.
4. Perform process-kill and concurrent start drills in the actual Windows/Linux deployment filesystem. Observe OS ownership release and verify no split brain.
5. Reconcile all open/unknown order intents, active STOP coverage, current positions and account scope before supervised live rollout.
6. Do not authorize wider lot sizes or 10 trades/day until POL-05 loss gate, broker order-limit UAT and recovery safeguards are reviewed.

## 5. Further R03 work

- Create a verified account-owner context inside *all mutation gateways*, not just `run_scheduler`; the account lease alone cannot cover the proxy server.
- Require lifecycle-aware broker identity read/validate **after** rate-limit and quote waits and immediately before the network POST.
- Design the append-only/durable transition evidence with explicit crash points and broker correlation. Only then wire `proposed_transition` to actual journal writes, preserving schema compatibility.
- Make failure to obtain remote/distributed ownership a fail-closed new-entry incident, **without** disabling legitimate management of existing exposure by the verified original owner.
- Preserve external research/legacy wrappers until their broker and filesystem side effects are verified.

**Do not describe this branch as end-to-end race-free or production-ready.**


## R04 gateway-level continuation

The next unmerged branch now binds the previously scheduler-held lease to native gateways and checks it again after rate-limit/payload waits. Native low-level HTTP mutations also require the gateway's OMS submission context. All changes are untested; proxy/legacy scripts and multiple-host execution remain outside this protection. See `docs/architecture/R04_GATEWAY_MUTATION_FENCING.md`.