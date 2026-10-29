# 🚀 Architecture Blueprint: Rolling 2m MACD & Prior-Day Warmup Engine

> **Document Status:** Complete Architecture & Implementation Blueprint  
> **Target Strategy:** Strategy 5 (Fast 2m MACD Momentum)  
> **Alignment:** 100% compliant with Charter Rule #1 (Deterministic Rules / Gatekeeper), Rule #2 (Workspace Isolation), and Rule #3 (Step-Ladder Compounding).

---

## Implementation review — 2026-10-29

Implemented rolling sampling, cached prior-session warmup, Path A's 09:30
activation/early ORB filter, and the explicitly listed Part 4 trailing values.
The prior morning floors (-8%, +1%, +10%) and 8% morning runner pullback remain.
Afternoon pullback is 3.5%; the aggressive pullback is capped at 3.5% as well
so crossing +50% cannot loosen it. Existing tighter stops remain binding.

The performance matrix below is supplied research, not independently reproduced
production performance. Rolling MACD(12,26,9) advances each minute, changing its
indicator horizon relative to stepped 2m MACD. No profitability claim is verified.

Implementation corrections: reject gaps and forming minutes; never pair across
sessions; keep prior warmup separate from today's VWAP/OR/RSI data; require a
confirmed breakout beyond OR high/low before 10:00 rather than an inside-range
test that conflicts with the resistance/support veto. The 60 prior minutes are
14:30 through 15:29 inclusive, closing at 15:30. Weekends and configured exchange
holidays are excluded; missing prior-session data blocks entries.

Existing `macd_fast/macd_slow/macd_signal` keys remain canonical; the example's
`fast_period/slow_period/signal_period` aliases are supported and conflicting
values are rejected. `prior_session_warmup_enabled: true` explicitly enables the
new data dependency. The same sampling and observation cutoff are used for Spot,
selected option evidence and decision replay. Existing closed 5m EMA warmup remains.

Verification: all 451 offline regression tests passed, along with Ruff lint,
runtime checks and Mypy (52 source files). October 27's decision replay completed
with 285 one-minute observations; this does not establish fills or profitability.

See [current session rules and verification](MACD_SESSION_RULES.md). Read-only
broker checks were attempted: Kite profile verification returned HTTP 403 and
Breeze remained unverified. Broker readiness is not established; no live engine
was started.

---

## Executive Summary

This blueprint defines the next generation enhancements for Strategy 5 (Fast 2m MACD Momentum), incorporating the two specific architectural upgrades proposed by the trader:
1. **Rolling 2-Minute Candle Resampling (Every Minute):** Instead of waiting 2 full minutes for stepped, fixed clock boundaries (`[0,1], [2,3], [4,5]`), the engine evaluates a sliding 2-minute window `[candles[i-1], candles[i]]` at the close of **every single minute**.
2. **Prior-Day Session Warmup (09:30 AM Entry Activation):** Pre-loading the final 60 one-minute candles from the prior trading day at engine startup. This completely eliminates the 54-minute cold-start indicator lag, unlocking high-probability morning momentum trades starting from **09:30 AM** (once the 15-minute Opening Range settles).

---

## 🔬 Empirical Backtest Matrix (Audited Across All 30 Sessions)

All variations were audited against the complete 30-session institutional dataset (September 15 – October 28, 2026), incorporating broker STT/slippage and the step-ladder compounding model:

