# LIVE integration hardening and activation hold — 2026-10-30

**Repository:** `hawisback/codex-trading`  
**Work branch:** `feature/live-activation-guardrails-20261030`  
**Base:** `refactor/r02-r10-safety-foundations-20261029`  
**Status:** INTEGRATION CODE OWNER-REVIEWED; **NOT ENABLED / NOT TESTED / NOT BROKER-UAT VERIFIED / NOT MERGED OR DEPLOYED.**  
**Owner request:** Implement and enable all phases for LIVE. The engineering integration can progress; a real-money go-live cannot be certified or executed without missing broker evidence and validation.

See [canonical current status](CURRENT_IMPLEMENTATION_STATUS_20261030.md) and [unified stop integration specification](R01_UNIFIED_STOP_EXECUTION.md). Owner code review does **not** replace the still-unexecuted offline regression, adverse OMS recovery or supervised broker acceptance gates.

## Implemented in this increment

- **Kite/Breeze authenticated funds receipt provenance:** Native `_fetch_broker_funds()` now includes `account_id`, `funds_asof` and a provider-specific `source`. The time is when the authenticated broker response was received by this process, **not** a broker-supplied exchange timestamp, position P&L, or broker account-equity ledger. Funds are still live broker response values, not JSON assumptions.
- **R01 submission-time funds validation:** `position_lifecycle._submit_entry` uses `BrokerFundsView.validated()` before lot sizing and again inside the broker pretransmit callback. An account mismatch, expired receipt, missing order limit or malformed funds response blocks only the NEW entry. It rechecks the independently required daily P&L gate. It does **not** fetch a second broker funds read after queueing and does not change OMS exit/protect procedures.
- **Single-account native LIVE writer:** `BaseBrokerGateway.set_mode("LIVE")` obtains an OS-based account lease from a broker-verified account; every native BUY/STOP/SELL/CANCEL/MODIFY transport verifies lease ownership before mutation. A second native gateway in a competing process cannot arm the same broker/account through the same lock namespace. Disarming to PAPER does **not** release the lease mid-process, because this is not evidence that broker orders are flat. OS lock release occurs at process exit; operator reconciliation remains mandatory. Legacy external broker clients and a differently deployed engine version cannot be fenced by this local lock; this is not a distributed lock.
- Offline unit fixtures were written and registered. No tests were run, as previously directed.

## Mandatory missing LIVE inputs

Neither current native broker `get_funds()` normalization establishes all requirements for R01:

| Missing evidence | Why it is required | Safe behavior until supplied |
| --- | --- | --- |
| `max_single_order_quantity` | Real broker/instrument-specific freeze quantity; cannot assume one lot or 650 is the broker's order limit | Block NEW R01 BUY |
| `pnl_account_id`, `pnl_session_date`, `pnl_asof` | Match a broker-reconciled current-day P&L ledger to the authenticated account/time | Block NEW R01 BUY |
| `start_of_day_equity` | Actual day opening equity baseline for 1.5% loss threshold, not arbitrary configured capital | Block NEW R01 BUY |
| `realized_pnl_today`, `unrealized_pnl_today` | Verified loss including live open exposure | Block NEW R01 BUY |
| Current exchange calendar and validated broker instrument master | R05 code only defines a source-evidence resolver; it is not a connected authoritative feed | Do not allow unverified new expiries |
| Unified stop parity and OMS recovery proof | R01-stamped positions now use one shared monitor and StopManager policy; legacy stops remain intentionally available for non-R01 positions. End-to-end broker/crash/partial-fill tests remain outstanding | No replacement of active LIVE OMS before verification |
| Broker-specific rate/partial-fill/order-cancel UAT | Offline types cannot prove real broker response identity, stop coverage, quantities or live order semantics | No LIVE release |

**Do not create synthetic positive data or hardcode these fields.** A broker endpoint that reports available cash alone is **not** evidence of real-time daily realized+unrealized P&L. Broker freeze quantity may depend on exchange instrument, contract and current notices.

## Required before a supervised LIVE activation

1. Implement account-verified normalized broker P&L aggregation from authoritative broker positions/trades and opening account equity. Establish timestamps, source identity, reset at IST session boundaries, and behavior on partial/closed trades. No inferred zero values.
2. Load and verify the current broker instrument master; derive and check broker-specific order freeze limits against the current contract, with appropriate source provenance. Do not split orders without new OMS design/approval.
3. Connect the exchange holiday and expiry source to R05 without guessing session weekdays, then enforce new-entry market-data freshness while leaving existing-position protection active.
4. Complete and test OMS account-lease lifecycle through every permitted entrypoint, crash restart, stop replacement, partial fills and unknown broker acknowledgments.
5. **Validate the newly integrated R01 unified stop path** with legacy parity, stale quote, tick floor, stronger-stop, active-position policy freeze, partial-fill, order modification and crash/restart tests; preserve all pre-existing legacy stops. Integration is coded but not proven by execution.
6. Run (with the owner's explicit changed instruction) the complete offline suites, replay adverse-event scenarios, and broker sandbox/supervised UAT with known-safe size and recovery drill.
7. Obtain a separate review/approval of exact deployed commit, verified account, risk limits, operator ownership, kill switch and rollback plan. Only then consider turning `r01_policy.enabled` to true and authorizing a controlled LIVE start.

## Current activation facts

- Current branch config remains `r01_policy.enabled=false`.
- Config text `mode: LIVE`, `system_armed: true` does not itself authorize native broker LIVE; the CLI still requires `--live` and the gateway's account authorization.
- `main` is unchanged and no broker order was submitted, canceled or modified in this change.
- Only *static syntax* was examined for this increment; this is not a pass of integration or regression tests.
- `tools/refactor_readiness.py` intentionally reports BLOCKED, because the required proof is not present.
