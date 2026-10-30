# Offline validation and remaining LIVE gates - 2026-10-30

**Offline result: PASS. Real-money release: BLOCKED.** The owner explicitly
authorized running and repairing tests in this session. This supersedes the
earlier no-tests instruction for this repair candidate.

## Candidate and evidence

- Branch: `feature/live-activation-guardrails-20261030`.
- Current owner-selected release target: **Kite only**. Breeze was initially
  included, then explicitly deferred. Its earlier diagnostic results below are
  historical observations and do not block the current Kite release.
- Base commit: `097eeece43c29fd175448af413c86b08a477f546`.
- Validation ran against the repair working tree before feature-branch check-in.
  The base commit alone does not contain the fixes; use the containing repair
  commit and source fingerprint below to identify the tested candidate.
- Environment: Windows, Python 3.14.6. The owner targets only this machine; Linux, remote CI, distributed deployment and additional security work are outside release scope.
- Final command: `python -m tools.quality`, exit **0**. Formatting, lint,
  runtime lint and mypy passed; the wrapper's `tools.checks` stage passed
  static boundaries and **574 offline tests in 60.493 seconds**. There were
  no failures, errors or blocked unexpected network attempts.
- `git diff --check` passed. Frozen files under `tests/fixtures/` are unchanged.
- Local detailed output: `.tools/tmp/quality-companion-final.log` (ignored by Git).
- Validated source manifest SHA-256:
  `b0ea771f48ce9d0663faf10be698d58c121990a7fb86190cc26231b7d837fe1a`.
  This hashes 421 files: tracked Python/JSON/TOML files and `requirements-dev.txt`,
  eleven new Python files (test helpers, R01/Kite evidence, operator controls and
  Codex companion components/tests), plus the runtime policy inputs `AGENTS.md`
  and `config/rules_playbook.md`. Sorted repository-relative filenames are UTF-8
  encoded; each is followed by a NUL byte and the raw SHA-256 digest of its bytes,
  then fed to the aggregate SHA-256. Other documentation, credentials, logs,
  installed tools and temporary locks are excluded. Runtime Markdown policy
  inputs are newly included because the Codex worker consumes them.


## Repairs and added coverage

- The isolated ownership gateway now implements the required quote interface.
  The stop-consultation fixture supplies its scheduler configuration.
- Native Kite/Breeze restart fixtures explicitly terminate the old simulated
  process before arming a replacement, and release test leases before Windows
  temporary-directory cleanup. Production PAPER disarming still retains the
  account lease. The test-only helper is `tests/gateway_lifecycle.py`.
- Fixed a production ownership defect: a stale gateway could previously
  mistake a replacement gateway's path registration for its own lease.
  Authorization now requires the exact held lease and acquiring PID. An
  inherited child cannot authorize mutations or explicitly unlock its parent's
  lease.
- Added independent-process exclusion and forced-process-termination recovery
  tests, including preservation of the durable journal and lease file.
- Added `tests/test_r01_native_workflow.py`, registered in the offline suite:
  actual deterministic consultation, fake native HTTP and explicitly fake
  normalized funds evidence exercise initial protection, profit ratcheting,
  restart with frozen R01 policy, disabled new-entry flag, missing funds/day
  ledger, loss cutoff, funds expiry during pacing, and partial-stop-fill exits.
  These tests do **not** prove genuine broker P&L normalization.
- Corrected type narrowing in money/order/stop contracts and removed lint
  errors. Applied the existing formatter to 58 files required by the quality
  gate. No frozen expected traces were regenerated and no tests were disabled.
- Corrected the read-only market diagnostic to probe the ATM call using the
  provider's normal three-second entry-read budget, capped by the operator's
  requested timeout. The old first-strike/one-second probe could be blocked by
  its own quote pacing. Runtime quote freshness/liquidity rules are unchanged;
  an added regression verifies contract selection and deadline preservation.

## Refreshed-session read-only acceptance

After the owner refreshed both sessions and supplied updated Breeze app settings,
the checks produced the following current results. Credential values are stored
only in the Git-ignored local `.env`, with primary and legacy aliases consistent.