| Configuration | Start Time | Total Trades | Win Rate % | Profit Factor | Net PnL (Fixed 2 Lots) | Compounded Capital (₹10k Start) |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| **Baseline Current Code (Stepped 2m, No Warmup)** | 10:09 AM | 32 | 75.0% | 1.61 | **+₹10,113.20** | ₹16,668.20 (+66.7%) |
| **Rolling 2m Alone (No Warmup)** | 10:09 AM | 20 | **80.0%** | **3.81** | **+₹16,012.58** | ₹19,842.10 (+98.4%) |
| **Stepped 2m + Warmup (Unfiltered Early)** | 09:30 AM | 42 | 57.1% | 0.72 | -₹8,953.82 | ₹7,140.20 (-28.6%) |
| **Rolling 2m + Warmup (Unfiltered Early)** | 09:30 AM | 31 | 67.7% | 1.17 | +₹3,307.08 | ₹12,410.50 (+24.1%) |
| **Rolling 2m + Warmup + ORB Breakout Rule (<10:00)** | **09:30 AM** | **34** | **67.6%** | **1.72** | **+₹13,750.87** | **₹17,987.97 (+79.9%)** |
| **Rolling 2m + Warmup (Clean Start at 09:50 AM)** | 09:50 AM | 27 | 74.1% | 1.85 | +₹11,261.88 | ₹17,120.40 (+71.2%) |
| **Rolling 2m + Warmup (Clean Start at 09:55 AM)** | 09:55 AM | 23 | **78.3%** | **3.30** | **+₹17,292.68** | **₹20,415.80 (+104.2%)** |

---

## 💡 Key Architectural Insights

### 1. Why Rolling 2m Drastically Improves Performance
- **Stepped Bars Flaw:** Stepped bars group minutes as `(0-1), (2-3), (4-5), (6-7), (8-9)`. If momentum starts turning at minute 8, the engine is blind until minute 9 completes. By minute 9, option premiums have already expanded 10%–15%, destroying the entry risk-reward ratio.
- **Rolling Window Advantage:** By evaluating `[candles[i-1], candles[i]]` every minute, the engine detects MACD histogram expansion on the exact minute it crosses. In backtesting, rolling 2m alone boosted win rate from **74.3% to 80.0%** and vaulted the Profit Factor from **1.97 to 3.81**!

### 2. The Early Morning (09:30 – 10:00 AM) Discovery
- Pre-loading prior-day candles enables MACD calculation at 09:15 AM.
- However, between 09:15 and 09:30 AM, the market builds the 15-minute Opening Range (OR).
- **The Pitfall of Unfiltered 09:30 AM Entries:** On days with wide opening candles (80–140 pts, e.g. Oct 07, Oct 14, Oct 22), taking trades inside the opening range resulted in whipsaws (5 early losses).
- **The Two Safe Implementation Paths:**
  - **Path A (Early ORB Filter):** Allow entries from 09:30 AM, but between 09:30 and 10:00 AM, require spot to be actively breaking or testing the Opening Range High (for CE) or Opening Range Low (for PE). This yields **+₹13,750.87** net PnL with **PF 1.72**.
  - **Path B (09:50 AM Clean Activation):** Maintain the 60-bar warmup so MACD is completely settled, but begin trade evaluations at **09:50 AM**. This avoids the initial 35-minute noise completely and yields **+₹11,261 to +₹17,292** net PnL with **PF 3.30** and **78.3% Win Rate**!

---

## 🛠️ Step-by-Step Implementation Blueprint

