import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import json, os
from datetime import datetime, timedelta
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from trading.domain.market_data import resample_two_minutes, two_minute_macd_metrics
from trading.strategies.macd_momentum import calculate_macd
import scratch.audit_macd_full_backtest as b

def test_morning_variations():
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    # Let's test 4 configurations:
    # Baseline: Current (no morning micro-trail, midday 5% active)
    # Config 1: Morning Breakeven at +6% (Lock +0.5% floor)
    # Config 2: Morning Progressive Trail (BE at +6%, at +10% lock +4% & trail 3%)
    # Config 3: Opening Range Filter (Veto PE within 10 pts of 15m OR Low, Veto CE within 10 pts of 15m OR High) + Extended VWAP (>50 pts)
    # Config 4: Both Config 2 + Config 3 combined!
    
    for cfg_id in [0, 1, 2, 3, 4]:
        trades = []
        for dt_str in b.DATES:
            spot_bars, opt_candles = b.load_session_data(dt_str)
            if not spot_bars or len(spot_bars) < 60: continue
            
            target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
            days_base = max(0.1, float((expiry_d - target_d).days))
            is_0dte = (target_d.weekday() == 1)
            
            res_2m = resample_two_minutes(spot_bars)
            closes_2m = [x["close"] for x in res_2m]
            macd, sig, hist = calculate_macd(closes_2m)
            
            in_trade_until = -1
            session_trades_count = 0
            
            # Opening 15m range (bars 0 to 14)
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
                
                # 2m Candle alignment
                candle_body = res_2m[i]["close"] - res_2m[i]["open"]
                if direction == "CE" and candle_body < 0: continue
                if direction == "PE" and candle_body > 0: continue
                
                bars_so_far = spot_bars[:end_1m + 1]
                vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
                
                # VWAP flow
                if direction == "CE" and spot_p < vwap - 12.0: continue
                if direction == "PE" and spot_p > vwap + 12.0: continue
                
                # Config 3 & 4 Filter: Opening Range Support/Resistance & Climax VWAP
                if cfg_id in (3, 4):
                    # Climax extension > 50 pts
                    if abs(spot_p - vwap) > 50.0: continue
                    # Opening Range bounce traps (within 10 pts of OR Low for PE, or OR High for CE)
                    if direction == "PE" and (spot_p - orl) < 10.0 and (spot_p - orl) >= -5.0: continue
                    if direction == "CE" and (orh - spot_p) < 10.0 and (orh - spot_p) >= -5.0: continue
                
                # Strict ITM Strike
                atm_strike = int(round(spot_p / 50.0)) * 50
                strike = atm_strike - 50 if direction == "CE" else atm_strike + 50
                
                # Strike 2m MACD Confluence Check
                strike_macd_data = b.compute_strike_macd(spot_bars, strike, direction, end_1m, days_base, opt_candles)
                if not strike_macd_data.get("expanding_positive", True) and strike_macd_data.get("histogram", 0) < 0:
                    continue
                    
                dossier = generate_market_dossier(
                    target_date=dt_str, candles=bars_so_far, current_bar_idx=end_1m,
                    direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                    option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
                )
                v = consultant.evaluate(dossier)
                if not v.is_approved: continue
                
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
                        if cfg_id == 1:
                            # Config 1: Morning Breakeven at +6%
                            if gain_pct >= 6.0:
                                stop_p = max(stop_p, entry_p * 1.005)
                        elif cfg_id in (2, 4):
                            # Config 2 & 4: Morning Progressive Trail (BE at +6%, at +10% lock +4% & trail 3%)
                            if gain_pct >= 10.0:
                                morn_floor = max(entry_p * 1.04, peak_p * 0.97)
                                stop_p = max(stop_p, morn_floor)
                            elif gain_pct >= 6.0:
                                stop_p = max(stop_p, entry_p * 1.005)
                    
                    # Standard higher runner tiers
                    if gain_pct >= 50.0: stop_p = max(stop_p, peak_p * 0.95)
                    elif gain_pct >= 40.0: stop_p = max(stop_p, entry_p * 1.30)
                    elif gain_pct >= 30.0: stop_p = max(stop_p, entry_p * 1.20)
                    elif gain_pct >= 20.0: stop_p = max(stop_p, entry_p * 1.10)
                    elif gain_pct >= 15.0 and not is_midday_trade and cfg_id == 0:
                        stop_p = max(stop_p, entry_p * 1.00)
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
        
        names = {
            0: "Baseline: Refined + Midday 5% Trail (No Morning Trailing)",
            1: "Config 1: Morning Breakeven Lock at +6% Gain",
            2: "Config 2: Morning Progressive Trailing (+6% Breakeven, +10% Lock +4% & Trail 3%)",
            3: "Config 3: Opening Range Bounce Trap Filter + Climax VWAP (>50 pts)",
            4: "Config 4: Full Optimization (Progressive Trailing + Range/Climax Filters)"
        }
        
        print("\n" + "=" * 90)
        print(f"🔬 {names[cfg_id]}")
        print("=" * 90)
        print(f"  Overall:  {tot} Trades | {len(wins)} Wins / {tot - len(wins)} Losses | Win Rate: {wr:.1f}% | Net PnL (2L): Rs {tot_pnl:+,.2f}")
        print(f"  Morning:  {len(morn)} Trades | {len(morn_w)} Wins / {len(morn) - len(morn_w)} Losses | Win Rate: {morn_wr:.1f}% | Morning PnL: Rs {morn_pnl:+,.2f}")
        print(f"  Midday:   {len(mid)} Trades | {len(mid_w)} Wins / {len(mid) - len(mid_w)} Losses | Win Rate: {mid_wr:.1f}% | Midday PnL: Rs {mid_pnl:+,.2f}")

if __name__ == "__main__":
    test_morning_variations()
