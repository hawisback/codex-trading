# ADR-003 — Single-machine live deployment and broker-session authentication

- **Decision:** Approved scope by owner, 2026-10-29
- **Status:** Architecture requirement; no runtime behavior changed by this ADR
- **Scope:** Native Kite/Breeze order execution, scheduler process ownership, broker sessions

## Decision

Deploy the live trading engine on **one machine** with **one active trading scheduler/OMS**. The machine interacts with Kite and Breeze via their existing broker-supported authenticated APIs. The operator supplies or refreshes the short-lived broker session/token using each broker's supported workflow as required (including daily renewal when required).

**Do not build an additional authentication, authorization, account security, identity service, MFA frontend, distributed lock, cloud coordination service or multi-host leadership system.** The broker remains the authority for accepting/expiring tokens; never bypass that authority or infer a session remains active solely because a token string exists.

## Keep local operational risk controls

These are **not extra broker authentication**:

- A single local scheduler process lock (and, for now, account-scoped local lease) to prevent accidental duplicate trading workers; no remote fencing.
- The existing explicit LIVE arming and broker session/account consistency checks; no fresh login secret or operator approval screen.
- Write-ahead order intents, unique IDs/tags, atomic journals, broker order reconciliation and strict handling of UNKNOWN submission outcomes.
- Price freshness, authenticated broker available margin, capital-based 2/4/6/8/10 lot ladder, mandatory consultation veto, risk preflight, time cutoffs and stop/exit safety.
- Operator emergency recovery via the authenticated broker when the trading engine cannot acquire its local lock; do not bypass state reconciliation or delete journals to force startup.

## Session turnover lifecycle

1. Renew the broker token via its supported mechanism when required, without putting token values into source control, docs or logs.
2. Start the same local scheduler with valid current credentials and existing LIVE arming.
3. Confirm authenticated account identity and journal account scope before any new order.
4. Reconcile unknown/pending orders, position fills and protective stop coverage from the broker. A new token does not reset broker exposure.
5. If expired or rejected during the session, prevent new entries; retain evidence and route protective management/recovery through a valid authenticated session or broker console, without duplicate orders.

## Explicit non-goals

- Cross-machine/distributed synchronization, remote fencing or remote leader election.
- Supplemental login, a new security/authorization layer, broker session-token generation bypass, or central secret vault integration.
- Changing existing stop percentages, trailing timings, AI approval, trading frequency, sizing, broker contract restrictions or safety cutoffs.
- Claiming session expiry times or daily renewal behavior identical for every broker.

## Implementation status

R04 native gateway local lease and OMS mutation-context checks are already on an unmerged branch. They are local concurrency and order-safety checks; they should **not** be marketed as extra authentication. No implementation changes or tests in this ADR-only clarification. Complete prepared offline tests and account/order-recovery drills before live deployment.
