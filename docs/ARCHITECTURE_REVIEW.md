# Behavior-preserving architecture review

> **Historical document / point-in-time snapshot:** This page preserves its original planning, inventory, findings or policy questions from its dated baseline. Some approvals, source values, lease wiring and stop integrations progressed afterward on `feature/live-activation-guardrails-20261030`. For **current branch status, approved R01 boundaries, integration coverage and activation blockers**, consult [the 2026-10-30 canonical release record](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md). No recent R01/LIVE/unified-stop regression tests or supervised broker UAT have run; the feature flag remains disabled. Do not treat old “pending” or “passed” statements as new acceptance results.

Update, 2026-10-20: the staged implementation is now covered in
[STAGED_REFACTOR.md](STAGED_REFACTOR.md), including completed components,
compatibility evidence and the unchanged policy decisions. The findings and
sequence below remain the original assessment record.

Reviewed on 2026-10-19. This assessment and first structural refactor do not
establish that every trading or operational risk has been eliminated. The
baseline was a clean worktree and 119 passing offline tests. No live engine,
historical simulation, broker order, or external historical database was run.

## Findings and priorities

| Priority | Evidence before this refactor | Consequence | Treatment |
| --- | --- | --- | --- |
| High | The 1,456-line scheduler mixes configuration, feeds, signals, sizing, monitoring and CLI scheduling | Changes span independent responsibilities | Extract cohesive services incrementally behind its existing facade |
| High | Lifecycle code owns serialization/migration plus reconciliation and exit transitions | Persistence and trade decisions are tightly coupled | Extract a repository while retaining schema and state semantics |
| High | The execution client owns low-level HTTP mechanics | Testing often intercepts private network functions | Extract an injectable transport with the same retry/error contract |
| High | Some root test files perform HTTP or historical work at import | Broad discovery can contact services or reach an external database | Use an explicit offline suite with network access blocked |
| High | AGENTS, JSON, playbook prose and runtime policy values differ | Consolidating values can change trades | Record discrepancies for separate policy decisions |
| Medium | Core objects construct their broker and news dependencies | Tests use globals, `__new__` and manual attributes | Add optional dependency injection; keep production defaults |
| Medium | Some root imports load environment files, reconfigure streams or create log directories | Imports depend on process state and working directory | Characterize startup behavior before moving bootstrap side effects |
| Medium | Scheduler and execution HTTP helpers have different defaults, budgets and retries | Blind DRY cleanup changes timing or authentication | Make transport policies explicit before sharing more code |
| Medium | Dictionaries carry decisions, quotes, orders and state | Field/schema errors appear at runtime | Introduce typed boundary views while preserving wire representations |
| Medium | Config paths are partly relative; historical DB path is machine-specific | Different launch directories can select different inputs | Test path/precedence contracts before changing configuration |
| Medium | No standard offline CI entry point existed | Regressions depend on remembering commands | Add dependency-free checks and a cross-platform workflow |

## Patterns applied

| Pattern/principle | Implementation | Preserved contract |
| --- | --- | --- |
| Adapter / single responsibility | `trading/adapters/http.py`: `JsonHttpTransport` | Request encoding, headers, GET-only timeout retry, delay, read budgets and error dictionaries |
| Repository / single responsibility | `trading/adapters/position_store.py`: `JsonPositionStore` | Schema-v2 fields, legacy aliases/migration, atomic writes and corrupt-state errors |
| Dependency inversion / interface segregation | `trading/ports.py`: quote, order-reader, order-writer, transport, position-store and intelligence protocols | Existing calls described without runtime coercion or new trading policy |
| Composition / dependency injection | Optional transport on the execution client; broker, intelligence and state store on the trader | Default construction and the actual AI consultant stay in place |
| Compatibility facade | Root modules, `_request()`, `save_active_position()` and `load_active_position()` remain | Existing imports, CLI flags and persisted-state readers stay compatible |
| Characterization testing | Fixed pre-refactor OMS traces | Ordered broker calls, payloads, results and saved position state match |
| Boundary checks | `python -m tools.checks` | Selected policy/dossier/radar/interface modules cannot directly import network or execution adapters |

The traces cover filled entry, partial fill with cancellation, and unknown
submission. They use actual AI evaluation and simulated broker responses. IDs,
trading times and monotonic time are fixed. Only the legacy verdict's display-only
host wall-clock `timestamp` is normalized; approval/quote times, expiry, fills and
other state fields remain compared. These cases are specific regression evidence,
not exhaustive equivalence for every possible market sequence.

New boundary modules perform no application I/O, environment mutation, logging
configuration or worker startup during import. Existing root import side effects
remain for compatibility. Locks and serialized mutations remain in the lifecycle;
the repository does not replace concurrency control. The network guard prevents
accidental connections in selected tests; it is not a hostile-code sandbox. The
import checks are direct rather than a proof of transitive dependency purity.

## Behavior retained

