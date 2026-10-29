# Daily logs and trade reports

The scheduler configures one background writer at CLI startup. No worker or
filesystem operation occurs just by importing a module. The usual launch command
is unchanged. Restart the scheduler normally to pick up this logging change;
there is no new service to launch.

```text
logs/
  trader-2026-10-20.log
  trader-2026-10-21.log
  daily/
    2026-10-20/
      events.jsonl
      trades.csv
      summary.json

  active_position.json              Existing recovery path
  broker_intents.json               Native gateway recovery metadata, when used
  breeze_api_usage.json             Persistent Breeze request-budget reservations
  scheduler.lock                    Existing singleton path
  latest_decision.json              Existing latest-analysis view
  latest_intelligence.json          Existing latest-intelligence view
  latest_intelligence.md
  pending_consultation.json         Existing chat communication paths
  pending_consultation.md
  ai_verdict.json
  trader.log                        Preserved legacy history
```

## Runtime files

Each record goes to `trader-YYYY-MM-DD.log` using the record's creation time in
IST, independent of the host timezone. The writer appends on restart and switches
files across midnight without a process restart. Records include the UTC offset,
severity, component, process ID and a per-start run ID. Console output is preserved.
The old `trader.log` is left intact and receives no new scheduler output after
the updated scheduler starts. Historical scratch scripts with that hardcoded
filename continue to inspect the legacy history; point future manual investigations
at the dated files.

## Structured journal and snapshots

`events.jsonl` is append-only UTF-8 JSON, one event per line. It records:

- Session starts/stops and lightweight neutral decisions.
- Candidate decisions with the market context and intelligence actually used.
- Consultation dossiers and actual AI verdicts, including vetoes and timeouts.
- Entry results and intelligence/session blocks after a candidate.
- Meaningful position/order changes: persisted intents, broker acknowledgements,
  confirmed partial/full fills, stop arming/cancellation/ratchets and exit states.
- Reconciliation failures and broker-confirmed flat closure before recovery-state
  deletion.

Candidate and run IDs connect the workflow events. Position snapshots retain
scope, entry/stop/exit order IDs and request IDs, including across recovery. A
recovered position may have no in-memory candidate ID; its persisted execution
evidence and broker references remain available. Changing mark-to-market/peak
prices alone does not generate another position snapshot.

Meaningful snapshots live inside journal events rather than thousands of separate
files. Latest-view and chat files keep their existing paths and overwrite/cleanup
behavior. In particular, `latest_decision.json` remains the pre-consultation view;
the permanent `ai_verdict` and `entry_result` events capture subsequent outcomes.
The engine never uses logs or reports to decide whether it can trade or recover.
`broker_intents.json` is execution metadata despite its location under `logs/`;
retain it with recovery state. See [native gateway recovery](NATIVE_GATEWAY_SAFETY.md).

## CSV and summary semantics

The writer creates reports on the first journal event for a date and rebuilds
them after verified closure. A day without completed trades has an empty CSV
with column headers and an empty `by_mode` summary. It is not necessary to wait
for an end-of-day timer, and a restart refreshes projections from existing events
when the next event is written.

`trades.csv` contains one row per completed tracked position, identified by its
execution scope and entry order IDs. Repeated closure observations on the same
day update that row rather than adding another trade. Partial entry fills and
multiple stop/exit fills are aggregated. A rejected or unknown submission is not
a completed trade. Remaining exposure, unresolved SELL orders or unbalanced fill
quantities also prevent inclusion.

Reports use explicit broker `filled_quantity` and order `average_price` fields.
They never substitute a limit price, trigger price or LTP for a fill price. Gross
PnL is confirmed SELL proceeds minus BUY cost. Charges are summed only when
numeric order `charges` values are available for every filled order; the writer
does not estimate exchange fees. Missing prices/charges produce blank CSV fields,
JSON `null` values and a `pnl_status` explaining what is missing.

`summary.json` separates PAPER from LIVE totals and counts missing price/charge
inputs. A total remains `null` if any constituent lacks the needed evidence.
Amounts are INR. Dates represent **when the engine observed verified closure
in IST**, not a reconstructed exchange execution date. Late recovery can therefore
appear on its observation date. Deduplication is within each daily report; this
is not a broker-wide statement or cross-day settlement reconciler.

The journal is the source; CSV and summary are rebuildable projections, written
atomically as individual files. Malformed/torn lines are retained, skipped and
counted in `malformed_lines`. `unreportable_closures` flags filled positions whose
closure evidence cannot support a report row. A torn final line is separated
before appending a new event so later valid events remain readable.

Rebuild a report while the scheduler is stopped:

```powershell
python -m tools.logs report 2026-10-20
```

## Retention and maintenance

Compression is explicit and configurable; nothing is automatically deleted.
For example, compress dated runtime files older than 30 days:

```powershell
python -m tools.logs compress --older-than-days 30
```

This produces `.log.gz` files, then removes the corresponding uncompressed file
only after the compressed file is successfully written. Existing archives are
never overwritten. Current/recent files, the legacy `trader.log`, journals,
reports and recovery/communication files are excluded. Journal retention is
independent: no automatic journal deletion policy is imposed.

Both maintenance commands acquire `scheduler.lock` and refuse to run against an
active scheduler using that log directory. For isolated local output, place
`--directory <workspace-path>` before the subcommand. CLI paths are confined to
the workspace. Neither command queries a broker or runs a strategy.

## Failure and shutdown behavior

An 8,192-record queue keeps log file writes, fsyncs, report generation and console
output off the scheduler thread. Snapshot copying and event construction still
occur on the caller; this does not guarantee a fixed cycle duration.

The queue is bounded. Overflow drops the incoming observational record and emits
a rate-limited stderr warning with a drop counter. Disk/format/report errors also
emit stderr warnings with a failure counter and do not raise into trading code.
An orderly shutdown attempts to drain the writer before releasing the singleton
lock; a five-second join timeout reports an incomplete drain. These are
observational logs, not an exactly-once transactional ledger: an abrupt kill,
power loss, overflow or disk failure can lose pending records, including closure
history. Recovery state retains its existing synchronous persistence and failure
semantics. There are no additional broker calls or AI replacements.

The offline checks cover IST midnight/restarts, queued snapshot immutability,
actual AI approvals/vetoes/timeouts, actual lifecycle transitions on a fake
broker, missing fill evidence, report deduplication, disk failure, queue overflow,
torn journals, compression and maintenance locking. No live scheduler or order
is started by those checks.
