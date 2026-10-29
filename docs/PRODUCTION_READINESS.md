# Trading engine: production-readiness gates and refactor backlog

**Review baseline:** `main` at `92da61d2a5c5a1ae5d5e7477db0027f196fb7c5f`, 2026-10-29.

**Status:** not approved for live deployment by this review. Do not infer live safety from offline tests or historical PnL.

## Architecture observed

The repository already separates policy calculations, strategy selection, application workflows,
execution adapters, position-state persistence, market-data adapters, and a compatibility CLI.
It includes offline network-blocked tests, an OMS journal, rate limits, broker adapters,
replay fixtures, pinned development tools and cross-platform CI. Retain those boundaries.
**Do not replace or bypass the real `AIConsultant.evaluate()` gate.** Rule-based/playbook
mode is deterministic, not a neural AI service.

## Findings and sequencing

| Priority | Evidence / risk | Next step / acceptance criteria |
| --- | --- | --- |
| P0 | Configuration, `AGENTS.md` and runtime disagree on lot caps, capital, 0DTE premium and entry/exit cutoff times (`docs/ARCHITECTURE_REVIEW.md`). | Record a signed-off policy specification and scenario fixtures before consolidating values; never silently increase exposure. |
| P0 | A broker acceptance or timeout is not a verified fill; startup, cancel/replace and crash recovery span multiple durable records (`docs/OMS_RECOVERY.md`). | Validate each broker's real request/ack, partial-fill, lost-response, restart and reconciliation behavior in a paper/UAT account; keep unknown outcomes blocking new entries. |
| P0 | State recovery previously accepted malformed order collection shapes; a string `stop_order_ids` could become character-by-character identities. | Implemented fail-closed collection validation and a standalone codec; verify using the added regression cases before deployment. |
| P1 | Nonblocking token acquisition previously accepted zero/negative/nonfinite requests, affecting accounting; limiter only controls this process. | Implemented shared strict validation and monotonic refill; verify request pacing using the added regression cases. |
| P1 | Broker intent metadata is protected by an in-process lock, but independent gateway processes can race to rewrite the same JSON journal. | Specify a single-writer process or implement tested cross-process coordination; do not enable competing writers before resolving this. |
| P1 | Entrypoints, runtime policy, risk constants, journal migration and research scripts coexist with historical legacy behavior. | Introduce separately reviewed typed schemas and explicit migration versions; characterize accepted legacy payloads first. |
| P1 | Two live gateway adapters and a proxy-oriented compatibility client need per-broker contract verification. | Version contract tests against recorded **redacted** broker responses, clock skew, outages, HTTP 429/5xx, rate budgets, quote age and order-book pagination. |
| P1 | Offline tests use fixed fixtures but do not establish PnL parity or exchange behavior. | Add deterministic event replay with delayed/duplicate/reordered events, process-kill fault injection, randomized invariant tests and idempotent order IDs. |
| P2 | Root contains numerous one-off analysis/test scripts alongside production entrypoints. | Inventory and classify scripts, move research tooling in mechanical PRs, keep CLI compatibility, and restrict CI to safe offline tests. |
| P2 | Operational telemetry and release procedures require explicit ownership. | Document alerts, audit-log retention, backup/restore, rollback, dry-run-to-live checklist and incident response; gate deploy on green tests and supervised broker UAT. |

## Required invariants before enabling live orders

1. Never issue an entry without a current, approved, non-trapped consultation verdict; failure or timeout means no entry.
2. Every order mutation has a durable request identity **before** transmission; ambiguous acknowledgements cannot cause blind retries.
3. Broker reconciliation must verify account, symbol, exchange, product, position and actual fills. Unknown/partial/truncated books must not be treated as flat.
4. A protective stop must cover verified residual exposure; cancel-before-replace and pending exits must not create competing SELLs.
5. Entry limits must be evaluated at submission time against verified margin, premium, current session, fresh quotes and the one-position gate.
6. Emergency square-off and a manual kill switch need supervised failure drills; a clock cutoff alone cannot guarantee zero overnight exposure.
7. State corruption, missing recovery journal, stale broker data and disk write failure must block **new** exposure and surface an actionable alarm.
8. Live broker credentials must never be committed, printed in logs or passed into offline CI.

## Validation and rollout

- Offline: run `python -m tools.checks` and `python -m tools.quality` before merging the changes.
- Paper/UAT: exercise each broker's real APIs without deploying capital; capture sanitized order traces.
- Shadow: replay and shadow-evaluate market sessions, ensuring no actual order writes and checking drift.
- Supervised limited-live: only after P0 findings are resolved, rollback/kill switches tested and policy owners sign off.

The refactor (`OMS_BOUNDARY_REFACTOR.md`) is a **safety-boundary increment**, not a certification of
end-to-end production readiness. It does not modify strategy logic, approval rules, timing,
lot caps, broker request payloads or live execution mode.
