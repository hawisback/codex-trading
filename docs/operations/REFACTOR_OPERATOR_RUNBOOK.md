# OMS and market-data operator recovery runbook (R02–R10)

**Status:** DRAFT — not validated by a supervised incident drill.  
**Never use this procedure to bypass an AI veto, kill switch, unverified broker account, uncertain order, or existing protective stop.**

## Before market open

1. Verify a single approved LIVE process/operator and broker account identity using the broker's own authenticated session. No LIVE arming from JSON alone; retain explicit `--live`.
2. Preserve state, journal, and recovery evidence; inspect OS-level OMS process lease and release only if the prior process is genuinely terminated and broker exposure has been reconciled. A leftover lock file alone is not proof of a live holder.
3. Confirm all NIFTY instruments, expiry/holiday sessions and current broker master match. Unknown or stale symbol/expiry → block NEW entries, manage existing positions.
4. Verify live available funds and per-order broker quantity freeze limit. For R01, also verify current-day start-of-day equity and realized/unrealized P&L for the same account, with explicit timestamps and correct IST session. **No static capital fallback**.
5. Confirm recent exact-contract bid/ask depth and completed strategy bars. Stale quotes/OI gaps block NEW exposure.
6. Check kill switch, stop coverage, durable unknown intents and any pending exit. Do not accept a startup READY verdict until the full offline suite and broker acceptance have been recorded.

## Unknown order result / lost ACK

- Stop new entries. Preserve request ID, account, broker, contract, client tag, journal and last transmission timestamps.
- Obtain fresh broker order/position books. Reject truncated responses and incorrect account/symbol/product/exchange.
- Determine filled quantity and any active protective SELL from broker-confirmed identifiers. Never infer rejected from timeout.
- Do not repeat the BUY, SELL or stop replacement until ownership and remaining filled quantity are reconciled.
- If position protection is not confirmed, escalate immediately. Never represent unknown exposure as flat.

## Partial fill or stop replacement uncertainty

- Compute protected residuals from verified entry fills minus verified stop/exit fills.
- Persist any STOP/CANCEL/MODIFY intent before sending. A successful HTTP response is not confirmation that a stop is broker-active.
- After cancellation, refresh fills and stop status; do not submit a competing SELL. On ambiguous cancel outcomes, hold unresolved state and escalate.
- Continue managing existing positions even if market data, P&L or calendar updates prevent NEW entries.

## Feed/calendar/market close outages

- Stale/invalid quote or expired instrument master: no new BUY, preserve active protection.
- At **14:15 IST**, block new entries. At **15:15 IST**, initiate mandatory exit management.
- If broker connection is lost at square-off, keep the incident and exposure open. Verify broker flatness and all resting SELL orders when connectivity returns.
- Prevent overnight hibernation while exposure or the completion of a SELL remains unverified.

## Stop trading / restart / rollback

- Operator should first establish account, process ownership, pending orders, broker positions and protective stops.
- Preserve and back up recovery files *before* changing binaries or config. Do not delete/copy old journal fragments into a new active account without verified reconciliation.
- `r01_policy.enabled` remains **false** until audited broker field normalization, offline tests and supervised UAT are complete.
- Rollback must preserve the older position policy version and any stronger confirmed stop floor. Never lower a stop due to a policy reload.
- Use `python -m tools.refactor_readiness` for a **read-only, intentionally BLOCKED** report; it does not connect, certify broker safety, or arm trading.

## Incident codes and escalation

| Code | Meaning | Immediate handling |
| --- | --- | --- |
| `ORDER_OUTCOME_UNKNOWN` | A send may have succeeded | Block new exposure, preserve evidence, reconcile |
| `POSITION_UNPROTECTED` | Residual risk has no verified stop | Critical operator incident; reconcile and protect/exit via existing verified OMS |
| `SQUAREOFF_UNVERIFIED` | Squareoff triggered but flatness unknown | Critical; keep active exposure incident |
| `JOURNAL_UNREADABLE` | Recovery evidence malformed/missing | No new entries; preserve files and investigate |
| `MARKET_FEED_STALE` | Exact contract quote stale/invalid | No new entries, continue protective actions |
| `DAILY_LOSS_LIMIT` | Broker-reconciled loss guard reached | Halt new entries for IST session |
| `EXPIRY_SOURCE_UNVERIFIED` | Exchange session / master mismatch | No inferred contract or symbol |

**No automated trading actions are emitted by the incident taxonomy.**
