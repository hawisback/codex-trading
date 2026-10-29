#!/usr/bin/env python3
"""
Backtest Replay for Today (2026-10-15): Pre-Patch Bug vs. Post-Patch Fix
Evaluates Strategy 3 (Institutional Pullback & ITM) across 1-minute microstructure
from 09:15 to 11:05+ IST.
"""

import os
import sys
import json
import math
import urllib.request
from datetime import datetime, timezone, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

IST = timezone(timedelta(hours=5, minutes=30))

def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bsm_price(spot: float, strike: float, days_to_expiry: float,
              r: float = 0.065, sigma: float = 0.135, is_call: bool = True) -> float:
    """Black-Scholes option pricing model calibrated for NIFTY weekly options."""
    T = max(0.0001, days_to_expiry / 365.0)
    if T <= 0.0002:
        return max(0.05, (spot - strike) if is_call else (strike - spot))
    d1 = (math.log(spot / strike) + (r + 0.5 * (sigma ** 2)) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        price = spot * norm_cdf(d1) - strike * math.exp(-r * T) * norm_cdf(d2)
    else:
        price = strike * math.exp(-r * T) * norm_cdf(-d2) - spot * norm_cdf(-d1)
    return max(0.05, round(price, 2))

def fetch(path):
    url = f"http://127.0.0.1:8000/api/v1/ai{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "BacktestScript"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())

def calculate_ema_sequence(prices, period):
    """Calculates EMA iteratively across a price sequence."""
    if not prices:
        return 0.0
    if len(prices) < period:
        # Pre-patch buggy behavior: if less than period, return last price
        return prices[-1]
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 2)

def calculate_ema_continuous(history_prices, period):
    """Calculates continuous EMA using all available historical bars."""
    if not history_prices:
        return 0.0
    k = 2.0 / (period + 1)
    ema = history_prices[0]
    for p in history_prices[1:]:
        ema = p * k + ema * (1 - k)
    return round(ema, 2)

def calculate_rsi(prices, period=14):
    if len(prices) <= period:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent_gains = [max(0.0, d) for d in deltas[-period:]]
    recent_losses = [max(0.0, -d) for d in deltas[-period:]]
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 1)

