# ADR-006 — POL-06 V1: MACD swing → Companion approval → common stop manager

- **Owner decision:** 2026-10-29
- **Branch:** `refactor/r06-unified-macd-swing-stop-policy-20261029`
- **Status:** implemented for isolated review; **tests deliberately NOT RUN**; no Kite/Breeze orders or broker UAT, not merged.
- **Trading mode:** single local machine, existing Kite/Breeze sessions, `--live` explicitly required.

## Entry: two distinct authorities

1. Active `macd_momentum` computes a **completed** rolling-2m MACD (12,26,9). A fresh CE/PE cross or a continuation within **8 completed MACD observations** of the most recent cross is eligible for evaluation if the histogram still supports its original side. An opposite cross replaces the previous swing immediately. Nothing is inferred from an unsynchronized/incomplete bar.
2. Candidate must still have an observed spot swing invalidation, valid instrument, priced executable option quotes and broker margin. The existing bounded five-candle swing/high/low is used as the initial structural anchor. The level is persisted with the position; it is not shifted outward during a trade.
3. VWAP and EMA9/EMA20 alignment, VWAP extension, opening-range, candle shape and midday context are **consultation evidence** rather than mandatory directional vetoes in the active MACD entry profile. The existing deterministic mandatory quote, risk, cooldown, age and session safety checks are retained. Explicitly configured stricter legacy filter flags still retain their old opt-in behavior.
4. `ai_consultation.default_mode=chat` remains. **A LIVE entry in any strategy requires actual Chat Companion `chat` mode.** Deterministic `playbook` and `interactive` modes cannot place LIVE entries under this policy. `EntryWorkflow` calls `AIConsultant.evaluate`, and only a timely, valid APPROVED verdict with all broker/risk checks can BUY. The candidate rationale is appended to the dossier as clearly labeled *nonapproval evidence*. A companion's response **cannot override** hard limits or preflight.
5. If the companion, quote, metadata, expiry or risk evaluation is unavailable/invalid, remain out of the market. Companion review can delay entry; the final quote and invalidation check must be repeated right before order submission.

## Shared stop policy

Every **new** position carries `exit_policy_version=POL06_V1` and `option_right=CE|PE`. This version triggers the common pure `trading/domain/unified_exit.py` decision functions via `PositionMonitor._manage_shared_policy`, irrespective of entry strategy. Legacy already-open positions retain their existing stored stop floors and older monitor semantics. The broker-side initial stop targets **20% below verified average filled premium** for new POL06 positions, while all previously tighter confirmed floors must only tighten. A hard premium stop does NOT guarantee fill or loss amount.

**Hybrid structural exit**: independent of AI, use either (a) the *latest completed one-minute candle close* on the adverse side of the frozen spot invalidation, or (b) **two distinct fresh provider-timestamped spot observations** exceeding the level by at least `max(5 NIFTY points, 0.5 × ATR(14) on completed 1m bars)`. Stale/missing candles or snapshot timestamps cannot count as independent observations; the verified premium stop remains active. Spot observations are read during the existing 5s active monitor cadence, not from an invented high-frequency feed.

**Profit protection is premium-bid based**, not NIFTY spot percentage and not underlying index LTP. These are first-review parameters, subject to offline replay:

| Time IST | Activation at peak bid gain | Floor / trailing |
| --- | --- | --- |
| 09:15–11:30 | +5%, +10%, +15% | Entry −8%, entry +1%, then max(entry +10%, peak bid −8%) |
| 11:30–13:15 | +5% | max(entry +3%, peak bid −3.5%) |
| 13:15–15:15 | +15% | max(entry +10%, peak bid −3.5%) |
| 14:00–15:15 (additional) | +4% | at least entry +1% |
| Any session | +20%, +30%, +40% | protect at least +10%, +20%, +30% respectively |
| Any session | +50% | max(already protected floors, peak bid −3.5%) |

`max(stored_floor, shared_floor, initial premium safety floor)` determines the candidate stop. The OMS still owns STOP acknowledgement, partial-fill adjustment, replace/cancel safety, stale-quote handling, position reconciliation and mandatory 15:15 square-off. A session change may never loosen a broker-confirmed stop. Structural and premium-loss exits do not wait for another Chat Companion verdict.

## Compatibility, assumptions and remaining release work

- The legacy separate 6-minute scalper hold timer and old local take-profit limits **do not apply to new POL06 positions**. Older positions continue under the previous policy.
- The central `config/strategies.json` entry mode is still `macd_momentum`. Other explicitly selected signal profiles remain available, but all **new** positions share the new exit policy and actual Chat Companion gate.
- Early decisive exits require actual source quote timestamps, not inferred receipt times. If the connected snapshot lacks timestamps, one-minute candle confirmation provides the valid structural path. Validate broker snapshot payload shapes before deployment.
- These values are candidate numbers chosen by discussion. Profit-lock percentages do not guarantee realizable profits; spread, gaps and latency can overshoot them.
- **Known acceptance gap:** source-only syntax checks are not sufficient. The unexecuted old session/strategy tests include legacy hard-filter expectations and need careful parity review. Run the full suite, mock Chat Companion, native gateway stop races, crash recovery and retrospective replay before merging, then supervised broker UAT. Test trade sizing, ₹5k circuit breaker, stale broker session and 15:15 exit behavior.
- No change to LIVE arming, Kite/Breeze authentication, AI approval semantics, broker order payloads, stop price bands or lot ladder outside the explicitly described policy changes.
