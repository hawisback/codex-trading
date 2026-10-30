# Kite local acceptance and recovery

Scope: this Windows checkout on this machine. Breeze is deferred. CI and
distributed deployment are not release requirements. Keep the existing account
identity, single-writer lease, consultant veto, risk gates and OMS protections.

## Completed engineering evidence

- Owner-approved lot milestones and per-entry INR 3,000-per-lot loss budget are
  implemented behind `r01_policy.enabled=false`.
- Local fake-transport tests exercise initial stops, ratchets, partial fills,
  unknown acknowledgements, cancellation, restarts and process ownership.
- Authenticated Kite and public NSE/Kite risk-source reads pass. Source failure
  blocks new entries; existing protection remains independent.
- See the [validation record](../architecture/OFFLINE_VALIDATION_20261030.md)
  for the tested source fingerprint and exact local test result.

## Remaining broker acceptance: operator actions

Actual financial order submissions and live engine activation must be performed
by the account owner/operator. The assistant can inspect read-only books and
logs and diagnose failures. It has not submitted, modified or canceled orders.

### ChatGPT IDE / Codex start-paused sequence

The persistent [Codex worker](../CODEX_COMPANION.md) is the selected neural
companion. The one-shot legacy watcher does not invoke it.

1. Check `python -m tools.codex_companion --check` and `--self-test`. Both are
   nontrading checks; no additional login is needed when they already pass.
2. For the **operator-controlled acceptance trial**, the operator sets
   `r01_policy.enabled=true` and `auto_trade_enabled=false` in
   `config/trading.json` **before starting a fresh scheduler**. Keep the approved
   risk fields intact. R01 is a startup policy; do not switch an existing legacy
   position to it. The checked-in/default working configuration remains R01-off
   until the operator performs this step.
3. Start `python -m tools.codex_companion` in one terminal. Start the documented
   Kite scheduler with `--ai-mode chat` in another. The operator performs this
   LIVE activation. Fresh controls are re-read by the entry cycle and immediately
   before BUY transport, including after broker pacing. While paused, no new
   candidate/model work or BUY is initiated; existing position management remains
   active. Missing/malformed control files block new entries.
4. After verifying the intended account, flat broker books, worker health and
   paused engine state, the operator changes `auto_trade_enabled=true` when ready
   to accept real exposure. A valid candidate must pass the actual neural
   consultation and all existing guards. If no candidate qualifies, remain in
   cash; do not manufacture a signal or bypass the gatekeeper.
5. After the first confirmed entry, the operator sets `auto_trade_enabled=false`
   again to prevent another entry. Keep both processes running while the engine
   manages protection and exits. Use engine-produced request/order references for
   acceptance. The CLI `--lots` flag is not an R01 hard sizing override; the
   approved capital/affordability model determines quantity.

`kill_switch=true`, `system_armed=false` or `auto_trade_enabled=false` blocks
new BUY submission. It does not cancel a BUY already transmitted. The pause
continues stop/exit management and is not proof of broker flatness. Stop or
restart the scheduler only after reconciling actual exposure and pending SELLs.

### Acceptance observations

1. Before any operator-controlled acceptance session, run:

   ```powershell
   python -m tools.brokers --broker kite
   python -m tools.verify_market_data --broker kite --timeout 45 --report .tools/tmp/kite-session-market-check.json
   ```

   Verify the intended account locally, complete books and no conflicting
   position/pending orders. Check current risk-source evidence as described in
   the validation record. Never interpret a failed read as a flat account.
2. In an operator-controlled broker acceptance environment, record a complete
   entry lifecycle: intended contract/account, requested versus actual filled
   quantity/price, matching protective SELL quantity and broker-confirmed stop
   trigger. An order ID alone does not establish execution or protection.
3. Record a confirmed protective-stop amendment and a reconciled exit. Confirm
   residual quantity after partial fills and that no orphan SELL remains when
   flat. Do not force market movement or deliberately expose capital to test a
   loss threshold; those risk/fault scenarios are covered offline.
4. Reconcile broker books and durable journal before any recovery start. Verify
   one local writer, preserved position policy and no duplicate BUY/SELL on
   restart. Stop the drill on an unknown acknowledgement or incomplete book;
   retain state and broker-side protection while resolving the discrepancy.
5. Confirm the 15:15 IST exit procedure and verify actual broker flatness. An
   exit request can fail or remain unfilled; retain an exposure incident until
   broker records prove closure.

Record timestamps, quantities, status transitions and nonsecret order references
locally. Share the result or let the assistant inspect the local records. Never
put session tokens or secrets in acceptance reports.

## Local startup and rollback record

- Retain the tested source fingerprint, current config and durable OMS state.
  Record the feature-branch repair commit after check-in. No separate deployment
  infrastructure is required for this local release.
- The default R01 setting stays disabled. A temporary operator-controlled R01
  trial uses the paused-start sequence above; ongoing LIVE use follows verified
  broker acceptance. All actual starts and real orders are operator actions.
- To stop new exposure, use the existing kill switch / new-entry controls.
  Continue managing existing broker protection. A process exit or PAPER toggle
  is not proof of flatness.
- Replace code/config only after reconciling active exposure. Preserve the
  journal and state; never delete them to clear a recovery block. An already
  stamped R01 position retains its frozen stop policy when new entries are
  disabled.

The remaining input needed from the owner is the operator-performed broker
acceptance result. No further risk-policy clarification is pending.
