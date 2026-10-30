# Native gateway safety and recovery

> **Unverified LIVE increment:** On `feature/live-activation-guardrails-20261030`, the native account lease and authenticated funds receipt provenance are coded but **not broker-UAT tested**. R01 remains disabled. See [current status](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md) and [broker integration](BROKER_INTEGRATIONS.md).


The proxy remains the default execution gateway. Native Kite and ICICI Breeze
require explicit `--broker kite --live` or `--broker breeze --live`. Omitting `--live` fails
before trader construction. Direct gateway objects also start disarmed; PAPER
mode cannot submit, modify or cancel real orders. Native PAPER simulation is not
implemented; use the proxy for paper execution.

Native Breeze now uses signed REST requests and the shared serialized OMS,
durable order correlation, residual-fill protection and exit workflow. Its
constructor does not log in or import the Breeze SDK. See
[broker setup and limitations](BROKER_INTEGRATIONS.md) for credentials,
request quotas, supported contracts and read-only data APIs. The existing proxy
remains available for both brokers and for paper execution.

## Account and contract identity

Kite credentials retain argument/environment/file precedence. The optional
`config/kite_credentials.json` contains `api_key`, `access_token` and `account_id`;
the example contains placeholders only. File-provided account identity is no
longer hidden by a placeholder default.

Before arming, `/user/profile` verifies the authenticated user. A configured
account must match that user. Profile verification is cached for up to 60 seconds
on the same credentials; HTTP 403 or changed credentials revoke authorization.
Credentials must be refreshed by the operator and execution explicitly rearmed.
No login is attempted during construction or import.

The scheduler's internal IDs (`INST-NIFTY-...`) and option-chain trading symbols
are separate identities. After actual AI approval, the lifecycle registers the
provided pair. Native quote requests and orders use the trading symbol, while
quote evidence and AI identity checks retain the internal ID. Missing mappings
and conflicting mappings are rejected; the gateway does not guess an expiry or
contract from an internal ID. Index and option quotes are requested together when
structural invalidation needs both, respecting the quote endpoint's pacing while
keeping the same entry freshness checks.

Native execution for both brokers still uses the local proxy's market-context/feed endpoints.
Selecting native Kite does not replace candle, technical, breadth or option-chain
ingestion. It requires a valid Kite session and access to the quote endpoints.
The same separation applies to native Breeze. Optional direct historical-data
and Breeze option-chain reads are explicit methods, not automatic feed failover.

## LIVE account ownership and strict R01 broker evidence

Native `BaseBrokerGateway` now requires an authenticated broker/account-scoped OS lease before LIVE arming and before every real mutation. It fences cooperating adapters sharing the same host lock namespace but not proxy OMS, other deployments with independent lock paths, or unrelated broker clients. A mode change to PAPER does not release the lease while the process is alive; operator reconciliation and supervised owner transition are required.

Native `get_funds()` responses include `account_id`, `source`, and `funds_asof` as receipt metadata. **Receipt time does not certify the broker's opening equity or current daily realized/unrealized P&L.** No missing per-instrument broker order freeze quantity is invented. The strict R01 LIVE entry/submit gates fail closed until the broker provides these claims with matching account, timestamp and contract provenance.

## Persistent execution metadata

`logs/broker_intents.json` is synchronous recovery metadata, **not an observational
log**. It stores broker/account-scoped internal request IDs, 20-character
alphanumeric broker tags, order IDs, parent entry references, contract identities
and submission phases. It contains no API credentials. Custom state stores place
this file beside `active_position.json` through the scheduler's composition.

The gateway atomically persists an intent before sending an order. Tags correlate
requests; they are not assumed to provide broker-side idempotency. All native
HTTP mutations use one transmission attempt. A network timeout, invalid response
or server-side failure preserves an unknown outcome. The gateway does not resend
it, even under a different request ID while an unresolved intent remains.

