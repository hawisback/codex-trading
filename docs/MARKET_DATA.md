# In-process market data

The six market capabilities now live in `trading/adapters/market_data.py`.
The scheduler injects this provider into `MarketContextService`; market context
does not call a server on port 8000. Its legacy path strings are only dispatch
keys for Python methods. New callers can use the methods directly:

```python
from trading.adapters.market_data import create_market_data

market = create_market_data("breeze")  # or "kite"
market.get_data_quality()
market.get_snapshot()
market.get_candles("1m", 375)
market.get_candles("5m", 50)
market.get_technicals("5m", 50)
market.get_options(strike_window=10, expiry=None)
market.get_heavyweights()
market.get_vix()
market.get_sectors()
market.get_contract_quote("INST-NIFTY-2026-10-27-22650-PE", timeout_sec=1.0)
```

## Select brokers

Set `MARKET_DATA_BROKER=kite` or `MARKET_DATA_BROKER=breeze` in the workspace
`.env`. The default is `kite`. Override it per process with
`--market-data-broker kite|breeze`. This is independent of execution selection
through `--broker` / `EXECUTION_BROKER`; there is no automatic broker fallback.
Restart the scheduler to change either broker; reconcile any existing position
before changing its execution account. Do not run two schedulers.

For example, once both sessions pass preflight:

```powershell
python nifty_trader_scheduler.py --broker kite --market-data-broker breeze --live --interval 60 --strategy ai_opportunity_radar --ai-mode playbook
```

`--live` retains the existing execution arming requirement. The execution
default remains `proxy`, so selecting only a market broker does not migrate
paper execution, funds, positions, or orders away from the execution proxy.
Use a native execution broker as well to run without that server.

## Sessions and instrument identity

Select Kite REST authentication with `MARKET_DATA_TRANSPORT=web|connect`.
`web` uses `KITE_ENCTOKEN` and `KITE_ACCOUNT_ID`. `connect` uses the existing
`KITE_API_KEY` and `KITE_ACCESS_TOKEN`, including when streaming is off. It
requires existing broker data access; selecting it does not purchase or activate
a subscription. Neither mode automatically logs in or refreshes credentials.
The web OMS routes are not a published stable Connect interface. Missing,
expired, or unsupported sessions make data unavailable and block entries.
The populated workspace `.env` currently selects Connect REST with streaming off.

Breeze uses `BREEZE_API_KEY`, `BREEZE_API_SECRET`, `BREEZE_API_SESSION`, and
`BREEZE_ACCOUNT_ID` through the existing signed gateway. When both selections
are Breeze, they share that gateway, its account verification, pacing and daily
quota. Otherwise, the market provider constructs a separate disarmed Breeze
reader. No market read arms execution or submits orders. The existing Breeze
100/minute and 5,000/day limits still apply, including reads by other clients.

Both sources use the public Zerodha NFO instrument CSV once per process per IST
date to discover actual expiries and exact Kite symbols. Breeze does not need
Kite login credentials for this reference download. `MARKET_INSTRUMENTS_FILE`
can instead select an operator-maintained current-day CSV inside this workspace.
An expired file, ambiguous identities, unavailable expiry, or incomplete strike
window fails rather than inventing symbols. The weekly/monthly expiry naming
convention is never inferred from dates.

## Data and failure semantics

- Snapshots and breadth use NIFTY spot and NSE cash quotes, never futures.
  Exchange timestamps must be from today, less than 20 seconds old, and no more
  than two seconds in the future. Health reports `quote_ready=false` on failure.
- Spot history is normalized from native broker responses, sorted, and checked
  for invalid OHLC or conflicting duplicates. Only completed 1m bars between
  09:15 and 15:30 IST are retained. Today's sequence must cover every completed
  minute from 09:15; gaps or lagging history block context assembly.
- Five-minute bars are resampled locally from five contiguous completed 1m
  bars, aligned to the session. A ten-calendar-day history request supplies
  prior-session warm-up. Indicators require at least 50 completed 5m bars.
  EMA uses the existing first-close seed; RSI uses the existing simple 14-period
  mean-gain/loss formula. MACD uses EMA12 minus EMA26, an EMA9 signal, and strict
  increase/decrease tests on the last two histogram values. Incomplete bars
  never enter these calculations. History is cached only within its IST minute.
- The existing context assembler computes the arithmetic mean of today's spot
  typical prices for session VWAP, plus the latest 15 completed minutes' box.
  It retains the existing context behavior of recomputing RSI from 1m closes;
  the provider's technicals response itself is strictly based on 5m candles.
- Options default to the nearest active expiry in the master, including expiry
  day. `strike_window=10` returns 21 strikes centered on ATM, each with both
  legs. PCR aggregates that returned window; a zero denominator returns `None`.
  Existing downstream expiry eligibility and AI policy remain authoritative.
