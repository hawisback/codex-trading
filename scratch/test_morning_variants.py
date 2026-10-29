import json
import os
import sys

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

import scratch.run_production_backtest_30_sessions as r
from trading.domain.market_data import exchange_time
from trading.strategies.macd_momentum import calculate_macd
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from trading.domain.indicators import select_strike
from trading.domain.trailing import session_trigger, runner_trigger
from datetime import datetime, timedelta

def build_rolling_2m(candles):
    bars = []
    for i in range(1, len(candles)):
        c1 = candles[i - 1]
        c2 = candles[i]
        bars.append({
            "start_time": c1["start_time"],
            "open": c1["open"],
            "high": max(c1["high"], c2["high"]),
            "low": min(c1["low"], c2["low"]),
            "close": c2["close"],
            "volume": c1.get("volume", 0) + c2.get("volume", 0)
        })
    return bars

def test_morning_variants(min_hist_early=0.20, require_orb_break=False, start_min=15):
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    exit_cfg = strat_cfg["exit"]
    trading_cfg = json.load(open("config/trading.json"))
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    all_trades = []
    
    for d_idx, dt_str in enumerate(r.DATES):
        spot_bars, opt_candles = r.load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60: continue
        
        prior_bars = []
        if d_idx > 0:
            prior_bars, _ = r.load_session_data(r.DATES[d_idx - 1])
        if not prior_bars:
            prior_bars = spot_bars[:60]
        warmup_bars = prior_bars[-60:]
        
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        session_trades_count = 0
        in_trade_until = -1
        
        orh = max(x["high"] for x in spot_bars[:15])
        orl = min(x["low"] for x in spot_bars[:15])
        
        for i in range(start_min, min(len(spot_bars) - 1, 300)):
            if i < in_trade_until: continue
            if session_trades_count >= 2: break
            
            bars_today = spot_bars[:i + 1]
            t_now = exchange_time(bars_today[-1]["start_time"]) + timedelta(minutes=1)
            time_hm = t_now.strftime("%H:%M")
            if time_hm >= "14:15": break
            
            combined = warmup_bars + bars_today
            bars_2m = build_rolling_2m(combined)
            closes_2m = [x["close"] for x in bars_2m]
            macd, sig, hist = calculate_macd(closes_2m)
            
            pe_cross = (macd[-1] < sig[-1]) and (macd[-2] >= sig[-2])
            ce_cross = (macd[-1] > sig[-1]) and (macd[-2] <= sig[-2])
            if not (pe_cross or ce_cross): continue
            
            # Hist threshold
            thresh = min_hist_early if i < 45 else 0.20
            if abs(hist[-1]) < thresh: continue
            
            direction = "PE" if pe_cross else "CE"
            spot_p = bars_today[-1]["close"]
            
            latest_2m = bars_2m[-1]
            body_2m = latest_2m["close"] - latest_2m["open"]
            if direction == "CE" and body_2m < 0: continue
            if direction == "PE" and body_2m > 0: continue
            
            vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_today) / len(bars_today)
            dist_vwap = abs(spot_p - vwap)
            if direction == "CE" and spot_p < vwap - 12.0: continue
            if direction == "PE" and spot_p > vwap + 12.0: continue
            if dist_vwap >= 72.0: continue
            
            if require_orb_break and i < 45: # Before 10:00 AM
                # Must break OR by at least 1 pt
                if direction == "CE" and spot_p <= orh: continue
                if direction == "PE" and spot_p >= orl: continue
            else:
                if direction == "PE" and 0.0 <= (spot_p - orl) <= 8.0: continue
                if direction == "CE" and 0.0 <= (orh - spot_p) <= 8.0: continue
                
            if 135 <= i <= 240:
                box_15 = bars_today[max(0, i - 14): i + 1]
                box_spread = max(x["high"] for x in box_15) - min(x["low"] for x in box_15)
                if box_spread < 18.0: continue
                
            strike = select_strike(spot_p, direction, "STRICT_ITM")
            if strike == spot_p: strike += -50 if direction == "CE" else 50
            
            strike_macd_data = r.compute_strike_macd(spot_bars, strike, direction, i, days_base, opt_candles)
            if not strike_macd_data.get("expanding_positive", True) and strike_macd_data.get("histogram", 0) < 0:
                continue
                
            dossier = generate_market_dossier(
                target_date=dt_str, candles=bars_today, current_bar_idx=i,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dossier)
            if not v.is_approved: continue
            
            next_idx = i + 1
            if next_idx >= len(spot_bars) - 1: continue
            entry_p = r.get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
            if entry_p <= 5.0: continue
            
            recent = spot_bars[max(0, i - 5): i + 1]
            if direction == "CE":
                inval_spot = min(min(x["low"] for x in recent) - 2.0, spot_p - 25.0)
            else:
                inval_spot = max(max(x["high"] for x in recent) + 2.0, spot_p + 25.0)
                
            initial_stop_p = entry_p * (1.0 - exit_cfg.get("initial_stop_pct", 25.0) / 100.0)
            known_floor = initial_stop_p
            peak_bid = entry_p
            exit_p = entry_p
            exit_reason = "1515_HARD_SQUAREOFF"
            exit_bar_idx = next_idx
            
            for m in range(next_idx + 1, min(len(spot_bars), 365)):
                sb = spot_bars[m]
                now_hm = exchange_time(sb["start_time"]).strftime("%H:%M")
                if now_hm >= "15:15":
                    exit_p = r.get_option_price(sb["open"], strike, direction, m, days_base, opt_candles, spot_bars)[0]
                    exit_bar_idx = m
                    break
                    
                m_open, m_high, m_low, m_close = r.get_option_price(sb["close"], strike, direction, m, days_base, opt_candles, spot_bars)
                if m_high > peak_bid: peak_bid = m_high
                gain_pct = ((peak_bid - entry_p) / entry_p) * 100.0
                
                if direction == "CE" and sb["low"] <= inval_spot:
                    exit_p = m_close
                    exit_reason = "SPOT_INVALIDATION"
                    exit_bar_idx = m
                    break
                elif direction == "PE" and sb["high"] >= inval_spot:
                    exit_p = m_close
                    exit_reason = "SPOT_INVALIDATION"
                    exit_bar_idx = m
                    break
                    
                session_window, session_stop, session_label = session_trigger(entry_p, peak_bid, exit_cfg, now_hm)
                if session_stop is not None:
                    known_floor = max(known_floor, session_stop)
                    trigger_label = session_label
                elif not session_window and exit_cfg.get("runner_trailing_enabled", True) and gain_pct >= exit_cfg.get("runner_activation_pct", 15.0):
                    runner_stop = runner_trigger(entry_p, peak_bid, exit_cfg)
                    known_floor = max(known_floor, runner_stop)
                    trigger_label = "DYNAMIC_RUNNER_RATCHET"
                else:
                    trigger_label = "INITIAL_STOP"
                    
                if m_low <= known_floor:
                    exit_p = known_floor
                    exit_reason = f"{trigger_label} ({known_floor:.2f})" if known_floor > initial_stop_p else "INITIAL_STOP"
                    exit_bar_idx = m
                    break
                    
            pnl_pts = exit_p - entry_p
            pnl_2lots = pnl_pts * 130 - 40.0
            entry_time_str = exchange_time(spot_bars[next_idx]["start_time"]).strftime("%H:%M")
            exit_time_str = exchange_time(spot_bars[exit_bar_idx]["start_time"]).strftime("%H:%M")
            
            all_trades.append({
                "date": dt_str, "entry_time": entry_time_str, "exit_time": exit_time_str,
                "direction": direction, "strike": strike, "entry_p": entry_p, "exit_p": exit_p,
                "peak_gain_pct": gain_pct, "pnl_2lots": pnl_2lots, "is_win": pnl_pts > 0, "exit_reason": exit_reason
            })
            session_trades_count += 1
            in_trade_until = exit_bar_idx + 10
            
    tot = len(all_trades)
    wins = [t for t in all_trades if t["is_win"]]
    losses = [t for t in all_trades if not t["is_win"]]
    wr = len(wins) / tot * 100.0 if tot else 0.0
    tot_pnl = sum(t["pnl_2lots"] for t in all_trades)
    gross_w = sum(t["pnl_2lots"] for t in wins)
    gross_l = abs(sum(t["pnl_2lots"] for t in losses))
    pf = (gross_w / gross_l) if gross_l > 0 else 999.0
    return {"trades": tot, "wins": len(wins), "losses": len(losses), "wr": wr, "pnl": tot_pnl, "pf": pf}

