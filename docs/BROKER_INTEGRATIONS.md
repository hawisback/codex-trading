# Kite and ICICI Breeze integrations

> **Current feature-branch integration (2026-10-30):** Native LIVE arming now requires a broker/account-scoped host OS ownership lease, and authenticated funds reads record local receipt provenance. Neither native adapter currently supplies the required **session realized/unrealized P&L ledger** or **contract-specific broker order freeze**. R01 is **disabled** and new R01 entries fail closed on missing evidence. The CLI commands below describe transport only, **not** a verified LIVE go-live procedure. See [current status](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md) and [LIVE hold](architecture/LIVE_ACTIVATION_HOLD_20261030.md).


Both native brokers implement the existing `ExecutionGateway` interface:
account/session verification, funds, positions, order reads, executable quotes,
BUY limit orders, protective SELL stop-limit orders, stop changes/cancellation,
and residual-position SELL exits. They share `BaseBrokerGateway` and the existing
position lifecycle. The factory default remains the local proxy.

The scheduler selects one execution broker at a time. It does not submit one
signal to both accounts or automatically switch accounts with an open position.
The existing singleton, one-position gate, actual AI consultant, cash reserve,
quantity limits and 15:15 IST square-off remain in force. This change does not
resolve the previously documented sizing/configuration-policy discrepancies.

## Credentials and session setup

Keep populated configuration local and untracked. The `.env.example` and
`config/*_credentials.json.example` files contain placeholders only.

| Broker | Environment | Optional local JSON |
| --- | --- | --- |
| Kite | `KITE_API_KEY`, `KITE_ACCESS_TOKEN`, `KITE_ACCOUNT_ID` | `config/kite_credentials.json`: `api_key`, `access_token`, `account_id` |
| Breeze | `BREEZE_API_KEY`, `BREEZE_API_SECRET`, `BREEZE_API_SESSION`, `BREEZE_ACCOUNT_ID` | `config/breeze_credentials.json`: `api_key`, `api_secret`, `api_session`, `account_id` |

Constructor arguments take precedence over environment values, which take
precedence over file values. Breeze requires an explicit expected account ID.
Its `api_session` is the daily login `API_Session` value, not the signed
`session_token`. The read-only customer-details call exchanges the former for
the latter and verifies `idirect_userid` before arming. Signed requests hash the
exact JSON bytes with a current UTC timestamp and the secret. Response bodies,
session tokens and secrets are not included in diagnostic output.

