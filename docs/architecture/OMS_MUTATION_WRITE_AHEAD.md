# OMS next increment — Write-ahead CANCEL / MODIFY / REPRICE intents

**Source:** `refactor/oms-intent-recovery-consistency-20261029`  
**Parent:** `refactor/r06-unified-macd-swing-stop-policy-20261029`.  
**Status:** committed for review, **not run, not merged, not broker validated**.  
**Change class:** OMS recovery hardening, not changes to signal, consultation, lot sizing, stop percentages, or risk thresholds.

## Problem

The native gateways already persist `ENTRY`, `STOP` and `EXIT` placement intents before network submission. Previously, a request to CANCEL an entry/stop/exit, MODIFY a stop, or REPRICE an exit could reach the network with no distinct durable mutation intent. After a timeout/restart, the engine could not distinguish an attempted mutation from a never-submitted one using the JSON gateway journal alone.

## Implemented increment

1. `GatewayJournal.prepare_mutation` runs an **OS-locked, force-reloaded check-and-insert**. It creates a separate stable request/tag for the mutation, with:
   - `kind=MUTATION`;
   - `mutation_action=CANCEL|MODIFY_STOP|REPRICE_EXIT`;
   - `target_kind=ENTRY|STOP|EXIT`;
   - `target_order_id` (reference to the original order);
   - `symbol` and `phase=PREPARED`.
2. The new mutation record does **not** claim the target's `order_id`; this preserves unique broker-order correlation in the original entry/stop/exit intent.
3. A **PREPARED/UNKNOWN/SENT** mutation for the same target prevents a second mutation being prepared. A failed journal write prevents the network operation.
4. `BaseBrokerGateway._mutate_existing` writes PREPARED first and uses the existing `_submission` ownership/context checks before the actual Kite/Breeze DELETE/PUT.
5. For explicit `not_submitted=True` preflight vetoes, the mutation becomes REJECTED. For a successful response, the mutation becomes ACKNOWLEDGED; **ACK is not evidence of the requested modification, cancellation, fill, or account-flat state**. All ambiguous network or malformed outcomes become UNKNOWN.
6. New BUY/STOP/EXIT placement result phases now go through the existing validated `GatewayJournal.transition` API as well. Older recovery-file hydration and broker identity reconciliation are not force-migrated.

This does not change native HTTP payloads or introduce network retries. Unknown outcomes are never automatically resubmitted. The existing single-machine account lease and explicit LIVE/session requirements remain intact.

## Recovery and operational limitations

- A journal's PREPARED state may mean the process crashed **after intent persistence but before transmission**, or that it crashed **during/after transmission**. It must not be treated as proof the exchange never received a mutation.
- An UNKNOWN CANCEL does not prove the protective stop was canceled; UNKNOWN MODIFY does not prove the new stop was accepted. Check actual order status, quantities, trigger levels, account identity and positions from a fresh broker book before acting.
- An ACKNOWLEDGED CANCEL likewise needs **terminal status confirmation**; an ACKNOWLEDGED MODIFY needs broker price/trigger confirmation.
- This change does **not** automatically classify old ambiguous mutations as RECONCILED. The existing `GatewayJournal.transition` permits UNKNOWN→RECONCILED only after separately verified broker evidence. No automatic blanket clearing and no unsafe journal deletion.
- An unresolved mutation blocks another mutation of the **same broker order**. The existing gateway placement gate additionally blocks new BUY/STOP/EXIT submissions while any unresolved journal phase remains, so a pending cancellation can delay recovery and may need human broker-console action. This trade-off must be evaluated with emergency protective exits.
- Distinct order targets can have separate mutation intents. A journal write lock is not execution-level authorization and does not replace single OMS process ownership.
- The external proxy service and scripts that bypass native gateways are outside this implementation; a single-machine deployment does not make those safe to run concurrently with the authorized scheduler.

## Acceptance evidence prepared (not executed)

`tests/test_existing_order_mutations.py` includes:
- Independent mutation identity without duplicating `order_id`.
- Concurrent journal instances failing to prepare a second unresolved mutation on the same target.
- Unknown-phase verification requirement.
- Offline simulated cancel/stop-modify success, rejection and lost mutation outcome.
- Old request-to-order correlation surviving cancellation.

These tests have **not** been run. Prior to any merge, perform offline fixture/replay verification and audit all pending and emergency exit paths. Before LIVE, run broker-specific cancel/modify observation tests including delayed ACK, partial fills, stop-trigger races, token expiry and interrupted journal writes. Do **not** remove an active protective stop or bypass broker status verification to clear recovery evidence.

## Next tasks

1. Design explicit evidence-backed reconciliation of PREPARED/UNKNOWN/ACKNOWLEDGED modifications and cancellations against current broker orders and positions. Do not mark flat just because a token refreshed.
2. Verify the new restrictions do not block emergency protection/mandatory square-off; add supervised operator recovery mechanisms.
3. Consolidate remaining local proxy/legacy writers so exactly one process can mutate the account on the single machine, without additional authentication infrastructure.
4. Continue the repository cleanup after entrypoint and recovery-file dependency inventory.
