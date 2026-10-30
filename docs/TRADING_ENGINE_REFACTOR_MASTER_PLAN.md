# Trading Engine Modernization — Master Refactoring Plan

> **Historical document / point-in-time snapshot:** This page preserves its original planning, inventory, findings or policy questions from its dated baseline. Some approvals, source values, lease wiring and stop integrations progressed afterward on `feature/live-activation-guardrails-20261030`. For **current branch status, approved R01 boundaries, integration coverage and activation blockers**, consult [the 2026-10-30 canonical release record](architecture/CURRENT_IMPLEMENTATION_STATUS_20261030.md). No recent R01/LIVE/unified-stop regression tests or supervised broker UAT have run; the feature flag remains disabled. Do not treat old “pending” or “passed” statements as new acceptance results.

**Repository:** hawisback/codex-trading  
**Plan date:** 2026-10-29  
**Reference baseline:** `main` at `92da61d2a5c5a1ae5d5e7477db0027f196fb7c5f`.  
**Existing unmerged safety increment:** `refactor/trading-engine-architecture-20261029` at `bc5a4b644041eae0ae5f51dfe1d0fabb2db92d17`.  
**Status:** PROPOSED. This document is a plan, not an assertion that implementations or validations have passed.

## 1. Objective and scope

Build a maintainable, auditable, deterministic-by-default intraday NIFTY options engine with well-defined boundaries, recoverable order management, validated broker data, enforceable risk policy, reproducible research, safe operations and explicit release control.

The work must improve correctness and maintainability **without silently changing live strategy decisions, risk limits, contract selection, monetary exposure, consultation requirements, price rounding, broker request semantics or existing storage formats**. Changes to any of those are separate, explicitly approved policy proposals.

The existing staged refactor already extracted much of the application, strategy and market-data code. Do **not** restart from scratch, migrate to microservices, replace the broker gateways, rewrite the consultation engine, or introduce a new database simply for architectural appearance.

### Work already completed / available

- Layered `trading/domain`, `trading/application`, `trading/adapters`, `trading/strategies`, `trading/ports.py` and `trading/models.py` modules, strategy registry and a thin scheduler compatibility facade.
- Reusable `MarketContextService`, `CycleWorkflow`, `EntryWorkflow`, `PositionMonitor`, `StopManager` and replay abstractions.
- Native Kite/Breeze and proxy execution adapters, a write-ahead intent journal, schema-v2 position state, and offline suites.
- First OMS boundary hardening increment on an **unmerged branch**, adding a position codec, more defensive journal parsing and rate-limiter validation. It was committed but **tests were intentionally not run**. Treat it as pending verification, not a merged baseline.

**Primary evidence:** `docs/ARCHITECTURE_REVIEW.md`, `docs/STAGED_REFACTOR.md`, `docs/OMS_RECOVERY.md`, `docs/NATIVE_GATEWAY_SAFETY.md`, `docs/PRODUCTION_READINESS.md` and the current source files.

## 2. Non-negotiable safety invariants

| ID | Invariant | Required behavior |
| --- | --- | --- |
| INV-01 | Consultation veto | Every entry calls the existing real `AIConsultant.evaluate(dossier)`; veto, missing response, trap, expiry and error mean **no order**. Rules/playbook mode is deterministic; only chat mode uses the separate neural companion. |
| INV-02 | Durable intent first | Persist a unique order request ID and intended action before any BUY, STOP, MODIFY, CANCEL or EXIT network mutation; no mutation proceeds if persistence fails. |
| INV-03 | Unknown != failed | A timeout/lost acknowledgment must not cause a blind duplicate submission; preserve an unresolved intent until broker/account reconciliation verifies the outcome. |
| INV-04 | One exposure authority | Never open a second position while an existing position, pending BUY, unresolved SELL or unverified broker state could represent exposure. |
| INV-05 | Residual protection | Stops and exits use **verified** filled BUY minus verified SELL fills; cancel/replace and races must not create unbacked or competing SELL orders. |
| INV-06 | Authoritative broker state | Incorrect account/symbol/product/exchange, truncated books, stale quotes, conflicting identities or malformed data must fail closed for **new entries**. |
| INV-07 | Submission-time risk | Recheck margin, quantity, contract, premium, freshness, time window, account, and consultation identity immediately before submission. |
| INV-08 | Market session | Preserve existing effective entry and square-off gates. A deadline is a target, **not a guarantee** that broker exposure is flat while disconnected. |
| INV-09 | Safe recovery | Restart with incomplete/corrupt state must block new exposure, preserve evidence and raise an actionable incident; do not delete recovery files to “repair” a position. |
| INV-10 | No unsafe default mode | Broker mutation requires explicit authorization and verified account identity. Document existing live configuration; changing defaults or modes is a reviewed operational policy change. |
| INV-11 | No lookahead | Strategy evaluation and replay use only data available at the decision timestamp, preserving candle completeness and exchange time semantics. |
| INV-12 | Auditability | Every decision, risk veto, order intent, broker response, position transition and reconciliation outcome has stable correlation identifiers and redacted evidence. |