Customer verification is cached for up to 60 seconds on unchanged credentials.
Session changes and HTTP/API 401/403 revoke authorization. Refresh credentials
locally and explicitly rearm; the adapter never automates broker login or OTPs.
Breeze orders require the account's registered static IP, according to the
[official reference](https://api.icicidirect.com/breezeapi/documents/index.html).

## Read-only verification

```powershell
python -m tools.brokers --broker both
python -m tools.brokers --broker kite
python -m tools.brokers --broker breeze
```

This command checks customer/profile, funds, positions and orders. It never calls
`set_mode("LIVE")` or submits, changes or cancels orders. It reports failed reads
and returns exit code 1 when either selected broker is unavailable. It does not
certify live quote entitlements, fills, static-IP acceptance or market readiness.
It performs real read requests only when explicitly invoked by the operator.

**Historical/native CLI syntax only; do not launch without a separately approved release.** Having a session and feed is insufficient until broker P&L/freeze, instrument master, offline validation, OMS crash recovery and supervised UAT are verified:

```powershell
python nifty_trader_scheduler.py --broker kite --live --interval 60 --strategy ai_opportunity_radar --ai-mode playbook
python nifty_trader_scheduler.py --broker breeze --live --interval 60 --strategy ai_opportunity_radar --ai-mode playbook
```

Run one scheduler. Both native modes require `--live`; use `--broker proxy`
for existing PAPER simulation. No native broker is armed by default.

## Current native ownership and broker funds provenance

`BaseBrokerGateway.set_mode("LIVE")` verifies the authenticated account and holds a per-(broker, account) host OS lease during the process. Every native mutation transport (BUY, SELL, STOP, modify and cancel) checks ownership. Switching back to PAPER disarms but intentionally retains the lease: this is **not** proof of a broker-flat account. A host lock does not fence other broker clients, distributed processes using a different lock directory or the proxy gateway.

Kite `/user/margins` and Breeze `/funds` provide actual broker margin and now attach `account_id`, `funds_asof` (**local response receipt time**, not broker P&L timestamp) and provider `source`. These APIs **do not** establish `start_of_day_equity`, `realized_pnl_today`, `unrealized_pnl_today` or a verified `max_single_order_quantity`. R01 requires those distinct account/session/contract claims at entry and pretransmit; missing evidence blocks new buys. Stop management/exits are not gated on the daily-loss ledger.

## Breeze contract identity and recovery

The lifecycle registers the approved pair of internal ID and trading symbol.
For Breeze, exact IDs have the form `INST-NIFTY-2026-10-27-23000-CE` or `...-PE`.
The adapter derives the explicit NIFTY stock code, expiry, strike and option right
from this structured ID. It never guesses metadata from a Kite trading symbol.
Foreign active exposure or ambiguous mappings require explicit reconciliation.
Native Breeze execution currently supports NIFTY NFO options only.

`logs/broker_intents.json` retains broker/account-scoped request IDs, tags and
order relationships. Each mutation is sent once. Unknown acknowledgements block
new requests until authoritative order reads recover the matching tag. Partial
stop fills during cancellation reduce exit quantity. Confirmed zero F&O funds
remain zero; unallocated bank cash and other segment allocations are excluded.
Available margin is the broker's F&O allocation minus its blocked F&O funds.

Breeze's `Ordered` + `StopLoss`, with verified pending quantity and a positive
trigger, is normalized to the shared conditional-stop state. Queued orders and
partial fills do not qualify. A known stop converted to `Limit` retains its STOP
identity and is exposed as OPEN, requiring the existing risk-exit workflow.
Expired orders without explicit expired quantities are rejected as unverified
rather than guessing fills. Broker integration testing must confirm these wire
representations for the enabled account before relying on native execution.

Breeze pacing is capped at 1.5 requests/second with capacity one, below the
documented 100/minute quota. Every attempted request, including session exchange,
reserves a persistent per-app daily count in `logs/breeze_api_usage.json`, capped
at 5,000. The shared scheduler singleton and process lock cover this client;
other applications still consume broker quota. Keep this metadata file alongside
the order journal; do not delete it to reset limits. Tight quote/read budgets can
fail during pacing and preserve cash. The broker's daily quota can prevent a
full session of frequent REST monitoring; this implementation does not promise
continuous five-second coverage. No streaming transport is added here.

## Optional direct data reads

Both native objects expose:

```python
gateway.get_historical_candles(instrument_id, from_date, to_date, interval="1m")
```

Breeze accepts the exact option ID or `INST-NIFTY-INDEX`, and native ISO8601
range strings. Kite additionally requires `instrument_token=...` from the broker
instrument master and its native `yyyy-mm-dd hh:mm:ss` range strings. Tokens
must be supplied explicitly; no expiry rollover or token inference occurs.
Supported interval aliases are `1m`, `5m`, `30m`, and `1d`.

Breeze additionally exposes:

```python
gateway.get_option_chain("2026-10-27", right="call")
gateway.get_option_chain("2026-10-27", right="put")
```

History returns `candles`, `source` and `instrument_id`; chain reads return
`contracts`, `source` and `expiry`. Candle/contract rows retain each broker's
native schema and may contain the current incomplete candle. The repo-owned
market-data provider normalizes these reads where applicable and filters
incomplete candles. Select direct Kite web-session or Breeze ingestion with
`--market-data-broker` / `MARKET_DATA_BROKER`, independently of execution.
See [market-data setup and preflight](MARKET_DATA.md). No automatic cross-source
fallback is introduced.

Direct Kite streaming/history belong to its paid Connect tier; its personal
tier covers order/portfolio APIs. The default path does not activate or purchase
a subscription. See [current official pricing](https://zerodha.com/products/api/)
and the [historical API contract](https://kite.trade/docs/connect/v3/historical/).
Existing session-based local market ingestion is retained to preserve the
workspace's zero-paid-API design.

## Validation

Run `python -m tools.quality` and `git diff --check`. Offline tests use fake
broker HTTP responses and the actual AI consultant. They cover both broker
factories, native mode guards, Breeze signing and account changes, zero funds,
quotes, real-AI entry gating, protective stops, changes, partial fills,
cancel/exit races, lost acknowledgements, restart recovery and quota failures.
No live broker session or order is required for these tests. They do not certify
exchange fills or all live broker response variants.

Wire contracts were checked against the official
[Breeze reference](https://api.icicidirect.com/breezeapi/documents/index.html),
[ICICI Python SDK](https://github.com/Idirect-Tech/Breeze-Python-SDK), and
[Kite docs](https://kite.trade/docs/connect/v3/).
