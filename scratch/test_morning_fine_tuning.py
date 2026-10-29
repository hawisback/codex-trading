import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import json
import scratch.audit_macd_full_backtest as b

# Let's test different morning trailing curves:
# Curve 0: Baseline (No trail until +15% / +20%)
# Curve 1: Soft Ratchet (at +8% peak -> stop becomes -8%; at +12% peak -> stop becomes 0% breakeven; at +16% -> stop becomes +6%; at +25% -> trail 10%)
# Curve 2: Medium Ratchet (at +7% peak -> stop becomes -5%; at +10% peak -> stop becomes +1.5%; at +15% -> stop becomes +8%)
# Curve 3: Opening Range Filter + Curve 1

def run_curve_test(curve_id: int):
    trades = []
    for dt_str in b.DATES:
        spot_bars, opt_candles = b.load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60: continue
        
        target_d = b.datetime.strptime(dt_str, "%Y-%m-%d").date()
        expiry_d = target_d + b.timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        res_2m = b.resample_two_minutes(spot_bars)
        closes_2m = [x["close"] for x in res_2m]
        macd, sig, hist = b.calculate_macd(closes_2m)
        
        in_trade_until = -1
        session_trades_count = 0
        
        # Opening 15m range (09:15 - 09:30)
        orh = max(x["high"] for x in spot_bars[:15])
        orl = min(x["low"] for x in spot_bars[:15])
        
        for i in range(26, len(res_2m)):
            end_1m = res_2m[i]["minute_idx"]
            if end_1m < in_trade_until or end_1m > 300: continue
            if session_trades_count >= 2: break
            
            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
            if not (pe_cross or ce_cross): continue
            if abs(hist[i]) < 0.20: continue
            
            direction = "PE" if pe_cross else "CE"
            spot_p = res_2m[i]["close"]
            
            candle_body = res_2m[i]["close"] - res_2m[i]["open"]
            if direction == "CE" and candle_body < 0: continue
            if direction == "PE" and candle_body > 0: continue
            
            bars_so_far = spot_bars[:end_1m + 1]
            vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
            
            if direction == "CE" and spot_p < vwap - 12.0: continue
            if direction == "PE" and spot_p > vwap + 12.0: continue
            
            if curve_id == 3:
                # Opening range filter
                if direction == "PE" and 0.0 <= (spot_p - orl) <= 8.0: continue
                if direction == "CE" and 0.0 <= (orh - spot_p) <= 8.0: continue
                if abs(spot_p - vwap) > 50.0: continue
                
            atm_strike = int(round(spot_p / 50.0)) * 50
            strike = atm_strike - 50 if direction == "CE" else atm_strike + 50
            
            strike_macd_data = b.compute_strike_macd(spot_bars, strike, direction, end_1m, days_base, opt_candles)
            if not strike_macd_data.get("expanding_positive", True) and strike_macd_data.get("histogram", 0) < 0:
                continue
                
            next_idx = end_1m + 1
            if next_idx >= len(spot_bars) - 1: continue
            entry_p = b.get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
            if entry_p <= 5.0: continue
            
            recent = spot_bars[max(0, end_1m - 5): end_1m + 1]
            if direction == "CE":
                inval_spot = min(min(x["low"] for x in recent) - 2.0, spot_p - 25.0)
            else:
                inval_spot = max(max(x["high"] for x in recent) + 2.0, spot_p + 25.0)
                
            peak_p = entry_p
            exit_p = entry_p
            exit_reason = "1515_EOD"
            is_midday_trade = (135 <= end_1m <= 240)
            is_morning_trade = (end_1m < 135)
            
            for m in range(next_idx + 1, min(len(spot_bars), 365)):
                sb = spot_bars[m]
                hh = (m + 15) // 60 + 9
                mm = (m + 15) % 60
                if hh > 15 or (hh == 15 and mm >= 15):
                    exit_p = b.get_option_price(sb["open"], strike, direction, m, days_base, opt_candles, spot_bars)[0]
                    break
                m_open, m_high, m_low, m_close = b.get_option_price(sb["close"], strike, direction, m, days_base, opt_candles, spot_bars)
                if m_high > peak_p: peak_p = m_high
                gain_pct = ((peak_p - entry_p) / entry_p) * 100.0
                
                if direction == "CE" and sb["low"] <= inval_spot:
                    exit_p = m_close
                    exit_reason = "SPOT_INVALIDATION"
                    break
                elif direction == "PE" and sb["high"] >= inval_spot:
                    exit_p = m_close
                    exit_reason = "SPOT_INVALIDATION"
                    break
                    
                stop_p = entry_p * 0.75 # 25% initial
                
                # Midday 5% Micro-Trail
                if is_midday_trade:
                    if gain_pct >= 5.0:
                        midday_floor = max(entry_p * 1.015, peak_p * 0.975)
                        stop_p = max(stop_p, midday_floor)
                elif is_morning_trade:
                    if curve_id in (1, 3):
                        # Curve 1: Soft Ratchet
                        # At +8% peak -> stop becomes -8%
                        if gain_pct >= 8.0: stop_p = max(stop_p, entry_p * 0.92)
                        # At +12% peak -> stop becomes breakeven (+0.5%)
                        if gain_pct >= 12.0: stop_p = max(stop_p, entry_p * 1.005)
                        # At +16% peak -> stop becomes +6%
                        if gain_pct >= 16.0: stop_p = max(stop_p, entry_p * 1.06)
                        # At +25% peak -> trail 10%
                        if gain_pct >= 25.0: stop_p = max(stop_p, entry_p * 1.15, peak_p * 0.90)
                    elif curve_id == 2:
                        # Curve 2: Medium Ratchet
                        if gain_pct >= 7.0: stop_p = max(stop_p, entry_p * 0.95)
                        if gain_pct >= 10.0: stop_p = max(stop_p, entry_p * 1.015)
                        if gain_pct >= 15.0: stop_p = max(stop_p, entry_p * 1.08, peak_p * 0.92)
                    else:
                        # Baseline
                        if gain_pct >= 15.0: stop_p = max(stop_p, entry_p * 1.00)
                
                # Standard higher runner tiers
                if gain_pct >= 50.0: stop_p = max(stop_p, peak_p * 0.95)
                elif gain_pct >= 40.0: stop_p = max(stop_p, entry_p * 1.30)
                elif gain_pct >= 30.0: stop_p = max(stop_p, entry_p * 1.20)
                elif gain_pct >= 20.0: stop_p = max(stop_p, entry_p * 1.10)
                if gain_pct >= 20.0: stop_p = max(stop_p, peak_p * 0.90)
                
                if m_low <= stop_p:
                    exit_p = stop_p
                    exit_reason = "DYNAMIC_STOP" if stop_p > entry_p else "INITIAL_STOP"
                    break
                    
            pnl_pts = exit_p - entry_p
            pnl_inr = pnl_pts * 130 - 40.0
            trades.append({
                "date": dt_str, "time": f"{(end_1m+15)//60+9:02d}:{(end_1m+15)%60:02d}",
                "direction": direction, "is_midday": is_midday_trade, "is_morning": is_morning_trade,
                "entry_p": entry_p, "exit_p": exit_p, "peak_gain_pct": gain_pct,
                "pnl_inr": pnl_inr, "is_win": pnl_pts > 0, "exit_reason": exit_reason
            })
            session_trades_count += 1
            in_trade_until = end_1m + 15
            
    tot = len(trades)
    wins = [t for t in trades if t["is_win"]]
    wr = len(wins) / tot * 100.0 if tot else 0.0
    tot_pnl = sum(t["pnl_inr"] for t in trades)
    
    morn = [t for t in trades if t["is_morning"]]
    morn_w = [t for t in morn if t["is_win"]]
    morn_wr = len(morn_w) / len(morn) * 100.0 if morn else 0.0
    morn_pnl = sum(t["pnl_inr"] for t in morn)
    
    mid = [t for t in trades if t["is_midday"]]
    mid_w = [t for t in mid if t["is_win"]]
    mid_wr = len(mid_w) / len(mid) * 100.0 if mid else 0.0
    mid_pnl = sum(t["pnl_inr"] for t in mid)
    
    labels = {
        0: "Curve 0: Baseline (Std Trail at +15%)",
        1: "Curve 1: Soft Ratchet (+8% -> -8% SL, +12% -> BE, +16% -> +6% Floor, +25% -> Trail 10%)",
        2: "Curve 2: Medium Ratchet (+7% -> -5% SL, +10% -> +1.5% Floor, +15% -> Trail)",
        3: "Curve 3: Opening Range Filter + Curve 1 Soft Ratchet"
    }
    
    print("\n" + "=" * 95)
    print(f"📈 {labels[curve_id]}")
    print("=" * 95)
    print(f"  Overall:  {tot} Trades | {len(wins)} Wins / {tot - len(wins)} Losses | Win Rate: {wr:.1f}% | Net PnL (2L): Rs {tot_pnl:+,.2f}")
    print(f"  Morning:  {len(morn)} Trades | {len(morn_w)} Wins / {len(morn) - len(morn_w)} Losses | Win Rate: {morn_wr:.1f}% | Morning PnL: Rs {morn_pnl:+,.2f}")
    print(f"  Midday:   {len(mid)} Trades | {len(mid_w)} Wins / {len(mid) - len(mid_w)} Losses | Win Rate: {mid_wr:.1f}% | Midday PnL: Rs {mid_pnl:+,.2f}")

if __name__ == "__main__":
    for c in [0, 1, 2, 3]:
        run_curve_test(c)