**Operational nuance:** “fail closed” means deny *new* risk; existing exposure must still enter a defined protect/reconcile/exit/escalate path, rather than being abandoned due to a missing news feed.

## 3. Observed architecture and specific gaps

| Area | Observed code | Gap / risk to address |
| --- | --- | --- |
| Policy | `config/trading.json`, `config/strategies.json`, `AGENTS.md`, `trading/domain/limits.py`, `entry_policy.py`, `ai_consultant.py` | Conflicting written/config/effective limits; no signed-off canonical policy inventory. |
| OMS | `position_lifecycle.py` (~762 lines), `trading/application/stop_manager.py`, `trading/adapters/position_store.py` | Recovery, reconciliation, transitions and submissions are still coupled in the lifecycle; test failure paths before extraction. |
| Journal | `trading/adapters/gateways/journal.py` | First patch improves parsing; its `threading.RLock` is not a cross-process transaction. |
| Gateways | `trading/adapters/gateways/base.py`, `kite.py`, `breeze.py`, `execution_client.py` | Many protocol and normalization assumptions need broker-specific contract evidence. |
| Market data | `trading/adapters/market_data.py`, `market_sources.py`, `trading/application/market_context.py` | Freshness, pagination, session gaps, OI baselines, identity and provider divergence need a single contract and observability. |
| Strategies | `trading/strategies/*`, `trading/application/selection.py`, `ai_consultant.py` | Strategies are extracted but decision DTOs and consultation responsibilities still use broad mutable dictionaries. |
| Replay | `trading/replay.py`, `backtest_engine.py`, `trading/hybrid_research.py`, root and `scratch/` research scripts | Decision replay and PnL backtesting are not equivalent; historic warmups, expiry and fills can diverge. |
| Configuration | `trading/configuration.py`, `trading/bootstrap.py`, JSON and environment | Many values are only partially validated; loading trading JSON currently tolerates corruption; global IPv4 monkeypatch deserves isolation review. |
| Operations | `trading/audit.py`, `trading/logging_setup.py`, `tools/*` | Need operator-focused alerts, incident procedures, state backup/restore and evidence retention. |
| Quality | `tests/test_regression.py`, `tools/checks.py`, `tools/quality.py`, `pyproject.toml` | Existing offline checks are valuable; safety-critical modules still have uneven typing/lint scope; separate legacy diagnostic scripts have import effects. |
| Startup | `config/trading.json` currently contains `mode: LIVE`, `auto_trade_enabled: true` and `system_armed: true`, while native CLI still requires explicit `--live` | Document actual effective arming semantics; reject assumptions that JSON flags alone authorize live orders. |

### Policy decision register — requires owner sign-off

