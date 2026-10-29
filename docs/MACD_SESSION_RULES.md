# Strategy 5 session rules

The active `macd_momentum` profile uses deterministic entry filters and exit
rules. `rules` and `playbook` modes use **NO AI**; true neural AI evaluation is
only provided by the Antigravity companion in `chat` mode. Every candidate must
still pass the actual consultant. Vetoes, errors and consultation timeouts
preserve cash.

## Entry policy

- Use overlapping two-minute candles evaluated at every completed minute, with
  the complete current session available. Warm up MACD with the previous trading
  session's 60 closing minutes (14:30 through 15:29), resampled separately so
  overnight OHLC is never merged. Missing warmup blocks entries. Prior candles
  stay separate from today's VWAP, opening range, RSI and structural prices. Reject a fresh crossover if the absolute
  histogram is below 0.20 or its trigger candle opposes its direction. A doji
  passes this strategy's color check; the gatekeeper can apply stricter checks.
- Require finite positive Spot and session VWAP. Calls cannot be more than
  12 points below VWAP; puts cannot be more than 12 points above it. Reject
  absolute VWAP distance at or above 72 points throughout the session.
- Reject calls within 8 points below the opening-range high and puts within
  8 points above its low, inclusive. Use the completed 09:15–09:30 range;
  a breakout beyond the relevant boundary passes this filter. Entries activate
  at 09:30 IST; before 10:00, both trigger close and current Spot must be beyond
  the opening-range high for calls or below its low for puts. Merely testing
  inside the range cannot qualify. The optional later-start path uses
  `entry_start_time` with `early_orb_required: false`.
- During **11:30 <= IST time < 13:15**, reject a completed trailing 15-minute
  high/low range below 18 points. Calculate the range from candles. This is a
  Strategy 5 range condition, not a reinstatement of the deprecated blanket
  Trap 1 midday veto.
- Select strict ITM contracts, including one strike inside Spot at an exact ATM
  boundary. Missing, invalid, unaffordable or over-premium ITM contracts mean
  cash; this profile does not fall back to ATM/OTM contracts.
- Limit entries to two per day. `min_spacing_bars: 10` means ten completed
  **one-minute** bars after the first verified flat observation, following the
  repository's existing post-exit spacing convention. Broker stop creation
  time cannot establish when that stop filled. A scoped session ledger beside
  the position file (`*_entry_limits.json`) preserves this observation across
  restarts. Missing or corrupt evidence blocks entry. A restart without a ledger
  conservatively starts the cooldown when flatness is first verified.
- Preserve at least a 25-point adverse Spot invalidation buffer. Reject new
  entries at or after 14:15 IST, including at final order submission.

## Position policy

All windows use current IST time, with an inclusive start and exclusive end.
Peak gain is based on the position's verified peak executable bid. At session
transitions, existing desired, confirmed and companion stops remain floors;
stops never move down.

| Window | Activation and protection |
| --- | --- |
| 09:15–11:30 | +8% peak locks -8%; +12% locks +1%; +18% locks the greater of +10% and an 8% peak pullback |
| 11:30–13:15 | +5% peak locks the greater of +1.5% and a 2.5% peak pullback |
| 13:15 onward | +15% activation, 3.5% peak pullback, progressive floors; pullback stays at most 3.5% at +50% |

Stronger progressive and aggressive protection is preserved for large morning
and midday runners. New session settings are opt-in and do not activate for
other strategies. Session ratchets do not suppress configured structural exits.
Initial broker protection is 25%; the frozen post-fill refinement band remains
15–20%. Previously opened positions retain their frozen policy and tighter stops.
Square-off remains mandatory at 15:15 IST, including when quotes are stale.

The profile retains its step-ladder settings. Existing stricter account caps
still apply: the current trading configuration caps orders at one lot/65
contracts and the option premium at ₹135. These account limits were not raised.

## Verification and evidence limits

Run offline checks from the repository root:

```powershell
python -m tools.checks
python -m unittest test_self_healing_exit.py
python -m unittest tests.test_macd_session_rules tests.test_rolling_macd
python -m tools.replay_hybrid --session 2026-10-27 --output scratch/rolling_macd_review_20261027.json
```

The October 27 rolling decision replay completed with 285 one-minute
observations: 279 neutral decisions, five candidates approved by the actual
rules consultant, and one candidate blocked by missing exact option history.
These are observations, not executed trades: the review does not simulate
portfolio constraints, fills, executable quotes or PnL. Prior performance claims
in the enhancement blueprint have not been independently reproduced. Rolling
MACD periods advance every minute and therefore differ from stepped 2m periods.

Offline coverage includes both directions, completed/partial minutes, invalid
prices, gaps, calendar warmup, early ORB boundaries, VWAP isolation, synchronized
Spot/option evidence, session transitions, persisted floors, strict ITM selection
and restart-safe limits. Tests use fake broker transport and retain the real
consultant wherever entry approval is required.

Verification on October 29: all **451 offline regression tests passed**. Ruff
lint and runtime checks passed; Mypy passed for all 52 source files. The October
27 replay report is `scratch/rolling_macd_review_20261027.json`.

Read-only broker checks on October 29 were blocked: Kite profile verification
returned HTTP 403 and Breeze reported an unverified account. After-hours market
data verification stopped at the Kite profile check. No live engine was started;
broker readiness and actual prior-session data remain unverified.

The supplied `scratch/validate_fast_macd.py` is not an acceptance test for this
implementation: it independently reimplements strategy/exits, substitutes
synthetic option prices and assumes fills/sizing. Its profit statistics cannot
validate the production strategy. Use the production decision replay and offline
tests above; live execution and profitability have not been validated here.