if __name__ == "__main__":
    runs = [
        ("Start 09:30 AM (Hist 0.20, No ORB)", dict(min_hist_early=0.20, require_orb_break=False, start_min=15)),
        ("Start 09:30 AM (Hist 0.50 Early, No ORB)", dict(min_hist_early=0.50, require_orb_break=False, start_min=15)),
        ("Start 09:30 AM (Hist 0.80 Early, No ORB)", dict(min_hist_early=0.80, require_orb_break=False, start_min=15)),
        ("Start 09:30 AM (Require ORB Break < 10:00)", dict(min_hist_early=0.20, require_orb_break=True, start_min=15)),
        ("Start 09:45 AM (Clean Start)", dict(min_hist_early=0.20, require_orb_break=False, start_min=30)),
        ("Start 09:50 AM (Clean Start)", dict(min_hist_early=0.20, require_orb_break=False, start_min=35)),
        ("Start 09:55 AM (Clean Start)", dict(min_hist_early=0.20, require_orb_break=False, start_min=40)),
    ]
    for label, kw in runs:
        res = test_morning_variants(**kw)
        print(f"{label:45} | {res['trades']:2d} Trades | {res['wins']:2d}W / {res['losses']:2d}L ({res['wr']:4.1f}%) | PF: {res['pf']:4.2f} | PnL: Rs {res['pnl']:+10.2f}")
