# Refactoring delivery status — 2026-10-29

> **ARCHIVED SNAPSHOT — not the latest implementation state.** This page describes the R02–R10 foundation branch *before* the 2026-10-30 native LIVE ownership/funds work and full R01 stop-monitor integration. In particular, the lines below saying that `AccountSessionLease` is unwired to native gateways, that R01 stops are only calculated by `StopManager`, or that native funds receipt provenance is absent are **historical**. See [canonical current status](CURRENT_IMPLEMENTATION_STATUS_20261030.md) and [activation blockers](LIVE_ACTIVATION_HOLD_20261030.md) for what is now coded and what is **still unverified**. No tests have been run for the newer work.


**Branch:** `refactor/r02-r10-safety-foundations-20261029`  
**Parent:** `feature/r01-approved-policy-contracts-20261029`  
**Environment:** CODE ONLY. No tests executed; no native broker UAT; no production deployment. `main` is unchanged.  
**Active flag:** `r01_policy.enabled=false`.

## Implemented in this branch

| Work package | New code/asset | Integration and verification still outstanding |
| --- | --- | --- |
| R00 baseline | Existing inventory, fixture index, risk register, ADR template | Golden fixtures not executed |
| R01 policy | Owner lot ladder, P&L gate, no penny veto, time cutoffs and shared stop-floor behind an OFF switch on the parent branch | Native broker identity, P&L baseline, freeze limits and full stop behavior parity; **do not enable** |
| R02 crash consistency | Integrated unmerged `position_codec.py`, position-store boundary, stricter journal checks and rate limiter; added **OS-level journal writer lock** and a per-account OMS lease abstraction | Account lease not wired through every proxy/native execution entrypoint; atomicity/partial-fill crash cases untested |
| R03 OMS typed states | `intent_transitions.py` immutable scoped intent state machine with invalid-transition and unknown outcome checks | Still a pure service; production `PositionLifecycle` and gateway journal retain legacy dictionaries |
| R04 broker contracts | `broker_contracts.py` strict funds and order evidence records, account match, freshness, quantity and unknown-status validation | Not wired into Kite/Breeze/proxy; no invented P&L/as-of, account equity, order freeze limits or live funding |
| R05 expiry & data | `expiry_evidence.py` exchange-session + broker-instrument-master cross-check without inferred symbols | Actual authoritative exchange calendar fetch, broker master refresh, timestamps and failover integration outstanding |
| R06 pre-trade risk | `pretrade_evidence.py` typed explainable veto aggregation | Existing mandatory live submit-time gate remains authoritative; new checker is NOT yet in its mutation path |
| R07 consultation | `consultation_contract.py` contract/account/time/price/one-use evidence check | Real `AIConsultant.evaluate` remains mandatory; new check is not a replacement and is not yet wired |
| R08 replay | `replay_provenance.py` deterministic source hashes, decision-only manifest and lookahead detection | Need real recorded input provenance, fill-model separation and replay fixture comparisons |
| R09 tooling/security | `trading/audit.py` observational log events now redact named sensitive fields via `audit_redaction.py`; read-only `tools/refactor_readiness.py` | Full import/bootstrap, packaging, secret audit and documented credential rotation still pending |
| R10 operations | `incident_contract.py`, operator runbook, read-only release blockers | Real alert sinks, metrics, on-call drills, broker outage and market-close UAT outstanding |

## Release blockers

1. **Do not enable the R01 feature flag:** native `get_funds()` is not yet proven to provide account-matched, live-sourced session P&L (`start_of_day_equity`, realized and unrealized), source timestamps, and instrument-specific `max_single_order_quantity`. A missing field must block only NEW entries, not protective exits. No static funds fallback.
2. **OMS account ownership is incomplete:** the journal now serializes its writes across processes, but **this is not proof of one exclusive OMS order writer**. `AccountSessionLease` must be incorporated into all supported live execution entrypoints with lifecycle and failure checks.
3. **Unified stops are not fully migrated:** the R01 shared stop floor supplements the existing `StopManager`, but `PositionMonitor` still contains strategy-specific exit/trailing policies. Do not assert strategy-independent end-to-end stops before behavioral parity review.
4. **Calendar and broker master are not connected** to the source-evidence resolver. Reject ambiguous new expiries, continue protecting existing positions.
5. **Structural DTOs are not live replacements** for the existing gateway/journal/consultation flow. Do not interpret a pure `RiskCheck.passed=True` or matching `ConsultationRecord` as permission to submit any order.
6. **No tests were run.** Offline regression, deterministic replay, crash injection, broker conformance, UAT, operational sign-off, and real account/quote identity evidence are still required.

## Compatibility and rollout

- Reused existing file formats and public callable broker interfaces. The prior position codec keeps schema-v2 aliases and hydrated legacy records but needs validation against actual position files.
- No automatic arming, no bypass of mandatory real consultation, no duplicate resubmissions after unknown outcomes, no assumed flat state on broker outage.
- Existing open positions retain the OMS recovery and protective path. Never delete journals to force a new session.
- Code changes are reviewable at [compare the feature branch](https://github.com/hawisback/codex-trading/compare/feature/r01-approved-policy-contracts-20261029...refactor/r02-r10-safety-foundations-20261029).
- A supervised release requires a separate tested integration PR and an operator-authorized deployment, **not** merely switching a feature flag.

## Explicit validation to schedule later (no execution this turn)

- `python -m tools.checks` and `python -m tools.quality` plus the registered `tests/test_regression.py` suite.
- Broker-specific response fixtures for Kite, Breeze and proxy including 401/403, 429, timeout-after-send, partial fills, canceled stop replacement, order-book truncation, missing P&L and stale account credentials.
- Multi-process OMS lease contention and journal crash-point tests, including `fsync`, restart and existing unprotected exposure management.
- Decision parity for normal sessions, 0DTE, penny-priced but liquid contracts, 10-entry cap, margin tier boundaries, stale quotes, confirmed AI veto and 14:15/15:15.
- Supervised broker UAT and rollback drill after the exchange/calendar contract is fully implemented.

**Conclusion:** R02–R10 now have new implementation foundations, but the *complete* refactor and LIVE activation are not finished or verified.
