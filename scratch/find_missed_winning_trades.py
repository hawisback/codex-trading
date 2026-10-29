import json
import os
import sys

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

from datetime import datetime, timedelta
from market_clock import MarketClock
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from trading.domain.indicators import select_strike
from trading.domain.market_data import exchange_time, resample_two_minutes, two_minute_macd_metrics
from trading.domain.trailing import session_trigger, runner_trigger
from trading.strategies.macd_momentum import calculate_macd, MacdMomentumStrategy
import scratch.run_production_backtest_30_sessions as r

DATES = r.DATES

def analyze_all_crossovers():
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    exit_cfg = strat_cfg["exit"]
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    # We will track all crossovers, evaluate which filters they pass/fail, and simulate their trade outcome
    all_crossovers = []
    
    for dt_str in DATES:
        spot_bars, opt_candles = r.load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60: continue
        
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        res_2m = resample_two_minutes(spot_bars)
        closes_2m = [x["close"] for x in res_2m]
        macd, sig, hist = calculate_macd(closes_2m)
        
        orh = max(x["high"] for x in spot_bars[:15])
        orl = min(x["low"] for x in spot_bars[:15])
        
        for i in range(26, len(res_2m)):
            end_1m = res_2m[i]["minute_idx"]
            if end_1m > 330: continue
            
            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
            if not (pe_cross or ce_cross): continue
            
            direction = "PE" if pe_cross else "CE"
            spot_p = res_2m[i]["close"]
            bars_so_far = spot_bars[:end_1m + 1]
            t_now = exchange_time(bars_so_far[-1]["start_time"]) + timedelta(minutes=1)
            time_hm = t_now.strftime("%H:%M")
            
            vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
            dist_vwap = spot_p - vwap
            
            # 15m Range
            box_15 = bars_so_far[max(0, end_1m - 14): end_1m + 1]
            box_spread = max(x["high"] for x in box_15) - min(x["low"] for x in box_15)
            
            # Check individual filter flags:
            hist_val = abs(hist[i])
            pass_hist = (hist_val >= 0.20)
            
            candle_body = res_2m[i]["close"] - res_2m[i]["open"]
            pass_candle = (direction == "CE" and candle_body >= 0) or (direction == "PE" and candle_body <= 0)
            
            pass_vwap_flow = not ((direction == "CE" and spot_p < vwap - 12.0) or (direction == "PE" and spot_p > vwap + 12.0))
            
            pass_climax = (abs(dist_vwap) < 50.0)
            
            # Opening Range filter
            dist_or = (spot_p - orl) if direction == "PE" else (orh - spot_p)
            pass_or = not (0.0 <= dist_or <= 8.0)
            
            # Midday dead zone (11:30 - 13:15)
            is_midday = (135 <= end_1m <= 240)
            pass_midday = not (is_midday and box_spread < 24.0)
            
            pass_cutoff = (time_hm < "14:15")
            
            # Strict ITM Strike
            strike = select_strike(spot_p, direction, "STRICT_ITM")
            if strike == spot_p: strike += -50 if direction == "CE" else 50
            
            strike_macd_data = r.compute_strike_macd(spot_bars, strike, direction, end_1m, days_base, opt_candles)
            pass_strike_macd = strike_macd_data.get("expanding_positive", True) or strike_macd_data.get("histogram", 0) >= 0
            
            # Simulate trade outcome if taken
            next_idx = end_1m + 1
            if next_idx >= len(spot_bars) - 1: continue
            entry_p = r.get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
            if entry_p <= 5.0: continue
            
            # 25-pt Spot buffer
            recent = spot_bars[max(0, end_1m - 5): end_1m + 1]
            if direction == "CE":
                inval_spot = min(min(x["low"] for x in recent) - 2.0, spot_p - 25.0)
            else:
                inval_spot = max(max(x["high"] for x in recent) + 2.0, spot_p + 25.0)
                
            known_floor = entry_p * 0.75 # 25% initial
            peak_bid = entry_p
            exit_p = entry_p
            exit_reason = "1515_HARD_SQUAREOFF"
            
            for m in range(next_idx + 1, min(len(spot_bars), 365)):
                sb = spot_bars[m]
                now_hm = exchange_time(sb["start_time"]).strftime("%H:%M")
                if now_hm >= "15:15":
                    exit_p = r.get_option_price(sb["open"], strike, direction, m, days_base, opt_candles, spot_bars)[0]
                    break
                m_open, m_high, m_low, m_close = r.get_option_price(sb["close"], strike, direction, m, days_base, opt_candles, spot_bars)
                if m_high > peak_bid: peak_bid = m_high
                gain_pct = ((peak_bid - entry_p) / entry_p) * 100.0
                
                if direction == "CE" and sb["low"] <= inval_spot:
                    exit_p = m_close
                    exit_reason = "SPOT_INVALIDATION"
                    break
                elif direction == "PE" and sb["high"] >= inval_spot:
                    exit_p = m_close
                    exit_reason = "SPOT_INVALIDATION"
                    break
                    
                session_window, session_stop, session_label = session_trigger(entry_p, peak_bid, exit_cfg, now_hm)
                if session_stop is not None:
                    known_floor = max(known_floor, session_stop)
                elif not session_window and exit_cfg.get("runner_trailing_enabled", True) and gain_pct >= exit_cfg.get("runner_activation_pct", 15.0):
                    runner_stop = runner_trigger(entry_p, peak_bid, exit_cfg)
                    known_floor = max(known_floor, runner_stop)
                    
                if m_low <= known_floor:
                    exit_p = known_floor
                    exit_reason = "DYNAMIC_STOP" if known_floor > entry_p * 0.75 else "INITIAL_STOP"
                    break
                    
            pnl_pts = exit_p - entry_p
            pnl_2lots = pnl_pts * 130 - 40.0
            is_win = (pnl_pts > 0)
            
            all_crossovers.append({
                "date": dt_str, "time": time_hm, "minute_idx": end_1m,
                "direction": direction, "strike": strike, "entry_p": entry_p, "exit_p": exit_p,
                "peak_gain_pct": gain_pct, "pnl_2lots": pnl_2lots, "is_win": is_win,
                "exit_reason": exit_reason, "box_spread": box_spread, "hist": hist_val,
                "candle_body": candle_body, "dist_vwap": dist_vwap, "dist_or": dist_or,
                "pass_hist": pass_hist, "pass_candle": pass_candle, "pass_vwap_flow": pass_vwap_flow,
                "pass_climax": pass_climax, "pass_or": pass_or, "pass_midday": pass_midday,
                "pass_cutoff": pass_cutoff, "pass_strike_macd": pass_strike_macd
            })

    print(f"Total Raw 2m MACD Crossovers Identified across 30 sessions: {len(all_crossovers)}")
    wins = [x for x in all_crossovers if x["is_win"]]
    losses = [x for x in all_crossovers if not x["is_win"]]
    print(f"Raw Crossover Baseline: {len(wins)} Wins / {len(losses)} Losses ({len(wins)/len(all_crossovers)*100:.1f}% WR)")
    
    with open("scratch/all_raw_crossovers_simulated.json", "w") as fp:
        json.dump(all_crossovers, fp, indent=2)

if __name__ == "__main__":
    analyze_all_crossovers()
