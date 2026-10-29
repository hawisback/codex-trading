import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()

from scratch.test_macd_ema_combination import load_session, calculate_ema, calculate_macd, calculate_rsi, DATES
from trading.domain.market_data import resample_two_minutes, resample_five_minutes
from ai_opportunity_radar import AIOpportunityRadar

def inspect_hybrid_trades():
    radar = AIOpportunityRadar()
    
    print("=" * 110)
    print("  DETAILED TRADE-BY-TRADE AUDIT: HYBRID MODELS (OCT 19 - OCT 27, 2026)")
    print("=" * 110)
    
    hybrid2_trades = []
    
    for date_str, label in DATES:
        bars = load_session(date_str)
        if not bars or len(bars) < 60:
            continue
            
        res_2m = resample_two_minutes(bars)
        closes_2m = [b["close"] for b in res_2m]
        macd_line, sig_line, hist_2m = calculate_macd(closes_2m)
        
        res_5m = resample_five_minutes(bars)
        closes_5m = [b["close"] for b in res_5m]
        ema9_5m_series = calculate_ema(closes_5m, 9)
        ema20_5m_series = calculate_ema(closes_5m, 20)
        
        last_entry_m = -999
        
        for m_idx in range(30, len(bars) - 15):
            bar = bars[m_idx]
            spot = bar["close"]
            time_str = bar.get("start_time", "")[11:16]
            
            m_2m_idx = (m_idx // 2)
            if m_2m_idx >= len(macd_line):
                continue
            macd_cur = macd_line[m_2m_idx]
            sig_cur = sig_line[m_2m_idx]
            macd_prev = macd_line[m_2m_idx - 1] if m_2m_idx > 0 else macd_cur
            sig_prev = sig_line[m_2m_idx - 1] if m_2m_idx > 0 else sig_cur
            
            m_5m_idx = (m_idx // 5)
            if m_5m_idx >= len(ema9_5m_series):
                continue
            ema9_5m = ema9_5m_series[m_5m_idx]
            ema20_5m = ema20_5m_series[m_5m_idx]
            
            macd_cross_ce = (macd_prev <= sig_prev) and (macd_cur > sig_cur) and (m_idx % 2 == 1)
            macd_cross_pe = (macd_prev >= sig_prev) and (macd_cur < sig_cur) and (m_idx % 2 == 1)
            
            is_near_ema = abs(spot - ema9_5m) <= 10.0
            
            # Hybrid 2 logic: 2m MACD crossover + EMA9 Nearness + EMA20 alignment
            signal = None
            if macd_cross_ce and is_near_ema and spot > ema20_5m:
                signal = "BUY_CE"
            elif macd_cross_pe and is_near_ema and spot < ema20_5m:
                signal = "BUY_PE"
                
            if signal and (m_idx - last_entry_m >= 10):
                last_entry_m = m_idx
                forward_bars = bars[m_idx + 1: min(len(bars), m_idx + 21)]
                if signal == "BUY_CE":
                    mfe = max(b["high"] for b in forward_bars) - spot
                    mae = spot - min(b["low"] for b in forward_bars)
                    net_15m = forward_bars[-1]["close"] - spot
                else:
                    mfe = spot - min(b["low"] for b in forward_bars)
                    mae = max(b["high"] for b in forward_bars) - spot
                    net_15m = spot - forward_bars[-1]["close"]
                    
                hybrid2_trades.append({
                    "date": date_str,
                    "time": time_str,
                    "signal": signal,
                    "spot": spot,
                    "ema9": ema9_5m,
                    "ema20": ema20_5m,
                    "mfe": mfe,
                    "mae": mae,
                    "net_15m": net_15m,
                    "win": mfe >= 25.0 and mae <= 20.0
                })

    print(f"{'Date':<12} | {'Time':<6} | {'Signal':<7} | {'Spot':<9} | {'5m EMA9':<9} | {'5m EMA20':<9} | {'Max Peak (MFE)':<15} | {'Max Dip (MAE)':<14} | {'15m Net':<9} | {'Outcome'}")
    print("-" * 115)
    for t in hybrid2_trades:
        out = "WIN (+)" if t["win"] else ("LOSS (-)" if t["mae"] > 20.0 else "SCRATCH")
        print(f"{t['date']:<12} | {t['time']:<6} | {t['signal']:<7} | {t['spot']:<9.1f} | {t['ema9']:<9.1f} | {t['ema20']:<9.1f} | +{t['mfe']:<14.1f} | -{t['mae']:<13.1f} | {t['net_15m']:<+8.1f} | {out}")

if __name__ == "__main__":
    inspect_hybrid_trades()
