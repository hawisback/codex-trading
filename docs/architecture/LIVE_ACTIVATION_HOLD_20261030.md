# LIVE integration hardening and activation hold — 2026-10-30

**Repository:** `hawisback/codex-trading`
**Work branch:** `feature/live-activation-guardrails-20261030`
**Current release target:** **Kite only; Breeze deferred by owner.** Breeze authentication is outside this release's gates. Kite R01 read-only evidence passes; actual broker order acceptance remains required.
**Base:** `refactor/r02-r10-safety-foundations-20261029`
**Status:** PRIOR INTEGRATION OWNER-REVIEWED; **LOCAL OFFLINE REPAIRS PASS / CONFIGURED FOR PAUSED ACCEPTANCE / NOT BROKER-UAT VERIFIED / NOT MERGED OR DEPLOYED.** See [executed validation and local candidate identity](OFFLINE_VALIDATION_20261030.md).
**Owner request:** Implement and enable all phases for LIVE. The engineering integration can progress; a real-money go-live cannot be certified or executed without missing broker evidence and validation.

See [canonical current status](CURRENT_IMPLEMENTATION_STATUS_20261030.md), [executed offline validation](OFFLINE_VALIDATION_20261030.md) and [unified stop integration specification](R01_UNIFIED_STOP_EXECUTION.md). Passing local fixtures does not establish real broker behavior or satisfy supervised broker acceptance.

## Implemented in this increment

- **Kite/Breeze authenticated funds receipt provenance:** Native `_fetch_broker_funds()` now includes `account_id`, `funds_asof` and a provider-specific `source`. The time is when the authenticated broker response was received by this process, **not** a broker-supplied exchange timestamp, position P&L, or broker account-equity ledger. Funds are still live broker response values, not JSON assumptions.
- **R01 submission-time funds validation:** `position_lifecycle._submit_entry` uses `BrokerFundsView.validated()` before lot sizing and again inside the broker pretransmit callback. An account mismatch, expired receipt, missing order limit or malformed funds response blocks only the NEW entry. It rechecks the independently required daily P&L gate. It does **not** fetch a second broker funds read after queueing and does not change OMS exit/protect procedures.
- **Single-account native LIVE writer:** `BaseBrokerGateway.set_mode("LIVE")` obtains an OS-based account lease from a broker-verified account; every native BUY/STOP/SELL/CANCEL/MODIFY transport verifies lease ownership before mutation. A second native gateway in a competing process cannot arm the same broker/account through the same lock namespace. Disarming to PAPER does **not** release the lease mid-process, because this is not evidence that broker orders are flat. OS lock release occurs at process exit; operator reconciliation remains mandatory. Legacy external broker clients and a differently deployed engine version cannot be fenced by this local lock; this is not a distributed lock.
- The owner subsequently authorized testing and repairs. The quality wrapper and 574 registered offline tests now pass locally; see the validation record. The feature-branch repair candidate still requires operator-run broker acceptance.

## Kite source integration and remaining acceptance

The owner revised the risk policy on 2026-10-30: up to 2 lots below INR 40k; 4/6/8/10 at INR 40k/60k/80k/100k, limited by executable premium and the INR 150 reserve. Daily realized + unrealized account loss is capped at INR 3,000 per actual proposed entry lot, recalculated at every entry. At a breach, only new entries are blocked; existing stop management continues. Opening-equity and the older 1.5% rule are not R01 requirements.

`KiteExecutionGateway.get_entry_funds()` now combines real authenticated margin, raw net/day positions reconciled against today's fills, exact current-master contract identity/lot/tick, published NSE NIFTY freeze quantity, and current-year FO holiday evidence through the R05 resolver. Account/session/credential changes, stale receipts, ambiguous/missing books, carry positions, unsupported calendars and changed contracts block new entries. The selected contract must meet the configured minimum remaining regular-session budget. These sources passed read-only acceptance against the refreshed Kite session; see [validation](OFFLINE_VALIDATION_20261030.md).

Actual broker order/protection/recovery acceptance is still pending. Follow the [local acceptance procedure](../operations/KITE_LOCAL_ACCEPTANCE_20261030.md). The operator must perform actual order submissions and activation; the assistant can inspect books and logs. No fake broker funds or arbitrary quantity constants were substituted to clear the gate.

This is a single-machine Windows release. No CI, Linux/distributed rollout, or new security project is required. Keep existing account identity, the local account lease, mandatory consultation and risk/OMS protections. The tested source fingerprint identifies the candidate. The owner requested feature-branch check-in; Git publication does not complete broker acceptance or authorize LIVE activation.

## Current activation facts

- Current branch config has `r01_policy.enabled=true` and `auto_trade_enabled=false` for a paused operator start; this does not arm a native gateway.
- Config text `mode: LIVE`, `system_armed: true` does not itself authorize native broker LIVE; the CLI still requires `--live` and the gateway's account authorization.
- `main` is unchanged and no broker order was submitted, canceled or modified in this change.
- The local repair candidate passed the quality wrapper and registered offline integration/regression tests. This does not establish real broker conformance or approve the final release commit.
- `tools/refactor_readiness.py` intentionally reports BLOCKED, because the required proof is not present.