def run_backtest(mode="POST_PATCH"):
    print("\n" + "=" * 105)
    print(f"RUNNING TODAY'S BACKTEST REPLAY: {mode}")
    print("=" * 105)

    # 1. Ingest Data
    c1m_resp = fetch("/nifty/candles?interval=1m&limit=500")
    c5m_resp = fetch("/nifty/candles?interval=5m&limit=100")

    all_1m = c1m_resp.get("candles", [])
    all_5m = c5m_resp.get("candles", [])

    # Filter today's 1m candles (starts with 2026-10-15)
    today_1m = []
    for c in all_1m:
        st = c.get("start_time", "")
        dt_utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        if dt_ist.strftime("%Y-%m-%d") == "2026-10-15":
            c_copy = dict(c)
            c_copy["ist_dt"] = dt_ist
            c_copy["time_str"] = dt_ist.strftime("%H:%M")
            today_1m.append(c_copy)

    # Split 5m candles into historical (prior to today) and today
    prev_5m_closes = []
    for c in all_5m:
        st = c.get("start_time", "")
        dt_utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        if dt_ist.strftime("%Y-%m-%d") < "2026-10-15":
            prev_5m_closes.append(c["close"])

    print(f"Loaded {len(today_1m)} 1-minute candles for today ({today_1m[0]['time_str']} to {today_1m[-1]['time_str']} IST).")
    print(f"Loaded {len(prev_5m_closes)} prior 5-minute closing bars for EMA seeding.")

    # Simulation State
    spot_prices = []
    spot_typicals = []
    trades = []
    active_trade = None
    last_exit_idx = -999

    # Days to expiry for today (Thursday, weekly expiry is typically today or next week)
    days_to_expiry = 4.0 # Calibrated to current option cycle

    # Bar-by-bar simulation
    print("\nTracing key evaluation bars...")
    for idx, bar in enumerate(today_1m):
        spot = bar["close"]
        high = bar["high"]
        low = bar["low"]
        time_str = bar["time_str"]

        spot_prices.append(spot)
        spot_typicals.append((high + low + spot) / 3.0)

        # Intraday Spot Session VWAP (strictly Spot Index)
        session_vwap = round(sum(spot_typicals) / len(spot_typicals), 2)

        # 5m Bars aggregation so far today
        # Every 5 1-minute bars forms a completed 5m bar
        today_completed_5m_closes = [spot_prices[i] for i in range(4, len(spot_prices), 5)]
        
        # Calculate 5m EMA9 and EMA20 based on mode
        if mode == "PRE_PATCH_BUG":
            # The bug: only today's completed 5m bars without seeding
            # If < 9 or < 20 bars, returns prices[-1] -> ema9 == ema20
            if not today_completed_5m_closes:
                today_completed_5m_closes = [spot]
            ema9 = calculate_ema_sequence(today_completed_5m_closes, 9)
            ema20 = calculate_ema_sequence(today_completed_5m_closes, 20)
        else:
            # Post-patch: continuous EMA seeded with previous days' 5m closes
            full_5m_closes = prev_5m_closes + today_completed_5m_closes
            ema9 = calculate_ema_continuous(full_5m_closes, 9)
            ema20 = calculate_ema_continuous(full_5m_closes, 20)

        rsi = calculate_rsi(spot_prices, 14)

        # 15m Consolidation Box
        recent_15m = today_1m[max(0, idx - 14): idx + 1]
        box_high = max(c["high"] for c in recent_15m)
        box_low = min(c["low"] for c in recent_15m)
        box_spread = round(box_high - box_low, 2)
        is_box = box_spread < 28.0 and len(recent_15m) >= 10

        # Check Active Position
        if active_trade is not None:
            # Option pricing at this bar
            days_rem = max(0.001, days_to_expiry - (idx / 375.0) * 0.25)
            opt_c = bsm_price(spot, active_trade["strike"], days_rem, is_call=(active_trade["direction"] == "CE"))
            opt_h = bsm_price(high, active_trade["strike"], days_rem, is_call=(active_trade["direction"] == "CE"))
            opt_l = bsm_price(low, active_trade["strike"], days_rem, is_call=(active_trade["direction"] == "CE"))

            if opt_h > active_trade["peak_price"]:
                active_trade["peak_price"] = opt_h
                active_trade["peak_gain_pct"] = round(((opt_h - active_trade["entry_price"]) / active_trade["entry_price"]) * 100, 2)

            exit_reason = None
            exit_price = opt_c

            # 1. Stop Loss (-30%)
            if opt_l <= active_trade["entry_price"] * 0.70:
                exit_reason = "INITIAL_STOP (-30%)"
                exit_price = round(active_trade["entry_price"] * 0.70, 2)

            # 2. Profit Target Cap (+50%)
            elif opt_h >= active_trade["entry_price"] * 1.50:
                # In Strategy 3, if runner trailing is enabled, we allow runners past 50%
                pass

            # 3. Dynamic Trailing Runner (Active once peak >= +15%)
            if active_trade["peak_gain_pct"] >= 15.0 and not exit_reason:
                floor_pct = 10.0
                if active_trade["peak_gain_pct"] >= 40.0:
                    floor_pct = 30.0
                elif active_trade["peak_gain_pct"] >= 30.0:
                    floor_pct = 20.0
                floor_price = active_trade["entry_price"] * (1.0 + floor_pct / 100.0)
                trail_stop = max(floor_price, active_trade["peak_price"] * 0.90)

                if opt_c <= trail_stop:
                    exit_reason = f"TRAILING_DYNAMIC_RATCHET (Stop Rs. {trail_stop:.2f})"
                    exit_price = round(trail_stop, 2)
                elif active_trade["direction"] == "CE" and spot < (ema9 - 4.0):
                    exit_reason = f"TRAILING_EMA9_RUNNER (Spot {spot:.1f} < EMA9 {ema9:.1f} - 4)"
                    exit_price = opt_c

            # 4. Structural Stops (if trailing not yet activated)
            elif not exit_reason:
                if active_trade["direction"] == "CE":
                    if spot < (session_vwap - 15.0):
                        exit_reason = f"STRUCTURAL_VWAP_STOP ({spot:.1f} < {session_vwap-15.0:.1f})"
                        exit_price = opt_c
                    elif spot < ema20 and ema9 < ema20:
                        exit_reason = f"STRUCTURAL_EMA20_STOP ({spot:.1f} < {ema20:.1f})"
                        exit_price = opt_c

            if exit_reason:
                active_trade["exit_bar"] = idx
                active_trade["exit_time"] = time_str
                active_trade["exit_price"] = exit_price
                active_trade["exit_reason"] = exit_reason
                active_trade["pnl"] = round((exit_price - active_trade["entry_price"]) * active_trade["quantity"], 2)
                active_trade["pnl_pct"] = round(((exit_price - active_trade["entry_price"]) / active_trade["entry_price"]) * 100, 2)
                trades.append(active_trade)
                print(f"  --> [EXIT] {time_str} | Strike {active_trade['strike']} CE | Exit: Rs. {exit_price:.2f} | Reason: {exit_reason} | PnL: Rs. {active_trade['pnl']:+,.2f} ({active_trade['pnl_pct']:+.1f}%) | Peak: +{active_trade['peak_gain_pct']:.1f}%")
                active_trade = None
                last_exit_idx = idx
            continue

        # Entry Evaluation
        if idx < 10 or idx > 330:
            continue
        if len(trades) >= 6:
            continue
        if (idx - last_exit_idx) < 10:
            continue

        # Strategy 3 Rules:
        # A. Bull Trend Alignment: Spot > 5m EMA9 > 5m EMA20 and Spot > Session VWAP
        trend_aligned_bull = (spot > ema9) and (ema9 > ema20) and (spot > session_vwap)
        trend_aligned_bear = (spot < ema9) and (ema9 < ema20) and (spot < session_vwap)

        # B. Pullback Confirmation: Low retested within 4.0 pts of 5m EMA9
        pullback_ce = (low <= ema9 + 4.0)
        pullback_pe = (high >= ema9 - 4.0)

        # Log around 09:40 to 09:50
        if "09:42" <= time_str <= "09:48":
            status_str = f"BullAligned: {trend_aligned_bull} (EMA9={ema9:.1f}, EMA20={ema20:.1f}, VWAP={session_vwap:.1f}) | Pullback: {pullback_ce} (Low={low:.1f} vs EMA9+4={ema9+4.0:.1f})"
            print(f"[{time_str}] Spot: {spot:.1f} | {status_str}")

        signal = None
        if trend_aligned_bull and pullback_ce:
            # Range Box Filter: do not buy ceiling of tight consolidation
            box_ceiling_blocked = is_box and spot < (box_high + 2.0) and spot >= (box_high - 6.0)
            # Value Proximity Filter: do not buy parabolic extension
            overextended = (spot - ema9) > 24.0 or rsi > 78.0

            if not box_ceiling_blocked and not overextended:
                signal = "BUY_CE"

        if signal == "BUY_CE":
            # Strict ITM Strike Selection
            strike = int(spot // 50) * 50
            days_rem = max(0.001, days_to_expiry - (idx / 375.0) * 0.25)
            entry_prem = bsm_price(spot, strike, days_rem, is_call=True)
            required_margin = entry_prem * 65

            # Zero-Shortfall Capital Protection check (safe budget)
            safe_budget = 9531.60
            if required_margin > safe_budget:
                # Stepdown to ATM
                atm_strike = int(round(spot / 50.0)) * 50
                entry_prem = bsm_price(spot, atm_strike, days_rem, is_call=True)
                strike = atm_strike
                required_margin = entry_prem * 65

            if required_margin <= safe_budget:
                active_trade = {
                    "trade_id": len(trades) + 1,
                    "symbol": f"NIFTY26OCT{strike}CE",
                    "direction": "CE",
                    "strike": strike,
                    "entry_bar": idx,
                    "entry_time": time_str,
                    "entry_spot": spot,
                    "entry_price": entry_prem,
                    "quantity": 65,
                    "margin_used": round(required_margin, 2),
                    "peak_price": entry_prem,
                    "peak_gain_pct": 0.0,
                    "status": "OPEN"
                }
                print(f"\n>>> [ENTRY] {time_str} IST | Strike: {strike} CE | Spot: {spot:.1f} | 5m EMA9: {ema9:.1f} | 5m EMA20: {ema20:.1f} | VWAP: {session_vwap:.1f}")
                print(f"    Option Premium: Rs. {entry_prem:.2f} | 1 Lot (65 Qty) | Margin Required: Rs. {required_margin:.2f} (Budget: Rs. {safe_budget:.2f} -> SAFE)")

    # If position still open at the end of the data
    if active_trade is not None:
        last_bar = today_1m[-1]
        days_rem = max(0.001, days_to_expiry - ((len(today_1m)-1) / 375.0) * 0.25)
        opt_c = bsm_price(last_bar["close"], active_trade["strike"], days_rem, is_call=True)
        active_trade["exit_bar"] = len(today_1m) - 1
        active_trade["exit_time"] = last_bar["time_str"]
        active_trade["exit_price"] = opt_c
        active_trade["exit_reason"] = "CURRENT_LIVE_OPEN_RUNNER"
        active_trade["pnl"] = round((opt_c - active_trade["entry_price"]) * active_trade["quantity"], 2)
        active_trade["pnl_pct"] = round(((opt_c - active_trade["entry_price"]) / active_trade["entry_price"]) * 100, 2)
        trades.append(active_trade)
        print(f"\n>>> [OPEN POSITION AS OF {last_bar['time_str']}] Strike: {active_trade['strike']} CE")
        print(f"    Entry: Rs. {active_trade['entry_price']:.2f} at {active_trade['entry_time']} | Current LTP: Rs. {opt_c:.2f}")
        print(f"    Unrealized PnL: Rs. {active_trade['pnl']:+,.2f} ({active_trade['pnl_pct']:+.1f}%) | Peak Gain: +{active_trade['peak_gain_pct']:.1f}%\n")

    # Summary
    print("-" * 105)
    print(f"SUMMARY FOR {mode}:")
    print(f"Total Trades Generated: {len(trades)}")
    total_pnl = sum(t["pnl"] for t in trades)
    print(f"Total PnL: Rs. {total_pnl:+,.2f}")
    for t in trades:
        print(f"Trade #{t['trade_id']}: {t['entry_time']} -> {t.get('exit_time')} | Strike {t['strike']} | Entry Rs. {t['entry_price']:.2f} -> Exit Rs. {t.get('exit_price', 0):.2f} | PnL: Rs. {t.get('pnl', 0):+,.2f} ({t.get('pnl_pct', 0):+.1f}%) | {t.get('exit_reason')}")
    print("=" * 105 + "\n")

    return trades

if __name__ == "__main__":
    trades_pre = run_backtest(mode="PRE_PATCH_BUG")
    trades_post = run_backtest(mode="POST_PATCH")
