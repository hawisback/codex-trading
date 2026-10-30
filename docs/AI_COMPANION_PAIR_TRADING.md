# Neural companion pair-trading architecture and runbook

> **Current branch (2026-10-30):** The selected companion is the persistent Codex worker in ChatGPT IDE. It explicitly invokes the installed CLI and stays armed for both request types; see [current Codex guide](CODEX_COMPANION.md). Offline tests and a nontradable CLI canary pass. Actual Kite order acceptance remains pending; no worker or LIVE scheduler was left running by implementation checks.
>
> New R01 positions retain the unified 25% initial stop authority and do not request competing legacy post-fill refinements. The two-step stop-refinement flow below applies only to eligible legacy positions. All requests use current frozen/authoritative policy, original deadlines and application-owned publication.
>
> **Execution mode:** `--ai-mode chat`. Rules/playbook is deterministic, with no neural AI.

---

## 1. Operational Overview & Two-Step Architecture

### The Dilemma of Monolithic Pre-Trade Stop Loss
Previously, attempting to calculate refined technical stop losses before order execution caused execution delays and price slippage, or relied on rigid hardcoded heuristics (such as heavyweight breadth flickers) that triggered premature shakeouts during normal 1-minute liquidity pullbacks.

### The Solution: Two-Step AI Stop-Loss Architecture
Per user directive, order execution and refined risk management are separated into a clean **two-step workflow**:

```mermaid
sequenceDiagram
    participant S as Nifty Trading Scheduler
    participant W as Persistent Codex Worker
    participant A as Codex Neural Companion
    participant OMS as Broker OMS Execution (Kite/Breeze)

    Note over S: STEP 1: FAST ENTRY EXECUTION
    S->>S: Completed 2m MACD crossover; EMAs advisory; attach selected strike 2m MACD
    S->>W: Writes logs/pending_consultation.json
    W-->>A: Reactive wake-up triggered (< 1 sec)
    A->>S: Writes entry verdict (APPROVED / VETOED)
    S->>OMS: Places BUY LIMIT order -> FILLED at market price
    OMS->>OMS: Arms resting initial safety stop (25% initial safety floor)

    Note over S: STEP 2: POST-FILL AI STOP-LOSS CONSULTATION
    S->>W: Publishes logs/pending_stop_loss.json with exact fill price & spot wicks
    W-->>A: Reactive wake-up triggered (< 1 sec)
    Note over A: Evaluates exact fill price, Spot wicks & candle structure
    A->>S: Writes logs/ai_stop_verdict.json (ai_stop_price, spot_invalidation)
    S->>OMS: Ratchets broker stop order to AI's refined level via StopManager.ratchet()
    S->>S: Enforces Spot invalidation level in 5-second PositionMonitor
```

### Key Principles of the Two-Step Architecture:
1. **Bounded Entry:** After companion approval, fresh quotes, identity, purchasing power and the approved price band are rechecked before order submission. Slippage is bounded, not guaranteed to be zero.
2. **Zero Naked Risk:** A hard default floor (25% initial safety stop) is placed directly at the broker exchange immediately upon entry fill. Protection is confirmed at the broker; failure to confirm protection triggers the existing risk-exit workflow.
3. **Exact Context for Stop Calculation:** The AI companion knows the *exact* broker execution price (e.g. ₹82.12) and the exact candle low/high at the moment of entry.
4. **Asynchronous & Non-Blocking:** Position monitoring runs continuously every 5 seconds. The scheduler never blocks or pauses while waiting for the AI stop-loss verdict.
5. **No Unannounced Rules:** No arbitrary, unannounced heuristics (like tick breadth panic exits). All risk parameters are explicitly set by the AI Companion or deterministic technical structures.

---

## 2. Verdict & Stop-Loss Payload Specifications

### Entry Verdict (`logs/ai_verdict.json`)
The evaluation parser in `ai_consultant.py` natively supports both `action` and `verdict`:
```json
{
  "request_id": "<request_id from the active pending_consultation.json>",
  "candidate_id": "<candidate_id from that same request>",
  "action": "APPROVED",
  "confidence": 88,
  "reason": "Reviewed current rules, macro/sector cues and the selected contract book.",
  "trailing": "runner_ema9",
  "submitted_at": "<current ISO timestamp with timezone>"
}
```

Use `python ai_consultant.py --approve --request-id <REQUEST_ID> --reason "..."`
or `--veto` for the explicit current request. The CLI binds the candidate ID
and publishes atomically. Bare, old, unbound, future-dated or expired responses
cannot approve an entry. Any explicit veto or trap dominates conflicting
approval aliases. Approval lifetime is bounded by submission time and the
consultation deadline.

The batch publishes Markdown first and JSON last, then waits for the neural companion.
The companion must read `config/rules_playbook.md` and enforce its risk rules
before returning its judgment. Missing or invalid responses preserve cash;
chat mode never substitutes a rules verdict for the companion.

