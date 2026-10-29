# R04 — Native gateway mutation fencing and atomic intent transition API

**Branch:** `refactor/r04-gateway-mutation-fencing-20261029`  
**Parent:** `refactor/r03-account-ownership-intent-model-20261029` at `52ffededc217421a5138d5b472c7ede2780c6d4f`.  
**Classification:** safety/behavioral hardening, not a strategy or risk-policy tuning PR.  
**Status:** committed for review. **No tests, broker connections, order placement, or broker UAT performed.** Not approved for live deployment.

## 1. Native mutation requires a bound and held execution lease

The local-host account lease introduced in R03 now becomes a **gateway-level precondition** for Kite/Breeze live order writes, not merely a scheduler startup convenience.

- After explicit LIVE arming, `trading/application/scheduler.py` acquires the account-specific `AccountExecutionLease` and calls `client.bind_account_lease(lease)` for native Kite/Breeze gateways. If the gateway lacks binding support or the verified account differs, startup fails closed.
- `BaseBrokerGateway.bind_account_lease` requires current LIVE authorization, a connected verified account, a held OS lock, and a lock path matching the exact verified `broker_name:account_id`. It does not accept an arbitrary or fabricated path.
- `BaseBrokerGateway._authorize` rechecks account scope, mode and held lease before entry/stop/exit/modify/cancel workflows.
- The concrete Kite and Breeze `_request` methods recheck ownership **after rate-limit waits and again after any deferred wire-payload callback**, immediately before the HTTP mutation. If authorization/ownership is lost, they return an error without submitting an order.
- Paper/unarmed native requests still fail as before. Proxy behavior is not silently altered by this change.

### Important account-ownership limitations

This is a cooperative **local-host OS advisory lease**, not a remote/distributed lock or broker-backed fencing token. It can exclude cooperating native schedulers sharing the same OS user, lock root and verified account; it does not exclude processes on other machines or legacy code that ignores the lease.

The native gateway low-level HTTP boundary additionally requires a scoped `BaseBrokerGateway._submission` context, so direct calls to `_submit_buy_order`, `_request("POST", ...)` and similar internal transport methods cannot bypass the usual OMS entrypoint *even when an account lease is held*. This context is a local programming safety boundary, **not** proof that a particular intent was durably committed (the high-level `_submit_intent` still owns that persistence).

**Incomplete coverage:**
- `AIExecutionClient` proxy and its external server require an independent, account-scoped ownership boundary; the ChatGPT/GitHub refactor does not change the running proxy server.
- Standalone root/manual scripts and custom broker clients may still access broker APIs outside the guarded gateway.
- Multiple hosts, containers and non-cooperating old binaries can still race. Stop/restrict those processes operationally until a shared coordinator or broker-side fencing architecture is selected.
- Network uncertainty still requires broker order/position reconciliation; the lease cannot prove no fill or stop coverage.

## 2. Existing order paths and compatibility

| Operation | Re-check location | Notes |
| --- | --- | --- |
| BUY, STOP, EXIT | `_authorize` and final native `_request` | Existing durable `PREPARED` request ID and callback preflight retained |
| STOP modify / cancel ENTRY/STOP/EXIT | `_authorize` and final native `_request` | Calls stay under `_submission`; separate mutation-specific write-ahead evidence still needs design |
| Broker profile / order / funds / quote GET | No order-write lease required | Read-only account verification and UAT remain available |
| Breeze session exchange | Existing read-only `GET /customerdetails` path | Not an order mutation; remains functional before arming |
| Proxy execution | Unchanged | Requires separate review and coverage |
| AI consultant / strategies / trailing math | Unchanged | Mandatory veto retained |

## 3. Durable intent transition API (staged)

`GatewayJournal.transition(request_id, next_phase, broker_verified=False, **updates)` provides a future-safe helper:

1. Obtain the journal's **existing OS writer lock** and force reload current on-disk evidence.
2. Require an existing, prepared request identity (cannot “create” an order through phase advancement).
3. Validate the phase advance using `trading/domain/intent_state.proposed_transition`.
4. For UNKNOWN→ACKNOWLEDGED/REJECTED/RECONCILED require independent broker verification as an explicit input.
5. Atomically write the validated record using the existing schema-v1 JSON and immutable request/tag rules.

The method is **available, not yet applied to all old journal update call sites**. In particular broker `get_orders` reconciliation, existing STOP/EXIT cancel/modify transitions, and the current `_submit_intent` phase updates still use compatibility `journal.put`. Do not claim end-to-end strict transitions until those are migrated with verified broker evidence and crash boundary tests.

## 4. Tests and runbook impact

Prepared, **not executed**: existing Kite/Breeze offline simulator fixtures now bind a held fake-account lease for authorized tests; new cases cover unbound LIVE mutation rejection, lease loss and low-level transport bypass; `tests/test_journal_intent_transitions.py` checks UNKNOWN resolution, phase invalidation and simultaneous journal-instance reloading. All are registered in `tests/test_regression.py`.

Before any merge or LIVE rollout:
1. Run `python -m tools.checks`, `python -m tools.quality`, broker gateway/offline tests, and targeted process/lock tests; record actual results.
2. Test mocked broker status refreshing after delay and after session/credential switch; verify rejection before network emission.
3. Validate Windows and Linux OS lock semantics, account lock permissions and deployment-specific lock root.
4. Verify normal BUY/STOP/EXIT and post-fill trailing/cancel flows with redacted broker test responses. The new fencing intentionally changes behavior for direct native gateway users: **they must hold and bind a verified account lease**.
5. Confirm emergency management of existing positions remains possible through the original authorized owner or broker console if another process is blocked.
6. Audit proxy/manual order writers, and do not deploy this code until that exposure is understood.

**Conservative policy:** do not merge/deploy this untested branch to a live capital account. An untested protection that accidentally blocks legitimate emergency exits also creates trading risk.
