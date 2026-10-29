# Background market intelligence

`MarketIntelligence` starts one daemon worker after initializing its cache and
locks. The scheduler's `get_market_intelligence(spot_change_pct=...)` signature is
unchanged. It now reads memory, returns an independent snapshot and calculates
spot-dependent advisories without HTTP, file I/O, sleeps or startup waits.

## Refresh and freshness

- Default refresh interval: 60 seconds, measured with a monotonic clock. Refreshes
  never overlap. Slow refreshes skip missed periods instead of queuing more work.
- Sources: five global quotes (Brent/Crude, Dow Jones, Nasdaq, USD/INR, and GIFT Nifty futures), Moneycontrol RSS
  and ET Markets RSS. No additional feeds, services or paid APIs were added.
- Each request retains its four-second socket-operation timeout. Payloads are
  limited to 1 MB. This is not a guaranteed overall HTTP wall-clock deadline.
- `cache_ttl_seconds=120` now means maximum permitted source age, not permission
  for a getter to fetch. TTL and refresh interval must be positive; the old
  `cache_ttl_seconds=0` synchronous-refresh pattern is no longer supported.
- Each source retains its own last successful data, success timestamp, age and
  latest error. A failed refresh never renews the age of retained data.
- Readiness requires all four quotes and at least one RSS feed within the TTL.
  One failed feed can use retained data until expiry; an expired feed is excluded
  from scoring when another feed is fresh. Partial availability is visible in
  source metadata and AI trap advisories.
- Source age measures successful retrieval, not whether an overseas market is
  currently open. Yahoo's observation timestamp is retained separately.

Snapshots include `ready`, `status`, `generation`, per-source health and worker
health alongside the existing sentiment fields. `timestamp` describes snapshot
publication, not successful retrieval of every source. Use source ages and
`ready` to assess availability. Initial neutral-shaped values have `ready=False`;
they must not be interpreted as a successful neutral market reading.

The worker builds a new snapshot outside the cache lock and swaps it under a
short lock. Readers copy the published snapshot outside that lock. Returned
nested dictionaries, headlines and trap lists do not alias the published cache.

## Trading behavior

Open-position monitoring and mandatory exits remain ahead of the news entry
gate. New entries are blocked while required intelligence is unavailable or
expired. The actual AI consultant remains mandatory for every approved candidate.
Freshness is checked again after consultation. If the news/macro fields supplied
to the AI changed during consultation, the scheduler defers entry until a fresh
decision on the next cycle; it never reuses approval for unevaluated context.

Intelligence JSON/Markdown snapshots are written by the worker, with atomic
replacement of each file. The scheduler no longer duplicates those writes.
Persisted advisories use the most recent spot change supplied to the getter;
their spot context is not a separate live quote subscription.

Normal monitoring sleeps for the remainder of its requested period, rather than
adding five seconds after the work finishes. Overruns trigger a warning and an
immediate next cycle, without queued catch-up ticks. Broker calls and structural
data reads can still exceed five seconds; this is not a real-time guarantee.

`[CYCLE TIMING]` logs include process/cycle IDs, total duration and stage durations
for reconciliation, context reads, intelligence cache reads, AI consultation and
execution. `[MONITOR OVERRUN]` identifies cycles exceeding their target interval.
Worker refresh durations and source ages are exposed separately in snapshots.

## Shutdown and reporting commands

The scheduler stops its worker in `finally`, covering `--once`, normal shutdown,
KeyboardInterrupt and exceptions after construction. Shutdown sets an event and
joins for at most one second. An in-flight socket operation cannot be forcibly
interrupted; the worker checks the stop event between requests, and daemon status
is the process-exit fallback. A stopped instance cannot be restarted.

`run_market_context.py` and `python market_intelligence.py` explicitly wait up to
30 seconds for ready data and then stop their worker through a context manager.
They report unavailability and return a nonzero status if readiness is not reached.
The trading scheduler never waits for news readiness: a cold `--once` run may
return an unavailable-intelligence result instead of submitting a trade.

Restart existing scheduler processes to load the changes. This update does not
restart the engine or prove provider availability through live requests.

## Offline verification

```powershell
python -m unittest test_market_intelligence test_self_healing_exit -v
```

Tests simulate provider stalls, concurrent readers/publications, source expiry,
partial failures, blocked/failed snapshot writes and shutdown. OMS regression and
actual playbook approval/veto tests remain included. Test state is restricted to
temporary repository directories; no broker orders or live provider calls occur.