| Decision | Conflicting evidence / question | Interim rule |
| --- | --- | --- |
| POL-01 Position sizing | `AGENTS.md` describes a 2–10 lot ladder, while trading JSON has `max_order_quantity: 65` and `max_lots_per_trade: 1` | Preserve effective runtime behavior; no exposure increase. |
| POL-02 Entry and exit cutoffs | JSON says 14:45 / 15:20; `trading/domain/limits.py` and other runtime guards use 14:15 / 15:15 | Keep the stricter/effective runtime paths until mapped and approved. |
| POL-03 Premium and penny trap | Historical docs mention ₹70, trading JSON `max_option_premium: 135` and playbook ₹12 vs ₹30 0DTE thresholds | Identify effective per-strategy limits and quote-time checks; no automatic “cleanup.” |
| POL-04 Account capital | `AGENTS.md` baseline ₹10,000 vs trading JSON `account_equity: 500000` and broker-verified available margin | Only verified broker funds may authorize live buying; classify other values as simulation-only if confirmed. |
| POL-05 Daily entry limits | Config `max_trades_per_day: 5` vs constant `MAX_DAILY_ENTRIES: 10` and strategy caps | Map all actual gates and agree on the intended global/strategy caps. |
| POL-06 Limits on stops/continuation | Current trailing/stop behavior depends on strategy config and live rules | Freeze current traces, then propose changes as separately reviewed strategy policy. |
| POL-07 Arming and kill switch | JSON contains live/armed flags and `kill_switch: false`; scheduler has explicit mode and broker checks | Define independent operator and broker authorization; no unreviewed activation changes. |
| POL-08 Holiday/expiry | Static exchange holiday settings and broker instrument master differ in authority | Explicit exchange calendar/versioning; do not infer expiry names or valid contracts. |

For each signed-off decision create a **policy ADR** with effective old value, proposed value, affected strategies, scenario-level before/after effects, risks, owner and implementation approval. Policy ADRs are not automatically implemented by a structural PR.

## 4. Target architecture (evolutionary, not a rewrite)

`CLI / process bootstrap` → `SessionOrchestrator` → `ContextAssembler` → `Strategy Signal` → `Risk + Consultation Gate` → `ExecutionCoordinator` → `Order/Position State Machine` → `ExecutionPort` → `Proxy | Kite | Breeze`.

In parallel: `MarketDataPort` → normalized timestamped quotes/candles; `IntentJournal/StateRepository` stores durable recovery; `AuditSink/Telemetry` records decisions and mutations; `ReplayRunner` substitutes recorded ports + controlled clock, **never a fake permissive consultation**.

Suggested ownership, introduced incrementally:

| Layer | Owned behavior | No direct access to |
| --- | --- | --- |
| `domain` | price/quantity value objects, normalized order/position states, risk predicates, indicators, state transitions | network, filesystem, environment, logger setup |
| `application` | orchestrated entry, reconciliation, protection, exit, risk consultation and shutdown workflows | broker-specific wire formats |
| `ports` | small capabilities: QuoteReader, OrderReader, OrderWriter, StateStore, EventClock, NewsSource, AuditSink | concrete SDK imports |
| `adapters` | Kite/Breeze/proxy transport mapping, source freshness validation, durable repositories | strategy policy decisions |
| `bootstrap` | configuration, selected account, dependency composition, process ownership | domain computation |
| `research` | decision replay, historical event data, fill model and methodology reports | live order-write capability |

Keep compatibility shims (`nifty_trader_scheduler.py`, `position_lifecycle.py`, `execution_client.py`, current CLI flags, JSON aliases) until call sites and users are migrated. No arbitrary “clean architecture” directory shuffle.

## 5. Phased work packages and acceptance criteria

### Phase 0 — Baseline, merge discipline and decision inventory (P0; foundation)

**R00.1** Review the unmerged OMS boundary branch and tag what has actually been validated; do not describe its checks as passed.  
**R00.2** Inventory every active CLI, root legacy script, research experiment and broker transport. Record production usage, secrets and side effects.  
**R00.3** Freeze golden event traces for new entry, partial fill, cancel race, stop replacement, unknown acknowledgment, restart, session boundary, AI veto, corrupt journal and broker outage.  
**R00.4** Capture a redacted contract inventory and existing configuration precedence per environment; never copy real credentials into fixtures.  
**R00.5** Create an ADR template, risk register, change-class labels (`STRUCTURAL`, `POLICY`, `BROKER_CONTRACT`, `OPERATIONS`), and pull-request checklist.

**Deliverables:** `docs/architecture/BASELINE.md`, `docs/adr/`, frozen fixture index, script inventory and a trace matrix.  
**Gate:** known baseline, explicit exclusions, a diff reviewer can identify which behavioral contracts are unchanged. No new execution behavior.