- Breeze maps native `chnge_oi` directly. Kite computes change against the most
  recent prior-session daily closing OI and caches that baseline for the session.
  A missing baseline is an error, never zero or first-observation OI. Cold Kite
  startup may require one daily-history request per option contract; allow time
  for preflight warm-up. Quotes are fetched after baseline collection and checked
  again before returning the chain.
- Entry context requires all five heavyweight quotes. Missing data raises and
  the entry cycle stands aside. Exposure monitoring retains its existing short
  read budget and optional heavyweight fallback. Direct-provider feed health
  cannot be bypassed with `--ignore-feed-health`. AI evaluation, AI vetoes,
  execution guards, sizing and square-off policy remain in their existing layers.

## Read-only preflight and verification

```powershell
python -m tools.market_data --broker kite --timeout 60
python -m tools.market_data --broker breeze --timeout 60
python test_api_endpoints.py
python test_api_endpoints.py --broker both
python test_api_endpoints.py --offline --report logs/api_contract_offline.json
python test_api_endpoints.py --broker kite --after-hours --timeout 60 --report logs/api_contract_after_hours.json
```

Each command checks ten variants across the core capabilities and enhancements
(both candle intervals, VIX, sectors, and native option depth), prints a JSON report,
and exits 1 on any failure. It never constructs
a trader or places orders. Live freshness checks will normally fail outside the
session. `MARKET_DATA_TIMEOUT_SEC` defaults to 30 seconds per normal capability
read; exposure monitoring supplies its existing tighter budget.

`test_api_endpoints.py` uses the repo-owned provider. Its default run checks
offline required-field/type mutations and actual Kite/Breeze request-header
builders, then reads the configured live provider. It covers ten payload variants
including both candle intervals, VIX, sectors and native option depth. It checks
finite JSON numbers, boolean types, integral quantities, IST timestamps, contract
identities, and the engine consumer's spot VWAP calculation. It never starts the
scheduler or submits orders.

The report at `logs/api_contract_verification.json` separates PASS, FAIL and
BLOCKED. Missing credentials, unavailable data, schema mismatches or unverified
live headers produce exit code 1. `--offline` checks fixtures and request builders
only; its exit code 0 does not establish live readiness. A separate `--report`
path preserves the live report when running this mode.

`--after-hours` checks authenticated Kite REST reads, current-day closed spot
candles, indicators, options/OI, breadth, VIX, sectors and native depth using the
same schema validator. It is refused during market hours. Diagnostic book status
is `CLOSED`; engine freshness checks remain enforced. Its report can pass the
closed-market checks while `live_verified` remains false. It also verifies the
production health response blocks stale quotes. A live-market run is still
required to verify fresh quotes and sub-second executable depth.

On 2026-10-22, the configured Kite account passed all 14 closed-market checks:
375 spot minutes, 50 five-minute bars, 21 option strikes for 2026-10-27,
five native depth levels, and 49 successful broker responses with verified
headers. See the local `logs/api_contract_after_hours.json` report. This run did
not open a WebSocket or submit orders.

In-process calls have no HTTP headers. The live checker instead observes broker
REST authentication/version/accept/content-type request headers and successful
response status/content-type, without recording credential values or response
bodies. WebSocket handshake headers, order execution, and all possible future
broker responses are outside this bounded verification. Passing configured
checks is not blanket certification of the trading system.

Run `python -m tools.quality` for formatting, lint, types, offline source-contract
tests, real-AI regression tests, and architecture checks. Offline fixtures do not
certify live broker data availability or web-session compatibility.