An acknowledged order is mapped durably. If acknowledgement persistence fails,
the response retains the known order ID and marks the outcome uncertain. Later
broker reads can recover it by its tag. Restart recovery imports known persisted
position references after verifying the account; it also supports unambiguous
legacy truncated tags. Null broker parent fields cannot erase saved references,
and conflicting identities block reconciliation. Duplicate tag matches are errors.

The metadata file retains completed relationships, so an earlier round trip in
the same contract can be excluded when reconciling a later trade. Separate gateway
objects refresh changed metadata before writing. Within the scheduler, its
existing OS singleton and serialized OMS owner remain in force.

Do not delete this file or the active-position file to clear an unknown outcome.
A missing/corrupt journal after use, ambiguous history, foreign active orders,
or mismatched account identity requires explicit broker reconciliation. An older
position with a placeholder account name may need manual identity reconciliation
before the corrected gateway can resume it. No automatic account relabeling occurs.
Runtime-log compression does not touch these files.

## Fills, stops and exits

An exit submits only SELL. Stop and exit quantities come from confirmed BUY fills
minus linked STOP/EXIT fills, checked against broker exposure. Pending SELL orders
block an additional exit for that entry reference; cancellation is followed by fresh verification. Partial
stop fills during cancellation reduce the exit quantity. A positive verified
partial entry fill can be protected while its remaining BUY cancellation is still
pending. A zero-fill entry cannot create a protective SELL.

The final check runs after rate-limit waiting and metadata persistence. Entry
preflight rechecks the existing AI band, freshness, expiry and invalidation rules.
Active trailing also uses fresh executable bids, pending modification verification
and durable 25-attempt stop replacement; see [trailing stops](TRAILING_STOPS.md).
Stop/exit preflight checks residual quantity again; a changed quantity rejects the
prepared order instead of sending the old size. Exit callbacks persist one intent
per actual attempt. This is client-side serialization and reconciliation, not an
exchange-atomic cancel-and-sell operation.

Kite orders/positions/funds failures and malformed responses remain errors.
Authoritative reconciliation bypasses TTL caches; an expired cache is never
returned as a successful broker verification. A verified zero live balance stays
zero. Quotes retain exchange timestamps and depth quantities; no local timestamp
or LTP bid/ask substitution is made.

Each actual HTTP attempt is paced. Quote requests use a separate one-per-second
bucket; other requests share the configured bucket capped at ten tokens/second.
GET retries are bounded by the remaining request/read budget. Entry quotes have
no automatic retry. Mutation retries are delegated to a future reconciled cycle
with a new persisted intent after a definitive rejection. Other applications can
still consume broker quota and cause 429 responses.

The remaining time budget caps each socket timeout and retry delay. Socket
timeouts are not hard end-to-end cancellation of DNS, operating-system stalls or
individual response reads. Existing cycle-overrun diagnostics remain relevant;
this does not promise a five-second upper bound or guaranteed fills.

## Verification

Run `python -m tools.quality` from the repository root. Native gateway tests are
registered in the offline suite and use fake HTTP broker responses. They exercise
actual AI approvals/vetoes/timeouts, restart and lost-acknowledgement recovery,
partial-fill protection, cancellation races, residual quantities, account/mode
guards, internal-ID translation, budget/rate waits, missing quote evidence and
persistence failures. Existing non-native OMS trace fixtures remain unchanged.

No broker session was opened or real order sent during verification. Offline
checks do not certify exchange integration, token entitlements, real fill latency
or all market conditions. The AI consultant is unchanged. The active strategy now
continues beyond +50% with a 5% peak pullback instead of a fixed profit target.

API contracts were checked against the official Kite documentation for
[orders](https://kite.trade/docs/connect/v3/orders/),
[profile and margins](https://kite.trade/docs/connect/v3/user/),
[quotes](https://kite.trade/docs/connect/v3/market-quotes/), and
[errors and limits](https://kite.trade/docs/connect/v3/exceptions/).