### Phase 1 — Risk-policy authority and configuration contract (P0)

**R01.1** Build a configuration usage map: key → readers → default → CLI/env precedence → current runtime effect → strategy.  
**R01.2** Resolve POL-01..08 with the owner; distinguish paper assumptions, live account limits, execution hard ceilings and strategy preferences.  
**R01.3** Introduce a typed, versioned `TradingPolicySnapshot`/`RiskPolicy` with immutable per-cycle views; validate enums, timestamps, price/lot bounds, numeric finiteness and contradictions.  
**R01.4** Provide `--validate-config` / read-only effective-policy report with redaction and source provenance.  
**R01.5** Version future policy changes and record effective policy hash with order intents/audit events; explicitly test config reload behavior or prohibit hot reload.  
**R01.6** Gate unsafe boot inputs and ambiguous mode selection, but do **not** silently change previously accepted configuration semantics in a structural-only PR.

**Modules:** `trading/configuration.py`, `trading/domain/limits.py`, `config/*.json`, `AGENTS.md`, `entry_policy.py`, scheduler CLI.  
**Gate:** operator-visible effective policy agrees with approved spec; no changed trade decisions in the structural PR. Any policy change ships separately.

### Phase 2 — Durable ownership and crash consistency (P0)

**R02.1** Decide deployment ownership: **single OMS writer per broker/account** is preferred; verify lock coverage through every entrypoint, not just the scheduler.  
**R02.2** Enforce process-safe coordination for every order/journal mutation (OS lease + account scope), or design a transactional store if multiple processes are a real requirement. Do not assume `RLock` is sufficient.  
**R02.3** Specify write-ahead intent states (`PREPARED` → `SENT/UNKNOWN` → `ACKNOWLEDGED/REJECTED` → `RECONCILED`), crash points and deduplication keys; retain old journal state via a deliberate migration adapter.  
**R02.4** Add atomic-write durability/error handling, malformed state quarantine **without deleting active evidence**, snapshot integrity/versioning and a documented manual recovery path.  
**R02.5** Define crash/restart procedure for position state and journal, with broker account/contract cross-check and safe handling of orphan orders.  
**R02.6** Decide whether JSON+lock remains sufficient; SQLite/WAL or an append-only event store is **conditional**, not an automatic rewrite.

**Modules:** `execution_safety.py`, `trading/adapters/gateways/journal.py`, `trading/adapters/position_codec.py` (pending merge), `trading/adapters/position_store.py`, `position_lifecycle.py`.  
**Gate:** a simulated crash at each persistence/network boundary cannot silently drop or duplicate an intent. Unverified state prevents fresh entries.

### Phase 3 — Explicit OMS state machine and commands (P0)

**R03.1** Document state/transition table for `ENTRY_PENDING`, partial entry, `OPEN`, `EXIT_PENDING`, `EXIT_UNKNOWN`, protection replacement and verified flat. Include invalid transitions and recovery rules.  
**R03.2** Separate pure transition/reconciliation calculations from broker I/O: e.g. `OrderStateMachine`, `ReconciliationService`, `EntryExecutionService`, `ExitCoordinator`.  
**R03.3** Replace ad hoc mutable order dictionaries internally with validated typed records or frozen views, using translators at existing JSON/API boundaries.  
**R03.4** Make single-command outcomes explicit (`APPROVED_TO_SEND`, `VETOED`, `UNKNOWN`, `REQUIRES_RECONCILIATION`) and return structured errors with stable reason codes.  
**R03.5** Preserve partial-fill, linked stop floors, stop ratchets, max modification count, cancel-before-replace, outstanding exit suppression and no overnight hibernation with exposure.  
**R03.6** Recheck entry and exit authorization under the mutation lock **after** all asynchronous/rate-limit waits. Do not schedule irreversible side effects inside a pure state transition.  
**R03.7** Retain old `PositionLifecycle` methods as delegating compatibility facades until callers migrate.

**Modules:** `position_lifecycle.py`, `trading/application/stop_manager.py`, `trading/application/entry.py`, `trading/application/position_monitor.py`, `trading/domain/states.py`, `trading/ports.py`.  
**Gate:** golden order call sequences, risk vetoes and persisted schema remain identical for behavior-preserving PRs; modeled unexpected event sequences remain fail-safe.

