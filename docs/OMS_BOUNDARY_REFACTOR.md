# OMS persistence and broker-journal boundary refactor

**Baseline:** `hawisback/codex-trading` at `92da61d2a5c5a1ae5d5e7477db0027f196fb7c5f` (2026-10-29).

## Scope

This change intentionally does **not** alter strategy math, consultation or veto rules,
position-sizing policies, session deadlines, broker requests, or the current on-disk
schema versions. It is a focused, first-stage refactor of the OMS storage boundary.

### Position-state codec: single responsibility

`trading/adapters/position_codec.py` owns the JSON-compatible schema-v2 aliases,
legacy entry/stop hydration and validation of persisted collection types. It has
no file or network I/O. `JsonPositionStore` now owns only file reads, atomic writes,
existence and deletion. Existing import paths (`JsonPositionStore`) remain valid.

- Decoding validates `entries`, `stops`, and `exits` as lists of dictionaries.
- `stop_order_ids`, when present, must be a list of nonempty string or positive
  integer order IDs. Legacy scalar `stop_order_id` and omitted fields continue
  to hydrate as before. Invalid collection types raise `ReconciliationError`
  rather than being interpreted as an empty broker book.
- Encoding retains the prior in-place mutation contract, schema version 2,
  compatibility aliases and filtering of terminal stops.
- Reads do not rewrite the persisted file.

### Gateway-intent journal: defensive persistence boundary

`GatewayJournal` keeps its schema version 1 and its account-specific intent
records. Before a journal is accepted it now validates record identities,
nonempty tags and uniqueness of tags/order IDs **within each account**.
Malformed/unreadable JSON produces `ReconciliationError`; no repair or deletion
is performed automatically. Returned records are deep copies, preventing an
external caller from changing in-memory recovery evidence by reference.

`GatewayJournal.put` treats the request ID and its derived broker tag as
immutable correlation identifiers. Other fields remain merged as before and
writes use the existing atomic writer. Scope/account ownership is unchanged.

### Broker rate limiting

The existing token-bucket limiter now uses one validated request path and a
shared, locked refill routine. Blocking and nonblocking acquisition reject
non-finite, non-positive or oversized token requests before changing token
accounting. Blocking requests reject malformed timeouts. Monotonic clock
regressions do not deduct accrued tokens. Valid pacing stays unchanged.

## Review and later verification

All changes are intentionally reviewable as a single source patch. Offline
regression cases were added to `tests/test_boundary_safety.py` and registered in
the existing explicit suite. **Tests have not been executed in this handoff**, at
user request; neither broker integration nor live execution is certified.

After applying the patch, run from the repo root:

```bash
python -m tools.checks
python -m tools.quality
```

**R02 follow-on (unmerged and untested):** `GatewayJournal.put` now acquires
an OS-level writer lock on `<journal>.writer.lock` for the entire
reload/validate/modify/atomic-save transaction. It always rereads the
persisted journal after acquiring ownership and does not rely on an old
mtime cache. This prevents lost-update races for **cooperating journal
writers using the same path and lock**, not competing BUYs across independent
live schedulers. The writer lock remains a file after release (an orphaned
lock file is harmless; the OS-held handle is authoritative). An unsuccessful
lock acquisition must block the write. Do not create alternate writer code
that bypasses this journal boundary.

R02 also extracts the pure per-entry SELL-fill balance calculation to
`trading/application/reconciliation.py` and stop-floor formulas to
`trading/domain/protection.py` while preserving the `PositionLifecycle` and
`StopManager` call signatures and existing strategy stop percentages.
The user-directed shared stop policy (POL-06) remains unspecified and
is **not** activated by this structural extraction.

Account-level **single OMS process per broker account** or an equivalent
broker-backed durable ownership design is still required. Journal locking
only protects JSON writes; it cannot prevent two independent instances
from concurrently deciding that an entry is eligible, reading old funds,
and both submitting a BUY. Broker-specific UAT, crash/partial-fill
replay and offline parity checks remain outstanding.

Policy corrections already landed in ancestor branch
`refactor/pol01-sizing-and-layout-20261029`; this R02 increment does not
further change lot tiers, risk thresholds or session cutoffs.
