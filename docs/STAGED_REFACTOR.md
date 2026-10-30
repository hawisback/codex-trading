# Staged structural refactor: implementation record

> **Historical document / point-in-time snapshot:** This page preserves its original planning, inventory, findings or policy questions from its dated baseline. Some approvals, source values, lease wiring and stop integrations progressed afterward on `feature/live-activation-guardrails-20261030`. For **current branch status, approved R01 boundaries, integration coverage and activation blockers**, consult [the 2026-10-30 canonical release record](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md). No recent R01/LIVE/unified-stop regression tests or supervised broker UAT have run; the feature flag remains disabled. Do not treat old “pending” or “passed” statements as new acceptance results.

Implemented on 2026-10-20. This follows the eight stages in
[the architecture review](ARCHITECTURE_REVIEW.md). Trading-policy discrepancies
remain explicit decisions rather than being silently resolved by a refactor.

## Stage completion

| Stage | Implementation | Evidence |
| --- | --- | --- |
| 1. Characterize behavior | Frozen market, strategy, AI, indicator and OMS fixtures | Seven market-response cases; 39 strategy-decision cases across four profiles; ten direct AI cases; three ordered OMS traces |
| 2. Extract market context | `MarketContextService` | Original request sequence, optional-read fallback, spot VWAP, RSI/EMA, order flow and four-second monitor budget tested |
| 3. Apply Strategy | `StrategyRegistry`, configured rule-based strategies and `RadarStrategy` | Call/put approvals, neutral/veto cases, climax spring/upthrust and margin fallback match original methods |
| 4. Separate workflows | `CycleWorkflow`, `EntryWorkflow`, `PositionMonitor`, session scheduler and dossier/selection services | Actual AI gate remains common; existing recovery, timing and shutdown tests pass |
| 5. Name states | String-compatible `PositionStatus`, shared exit-state predicate | JSON values remain strings; pending submission, recovery, open, pending exit and flat transitions tested |
| 6. Configuration/startup | `RuntimeConfiguration`, explicit environment/console setup | Argument/environment/config precedence, missing/corrupt-file outcomes and import-side-effect tests pass |
| 7. Live/replay sharing | Shared strike/EMA/simple-RSI/rounding/sizing/dossier policies; `ReplayService`; workspace historical adapter | Replay uses actual AI and matches the frozen live decision cases; explicit historical input never falls back to a database |
| 8. Quality checks | Pinned Ruff/mypy, boundary checks, offline suite, CI and scoped benchmark tool | Lint/type checks and 153 offline tests pass locally; remote matrix is configured, not locally certified |

The scheduler root module is now a small compatibility facade, reduced from
approximately 1,456 lines to 223. The actual `AIConsultant.evaluate()` and
`_evaluate_playbook()` method bodies are unchanged from the pre-refactor source.

## Component responsibilities

```text
nifty_trader_scheduler.py          Existing CLI/import facade and dependency assembly
trading/
  bootstrap.py                    Explicit dotenv/console startup
  configuration.py                Typed configuration assembly and radar factory
  models.py, ports.py              Internal data views and dependency interfaces
  domain/
    indicators.py, prices.py       Shared deterministic calculations
    limits.py, sizing.py           Current runtime limits and compounding
    states.py, intelligence.py     State names and macro/news equality
  strategies/
    registry.py, legacy.py         Profile selection and existing rule filters
    radar.py                      Live radar candidate construction
  application/
    market_context.py             Ordered reads and context calculations
    dossier.py, selection.py       Candidate dossier and affordable instrument selection
    entry.py                      Session/news checks, actual AI gate, entry handoff
    workflows.py                  Cycle coordination and decision reporting
    position_monitor.py           Exit/ratchet decisions through serialized callbacks
    scheduler.py                  CLI arguments, cadence, waiting and teardown
  adapters/
    http.py, position_store.py     Existing transport/persistence contracts
    historical.py                 Explicit workspace-local recorded data
  replay.py                       Offline decisions through live policies and actual AI
```

`PositionLifecycle` retains ownership of reconciliation, OS/process locks,
mutation serialization, request-ID recovery, protective stops and verified exits.
Its cohesive recovery behavior was not distributed among competing workers.
Strategies have no broker gateway and propose candidates only. Registry extensions
still pass the same actual AI gate; a test explicitly exercises a proposed entry
that the actual consultant vetoes.

## Compatibility and intentional startup cleanup

Existing root imports, method names, CLI arguments, broker payloads, persisted
schema and singular ID aliases remain. `round_tick` and timing helpers remain
available through their prior root modules. The helper implementations are shared.

Importing core modules now does not read `.env`, create application directories,
start workers or reconfigure streams. Environment loading occurs explicitly at
construction/startup or first legacy HTTP use, with the existing parser and
process-environment precedence. Console setup occurs at CLI execution boundaries;
chat consultation creates its required directories when used. Config file paths
remain relative to the launch directory by default, matching existing commands.

