# Execution recovery and verification

The scheduler uses `position_lifecycle.py` for deterministic order management and
`execution_safety.py` for atomic state, response validation and the process lock.
Strategy analysis still calls the mandatory AI consultant before proposing an
entry to this layer. Disabling AI consultation is rejected by the scheduler.

## State and recovery

`logs/active_position.json` is repository-relative, schema version 2. It retains
entry, stop and exit records, request IDs, fill quantities and individual confirmed
stop triggers. Legacy single-ID state is migrated on a verified reconciliation.
Compatibility `entry_order_id` and `stop_order_id` aliases remain available; OMS
operations use the complete records and ID lists.

Every BUY, protective STOP and EXIT intent is written and flushed before sending
the request. State replacement is atomic. A corrupt/unwritable state file blocks
new exposure. Do not delete state to work around a reconciliation error.

Network failures are **unknown**, never a flat broker book. A mutation timeout is
not retried: the next cycle searches the journal for its persisted request ID,
then checks the actual order. If an outcome cannot be resolved, the scheduler
preserves the intent and blocks new entries. Restarts follow the same procedure.

Reconciliation discovers related entries and both trigger-pending and triggered
OPEN stop orders. Earlier completed round trips do not contribute stop floors to
new trades. Unfilled BUY quantity is cancelled and reconciled; any partial fill
is protected using the entry's remaining quantity. Failed or unverified stop
placement is never reported as a successfully protected entry.

## Trailing and exits

Each stop has its own confirmed trigger and modification count. Failed updates
remain eligible for retry; successful updates do not hide lagging stops. Current
broker triggers are checked before modification. Stops never intentionally move
down. After 25 local modification attempts, the next required improvement uses
durable cancel/verify/reconcile/create replacement, preserving the strongest floor
and only protecting verified residual quantity. Pending modification targets must
be confirmed before another update is sent. Counts recovered without local
history cannot establish modifications previously made through other clients.

Exits persist `EXIT_PENDING`, discover and cancel owned stops, verify their terminal
statuses, and refresh fills and broker exposure before submitting a SELL for an
entry's residual quantity. Filled stops are reconciled as fills, not cancellation
success. Pending exits block duplicate SELLs for their entry reference; other
verified references can be exited without waiting for the first to fill. Unknown
outcomes still block unverified submissions. Native open exits can be repriced or
cancelled without creating competing orders. `OPEN` is not closed.
State is removed only after verified flat exposure with no unresolved orders and
consistent fill accounting.

Only explicit quote-band rejections or the explicit cancellation conflict can
trigger an exit retry. Cancellation retries require verified cancellation and
fresh exposure checks. New retry intents are persisted before submission. A
definitively rejected exit may re-arm protection at the previous trailing floor;
an unknown exit outcome must not re-arm competing SELL orders.

Open exposure is managed before entry analysis, feed-readiness gates or news.
Structural context reads have a four-second budget; failure retains option-price
and broker stop guards. Reconciliation reads have a twenty-second budget; normal
reads use ten-second request timeouts and one 500 ms delayed timeout retry. These
budgets do not promise a five-second round trip during an outage. The mandatory
15:15 IST square-off precedes structural data reads, and unresolved exposure
prevents overnight hibernation. Live entry session limits are rechecked after AI
consultation; the margin buffer, lot rounding and configured quantity cap apply
immediately before submission.

## Process ownership and service requirements

`logs/scheduler.lock` is an OS-owned lock held for the scheduler lifetime, including
`--once`. A leftover file after a crash does not retain ownership. Entry submission
also uses a shared in-process guard and revalidates broker state under the OMS
lock after AI consultation. Restart existing scheduler processes to load these
changes; an older process that does not acquire this lock cannot be excluded by it.

The existing service exposes a bounded journal, not a guaranteed complete broker
order book. A response at its 200-record limit or marked truncated blocks
reconciliation. Recovery requires identifiable instruments, mode/ownership,
entry linkage for SELL fills, actual filled quantities, and stop quantities and
triggers. Missing identity or fill information is not guessed. Request-ID recovery
requires the service to return the original client request ID in journal records.

No execution service files outside this repository were changed. This client
cannot discover manual orders omitted by that service, provide an account-wide
transaction against other clients, guarantee fills of accepted limit orders, or
confirm closure while the broker is unreachable. An orphan OPEN exit on an
already-flat book remains blocked and logged for reconciliation; the documented
API has no general exit-order cancellation/repricing contract. These service
capabilities require broker-connected validation before live rollout. No live
orders are needed for the offline tests below.

## Offline checks

See [trailing strategy and transitions](TRAILING_STOPS.md) for the uncapped active
runner, 5% peak pullback from +50% gain, fresh bid requirements, our engine's
transition ownership, and the passive execution proxy's pending-exit capabilities.

```powershell
python -m unittest test_self_healing_exit -v
```

Tests use simulated execution responses and temporary directories inside this
repository. They do not run trading backtests, replace the AI consultant, contact
the broker, or write the real active-position state. Scenarios include timeout
recovery across restarts, partial fills, cancellation races, multiple stops,
partial ratchet failure, unfilled exits, scope mismatch, corrupt/failed state
writes, the session cutoff and cross-process lock exclusion.
