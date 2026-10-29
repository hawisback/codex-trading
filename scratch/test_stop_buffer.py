import json
import os
import sys

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from trading.domain.market_data import resample_two_minutes
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

def run_test(min_inval_buffer_pts: float):
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    trades = []
    
    for dt_str in DATES:
        spot_bars, opt_candles = load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60: continue
        
        # Calculate expiry days
        from datetime import datetime, timedelta
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        res_2m = resample_two_minutes(spot_bars)
        closes_2m = [b["close"] for b in res_2m]
        macd, sig, hist = calculate_macd(closes_2m)
        
        in_trade_until = -1
        
        for i in range(26, len(res_2m)):
            end_1m = res_2m[i]["minute_idx"]
            if end_1m < in_trade_until or end_1m > 300: continue
            
            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
            if not (pe_cross or ce_cross): continue
            
            direction = "PE" if pe_cross else "CE"
            spot_p = res_2m[i]["close"]
            
            # 2m Candle alignment check (Green for CE, Red for PE)
            candle_body = res_2m[i]["close"] - res_2m[i]["open"]
            if (direction == "CE" and candle_body < 0) or (direction == "PE" and candle_body > 0):
                continue # Skip counter-candle fakeouts
                
            atm_strike = int(round(spot_p / 50.0)) * 50
            # Strict ITM Strike (50 pts ITM) for real delta
            strike = atm_strike - 50 if direction == "CE" else atm_strike + 50
            
            dossier = generate_market_dossier(
                target_date=dt_str, candles=spot_bars[:end_1m + 1], current_bar_idx=end_1m,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dossier)
            if not v.is_approved: continue
            
            # Entry next bar
            next_idx = end_1m + 1
            if next_idx >= len(spot_bars) - 1: continue
            entry_p = get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
            if entry_p <= 5.0: continue
            
            # Invalidation spot level: Swing extreme WITH min_inval_buffer_pts (at least 15-20 pts)
            recent = spot_bars[max(0, end_1m - 5): end_1m + 1]
            if direction == "CE":
                inval_spot = min(min(b["low"] for b in recent) - 2.0, spot_p - min_inval_buffer_pts)
            else:
                inval_spot = max(max(b["high"] for b in recent) + 2.0, spot_p + min_inval_buffer_pts)
                
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
                    
                # Dynamic Stop Loss
                stop_p = entry_p * 0.75 # 25% initial
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
            pnl_inr = pnl_pts * 130 - 40.0
            trades.append({"is_win": pnl_pts > 0, "pnl_inr": pnl_inr, "pnl_pts": pnl_pts})
            in_trade_until = end_1m + 15

    tot = len(trades)
    w = len([t for t in trades if t["is_win"]])
    wr = w / tot * 100 if tot else 0
    tot_pnl = sum(t["pnl_inr"] for t in trades)
    print(f"Min Inval Buffer {min_inval_buffer_pts:4.1f} pts: {tot:3d} trades | {w:2d} Wins (WR: {wr:4.1f}%) | Net PnL (2 lots): Rs {tot_pnl:+10,.2f}")

print("Testing different structural invalidation buffers on 2m MACD Crossover:")
for buf in [5.0, 15.0, 20.0, 25.0, 30.0]:
    run_test(buf)
