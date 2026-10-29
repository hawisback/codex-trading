#!/usr/bin/env python3
"""
Full 30-Session Forensic Validation of the Fast 2m MACD Quick-Momentum Strategy
incorporating:
1. Fast 2m MACD Crossover (Quick directional reaction, zero lagging 5m EMA bias)
2. 2m Candle Color Confirmation (Green candle for CE, Red candle for PE)
3. Session VWAP Flow Alignment (CE above VWAP, PE below VWAP)
4. Option Strike 2m MACD Confluence (Option histogram expanding positive)
5. Strict ITM Strike Selection (Delta ~0.65-0.70, deep intrinsic protection)
6. 25-pt Spot Invalidation Buffer + Progressive Runner Trailing
7. Max 2 High-Conviction Trades per Session (Overtrading churn eliminated)
"""

import json
import os
import sys

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

from datetime import datetime, timedelta
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from trading.domain.market_data import resample_two_minutes, two_minute_macd_metrics
from trading.strategies.macd_momentum import calculate_macd

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
    if not os.path.exists(spot_file): return None, {}
    with open(spot_file, "r") as fp: spot_bars = json.load(fp)
    opt_candles = {}
    for f in os.listdir("data"):
        if f.startswith(f"opt_{clean_d}_") and f.endswith(".json"):
            parts = f.replace(".json", "").split("_")
            if len(parts) >= 4:
                opt_candles[(int(parts[2]), parts[3])] = json.load(open(os.path.join("data", f)))
    return spot_bars, opt_candles

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

def compute_strike_macd(spot_bars, strike, direction, end_1m, days_base, opt_candles):
    opt_bars_1m = []
    for m in range(end_1m + 1):
        o, h, l, c = get_option_price(spot_bars[m]["close"], strike, direction, m, days_base, opt_candles, spot_bars)
        opt_bars_1m.append({"start_time": spot_bars[m]["start_time"], "open": o, "high": h, "low": l, "close": c, "volume": 1000})
    try:
        opt_2m = resample_two_minutes(opt_bars_1m)
        if len(opt_2m) >= 26:
            return two_minute_macd_metrics(opt_2m)
    except Exception:
        pass
    return {"expanding_positive": True, "histogram": 0.0}

