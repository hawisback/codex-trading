#!/usr/bin/env python3
"""
Forensic Comparative Audit across 30 Sessions (2026-09-11 to 2026-10-27):
Comparing:
1. Strategy 5 (Current: Raw 2m MACD Crossover, EMA flags False)
2. Strategy 5 (Refined: 2m MACD with 5m EMA Trend Alignment & Proximity)
3. Strategy 4 (AI Opportunity Radar: Pullbacks + Climax Springs)
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading.bootstrap import configure_console
configure_console()

from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from trading.domain.market_data import resample_two_minutes
from trading.strategies.macd_momentum import calculate_macd, calculate_ema

DATES = [
    "2026-09-11", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
    "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-05",
    "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12",
    "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19",
    "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"
]

def load_session_data(date_str: str):
    clean_d = date_str.replace("-", "")
    spot_file = f"data/spot_candles_{clean_d}.json"
    fut_file = f"data/fut_candles_{clean_d}.json"
    if not os.path.exists(spot_file):
        return None, None, {}
    with open(spot_file, "r", encoding="utf-8") as fp:
        spot_bars = json.load(fp)
    fut_bars = []
    if os.path.exists(fut_file):
        with open(fut_file, "r", encoding="utf-8") as fp:
            fut_bars = json.load(fp)
    opt_candles = {}
    for f in os.listdir("data"):
        if f.startswith(f"opt_{clean_d}_") and f.endswith(".json"):
            parts = f.replace(".json", "").split("_")
            if len(parts) >= 4:
                strike_k = int(parts[2])
                right_k = parts[3]
                with open(os.path.join("data", f), "r", encoding="utf-8") as fp:
                    opt_candles[(strike_k, right_k)] = json.load(fp)
    return spot_bars, fut_bars, opt_candles

def get_option_price(spot_p: float, strike: int, direction: str, bar_idx: int, days_base: float, opt_candles: dict, spot_bars: list):
    key = (strike, direction)
    if key in opt_candles and bar_idx < len(opt_candles[key]):
        c = opt_candles[key][bar_idx]
        return c.get("open", c["close"]), c["high"], c["low"], c["close"]
    days_rem = max(0.001, days_base - (bar_idx / 375.0) * 0.25)
    is_call = (direction == "CE")
    sb = spot_bars[bar_idx]
    c_open = bsm_price(sb["open"], strike, days_rem, is_call=is_call)
    c_close = bsm_price(sb["close"], strike, days_rem, is_call=is_call)
    c_high = bsm_price(sb["high"] if is_call else sb["low"], strike, days_rem, is_call=is_call)
    c_low = bsm_price(sb["low"] if is_call else sb["high"], strike, days_rem, is_call=is_call)
    return c_open, max(c_open, c_close, c_high), min(c_open, c_close, c_low), c_close

def simulate_trade(entry_idx: int, strike: int, direction: str, spot_bars: list, days_base: float, opt_candles: dict, inval_spot: float):
    next_idx = entry_idx + 1
    if next_idx >= len(spot_bars) - 1:
        return None
    o_open, _, _, _ = get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)
    entry_p = o_open
    if entry_p <= 1.0:
        return None
    peak_p = entry_p
    exit_p = entry_p
    exit_reason = "1515_EOD"
    
    for m in range(next_idx + 1, min(len(spot_bars), 365)):
        sb = spot_bars[m]
        hh = (m + 15) // 60 + 9
        mm = (m + 15) % 60
        if hh > 15 or (hh == 15 and mm >= 15):
            exit_p = get_option_price(sb["open"], strike, direction, m, days_base, opt_candles, spot_bars)[0]
            exit_reason = "1515_EOD"
            break
        m_open, m_high, m_low, m_close = get_option_price(sb["close"], strike, direction, m, days_base, opt_candles, spot_bars)
        if m_high > peak_p:
            peak_p = m_high
        gain_pct = ((peak_p - entry_p) / entry_p) * 100.0
        
        # Spot swing invalidation
        if direction == "CE" and sb["low"] <= inval_spot:
            exit_p = m_close
            exit_reason = "SPOT_INVALIDATION"
            break
        elif direction == "PE" and sb["high"] >= inval_spot:
            exit_p = m_close
            exit_reason = "SPOT_INVALIDATION"
            break
            
        # Two-step stop loss
        stop_p = entry_p * 0.70 # 30% initial
        if gain_pct >= 50.0:
            stop_p = max(stop_p, peak_p * 0.95)
        elif gain_pct >= 40.0:
            stop_p = max(stop_p, entry_p * 1.30)
        elif gain_pct >= 30.0:
            stop_p = max(stop_p, entry_p * 1.20)
        elif gain_pct >= 20.0:
            stop_p = max(stop_p, entry_p * 1.10)
        elif gain_pct >= 15.0:
            stop_p = max(stop_p, entry_p * 1.00)
            
        if gain_pct >= 20.0:
            stop_p = max(stop_p, peak_p * 0.90)
            
        if m_low <= stop_p:
            exit_p = stop_p
            exit_reason = "DYNAMIC_STOP" if stop_p > entry_p else "INITIAL_STOP"
            break
            
    pnl_pts = exit_p - entry_p
    pnl_inr = pnl_pts * 130 - 40.0 # Fixed 2 lots
    return {
        "entry_idx": entry_idx,
        "entry_p": entry_p,
        "exit_p": exit_p,
        "pnl_pts": pnl_pts,
        "pnl_inr": pnl_inr,
        "is_win": pnl_pts > 0,
        "exit_reason": exit_reason
    }

print("Running 30-session comparative diagnostic...")
def run_comparison():
    trading_cfg = json.loads(Path("config/trading.json").read_text(encoding="utf-8"))
    strats_cfg = json.loads(Path("config/strategies.json").read_text(encoding="utf-8"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    # Trackers for the models
    results = {
        "A_raw_macd": {"trades": 0, "wins": 0, "pnl": 0.0},
        "B_macd_plus_ema": {"trades": 0, "wins": 0, "pnl": 0.0},
        "C_radar_pullback_spring": {"trades": 0, "wins": 0, "pnl": 0.0}
    }
    
    for dt_str in DATES:
        spot_bars, fut_bars, opt_candles = load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60:
            continue
            
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        if target_d.weekday() <= 1:
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
        else:
            expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        # Precompute 5m bars & EMAs
        res_5m = []
        for g_idx in range(0, len(spot_bars), 5):
            group = spot_bars[g_idx:g_idx + 5]
            if group:
                res_5m.append(group[-1]["close"])
        ema9_5m = calculate_ema(res_5m, 9)
        ema20_5m = calculate_ema(res_5m, 20)
        
        # 2m bars & MACD
        res_2m = resample_two_minutes(spot_bars)
        closes_2m = [b["close"] for b in res_2m]
        macd, sig, hist = calculate_macd(closes_2m)
        
        # -------------------------------------------------------------
        # MODEL A: Raw 2m MACD (Current Strategy 5)
        # -------------------------------------------------------------
        in_trade_until_A = -1
        for i in range(26, len(res_2m)):
            end_1m = res_2m[i]["minute_idx"]
            if end_1m < in_trade_until_A:
                continue
            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
            if not (pe_cross or ce_cross):
                continue
            direction = "PE" if pe_cross else "CE"
            spot_p = res_2m[i]["close"]
            strike = int(round(spot_p / 50.0)) * 50
            
            # Check AI playbook gatekeeper
            dossier = generate_market_dossier(
                target_date=dt_str, candles=spot_bars[:end_1m + 1], current_bar_idx=end_1m,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dossier)
            if not v.is_approved:
                continue
                
            recent = spot_bars[max(0, end_1m - 5): end_1m + 1]
            inval = (min(b["low"] for b in recent) - 2.0) if direction == "CE" else (max(b["high"] for b in recent) + 2.0)
            res = simulate_trade(end_1m, strike, direction, spot_bars, days_base, opt_candles, inval)
            if res:
                results["A_raw_macd"]["trades"] += 1
                if res["is_win"]:
                    results["A_raw_macd"]["wins"] += 1
                results["A_raw_macd"]["pnl"] += res["pnl_inr"]
                in_trade_until_A = end_1m + 20

        # -------------------------------------------------------------
        # MODEL B: 2m MACD with 5m EMA Trend Alignment & Proximity
        # -------------------------------------------------------------
        in_trade_until_B = -1
        for i in range(26, len(res_2m)):
            end_1m = res_2m[i]["minute_idx"]
            if end_1m < in_trade_until_B:
                continue
            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
            if not (pe_cross or ce_cross):
                continue
            direction = "PE" if pe_cross else "CE"
            spot_p = res_2m[i]["close"]
            strike = int(round(spot_p / 50.0)) * 50
            
            # 5m EMA context
            g_5m = min(len(ema9_5m) - 1, end_1m // 5)
            e9 = ema9_5m[g_5m]
            e20 = ema20_5m[g_5m]
            
            # Trend alignment: CE requires spot > e20 and e9 > e20; PE requires spot < e20 and e9 < e20
            trend_ok = (spot_p > e20 and e9 >= e20 - 2.0) if direction == "CE" else (spot_p < e20 and e9 <= e20 + 2.0)
            # Proximity: spot within 15 pts of EMA9 (value entry, not extended)
            dist_e9 = abs(spot_p - e9)
            prox_ok = (dist_e9 <= 18.0)
            
            if not (trend_ok and prox_ok):
                continue
                
            dossier = generate_market_dossier(
                target_date=dt_str, candles=spot_bars[:end_1m + 1], current_bar_idx=end_1m,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dossier)
            if not v.is_approved:
                continue
                
            recent = spot_bars[max(0, end_1m - 5): end_1m + 1]
            inval = (min(b["low"] for b in recent) - 2.0) if direction == "CE" else (max(b["high"] for b in recent) + 2.0)
            res = simulate_trade(end_1m, strike, direction, spot_bars, days_base, opt_candles, inval)
            if res:
                results["B_macd_plus_ema"]["trades"] += 1
                if res["is_win"]:
                    results["B_macd_plus_ema"]["wins"] += 1
                results["B_macd_plus_ema"]["pnl"] += res["pnl_inr"]
                in_trade_until_B = end_1m + 20

        # -------------------------------------------------------------
        # MODEL C: AI Opportunity Radar (Strategy 4: Pullback + Climax Spring)
        # -------------------------------------------------------------
        in_trade_until_C = -1
        for m in range(25, min(300, len(spot_bars))):
            if m < in_trade_until_C:
                continue
            sb = spot_bars[m]
            spot_p = sb["close"]
            g_5m = min(len(ema9_5m) - 1, m // 5)
            e9 = ema9_5m[g_5m]
            e20 = ema20_5m[g_5m]
            
            bars_so_far = spot_bars[:m + 1]
            typicals = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars_so_far]
            vwap = sum(typicals) / len(typicals)
            
            # 15m box
            box_bars = bars_so_far[max(0, m - 14): m + 1]
            box_h = max(b["high"] for b in box_bars)
            box_l = min(b["low"] for b in box_bars)
            box_spread = box_h - box_l
            
            direction = None
            setup_type = None
            
            # 1. Climax Spring
            dist_vwap = spot_p - vwap
            if m <= 120 and abs(dist_vwap) >= 45.0:
                if dist_vwap <= -45.0 and (sb["close"] - sb["open"]) >= 15.0:
                    direction = "CE"
                    setup_type = "CLIMAX_SPRING"
                elif dist_vwap >= 45.0 and (sb["open"] - sb["close"]) >= 15.0:
                    direction = "PE"
                    setup_type = "CLIMAX_SPRING"
                    
            # 2. Dynamic Trend Pullback
            if not direction and box_spread >= 24.0:
                ce_trend = (spot_p > e9) and (e9 > e20) and (spot_p > vwap)
                ce_pullback = (sb["low"] <= e9 + 4.0) and (spot_p - e9 <= 20.0)
                ce_not_box_top = (spot_p < box_h - 2.0)
                
                pe_trend = (spot_p < e9) and (e9 < e20) and (spot_p < vwap)
                pe_pullback = (sb["high"] >= e9 - 4.0) and (e9 - spot_p <= 20.0)
                pe_not_box_bot = (spot_p > box_l + 2.0)
                
                if ce_trend and ce_pullback and ce_not_box_top:
                    direction = "CE"
                    setup_type = "TREND_PULLBACK"
                elif pe_trend and pe_pullback and pe_not_box_bot:
                    direction = "PE"
                    setup_type = "TREND_PULLBACK"
                    
            if not direction:
                continue
                
            strike = int(round(spot_p / 50.0)) * 50
            dossier = generate_market_dossier(
                target_date=dt_str, candles=bars_so_far, current_bar_idx=m,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dossier)
            if not v.is_approved:
                continue
                
            recent = bars_so_far[max(0, m - 5): m + 1]
            inval = (min(b["low"] for b in recent) - 2.0) if direction == "CE" else (max(b["high"] for b in recent) + 2.0)
            res = simulate_trade(m, strike, direction, spot_bars, days_base, opt_candles, inval)
            if res:
                results["C_radar_pullback_spring"]["trades"] += 1
                if res["is_win"]:
                    results["C_radar_pullback_spring"]["wins"] += 1
                results["C_radar_pullback_spring"]["pnl"] += res["pnl_inr"]
                in_trade_until_C = m + 20

    print("=" * 95)
    print(" 📊 COMPARATIVE AUDIT: TRADE IDENTIFICATION MODELS (30 SESSIONS)")
    print("=" * 95)
    for model_key, data in results.items():
        t = data["trades"]
        w = data["wins"]
        l = t - w
        wr = (w / t * 100.0) if t > 0 else 0.0
        pnl = data["pnl"]
        print(f" Model: {model_key:<25} | Trades: {t:>3} | Wins: {w:>3} | Losses: {l:>3} | Win Rate: {wr:>5.1f}% | Net PnL (2 Lots): Rs {pnl:>+11,.2f}")
    print("=" * 95)

if __name__ == "__main__":
    run_comparison()
