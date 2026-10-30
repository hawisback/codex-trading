# R00 fixture inventory and coverage plan

No reference traces were generated, modified or executed in this increment. Preserve original bytes; review results only after owner-run verification.

| Existing artifact | Intended contract | Status |
| --- | --- | --- |
| `tests/fixtures/oms_reference.json` | Filled entry, partial filled/cancelled entry, unknown submission; ordered broker calls and recovery state | EXISTING, not executed in this change |
| `tests/fixtures/staged_reference.json` | Pre-extraction market/strategy decision parity | EXISTING, not executed |
| `tests/fixtures/staged_approved_reference.json` | Approved candidate parity by strategy | EXISTING, not executed |
| `tests/fixtures/staged_extra_reference.json` | Climax and extra fallbacks | EXISTING, not executed |
| `tests/fixtures/indicators_reference.json` | Indicators and numeric parity | EXISTING, not executed |
| `tests/fixtures/replay_example.json` | Deterministic decision replay context | EXISTING, not executed |
| `tests/fixtures/PATH_A_POLICY.md` | Active Path A fixture expectations, premium cap and consultation TTL | EXISTING, not executed |

## Newly authored fixtures (not executed in this increment)

- `tests/test_unified_stop_integration.py`: shared decision and initial broker stop across strategy names; IST phases, stale quotes, upward 0.05-tick rounding, stronger floor, version persistence, separation of legacy-vs-R01 behavior and square-off. Registered in `tests/test_regression.py`.
- `tests/test_live_activation_guardrails.py`: account-ownership and broker funds provenance/absent P&L contract cases. Registered but not run.
- Existing legacy stop, native gateway and OMS suites remain part of the explicit offline regression. **Authored does not mean passed**; broker-verified crash/partial-fill and UAT scenarios are still open.

## Required future redacted fixture cases

| ID | Case | Evidence | Expected invariants | Owner |
| --- | --- | --- | --- | --- |
| F-01 | Broker BUY response lost before acknowledgment | Fake response + durable intent | No blind retry; reconcile first | OMS |
| F-02 | Partial BUY fill during cancellation | Order/position snapshots | Stop covers verified residual only | OMS |
| F-03 | STOP cancel/replace races a trigger | Event trace | No weaker floor or duplicate SELL | OMS |
| F-04 | EXIT lost acknowledgment + restart | Durable state and post-restart broker book | No second SELL without verified residual | OMS |
| F-05 | AI denial, stale ID, timeout and late reply | Dossier + real deterministic gate | No BUY | Policy |
| F-06 | 14:15 entry and 15:15 square-off | Controlled IST clock | Preserve effective session checks | Policy |
| F-07 | Corrupt/missing state and disk failure | Recovery file fault events | Block new risk; evidence preserved | State |
| F-08 | Multi-process journal writers | Separate writer processes | Single owner or safe conflict handling | State |
| F-09 | Broker account switch + foreign active order | Redacted broker book | No false flatness or unauthorized cancel | Broker |
| F-10 | Truncated order book/stale quote/missing depth | Redacted quote & book responses | No new entry | Broker |
| F-11 | Market gap/incomplete 1m bar/expiry mismatch | Timestamped source data | No forward-looking or invented data | Market |
| F-12 | Configuration source conflict | JSON + CLI/environment overrides | Report provenance, never silently increase limits | Policy |

Review fixture provenance before adding broker-derived captures; redact credentials, account identity and personally identifying order metadata. Do not regenerate frozen references just to make a change pass.