- Actual AI consultation, veto authority, evaluation order and error outcomes.
- Signal math, sizing calculations, current quantity caps, ₹150 affordability
  reserve, entry tolerances and configured values.
- Singleton locking, one-position gate, serialized mutations, request-ID recovery,
  multi-stop tracking, ratchets and cancel-before-exit behavior.
- Broker routes/payloads, retry semantics, JSON aliases, atomic-write ordering,
  configuration precedence, session cutoffs and CLI commands.

No new queue, broker thread, paid API, or additional quote request was introduced
by this structural refactor.

Validation completed locally on Python 3.14.7: 128 offline tests and the static
boundary/syntax checks pass, including the three baseline trace comparisons.
Selected strategy and lifecycle method ASTs also match the pre-refactor source
after normalizing only delegated repository `exists`/`delete` calls. One Windows
run encountered `WinError 5` at the unchanged atomic writer's `os.replace` call;
the focused checks and subsequent complete run passed. Its cause was not proven,
and no persistence retry/failure policy was changed. The configured remote CI
matrix has not been run as part of this local work.

## Policy discrepancies: separate decisions required

None of these values were changed here.

| Topic | Current evidence | Why consolidation needs review |
| --- | --- | --- |
| Sizing | AGENTS baseline is 2 lots / 130 contracts; trading JSON caps individual orders at 1 lot / 65 | Changing the cap changes exposure |
| Session timing | JSON says 14:45 entry cutoff / 15:20 exit; runtime enforces 14:15 / 15:15 | Replacing constants with JSON could relax gates |
| 0DTE penny trap | Runtime and AGENTS use ₹12; prose playbook states ₹30 | One shared constant changes which candidates receive a veto |
| Compressed ribbon | AGENTS describes a veto without breakout; consultant comments permit breakout entries without a blanket ribbon veto | Rule extraction requires scenario-level AI parity tests |
| Capital assumptions | AGENTS baseline is ₹10,000; JSON has `account_equity: 500000`; execution checks live available margin | Static equity and purchasing power feed different paths |

`backtest_engine.py` contains an absolute DB path outside this workspace. It was
not opened. Historical validation needs an authorized snapshot inside this
repository and the actual AI gate. Policy parity across the research variants has
not been established by these checks.

## Next refactors, in order

1. **Characterize decisions and data contracts.** Add fixed candle/quote fixtures
   for active strategies, AI traps, session boundaries and failed API responses.
   Compare decision dictionaries and actual AI verdicts. PnL alone is insufficient
   evidence of equivalent behavior; do not bypass AI to simplify replay.
2. **Extract market-context assembly.** Move collection and calculations into a
   `MarketContextService`, preserving routes, call order, optional-read fallbacks,
   formulas and monitor budgets. Retain the scheduler method as a facade.
3. **Apply Strategy to signal evaluation.** Give current branches an
   `evaluate(context)` contract and registry using the existing names. Keep AI
   consultation as the mandatory common gate after candidate construction.
   Preserve condition/veto ordering and dictionary output first.
4. **Separate workflows from timing.** Extract entry and monitoring services;
   leave cadence, lifecycle and coordination with the scheduler. Retain a single
   serialized mutation owner for this one-position engine. Async scheduling or a
   queue changes ordering and needs a separate design.
5. **Make transitions explicit.** Characterize `ENTRY_PENDING`, `OPEN`, exit and
   unknown/recovery paths before adding string-compatible enums or transition
   functions. A separate class for every state is unnecessary at present.
6. **Consolidate configuration and bootstrap.** Decide policy disagreements
   separately, then introduce typed loading and explicit startup. Preserve path
   and environment precedence. Stricter validation or changing a fallback is a
   behavior change, not a neutral cleanup.
7. **Share live/backtest policy carefully.** Audit variants with workspace-local
   fixtures before extracting shared calculations and actual AI consultation.
   Running every legacy script is not an appropriate substitute.
8. **Broaden quality tooling gradually.** Add lint/type checks after boundary
   signatures and baseline findings are settled. Review development dependencies;
   keep runtime dependencies minimal. Add replay/performance checks for specific
   relevant contracts.

Each extraction should establish fixtures, move one responsibility, retain the
facade, compare outputs and ordered effects, run offline checks, and review the
diff for policy changes. Renaming a module does not establish safer execution.

## Primary references

- Python [protocols and structural subtyping](https://typing.python.org/en/latest/reference/protocols.html)
  support role interfaces without requiring a shared concrete base class.
- Python [unittest discovery](https://docs.python.org/3/library/unittest.html#test-discovery)
  imports test modules, explaining the need for an explicit suite here.
- Python [logging guidance](https://docs.python.org/3/howto/logging.html#configuring-logging-for-a-library)
  assigns application logging configuration to application startup.
- Official [checkout](https://github.com/actions/checkout) and
  [setup-python](https://github.com/actions/setup-python) documentation describe
  the actions whose verified v6 commit references are pinned in the workflow.