### Phase 4 — Broker gateways and execution contracts (P0/P1)

**R04.1** Define canonical `BrokerOrder`, `Position`, `Quote`, `Funds` and `BrokerError` schema with mandatory identity, timestamps, status, filled/remaining quantity and source.  
**R04.2** Use anti-corruption adapters to normalize Kite, Breeze and proxy responses; never erase unknown native statuses. Preserve raw redacted evidence for audit.  
**R04.3** Make network timeouts, read budgets, rate-limit queues, idempotency/reconciliation and retry policy explicit **per operation and broker**. Only idempotent reads may have bounded retries.  
**R04.4** Test/account for order-book truncation, incomplete pagination, 403 session expiry, 429 throttling, 5xx, lost ACKs, partial fills, order cancel races and stale identity.  
**R04.5** Enforce source-account and product/exchange/symbol constraints; never guess a contract expiry, broker instrument mapping, or missing fill count.  
**R04.6** Add sanitized, schema-versioned fixture sets for each supported broker and execution proxy.  
**R04.7** Separate rate-limit concerns for quote and mutation requests; document quota accounting shared with other clients.

**Modules:** `trading/adapters/gateways/{base,kite,breeze,rate_limiter,journal}.py`, `execution_client.py`, `trading/adapters/http.py`.  
**Gate:** adapter conformance across all three gateways; no non-idempotent retry; native broker UAT required independently of offline evidence.

### Phase 5 — Market-data contracts and determinism (P1)

**R05.1** Establish data lineage: exchange timestamp, received timestamp, freshness threshold, instrument identity, source, session and completed-bar flag.  
**R05.2** Extract pure candle normalization, gap detection, expiry/holiday resolution and OI baseline logic into testable domain functions while preserving existing EMA/RSI/MACD variants.  
**R05.3** Normalize provider errors and freshness gates: no fabricated liquidity, stale candle, zero OI baseline, inferred top-of-book or invented instrument expiry.  
**R05.4** Separate snapshot cache from broker-verified entry quote and reconciliation reads; make budgets observable and broker-specific.  
**R05.5** Characterize in-process Kite/Breeze API differences, stock breadth and VIX/sector divergence rules; make fallback permitted only when explicitly safe.  
**R05.6** Track rejected/missing data as structured counters for feed incident triage.

**Modules:** `trading/adapters/{market_data,market_sources,kite_stream}.py`, `trading/domain/{market_data,market_contracts,indicators}.py`, `trading/application/market_context.py`.  
**Gate:** identical signal inputs for recorded sessions; a gap, stale depth, unexpected schema or corrupt timestamp yields NO NEW ENTRY.

### Phase 6 — Centralized, independently reviewable risk gate (P0/P1)

**R06.1** Define a shared pre-trade gate that always runs with existing consultation and validated policy; do not replace or simulate away `AIConsultant.evaluate`.  
**R06.2** Separate account limits from strategy preferences: purchasing power, ₹150 reserve, quantity/lot limits, maximum exposure, one-position rule, premium/liquidity/slippage, allowable hours and daily counters.  
**R06.3** Audit which configured loss stops, drawdown thresholds, failed-entry limits and cooldowns are actually enforced; mark unimplemented settings as **non-operative**, not guaranteed protections.  
**R06.4** Design kill-switch semantics (block new entries, attempt safe protective/exit actions, operator escalation, no unverified flatness claim). Require an explicit decision before changing arming.  
**R06.5** Add explainable `RiskDecision` with immutable policy/version/quote references and a reason-code catalog for vetoes.  
**R06.6** Treat contract price, tick size and money carefully; introduce `Decimal` / tick integer value objects only after golden rounding parity has been proven.

**Modules:** `entry_policy.py`, `trading/domain/{limits,sizing,prices}.py`, `trading/application/{entry,selection}.py`, `position_lifecycle.py`.  
**Gate:** every entry is denied on any missing hard prerequisite; policy changes show explicit approved before/after fixture differences.

### Phase 7 — Strategy and consultation boundary (P1)