Malformed trading JSON still follows its previous logged fallback; malformed
strategy JSON still raises. This refactor does not convert previously tolerated
configuration into a new startup failure. Internal typing adds no coercion or
alternative risk defaults. Imports becoming free of application side effects is
an intentional lifecycle improvement, distinct from changing trading rules.

`PositionStatus` names persist the same strings. It is not a new transition
validator: unknown legacy values keep their original reconciliation treatment.
Flatness is still represented by verified absence of active state, not by a new
stored terminal-state schema.

## Replay and legacy research audit

Run a decision replay without creating an execution gateway:

```powershell
python -m tools.replay tests/fixtures/replay_example.json --strategy ai_opportunity_radar
```

An input is a list of records containing `now`, `context` and `intelligence`,
optionally `history` and `today_entries`. These are recorded inputs, not live
quotes. Output contains the candidate, actual AI verdict and blocking reason.
The example intentionally demonstrates a candidate the AI can veto. No position
is opened. Optional `--output` reports are constrained to the workspace.

Replay uses a nested, exception-safe context clock; the live clock still uses
wall time unless a replay scope is explicitly entered. It shares live strategy,
contract selection, sizing and dossier services and constructs the actual playbook
consultant. It does not accept an AI replacement. Session/news gates and AI
timeout/veto outcomes preserve cash. It produces decisions rather than PnL, broker
fills, or simulated stop execution.

`BacktestEngine` now accepts an explicit `data_source` with a `load_day(date)`
contract. `WorkspaceHistoricalSource` reads a workspace JSON object with
`target_date`, `spot_candles`, `options_data` and `is_synthetic_options`. When
provided, it returns before the legacy filesystem/database fallback. Tests assert
that no database connection occurs. Default historical data-loading behavior is
retained for compatibility and was not executed against the external database.

Legacy research engines are not assumed equivalent to the live engine:

- The historical radar uses bar indices for time gates; live radar uses true
  session minutes and configurable radar thresholds.
- Historical EMA warm-up can return the last price while live fallback EMA seeds
  from the first available price. The shared helper makes this distinction
  explicit rather than changing either result.
- Live rolling radar RSI uses Wilder smoothing; context/backtest simple RSI uses
  its existing recent-window calculation. These distinct algorithms were not
  conflated.
- Expiry/holiday treatment, synthetic option prices, entry-gate checks, fills and
  trailing simulations differ among research paths. Their published PnL was not
  recomputed or rewritten to imply live equivalence.

Only proven-identical calculations were shared. The canonical replay path is the
route for comparing current live decisions using recorded workspace-local inputs.
No legacy simulation or backtest was run without actual AI consultation.

## Preserved policy decisions

Current runtime values remain: 65-contract default order cap, the configured
compounding policy, ₹150 cash reserve, ₹70 premium ceiling, entry tolerance bands,
14:15 entry lockout and 15:15 mandatory square-off. Daily candidate cap remains the
existing runtime value of ten, despite other daily-limit values in JSON.

The earlier sizing, session, ₹12/₹30 penny-trap, compressed-ribbon and static-equity
disagreements in the architecture review remain separate policy decisions. No
trade rule was relaxed to simplify the extraction, enable a fixture, or make a
historical result look consistent.

## Checks, scope and performance evidence

```powershell
python -m tools.quality
python -m tools.checks
git diff --check
```

`tools.quality` checks formatting, runs Ruff/mypy and the explicit offline suite.
The pinned tools and their dependencies are development-only. `tools.checks` remains usable with
the standard library alone. Lint covers the new package, tools/tests and selected
existing safety modules, with additional critical-error lint on root runtime files.
Type checks cover the extracted package, with stricter
checks on models/interfaces/configuration and selected domain functions; this
does not claim every legacy script is strictly typed.

The offline suite blocks accidental network use and does not discover legacy
diagnostic scripts. Baseline comparison normalizes only the old display-only
host-wall-clock verdict timestamp; price, reason, identity, approval/expiry,
quantity, ordered broker effects and saved state remain checked.

For a scoped compute measurement:

```powershell
python -m tools.benchmark tests/fixtures/replay_example.json --iterations 100 --output .tools/benchmarks/replay_cpu.json
```

One local 100-iteration run measured median 1.96 ms, p95 3.55 ms and p99 3.78 ms.
That sample contained 100 AI vetoes. It measures recorded-context decision and
actual playbook-AI compute only; it includes no broker/network or human/chat
consultation latency. There is no CI speed threshold that would depend on runner
hardware. This refactor does not guarantee a five-second cycle or immediate fills.

Validated locally on Windows/Python 3.14.7. The configured Windows/Linux,
Python 3.10/3.14 CI matrix has not been run remotely during this work. Real broker
integration and full historical-session/PnL equivalence remain outside the
evidence provided by these offline fixtures.

Tooling references: [Ruff configuration](https://docs.astral.sh/ruff/configuration/)
and [mypy configuration](https://mypy.readthedocs.io/en/stable/config_file.html).