Chat dossiers include a fresh, validated snapshot of the selected contract's
bid/ask prices, quantities, available depth and quantity imbalance, plus option
chain OI context. The dossier distinguishes executable depth from positioning.
Missing, stale or mismatched quotes block consultation/execution. Quotes are
checked again after approval; the dossier book is not reused for order pricing.


### Post-Fill Stop-Loss Verdict (`logs/ai_stop_verdict.json`)
Written by the AI Companion or via the CLI helper `python ai_consultant.py --set-sl <PRICE> --invalidation <SPOT> --request-id <REQUEST_ID>`:
```json
{
  "request_id": "<request_id from the current stop dossier>",
  "trade_id": "<trade_id from the current stop dossier>",
  "ai_stop_price": 68.50,
  "spot_invalidation_level": 22608.0,
  "trailing_style": "standard",
  "reasoning": "Technical stop placed below trigger candle low (22,608 Spot). Option risk capped at ₹68.50 (-16.5%).",
  "submitted_at": "2026-10-26T13:43:20+05:30"
}
```

Stop verdicts must match the pending request and trade, include a timezone-aware submission time, and arrive before the configured consultation deadline. The CLI validates these fields and publishes the verdict atomically. Unbound, expired, or malformed responses leave existing broker protection in place.

The trigger candle context is frozen with the entry decision and persisted with the position. For the hybrid policy, observed Spot is updated from the final validated pre-submit Spot quote; its timestamp is retained. The stop dossier identifies its observation time and source; recovered positions without an entry snapshot use the first complete monitoring snapshot. Missing technical data defers consultation without inventing Spot or wick levels.

An accepted stop first enters `APPLYING`. It becomes `ARMED` only when the broker confirms protective coverage at or above the requested option floor. Position monitoring continues if consultation publication or ingestion fails.

---

## 3. Capital & Purchasing Power Constraints

### Broker-Verified Purchasing Power
Sizing is recalculated from available broker margin for every candidate using
the configured 2/4/6/8/10-lot milestones, capped at 650 contracts and by
`(available_margin - 150) // (premium * 65)`. A milestone target can be reduced
when purchasing power cannot fund it. Drawdowns automatically reduce sizing.

The legacy premium cap is **135.0**; opted-in R01 disables arbitrary price-only bands while preserving affordability and quote checks. Quote revalidation, order limits and the
?150 purchasing-power buffer remain mandatory before submission.

---

## 4. ChatGPT IDE / Codex launch

Use the [current Codex worker guide](CODEX_COMPANION.md) and [start-paused operator acceptance procedure](operations/KITE_LOCAL_ACCEPTANCE_20261030.md).

```powershell
python -m tools.codex_companion --check
python -m tools.codex_companion --self-test
python -m tools.codex_companion
```

The first two commands do not consume the live inbox or place orders. The third stays armed for entry and legacy stop requests. It does not continue the visible IDE conversation; it invokes the installed Codex CLI using the local ChatGPT login. Application code validates and publishes all responses. The legacy one-shot watcher remains available for manual notifications only.

The operator starts the Kite scheduler separately, initially with new entries paused and the approved trial policy loaded. The application re-reads operator entry controls before candidate discovery and at the actual BUY boundary, while continuing existing stop/exit management. Do not use a one-cycle run for an acceptance session that may create exposure.

## Path A candles and reversal protection

Strategy 5 uses completed rolling 2-minute candles evaluated every minute,
with the previous trading session's last 60 minutes warming up MACD. Every
trigger requires two contiguous completed minutes within today's session.
Prior candles remain separate from today's VWAP and opening range. Entries
activate at 09:30, with an OR breakout required before 10:00. Missing,
duplicate, unordered or stale timestamps block the signal. A doji is not an
aligned directional trigger for the Trap 7 reversal exception. The Strategy 5 candle-color filter alone permits a doji.

For `MACD_2M_MOMENTUM` with a valid swing invalidation, VWAP/EMA reference exits
arm only after spot has reclaimed the corresponding reference in the trade's
direction. The latches are persisted and survive restart. A reversal therefore
is not liquidated merely because it starts on the far side of VWAP. The initial
broker stop, spot swing invalidation, option floors, timeout handling and 15:15
square-off remain active. Morning and midday use the session-specific ratchets in
[MACD session rules](MACD_SESSION_RULES.md). The afternoon runner activates at
+15% and uses a 3.5% peak pullback; +50% cannot loosen this stop. Initial protection is 25%.

## Historical comparison limitations