**R07.1** Keep strategies pure: candidate signal, reasons and structural invalidation; they must never own broker order writes.  
**R07.2** Standardize `SignalContext` / `CandidateSignal` / `ConsultationRequest` / `ApprovalEnvelope` with stable timestamps and request IDs.  
**R07.3** Make the three modes explicit: deterministic rules, legacy playbook alias, and interactive neural chat companion; never label deterministic heuristics as neural AI.  
**R07.4** Keep consultation identity-bound, time-limited, and single-use for an exact contract, price envelope and risk snapshot. Veto and trap always dominate approvals.  
**R07.5** Separate chat inbox/file transport from decision semantics; protect against stale files, replayed responses, duplicate responses and partial writes.  
**R07.6** Preserve the active MACD/radar/legacy strategy decisions during structure-only changes; strategy tuning is its own policy proposal.

**Modules:** `ai_consultant.py`, `trading/strategies/*`, `trading/application/{dossier,entry,selection}.py`, `ai_context_dossier.py`.  
**Gate:** all frozen candidate outcomes and actual consultation verdicts agree with baseline except explicitly signed-off policy experiments.

### Phase 8 — Replay, backtesting and research provenance (P1/P2)

**R08.1** Create a deterministic event/time abstraction and a non-executing recorded transport so the same production decision services can be replayed.  
**R08.2** Version input datasets, option-chain snapshots, session calendars, recorded news availability, fees/slippage and broker fill-model assumptions.  
**R08.3** Split **decision parity** (what would the strategy and actual rules gate decide?) from **PnL simulation** (assumed fills/stops/costs), reporting uncertainty and limitations separately.  
**R08.4** Detect lookahead bias, missing ticks, synthesized option data, incomplete warmup, survivorship and parameter overfitting.  
**R08.5** Consolidate research entrypoints under `research/` / `tools/` gradually, retaining compatibility wrappers and moving only characterized scripts.  
**R08.6** Add replay comparisons for worst-case fills, gap-through stops, stale data and delayed acknowledgments; backtest profits are not a safety certificate.

**Modules:** `trading/replay.py`, `backtest_engine.py`, `trading/hybrid_research.py`, root `run_*`/`audit_*` and `scratch/` scripts.  
**Gate:** reproducible outputs with provenance; replay has no live network/order capability and does not bypass the real rule gate.

### Phase 9 — Secure configuration, packaging and tooling (P1/P2)

**R09.1** Enforce side-effect-free imports and explicit composition at bootstrap; audit global `socket.getaddrinfo` IPv4 monkeypatch for safe scoped alternatives.  
**R09.2** Keep secrets out of the repo, tests, error reports and diagnostics; add sample-only credentials, redacted logs, rotation and credential-expiry SOP.  
**R09.3** Formalize runtime environment constraints, Python compatibility, requirements/lock strategy, executable entrypoints and optional market streaming dependencies.  
**R09.4** Add type checking and lint coverage incrementally to critical root modules, prioritizing contracts over cosmetic style; remove obsolete suppression only after targeted fixes.  
**R09.5** Isolate diagnostic scripts that access broker data or a local historical DB; require explicit run mode and no side-effect import.  
**R09.6** Document filesystem location and backup/restore of the active journal/state, with explicit file ownership and permissions.  
**R09.7** Prefer secure standards-based authentication; never add personal tokens or real broker credentials to committed fixtures.

**Modules:** `trading/bootstrap.py`, `pyproject.toml`, `requirements-*.txt`, `tools/*`, `.gitignore`, `.env.example`, `CONTRIBUTING.md`.  
**Gate:** developer setup is reproducible, imports are passive, critical modules are typed, and secrets are not disclosed by logs.

### Phase 10 — Observability, operations and controlled rollout (P0/P1)

**R10.1** Define structured audit schema: UTC and IST timestamps, correlation/request IDs, policy version, data provenance, broker account alias, state transition and redacted error classification.  
**R10.2** Separate immutable execution evidence from best-effort human logs; observability failures must not silently invalidate durable recovery.  
**R10.3** Define alerts/health: feed stale, journal error, unresolved order, stop unprotected, pending exit age, rate-limit exhaustion, daily loss veto, missed square-off and worker death.  
**R10.4** Write operator runbooks for pre-open checks, broker re-authentication, session restart, lost response, protective-stop failure, orphan order, outage, emergency flatten and post-trade reconciliation.  
**R10.5** Establish a staged release ladder: offline fixture acceptance → broker paper/UAT → shadow session/no writes → supervised limited live → wider rollout only after explicit owner acceptance.  
**R10.6** Establish revert conditions: mismatched order IDs, phantom positions, duplicate orders, unprotected verified exposure, stale data accepted, breached hard risk limit or any unreconciled broker write.