### Part 1: Rolling 2-Minute Resampling Function
**Location:** [`trading/strategies/macd_momentum.py`](file:///c:/Users/hawis/Documents/antigravity/splendid-bardeen/trading/strategies/macd_momentum.py)

Replace or supplement `resample_1m_to_2m` with `resample_1m_to_rolling_2m`:

```python
def resample_1m_to_rolling_2m(candles: List[Dict]) -> List[Dict]:
    """
    Construct continuous rolling 2-minute candles evaluated at every minute.
    Each bar i combines candles[i-1] and candles[i].
    
    Attributes of rolling bar:
      - open: candles[i-1]["open"]
      - high: max(candles[i-1]["high"], candles[i]["high"])
      - low: min(candles[i-1]["low"], candles[i]["low"])
      - close: candles[i]["close"]
      - volume: candles[i-1]["volume"] + candles[i]["volume"]
    """
    if len(candles) < 2:
        return []
    
    bars = []
    for i in range(1, len(candles)):
        c0 = candles[i - 1]
        c1 = candles[i]
        bars.append({
            "start_time": c0["start_time"],
            "end_time": c1["start_time"],
            "minute_idx": i,
            "open": c0["open"],
            "high": max(c0["high"], c1["high"]),
            "low": min(c0["low"], c1["low"]),
            "close": c1["close"],
            "volume": c0.get("volume", 0) + c1.get("volume", 0),
        })
    return bars
```

### Part 2: Prior-Day Warmup Data Pipeline
**Location:** [`nifty_trader_scheduler.py`](file:///c:/Users/hawis/Documents/antigravity/splendid-bardeen/nifty_trader_scheduler.py) & [`trading/application/`](file:///c:/Users/hawis/Documents/antigravity/splendid-bardeen/trading/application/)

1. **Pre-Market Ingestion (09:00 - 09:15 IST):**
   - Query broker API (Kite / Breeze) for the previous trading day's last 60 1-minute spot candles (14:30 to 15:30 IST).
   - Cache these candles in memory as `self.prior_session_warmup_candles = [...]`.
2. **Context Assembly:**
   - In the scheduler's context assembly, attach `prior_session_warmup_candles` separately. Prepend its resampled observations only to MACD indicator input; keep `candles_1m` strictly current-session.
   - **Crucial Invariant:** Today's **Session VWAP** must strictly calculate from `candles_1m` belonging to today (starting at 09:15 IST). Prior-day candles are used **ONLY** for MACD and EMA indicator warmup, never for today's VWAP!

### Part 3: Strategy Parameter Updates
**Location:** [`config/strategies.json`](file:///c:/Users/hawis/Documents/antigravity/splendid-bardeen/config/strategies.json)

Update the `macd_momentum` entry configuration:

```json
{
  "strategies": {
    "macd_momentum": {
      "entry": {
        "fast_period": 12,
        "slow_period": 26,
        "signal_period": 9,
        "use_rolling_2m": true,
        "prior_session_warmup_enabled": true,
        "entry_start_time": "09:30",
        "early_orb_required": true,
        "early_orb_cutoff_time": "10:00",
        "require_candle_alignment": true,
        "require_vwap_alignment": true,
        "vwap_tolerance_pts": 12.0,
        "vwap_climax_pts": 72.0,
        "opening_range_filter_enabled": true,
        "opening_range_buffer_pts": 8.0,
        "min_invalidation_buffer_pts": 25.0,
        "min_hist_threshold": 0.20,
        "midday_dead_zone_filter": {
          "enabled": true,
          "start_minute": 135,
          "end_minute": 240,
          "min_15m_range_pts": 18.0
        },
        "strike_selection": "STRICT_ITM",
        "max_daily_entries": 2,
        "min_spacing_bars": 10
      }
    }
  }
}
```

### Part 4: Trailing Ratchets & Risk Controls (Preserved Intact)
All existing session-specific trailing controls remain fully active:
- **Morning (09:15 – 11:30):** 3-Tier Progressive Trailing (Soft-SL at +5%, Breakeven at +10%, Runner Lock at +15%).
- **Midday (11:30 – 13:15):** 5% Micro-Trailing Ratchet (Locks +3% floor at +5% gain; 1.5% trailing thereafter).
- **Afternoon (13:15 – 14:15):** Dynamic Runner Ratchet (Activates at +15%, trails by 3.5%).
- **Hard Guardrails:** 14:15 Hard Entry Cutoff, 15:15 Mandatory Broker Square-off, Max 1 Concurrent Position, Max 2 Trades/Day.

---

## 📋 Comprehensive Verification Checklist

Before deploying live:
- [x] **Unit Tests:** Rolling, gap, boundary, warmup, early-ORB and synchronization cases in `tests/test_rolling_macd.py`.
- [x] **VWAP Isolation Test:** Verify session VWAP, box and RSI ignore prior-day warmup candles.
- [x] **Replay Verification:** October 27 production decision replay completed at one-minute cadence; this is not a portfolio/fill/PnL validation.
- [ ] **Broker Pre-Flight:** Commands attempted; blocked by Kite HTTP 403/profile verification and unverified Breeze account. Rerun after broker session verification succeeds.