| Broker / scope | Result | Observed limits |
| --- | --- | --- |
| Kite profile, funds, positions, orders | **PASS** | Available margin INR 14,663.10; zero positions and zero orders in the observed snapshot. This margin is not opening account equity or a P&L ledger. |
| Kite live read-only market conformance | **PASS** | Data quality, snapshot, 1m/5m candles, technicals, options, heavyweights, VIX, sectors, ATM depth, engine consumer and actual REST headers passed. |
| Breeze session exchange / expected account | **PASS** | Returned account matches the configured account; the exchanged token has the expected format. |
| Breeze signed funds, positions, orders | **BLOCKED: HTTP 401** | These books remain unknown, not empty. Supplied credentials were applied locally and the same rejection persisted. App credentials/authorization require resolution. |

The first Breeze request encountered certificate-chain verification error 19.
Windows subsequently validated the endpoint with its normal TLS trust handling;
later Python requests also passed certificate verification. No unverified TLS
context, disabled hostname check, or certificate-validation bypass was used.
The server clock differed from the local UTC clock by approximately one second.

Breeze signing was compared with the broker's
[official SDK request builder](https://github.com/Idirect-Tech/Breeze-Python-SDK/blob/main/breeze_connect/breeze_connect.py)
and [API reference](https://api.icicidirect.com/breezeapi/documents/index.html).
The comparison found no discrepancy in the timestamp/body/checksum/header
construction. It does not prove that the broker accepts the configured secret,
app permissions or account authorization; signed reads still returned 401.

Commands and local outputs:

- `python -m tools.brokers --broker both`: exit 1, because Breeze signed reads fail.
- `python -m tools.verify_market_data --broker kite --timeout 45 --report .tools/tmp/kite-session-market-check.json`
  with process-local `MARKET_DATA_STREAMING=off`: exit 0, 13 offline contract tests
  and all live **read-only** market checks pass. This diagnostic does not arm
  the scheduler or authorize real orders.

## Revised owner policy and Kite source acceptance

- Minimum capital milestones: positive verified margin below INR 40k permits up to 2 lots; INR 40k/60k/80k/100k permits 4/6/8/10 respectively. Actual option entry-limit affordability, the INR 150 reserve, verified exchange freeze and hard position cap can reduce quantity. Tests cover exact milestone and funding boundaries.
- Daily combined realized + unrealized loss blocks each proposed entry at INR 3,000 times its actual affordable lot count. Recalculate for every entry, including de-escalation; no opening-equity baseline is required. Equality blocks. A breach blocks only new entries; normal stop management and exits remain active.
- `get_entry_funds()` now combines authenticated Kite margin and raw portfolio positions/daily fills with exact Kite master contract identity/lot/tick and NSE NIFTY freeze/calendar evidence. Missing, malformed, stale, partial, duplicate or mismatched books do not become zero. Carry positions are unsupported and block new entries.
- Contract/calendar source URLs, hashes and receipt timestamps are retained with entry evidence. The R05 resolver rejects non-sessions and invalid expiry dates; the configured minimum remaining regular-session budget is enforced. Special sessions and expiries outside the available calendar year fail closed. Published exchange limits do not guarantee broker RMS acceptance.
- New offline coverage: `tests/test_kite_risk_evidence.py` checks partial/closed P&L, authenticated complete empty books, unknown/truncated books, fill identity/date/quantity/value reconciliation, overnight ambiguity, malformed/changed contracts, ambiguous freeze data, calendar freshness and source binding. Native R01 tests verify one affordable lot gets INR 3,000 rather than INR 6,000 and that crossing the cap does not force an existing position to exit.
- One intermediate full run failed the existing companion handoff fixture. A deliberate transient Windows state-file lock reproduced its polling mock reading a deleted consultation request during an unrelated filesystem retry. The fixture now leaves non-consultation waits to the real retry mechanism and retains that deliberate lock case. The actual consultant and mandatory protection assertions remain intact. Focused reproduction/fix logs are `.tools/tmp/handoff-lock-reproduction.log` and `.tools/tmp/handoff-lock-fixed.log`.

At **10:09 IST on 2026-10-30**, the final read-only Kite risk-source probe passed:

| Evidence | Observed result |
| --- | --- |
| Authenticated actual available margin | INR 14,663.10 |
| Reconciled current-day realized / unrealized P&L | INR 0 / INR 0 from complete empty authenticated books |
| Published NSE NIFTY single-order freeze | 3,510 contracts; fetched source data, not a hardcoded runtime value |
| Exact diagnostic contract master lot / tick | 65 / INR 0.05 |
| Listed diagnostic expiry / remaining regular sessions | 2026-11-03 / 2; passes the configured two-session minimum |
| One-lot cash policy validation | OK; separate from execution authorization |
| Native LIVE authorization | false; no orders or scheduler activation |

This sampled contract is only a source-conformance probe, not a trading recommendation. The result is a point-in-time account/source observation, not a future-session guarantee. Source hashes and details are in `.tools/tmp/kite-risk-source-check.json`. Source semantics are documented with primary references in the [entry evidence contract](R01_ACTIVATION_RUNBOOK.md).

## Codex companion and operational pause integration

- Added persistent `tools.codex_companion`, independent entry/stop inference
  slots, original-deadline cancellation, durable at-most-once request claims,
  strict schemas and application-owned helper publication. New tests cover
  multiple requests/restart, stop priority, malformed/stale/replaced responses,
  source changes, prior manual veto, explicit trap dominance, model failure and
  process cancellation, as well as the real chat-consultant handoff/15-second TTL.
- Reconciled the charter workspace and neural-companion terminology, 25% initial
  protection and removed Trap 1 checklist entry. Requests now carry authoritative
  risk metadata; R01-facing packets do not expose competing legacy refinement
  bands. R01 unified stops remain the position authority.
- Fixed an operational gap: the JSON kill/pause fields previously appeared in
  reports but did not gate actual entry submission. Fresh exact-boolean controls
  now gate LIVE discovery, entry preparation and BUY pretransmit (after pacing).
  Missing/malformed files block new entries. Tests verify start-paused/resume,
  pause during pacing and continued stop ratchets/exits.
- The installed CLI is `codex-cli 0.162.0-alpha.17.2`, authenticated using ChatGPT.
  The final nontradable `--self-test` passed in **8.272 seconds**. It consumed no
  live inbox, published no verdict and submitted no order. This establishes the
  CLI transport/schema path, not live decision quality or future response speed.
  Report: `.tools/tmp/codex-companion-selftest.json`.
- Refreshed read-only acceptance at 10:23 IST passed: authenticated Kite, zero
  positions/orders, current risk-source evidence and all market/header checks.
  Reports: `.tools/tmp/kite-acceptance-baseline-20261030.json` and
  `.tools/tmp/kite-acceptance-market-20261030.json`.
- Current [worker guide](../CODEX_COMPANION.md) and [operator procedure](../operations/KITE_LOCAL_ACCEPTANCE_20261030.md)
  specify the controlled start-paused R01 trial. The default R01 flag is still
  false; no worker or LIVE scheduler was left running by these checks.

## Remaining release work

**Actual broker order acceptance is still pending.** The operator must perform the real entry/confirmed protection/ratchet/exit and recovery steps in the [local acceptance procedure](../operations/KITE_LOCAL_ACCEPTANCE_20261030.md). The assistant can inspect read-only books/logs but has not performed financial order submissions or activation. No further owner clarification of risk semantics is pending.

This Windows machine is the release target. No CI, cross-platform or distributed fencing requirement has been added. Existing authenticated account identity, mandatory consultation, local single-writer ownership and risk/OMS correctness checks remain. The source fingerprint identifies the tested candidate. The owner subsequently requested feature-branch check-in; publication does not complete broker acceptance or authorize LIVE activation.

`r01_policy.enabled` remains **false**. No real broker order was submitted,
canceled or modified. No scheduler was armed. `tools.refactor_readiness`
continues to deliberately report BLOCKED; it does not consume this document
as externally reviewed acceptance evidence.

The previous failing run left 75 untracked `.native-test-*` / `.breeze-test-*`
directories containing 104 inactive synthetic lock files. Their paths and
exclusive file accessibility were checked. Automatic approval review rejected
even explicit file-only cleanup with `blocked by policy`; the files remain.
The repaired fixtures successfully clean up their own new test state.