**Modules:** `trading/audit.py`, `trading/logging_setup.py`, `tools/*`, `docs/*`, scheduler, gateway health hooks.  
**Gate:** operator can explain each trading decision, detect pending exposure and recover/revert safely using documented evidence; no claim of guaranteed fills or zero overnight exposure during outages.

## 6. Implementation order and review slices

Ship small, independently reviewable PRs. **Do not combine policy modifications with mechanical extraction.** Suggested dependency order:

| PR | Class | Contents | Depends on |
| --- | --- | --- | --- |
| A0 | STRUCTURAL | Review and validate existing OMS boundary patch; merge or correct it | Current unmerged branch |
| A1 | DOCUMENTATION | Baseline inventory, ADR templates, fixture catalogue, effective-policy map | A0 baseline chosen |
| A2 | POLICY-SPEC | Resolve POL-01..08 on paper; no behavior modifications | A1 / owner approval |
| A3 | STRUCTURAL | Immutable policy view and read-only effective-policy report | A2 |
| B1 | SAFETY | Process ownership boundary for journal writes; fault scenarios | A0 |
| B2 | SAFETY | Explicit durable intent transitions and migration/compatibility reader | B1 |
| B3 | STRUCTURAL | Pure reconciliation rules extracted behind `PositionLifecycle` | B2 |
| B4 | STRUCTURAL | Entry and exit command/state machine extraction | B3 |
| C1 | BROKER_CONTRACT | Canonical broker DTOs and wire fixture coverage | A1 |
| C2 | BROKER_CONTRACT | Kite and proxy normalization, failure semantics | C1, B3 |
| C3 | BROKER_CONTRACT | Breeze normalization, pacing and quota evidence | C1, B3 |
| D1 | STRUCTURAL | Market timestamp, instrument and candle contracts | A1 |
| D2 | STRUCTURAL | Complete-bar, OI and freshness services | D1 |
| E1 | SAFETY | Central risk-decision types and preflight audit | A3, B4 |
| E2 | POLICY | Any approved capital/cutoff/kill-switch behavior changes | E1 + signed ADR |
| F1 | STRUCTURAL | Typed candidate / consultation envelopes | A3, D2 |
| F2 | STRUCTURAL | Chat transport isolated from veto logic | F1 |
| G1 | RESEARCH | Deterministic event replay and decision parity | B4, D2, F1 |
| G2 | RESEARCH | Versioned data/fill models and script consolidation | G1 |
| H1 | OPERATIONS | Structured audit, alert catalogue and runbooks | B2, C1 |
| H2 | OPERATIONS | Release procedures, incident drills and validation handover | All relevant safety gates |

The table is a *suggested review sequence*, not a commitment to large-bang sequencing. Independent workstreams can be developed in parallel after their foundations are stable. A failure in a risk gate blocks its merge, not unrelated documentation.

## 7. Acceptance matrix (tests to execute later, not executed for this plan)