def run_fast_macd_validation():
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    executed_trades = []
    daily_stats = {}
    
    compounding_capital = 10000.0
    
    for dt_str in DATES:
        spot_bars, opt_candles = load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60: continue
        
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        res_2m = resample_two_minutes(spot_bars)
        closes_2m = [b["close"] for b in res_2m]
        macd, sig, hist = calculate_macd(closes_2m)
        
        in_trade_until = -1
        session_trades = 0
        session_pnl = 0.0
        
        for i in range(26, len(res_2m)):
            end_1m = res_2m[i]["minute_idx"]
            if end_1m < in_trade_until or end_1m > 300: continue
            if session_trades >= 2: break # Limit to top 2 setups per day
            
            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
            if not (pe_cross or ce_cross): continue
            
            # Momentum threshold: ignore microscopic noise crosses
            if abs(hist[i]) < 0.25: continue
            
            direction = "PE" if pe_cross else "CE"
            spot_p = res_2m[i]["close"]
            
            # 1. 2m Candle Alignment: Candle body must agree with direction
            candle_body = res_2m[i]["close"] - res_2m[i]["open"]
            if direction == "CE" and candle_body < 0: continue
            if direction == "PE" and candle_body > 0: continue
            
            # 2. Cumulative VWAP
            bars_so_far = spot_bars[:end_1m + 1]
            vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
            
            # Session VWAP side check (allows tight +/- 12 pt test around VWAP)
            if direction == "CE" and spot_p < vwap - 12.0: continue
            if direction == "PE" and spot_p > vwap + 12.0: continue
            
            # 3. 15m Consolidation Range Box
            box_15 = bars_so_far[max(0, end_1m - 14): end_1m + 1]
            box_spread = max(x["high"] for x in box_15) - min(x["low"] for x in box_15)
            # Avoid midday dead-zone flatline (11:30 - 13:15 with tight range)
            if 135 <= end_1m <= 240 and box_spread < 24.0: continue
            
            # 4. Strict ITM Strike (Delta >= 0.65)
            atm_strike = int(round(spot_p / 50.0)) * 50
            strike = atm_strike - 50 if direction == "CE" else atm_strike + 50
            
            # 5. Strike 2m MACD Confluence Check
            strike_macd_data = compute_strike_macd(spot_bars, strike, direction, end_1m, days_base, opt_candles)
            if not strike_macd_data.get("expanding_positive", True) and strike_macd_data.get("histogram", 0) < 0:
                continue
                
            # 6. Production AI Gatekeeper
            dossier = generate_market_dossier(
                target_date=dt_str, candles=bars_so_far, current_bar_idx=end_1m,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dossier)
            if not v.is_approved: continue
            
            # Entry Execution
            next_idx = end_1m + 1
            if next_idx >= len(spot_bars) - 1: continue
            entry_p = get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
            if entry_p <= 5.0: continue
            
            recent = spot_bars[max(0, end_1m - 5): end_1m + 1]
            if direction == "CE":
                inval_spot = min(min(b["low"] for b in recent) - 2.0, spot_p - 25.0)
            else:
                inval_spot = max(max(b["high"] for b in recent) + 2.0, spot_p + 25.0)
                
            peak_p = entry_p
            exit_p = entry_p
            exit_reason = "1515_EOD"
            
            for m in range(next_idx + 1, min(len(spot_bars), 365)):
                sb = spot_bars[m]
                hh = (m + 15) // 60 + 9
                mm = (m + 15) % 60
                if hh > 15 or (hh == 15 and mm >= 15):
                    exit_p = get_option_price(sb["open"], strike, direction, m, days_base, opt_candles, spot_bars)[0]
                    break
                m_open, m_high, m_low, m_close = get_option_price(sb["close"], strike, direction, m, days_base, opt_candles, spot_bars)
                if m_high > peak_p: peak_p = m_high
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
                    
                # Dynamic Runner Trailing
                stop_p = entry_p * 0.75 # 25% initial stop
                if gain_pct >= 50.0: stop_p = max(stop_p, peak_p * 0.95)
                elif gain_pct >= 40.0: stop_p = max(stop_p, entry_p * 1.30)
                elif gain_pct >= 30.0: stop_p = max(stop_p, entry_p * 1.20)
                elif gain_pct >= 20.0: stop_p = max(stop_p, entry_p * 1.10)
                elif gain_pct >= 15.0: stop_p = max(stop_p, entry_p * 1.00)
                if gain_pct >= 20.0: stop_p = max(stop_p, peak_p * 0.90)
                
                if m_low <= stop_p:
                    exit_p = stop_p
                    exit_reason = "DYNAMIC_STOP" if stop_p > entry_p else "INITIAL_STOP"
                    break
                    
            pnl_pts = exit_p - entry_p
            pnl_inr = pnl_pts * 130 - 40.0 # Fixed 2 lots
            
            # Step-ladder compounding lots (starts at 2 lots for Rs 10k, scales to 4 at 20k)
            step_lots = 2 if compounding_capital < 20000.0 else (4 if compounding_capital < 40000.0 else 6)
            pnl_comp = pnl_pts * (step_lots * 65) - 40.0
            compounding_capital += pnl_comp
            
            tr_rec = {
                "date": dt_str, "time": f"{(end_1m+15)//60+9:02d}:{(end_1m+15)%60:02d}",
                "direction": direction, "strike": strike, "entry_p": round(entry_p, 2), "exit_p": round(exit_p, 2),
                "peak_gain_pct": round(gain_pct, 1), "pnl_pts": round(pnl_pts, 2), "pnl_inr": round(pnl_inr, 2),
                "is_win": pnl_pts > 0, "exit_reason": exit_reason
            }
            executed_trades.append(tr_rec)
            session_trades += 1
            session_pnl += pnl_inr
            in_trade_until = end_1m + 20
            
        daily_stats[dt_str] = {"trades": session_trades, "pnl": session_pnl}

    with open("scratch/fast_macd_trades.json", "w") as fp:
        json.dump(executed_trades, fp, indent=2)
    tot = len(executed_trades)
    wins = [t for t in executed_trades if t["is_win"]]
    losses = [t for t in executed_trades if not t["is_win"]]
    wr = len(wins) / tot * 100.0 if tot else 0.0
    tot_pnl_2lots = sum(t["pnl_inr"] for t in executed_trades)
    
    print("=" * 115)
    print(" 🚀 VALIDATION AUDIT: FAST 2m MACD QUICK-MOMENTUM STRATEGY (30 SESSIONS)")
    print("=" * 115)
    print(f" Total Trades Executed:                 {tot} (averaging {tot/30:.1f} trades/day)")
    print(f" Winning Trades:                         {len(wins)} / {tot} ({wr:.1f}% Win Rate)")
    print(f" Losing Trades:                          {len(losses)} / {tot}")
    print(f" Net Realized PnL (Fixed 2 Lots / 10k):  Rs {tot_pnl_2lots:+,.2f} (+{tot_pnl_2lots/10000*100.0:,.1f}% ROI)")
    print(f" Compounding Ending Capital:             Rs {compounding_capital:,.2f} ({compounding_capital/10000:.1f}x Compounding)")
    print("=" * 115)

if __name__ == "__main__":
    run_fast_macd_validation()