Broker response references: [Kite instruments and quotes](https://kite.trade/docs/connect/v3/market-quotes/),
[Breeze API](https://api.icicidirect.com/breezeapi/documents/index.html), and
[Kite pricing](https://zerodha.com/products/api/). Kite web-session support is a
separate transport from the published paid Connect data API.

## VIX, sector breadth and native option depth

Full snapshots now include timestamped `vix` and `sectors` objects. Dedicated
`get_vix()` and `get_sectors()` calls are also available. Kite reads `INDIA VIX`,
`NIFTY BANK` and `NIFTY IT` from NSE cash indices. Breeze uses its native index
codes `INDVIX`, `CNXBAN` and `CNXIT`. Broker account support for these indices must
pass preflight; missing index data is never synthesized. `BreezeMarketSource`
also accepts a `stock_codes` mapping for account-specific code configuration.

The context assembler passes these objects to the actual AI dossier. Quotes
must still be fresh when the dossier is built. The playbook AI vetoes banking/IT
divergence when the indices move in opposite directions and both absolute
percentage changes meet the threshold (default 0.5 percentage points). This
check follows the existing eight traps; none of those checks is bypassed.
Settings in `config/trading.json` can customize this additional AI policy:

```json
{
  "ai_context": {
    "sector_divergence_threshold_pct": 0.5,
    "sector_divergence_veto": true
  }
}
```

`get_contract_quote()` resolves internal option IDs or exact Kite symbols through
the current instrument master. It returns executable bid/ask prices, their
quantities, timestamp, status, and native depth. Kite full quotes retain up to
five real levels on each side. Breeze REST quotes expose the native top level;
additional levels are not invented. Empty/crossed books, invalid quantities,
off-tick top prices, ambiguous identities, timestamps in the future, and books
at least one second old return an unavailable result.

The trader injects this provider as its quote reader for pre-submit spread and
price validation, structural-invalidation checks, and open-position bid monitoring.
It retains execution-broker account verification, funds, approved contract
registration, the actual AI approval envelope and durable OMS reconciliation.
An explicit `quote_reader` constructor argument supports other verified quote
sources and offline execution tests. The local dispatch alias
`/market/quote/{instrument_id}` performs the same Python call; it creates no HTTP
server. REST pacing/network delay can exhaust a one-second read budget; an
unavailable book blocks the order rather than falling back to LTP.

An optional `exit.vix_adaptation` object in the selected strategy enables
tightening of targets and runner/morning pullbacks during low or falling VIX:

```json
{
  "vix_adaptation": {
    "enabled": true,
    "low_vix_below": 13.0,
    "crush_change_pct": -3.0,
    "target_factor": 0.8,
    "pullback_factor": 0.75
  }
}
```

For example, a configured 50% target becomes 40%, and a 10% pullback becomes
7.5%. The initial stop, position size and square-off policy are unchanged. Stale
or missing VIX retains the base exit settings; the persisted broker/trailing floor
always prevents lowering an already established stop. The policy is disabled
unless explicitly enabled. These thresholds are configurable policy defaults,
not a validated claim of improved returns. Exposure monitoring fetches a bounded
spot/VIX snapshot; optional VIX/sector reads do not delay mandatory square-off.

## KiteTicker streaming

The default remains `MARKET_DATA_STREAMING=off` for the standard-library REST
runtime. To enable streaming, install `requirements-streaming.txt` into a
workspace-local virtual environment and choose one explicit transport:

```dotenv
MARKET_DATA_BROKER=kite
MARKET_DATA_TRANSPORT=web
MARKET_DATA_STREAMING=web
```

`web` uses the configured `KITE_ENCTOKEN` and `KITE_ACCOUNT_ID` against the web
session's socket. It does not use or purchase paid Connect data. This transport
uses an undocumented web-session interface and requires live compatibility
verification. There is no automatic switch to Connect if it fails.

`MARKET_DATA_STREAMING=connect` instead uses existing `KITE_API_KEY` and
`KITE_ACCESS_TOKEN` credentials and an existing Connect market-data entitlement.
Set `MARKET_DATA_TRANSPORT=connect` as well; enabled streaming and REST must use
matching authentication transports.
It uses the official socket and authenticated Connect REST for bootstrap reads.
Selecting this transport does not purchase a subscription. Connect streaming is
part of Zerodha's paid tier; use `web` or `off` to preserve the zero-paid-API path.
Breeze selection continues to use its signed native REST adapter.

The worker uses `kiteconnect.KiteTicker` in full mode, with bounded reconnect
delays, thread-safe subscriptions, and a 3,000-instrument subscription cap. Token
discovery occurs once per symbol/session; option tokens come from the master.
Warm quote reads use a locked in-memory cache and do not poll REST. Index packet
exchange timestamps are mandatory. Quote health checks both exchange age and
monotonic receive age; a connected socket alone is insufficient.

Spot ticks build 1m OHLC in memory with zero index volume. Existing local
resampling derives completed 5m bars. The engine continues to use completed bars;
forming bars never become signal input. REST seeds the historical session and
indicator warm-up. A partial startup minute, disconnect, or index-tick gap of
20 seconds invalidates affected minutes and forces authoritative REST backfill
before those candles can be used. Missing ticks are not filled with invented
flat candles. Option OI baselines still require historical reads on cold startup.

Disconnects clear executable quotes; reconnects resubscribe in full mode and
require new ticks. Request budgets bound first-tick waits. The scheduler and
preflight close the socket at teardown. Streaming reduces repeated REST reads;
bootstrap, OI baselines and gap repair remain subject to REST quotas. Transport
latency, packet loss, entitlements, session expiry and subscription limits still
apply. See [official streaming limits and packet formats](https://kite.trade/docs/connect/v3/websocket/)
and [official KiteTicker implementation](https://github.com/zerodha/pykiteconnect/blob/master/kiteconnect/ticker.py).

Validation for this implementation passed 319 offline regression tests plus a
real KiteTicker 5.2.2 import/construction and binary-parser smoke check on the
workspace's Python 3.14 runtime. The smoke check decoded a full index packet and
five-level option packet, including IST timestamps, without an external socket
connection. The optional SDK dependencies used for that check are isolated under
`.tools/streaming`; they do not change the system Python installation. A live
WebSocket handshake and fresh streaming validation remain pending a market-hours check.
