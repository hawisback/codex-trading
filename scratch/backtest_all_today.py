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
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bsm_price(spot: float, strike: float, days_to_expiry: float,
              r: float = 0.065, sigma: float = 0.135, is_call: bool = True) -> float:
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

def calc_ema_backend(prices, span):
    if len(prices) < span:
        return prices[-1]
    k = 2.0 / (span + 1)
    e = sum(prices[:span]) / span
    for p in prices[span:]:
        e = p * k + e * (1 - k)
    return round(e, 2)

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

def run_strategy(name, require_pullback=True, pullback_type="EMA9_STRICT"):
    c1m_resp = fetch("/nifty/candles?interval=1m&limit=500")
    c5m_resp = fetch("/nifty/candles?interval=5m&limit=100")

    all_1m = c1m_resp.get("candles", [])
    all_5m = c5m_resp.get("candles", [])

    today_1m = []
    for c in all_1m:
        st = c.get("start_time", "")
        dt_utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        if dt_ist.strftime("%Y-%m-%d") == "2026-10-15":
            c_copy = dict(c)
            c_copy["time_str"] = dt_ist.strftime("%H:%M")
            today_1m.append(c_copy)

    # Pre-seed 5m candles
    prev_5m = [c for c in all_5m if datetime.fromisoformat(c["start_time"].replace("Z", "+00:00")).astimezone(IST).strftime("%Y-%m-%d") < "2026-10-15"]
    today_5m_all = [c for c in all_5m if datetime.fromisoformat(c["start_time"].replace("Z", "+00:00")).astimezone(IST).strftime("%Y-%m-%d") == "2026-10-15"]

    spot_prices = []
    spot_typicals = []
    trades = []
    active_trade = None
    last_exit_idx = -999
    days_to_expiry = 4.0
    safe_budget = 9531.60

    for idx, bar in enumerate(today_1m):
        spot = bar["close"]
        high = bar["high"]
        low = bar["low"]
        time_str = bar["time_str"]

        spot_prices.append(spot)
        spot_typicals.append((high + low + spot) / 3.0)
        session_vwap = round(sum(spot_typicals) / len(spot_typicals), 2)

        # 5m rolling calculation using 50-bar window
        completed_5m_count = idx // 5
        active_5m_slice = prev_5m + today_5m_all[:completed_5m_count]
        closes_5m = [c["close"] for c in active_5m_slice[-50:]]
        ema9 = calc_ema_backend(closes_5m, 9)
        ema20 = calc_ema_backend(closes_5m, 20)
        rsi = calculate_rsi(spot_prices, 14)

        recent_15m = today_1m[max(0, idx - 14): idx + 1]
        box_high = max(c["high"] for c in recent_15m)
        box_low = min(c["low"] for c in recent_15m)
        box_spread = round(box_high - box_low, 2)
        is_box = box_spread < 28.0 and len(recent_15m) >= 10

        # Position management
        if active_trade is not None:
            days_rem = max(0.001, days_to_expiry - (idx / 375.0) * 0.25)
            opt_c = bsm_price(spot, active_trade["strike"], days_rem, is_call=True)
            opt_h = bsm_price(high, active_trade["strike"], days_rem, is_call=True)
            opt_l = bsm_price(low, active_trade["strike"], days_rem, is_call=True)

            if opt_h > active_trade["peak_price"]:
                active_trade["peak_price"] = opt_h
                active_trade["peak_gain_pct"] = round(((opt_h - active_trade["entry_price"]) / active_trade["entry_price"]) * 100, 2)

            exit_reason = None
            exit_price = opt_c

            if opt_l <= active_trade["entry_price"] * 0.70:
                exit_reason = "INITIAL_STOP (-30%)"
                exit_price = round(active_trade["entry_price"] * 0.70, 2)
            elif active_trade["peak_gain_pct"] >= 20.0:
                floor_pct = 10.0
                if active_trade["peak_gain_pct"] >= 40.0:
                    floor_pct = 30.0
                elif active_trade["peak_gain_pct"] >= 30.0:
                    floor_pct = 20.0
                floor_price = active_trade["entry_price"] * (1.0 + floor_pct / 100.0)
                trail_stop = max(floor_price, active_trade["peak_price"] * 0.90)

                if opt_c <= trail_stop:
                    exit_reason = f"TRAILING_RATCHET (Stop Rs. {trail_stop:.2f})"
                    exit_price = round(trail_stop, 2)
                elif spot < (ema9 - 4.0):
                    exit_reason = f"TRAILING_EMA9 ({spot:.1f} < {ema9-4.0:.1f})"
                    exit_price = opt_c
            else:
                if spot < (session_vwap - 15.0):
                    exit_reason = "STRUCTURAL_VWAP_STOP"
                    exit_price = opt_c
                elif spot < ema20 and ema9 < ema20:
                    exit_reason = "STRUCTURAL_EMA20_STOP"
                    exit_price = opt_c

            if exit_reason:
                active_trade["exit_bar"] = idx
                active_trade["exit_time"] = time_str
                active_trade["exit_price"] = exit_price
                active_trade["exit_reason"] = exit_reason
                active_trade["pnl"] = round((exit_price - active_trade["entry_price"]) * active_trade["quantity"], 2)
                active_trade["pnl_pct"] = round(((exit_price - active_trade["entry_price"]) / active_trade["entry_price"]) * 100, 2)
                trades.append(active_trade)
                active_trade = None
                last_exit_idx = idx
            continue

        if idx < 10 or idx > 330:
            continue
        if len(trades) >= 6:
            continue
        if (idx - last_exit_idx) < 10:
            continue

        trend_aligned_bull = (spot > ema9) and (ema9 > ema20) and (spot > session_vwap)
        
        # Pullback condition
        if not require_pullback:
            pullback_ok = True
        elif pullback_type == "EMA9_STRICT":
            pullback_ok = (low <= ema9 + 4.0)
        elif pullback_type == "EMA9_OR_VWAP":
            # On gap-up days, pullback retests either 5m EMA9 or Session VWAP
            pullback_ok = (low <= ema9 + 4.0) or (low <= session_vwap + 6.0)

        if trend_aligned_bull and pullback_ok:
            box_ceiling_blocked = is_box and spot < (box_high + 2.0) and spot >= (box_high - 6.0)
            overextended = (spot - ema9) > 35.0 or rsi > 78.0

            if not box_ceiling_blocked and not overextended:
                strike = int(spot // 50) * 50
                days_rem = max(0.001, days_to_expiry - (idx / 375.0) * 0.25)
                entry_prem = bsm_price(spot, strike, days_rem, is_call=True)
                required_margin = entry_prem * 65

                if required_margin > safe_budget:
                    atm_strike = int(round(spot / 50.0)) * 50
                    entry_prem = bsm_price(spot, atm_strike, days_rem, is_call=True)
                    strike = atm_strike
                    required_margin = entry_prem * 65

                if required_margin <= safe_budget:
                    active_trade = {
                        "trade_id": len(trades) + 1,
                        "strategy": name,
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

    if active_trade is not None:
        last_bar = today_1m[-1]
        days_rem = max(0.001, days_to_expiry - ((len(today_1m)-1) / 375.0) * 0.25)
        opt_c = bsm_price(last_bar["close"], active_trade["strike"], days_rem, is_call=True)
        active_trade["exit_bar"] = len(today_1m) - 1
        active_trade["exit_time"] = last_bar["time_str"]
        active_trade["exit_price"] = opt_c
        active_trade["exit_reason"] = "STILL_RUNNING_LIVE"
        active_trade["pnl"] = round((opt_c - active_trade["entry_price"]) * active_trade["quantity"], 2)
        active_trade["pnl_pct"] = round(((opt_c - active_trade["entry_price"]) / active_trade["entry_price"]) * 100, 2)
        trades.append(active_trade)

    print(f"\n--- Strategy: {name} ---")
    print(f"Trades Count: {len(trades)}")
    for t in trades:
        print(f"  Trade #{t['trade_id']}: Entry {t['entry_time']} @ Rs. {t['entry_price']:.2f} (Spot {t['entry_spot']:.1f}, Strike {t['strike']} CE)")
        print(f"     Exit: {t['exit_time']} @ Rs. {t['exit_price']:.2f} | Reason: {t['exit_reason']}")
        print(f"     PnL: Rs. {t['pnl']:+,.2f} ({t['pnl_pct']:+.1f}%) | Peak Gain: +{t['peak_gain_pct']:.1f}% | Margin: Rs. {t['margin_used']:.2f}")

    total_pnl = sum(t["pnl"] for t in trades)
    print(f"Total Strategy PnL: Rs. {total_pnl:+,.2f}")
    return trades

if __name__ == "__main__":
    t_s2 = run_strategy("Strategy 2 (Structural Runner)", require_pullback=False)
    t_s3_vwap = run_strategy("Strategy 3 (Pullback to EMA9 or Session VWAP)", require_pullback=True, pullback_type="EMA9_OR_VWAP")
    t_s3_strict = run_strategy("Strategy 3 (Strict EMA9 Pullback <= 4 pts)", require_pullback=True, pullback_type="EMA9_STRICT")