`scratch/compare_paradigms.py` is a deterministic rules comparison: **NO AI**.
Its corrected data path requires an adjacent `opt_YYYYMMDD_STRIKE_RIGHT.meta.json`
with `session`, `expiry`, `strike`, `right`, and broker `symbol`. The fetch helper
writes these facts only when fetching the actual contract. Do not invent metadata
for old files whose identity cannot be verified.

Candidates use exact contract and timestamp matches; missing data is excluded
without a synthetic pricing fallback. Estimated entry is the next minute open;
existing stops are evaluated before a new minute high raises the next minute's
ratchet. Gaps use the worse open. OHLC cannot establish executable bid/ask fills,
stop-limit fill probability, live companion judgments, or intrabar ordering.
The comparison uses a limited OHLC risk model and approximate fees, not the full
live context and post-fill companion stop workflow. Previous profit/ROI/win-rate
claims are unverified and must not be carried forward as validated results.


## Spot / selected strike MACD confluence and frozen risk bounds

The active profile requires completed 2m MACD(12,26,9) crossovers.
`entry.require_ema_confirmation` and `entry.require_ema20_trend_alignment` are
both `false`: EMA9 proximity and EMA20 trade-side alignment no longer veto a
candidate before consultation. The completed 5m EMA values remain calculated
and included in the dossier. Existing institutional trap checks remain active;
relaxing these two strategy flags does not disable the mandatory gatekeeper.

The dossier's **Strike Premium Momentum (Option MACD)** section includes
`strike_macd_line`, `strike_signal_line`, `strike_histogram`, previous histogram,
positive-expansion flag and `strike_momentum_status`. The market-data adapter
resolves the selected contract to its exact instrument-master token, reads
Kite's native 1m option history and resamples complete, contiguous pairs anchored
within each session. Spot and premium use the same completed-minute cutoff,
rolling 2m sampling and MACD(12,26,9). Each uses the prior session's last 60
minutes for indicator warmup; overnight OHLC is never combined. Forming candles are
excluded. Missing, stale, gapped or mismatched history is explicitly unavailable;
it is never replaced with Spot or zero-valued MACD. Native option minute history
currently requires Kite as the market-data source; Breeze data reports this
context unavailable. The execution broker can still be Kite or Breeze.

In **chat mode**, the explicitly invoked neural companion evaluates confluence:

- Spot bullish (2m MACD above signal) plus selected CE histogram positive and
  increasing supports a **high-conviction BUY_CE candidate**, subject to all
  remaining traps, account constraints and the companion's explicit verdict.
- Spot bullish but selected CE momentum lagging/negative requires assessment
  of premium absorption versus decay using momentum, book/spread, OI, expiry
  and macro context. MACD alone cannot establish absorption or decay.
- For BUY_PE, bearish Spot should align with a strengthening purchased put:
  the PE premium histogram should expand **positive**, not negative.
- Missing strike evidence cannot establish confluence. State the uncertainty
  and veto if it cannot be resolved. EMA proximity/alignment remain advisory;
  the companion must not reinstate them as unconditional entry vetoes.

This rubric is published in both pending consultation JSON and Markdown.
Confluence is guidance for the Neural LLM, not an automatic approval rule.
`rules` / `playbook` modes remain deterministic (**NO AI**). Evaluation errors
and consultation timeouts preserve cash; all explicit vetoes remain binding.

Initial broker protection is **25%**. `exit.post_fill_stop_loss` explicitly sets
`min_loss_pct: 15` and `max_loss_pct: 20`. The policy and trigger structure are
persisted with the position. The companion chooses a technical stop inside that
band; the engine does not substitute a rules decision in chat mode. The stop
request publishes the allowed exchange-tick price range and structural limit.
Both CLI submission and file ingestion validate those frozen bounds.

A hybrid structural invalidation must remain at least **25 Spot points** from
the final observed entry Spot, in the adverse direction. The entry is blocked
if the last pre-submit quote makes the approved buffer too small. A post-fill
response cannot move the invalidation back inside that buffer. Invalid
responses leave the existing broker stop intact and are retried until timeout;
expiry retains baseline protection. Existing tighter broker, profit and legacy
structural floors are preserved rather than loosened to fit a new loss band.
EMA exits, option floors, runner trailing and mandatory square-off remain active.
The minimum buffer applies to structural invalidation, not a minimum holding
period or a promise that no other risk exit can occur sooner.

For causal historical decision review, use:

```powershell
python -m tools.replay_hybrid --session 2026-10-27 --output .tools/hybrid_replay.json
```

This tool uses the actual hybrid strategy, closed 5m candles with 50-bar warmup,
verified option contract identity/timestamps, and the actual deterministic
consultant (`rules`, **NO AI**). Missing warmup, option evidence, or context is
reported explicitly. It does not invent post-fill companion responses, fills,
PnL, ROI, or win rates. The former hybrid scratch simulation entry points now
route to this review tool. Broker/news readiness and live companion response
handling must still be verified in the live operating environment.