| Scenario | Expected invariant |
| --- | --- |
| AI veto/timeout, stale approval or wrong request ID | No BUY and actionable veto reason |
| Quote old by threshold, missing depth, wrong instrument or exchange | No BUY; no fallback to LTP as executable price |
| Available margin is zero/unknown or quantity exceeds effective cap | No BUY; no optimistic margin assumption |
| Duplicate cycle, concurrent process, overlapping gateway writers | At most one authorized mutation owner; no duplicate exposure |
| BUY response lost before acknowledgement | Persist UNKNOWN and reconcile before further BUY |
| BUY partial fill; cancel races another fill | Stop quantity never exceeds verified residual |
| STOP modify fails; cancel/replace races trigger | No weaker stop floor or competing SELL |
| EXIT timeout, partial stop fill and later restart | No blind second SELL; verify net residual |
| Corrupt/missing journal, disk full and interrupted atomic replace | New entries blocked; evidence retained and incident raised |
| Broker account changes after startup | Revoke authorization; block actions until account scope verified |
| Order book truncated, foreign order or divergent positions/orders | No false flatness or auto-cancel of unrelated orders |
| 14:15/15:15 boundary crossing and broker outage | Effective gates enforced; unresolved exposure remains monitored/escalated |
| Missing 1m bars, incomplete candles, expiry/holiday mismatch | No lookahead, fake liquidity or silent failover |
| Old vs new golden traces | Identical order calls, decisions, rounding, state and vetoes in STRUCTURAL PRs |
| Recovery after process kill between each journal write and network operation | Safe continuation or explicit reconciliation block |
| Log worker failure, stale external intelligence | Audit failure surfaces; new entries stay conservative while exposed positions still receive risk management |

**Owner-run verification later:** `python -m tools.checks`, `python -m tools.quality`, `git diff --check`, offline fault injection and broker UAT. Per current user instruction, **do not run tests now**. CI status is not a blocker to *drafting* this plan, but no safety-critical change should be treated as verified until its acceptance evidence exists.

## 8. Rollout and rollback requirements

1. Develop every safety-critical increment on a branch; do not alter `main` directly.
2. Before merging a STRUCTURAL PR: show baseline/golden parity and exact changed contracts. Before merging a POLICY PR: link a signed ADR with intended behavioral differences.
3. Never try a new storage migration directly against the only live state. Support read-old/write-new transitions only after backup and proven recovery; preserve known request IDs and journal metadata.
4. Reconcile broker account and actual positions before activating a new build; do not infer that no local state means a flat broker account.
5. A release can be rolled back **only** when the old binary can safely understand the persisted state; otherwise perform a documented forward-recovery or explicit controlled stop.
6. Operational safe stop means deny new entries and retain management of existing exposure, with manual broker action if the engine cannot verify its own state.
7. Owner sign-off requires broker-by-broker UAT of live-capable pathways and a documented emergency response; green unit tests or profitable backtests are insufficient.

## 9. Decisions needed before implementation

**Immediate owner approvals (no urgency to decide policy values until usage mapping exists):**

- Confirm the intended source of truth for risk settings and who signs policy ADRs.
- Confirm whether a single scheduler/process per execution account is an acceptable permanent rule. If yes, avoid an unnecessary database migration.
- Confirm whether the current proxy, Kite and Breeze pathways all remain supported.
- Confirm intended support for chat companion vs deterministic rules mode; the existing gate must not be removed from any path.
- Confirm operating environment (Windows-only or Windows/Linux), broker UAT access, and willingness to keep historical research scripts as separate non-production tooling.
- Confirm that plan-only and structural PRs may proceed without changes to PnL targets, strategy rules or live order settings.

**Default recommendation:** preserve all current effective trading behavior, impose **single-writer ownership**, start with R00 → R01 → R02 → R03, and defer strategy optimization or performance claims until the core is recoverable and auditable.

## 10. Definition of done for the modernization program

- A new developer can identify who owns market data, policy, consultation, OMS state, broker mappings, persistence and audit without reading a monolithic file.
- Each live mutation has durable identity, account scope, validated preflight, an explicit unknown/retry policy and a recoverable state transition.
- Broker data and market context use typed, versioned boundary contracts; invalid data never creates new exposure.
- Operator can inspect effective risk policy and distinguish approved rules from merely documented or unused configuration.
- Actual consultation vetoes and strategy outcomes are unchanged by mechanical refactors; intentionally changed policy is approved and documented.
- Replay and backtest reports state provenance, costs, assumptions and decision-vs-PnL differences.
- Crash, outage, partial fill, clock/expiry, multi-process, and stop-failure scenarios have documented owner-executed verification evidence.
- Secrets are excluded from source and traces; logs and emergency actions are operationally documented.
- Deployment/rollback rules account for persisted-state version compatibility and manual broker reconciliation.
- **The engine is not called production-ready until operational UAT and owner acceptance are completed.**

---
*Planning document only. No test suite, live broker connection, historical simulation, or production code path was executed for this document.*