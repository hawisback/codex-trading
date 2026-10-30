# Persistent Codex companion for ChatGPT IDE

The application worker explicitly invokes the installed Codex CLI for each
current `--ai-mode chat` consultation. It uses the local ChatGPT login; it does
not rely on an IDE notification waking a model or on this chat staying active.
The worker process remains armed after each response or per-request failure.
Codex usage consumes the account's available plan quota. No broker credentials
or separate OpenAI API key are passed to the judgment process.

## Responsibility and policy

- **Codex:** supplies a structured entry judgment or legacy stop judgment.
- **Application:** validates schema, request/candidate/trade identity, unchanged
  request/policy sources, timestamps and deadlines; existing submission helpers
  publish verdicts with atomic writes.
- **Engine/OMS:** owns fresh quotes, funds, lot sizing, daily risk, order
  placement, protection, stop amendments, fill/cancel reconciliation and exits.
  The worker imports no broker adapter and cannot submit an order.
- **Current protection:** MACD and R01 start at 25%. Requests carry an
  `authoritative_risk_policy`; existing positions retain frozen policy and
  stronger stops. R01 uses unified stops and does not publish competing legacy
  post-fill refinements. The worker nevertheless monitors stop requests for
  eligible legacy positions. Their frozen refinement band is 15–20% when
  configured, and structural invalidation uses the frozen buffer.
- **Trap 1 is removed.** Historical setup examples cannot reinstate it or
  override current risk/stop policy. Rules/playbook mode is deterministic and
  uses no neural AI. Chat mode alone is not evidence that a model answered;
  worker records establish an actual invocation and validated handoff.

The Codex process receives the dossier, current playbook and charter, evaluation
rubric, authoritative policy, exact identities and original deadline. R01-facing
risk metadata has one unified authority. Named credential/account fields are
redacted. Codex runs ephemerally with shell, additional agents and hooks disabled,
read-only sandboxing and user-config integrations excluded. Only application
code can publish to the consultation inbox. These are execution-boundary
controls for this integration, not a CI or deployment security project.

## Timing and failure behavior

- The original **45-second** request window includes process/model startup,
  judgment, validation and handoff. Request age is never reset on worker restart.
  Two seconds are reserved for publication; a newly observed request therefore
  has at most 43 seconds for the model, less any time already elapsed.
- The existing engine limits entry approval to **15 seconds after application
  submission**, clipped to the original consultation deadline. Codex cannot
  supply or backdate the submission timestamp.
- Entry and stop jobs have separate bounded slots. A slow entry does not prevent
  discovery/processing of a stop request. Superseded/expired work is canceled.
- Malformed output, wrong identities, explicit traps, changed policy, missing
  evidence, quota/network/process errors and late responses cannot approve an
  entry. No deterministic approval is substituted for a failed neural call.
- A stop `HOLD`, failure or timeout retains existing protection. `ADJUST` still
  passes the existing frozen-band/current-floor validation and broker OMS.
- Durable claims in `logs/codex_companion_state.json` prevent re-invoking an
  already claimed request after a worker restart. A crashed in-flight request
  expires safely; a new request is processed normally. Existing same-request
  verdicts, including manual vetoes, are not overwritten.
- One worker per checkout is enforced by `logs/codex_companion.lock`. Do not
  delete state or locks to work around an unresolved process/order condition.

## Checks and operator launch

From the repository root:

```powershell
python -m tools.codex_companion --check
python -m tools.codex_companion --self-test
```

`--check` validates the installed CLI/ChatGPT login and agreed timing/protection
configuration. `--self-test` invokes a nontradable canary and requires a bound
VETOED response. It never consumes the live inbox, publishes a verdict or arms
the scheduler. Results are written to
`.tools/tmp/codex-companion-selftest.json`. A passing canary demonstrates the
transport, not live decision quality or a future latency guarantee.

The operator starts the persistent worker in one terminal:

```powershell
python -m tools.codex_companion
```

The operator starts the scheduler in another terminal, using the **start-paused
acceptance sequence** in [Kite local acceptance](operations/KITE_LOCAL_ACCEPTANCE_20261030.md).
Do not use `--once` for an acceptance session that may create exposure.

```powershell
python nifty_trader_scheduler.py --broker kite --market-data-broker kite --live --strategy macd_momentum --ai-mode chat --wait-until-market-open
```

Optional `--model NAME` explicitly selects a model; otherwise the installed
CLI default is used. `--run-seconds N` limits worker uptime; the default stays
armed until stopped. This is a separate CLI judgment session, not a continuation
of the visible IDE conversation. No worker or LIVE scheduler was left running
by implementation tests.

The older `tools/watch_consultation.py` remains a legacy one-shot notification
helper. It neither invokes Codex nor replaces this worker.

## Evidence to inspect

Keep worker status output, `logs/codex_companion_state.json`, engine audit/runtime
logs, durable broker intents and broker order/fill records. Correlate each
request/candidate ID with its accepted verdict and entry, and any legacy stop
request with its trade. A model judgment or an order acknowledgement alone does
not establish a fill, protective coverage or broker flatness.

The implementation uses the documented [`codex exec` structured-output mode](https://learn.chatgpt.com/docs/non-interactive-mode)
and [CLI flags](https://learn.chatgpt.com/docs/developer-commands). Installed CLI
version and authentication are checked locally; model errors fail closed.
