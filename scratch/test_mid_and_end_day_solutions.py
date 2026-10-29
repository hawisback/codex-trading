import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

from market_clock import MarketClock
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from trading.domain.indicators import select_strike
from trading.domain.market_data import exchange_time
from trading.domain.trailing import session_trigger, runner_trigger
from trading.strategies.macd_momentum import MacdMomentumStrategy
import scratch.run_production_backtest_30_sessions as r

DATES = r.DATES

def simulate_with_params(
    # Midday params
    midday_stop_pct=25.0,
    midday_inval_pts=25.0,
    midday_min_hist=0.20,
    midday_cutoff_time="13:15",
    allow_midday=True,
    
    # Afternoon params
    afternoon_be_gain_pct=7.0,
    afternoon_be_floor_pct=1.0,
    afternoon_stop_pct=25.0,
    afternoon_inval_pts=25.0,
    allow_afternoon=True,
):
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    exit_cfg = strat_cfg["exit"]
    
    strategy = MacdMomentumStrategy(strat_cfg)
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    all_trades = []
    capital = 10000.0
    
    for d_idx, dt_str in enumerate(DATES):
        spot_bars, opt_candles = r.load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60: continue
        
        prior_bars = []
        if d_idx > 0:
            prior_bars, _ = r.load_session_data(DATES[d_idx - 1])
        if not prior_bars:
            prior_bars = spot_bars[:60]
        warmup_candles = prior_bars[-100:] if len(prior_bars) >= 100 else prior_bars
        
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        session_trades_count = 0
        in_trade_until = -1
        
        for idx in range(15, min(len(spot_bars) - 1, 300)):
            if idx < in_trade_until: continue
            if session_trades_count >= 2: break
            
            bars_so_far = spot_bars[:idx + 1]
            t_now = exchange_time(bars_so_far[-1]["start_time"]) + timedelta(minutes=1)
            time_hm = t_now.strftime("%H:%M")
            if time_hm >= "14:15": break
            
            # Check window permissions
            is_midday = ("11:30" <= time_hm < "13:15")
            is_afternoon = (time_hm >= "13:15")
            
            if is_midday and not allow_midday: continue
            if is_midday and time_hm >= midday_cutoff_time: continue
            if is_afternoon and not allow_afternoon: continue
            
            vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
            
            with MarketClock.at(t_now):
                ctx = {
                    "candles_1m": bars_so_far,
                    "prior_session_warmup_candles": warmup_candles,
                    "exchange_holidays": trading_cfg.get("option_selection", {}).get("exchange_holidays", []),
                    "spot": bars_so_far[-1]["close"],
                    "session_vwap": vwap,
                }
                candidate = strategy.evaluate(ctx)
                
            if candidate.signal == "NEUTRAL": continue
            
            # Check custom midday hist filter
            if is_midday and midday_min_hist > 0.20:
                # macd hist is in candidate reason or we can check closes
                # let's parse or extract
                pass
                
            direction = candidate.signal.replace("BUY_", "")
            spot_p = bars_so_far[-1]["close"]
            strike = select_strike(spot_p, direction, "STRICT_ITM")
            if strike == spot_p: strike += -50 if direction == "CE" else 50
            
            strike_macd_data = r.compute_strike_macd(spot_bars, strike, direction, idx, days_base, opt_candles)
            if not strike_macd_data.get("expanding_positive", True) and strike_macd_data.get("histogram", 0) < 0:
                continue
                
            dossier = generate_market_dossier(
                target_date=dt_str, candles=bars_so_far, current_bar_idx=idx,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dossier)
            if not v.is_approved: continue
            
            next_idx = idx + 1
            if next_idx >= len(spot_bars) - 1: continue
            entry_p = r.get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
            if entry_p <= 5.0: continue
            
            # Determine window-specific stop loss and invalidation
            entry_time_str = exchange_time(spot_bars[next_idx]["start_time"]).strftime("%H:%M")
            is_entry_midday = ("11:30" <= entry_time_str < "13:15")
            is_entry_afternoon = (entry_time_str >= "13:15")
            
            if is_entry_midday:
                stop_pct = midday_stop_pct
                inval_buf = midday_inval_pts
            elif is_entry_afternoon:
                stop_pct = afternoon_stop_pct
                inval_buf = afternoon_inval_pts
            else:
                stop_pct = exit_cfg.get("initial_stop_pct", 25.0)
                inval_buf = 25.0
                
            recent = spot_bars[max(0, idx - 5): idx + 1]
            if direction == "CE":
                inval_spot = min(min(x["low"] for x in recent) - 2.0, spot_p - inval_buf)
            else:
                inval_spot = max(max(x["high"] for x in recent) + 2.0, spot_p + inval_buf)
                
            initial_stop_p = entry_p * (1.0 - stop_pct / 100.0)
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
                    
                # Trailing logic
                session_window, session_stop, session_label = session_trigger(entry_p, peak_bid, exit_cfg, now_hm)
                if session_stop is not None:
                    known_floor = max(known_floor, session_stop)
                    trigger_label = session_label
                elif is_entry_afternoon and gain_pct >= afternoon_be_gain_pct:
                    # Afternoon specific Breakeven / Soft-SL ratchet
                    be_floor = entry_p * (1.0 + afternoon_be_floor_pct / 100.0)
                    known_floor = max(known_floor, be_floor)
                    trigger_label = f"AFTERNOON_BE_TRAIL ({known_floor:.2f})"
                    if gain_pct >= exit_cfg.get("runner_activation_pct", 15.0):
                        runner_stop = runner_trigger(entry_p, peak_bid, exit_cfg)
                        known_floor = max(known_floor, runner_stop)
                        trigger_label = "DYNAMIC_RUNNER_RATCHET"
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
            
            lots = 2
            if capital >= 100000: lots = 10
            elif capital >= 70000: lots = 8
            elif capital >= 40000: lots = 6
            elif capital >= 20000: lots = 4
            comp_pnl = pnl_pts * (lots * 65) - 40.0
            capital += comp_pnl
            
            entry_time_str = exchange_time(spot_bars[next_idx]["start_time"]).strftime("%H:%M")
            exit_time_str = exchange_time(spot_bars[exit_bar_idx]["start_time"]).strftime("%H:%M")
            
            all_trades.append({
                "date": dt_str, "entry_time": entry_time_str, "exit_time": exit_time_str,
                "direction": direction, "strike": strike, "entry_p": entry_p, "exit_p": exit_p,
                "peak_gain_pct": gain_pct, "pnl_2lots": pnl_2lots, "comp_pnl": comp_pnl,
                "lots": lots, "is_win": pnl_pts > 0, "exit_reason": exit_reason
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
    
    morning = [t for t in all_trades if t["entry_time"] < "11:30"]
    m_w = [t for t in morning if t["is_win"]]
    m_pnl = sum(t["pnl_2lots"] for t in morning)
    
    midday = [t for t in all_trades if "11:30" <= t["entry_time"] < "13:15"]
    mid_w = [t for t in midday if t["is_win"]]
    mid_pnl = sum(t["pnl_2lots"] for t in midday)
    
    afternoon = [t for t in all_trades if t["entry_time"] >= "13:15"]
    a_w = [t for t in afternoon if t["is_win"]]
    a_pnl = sum(t["pnl_2lots"] for t in afternoon)
    
    return {
        "trades": tot, "wins": len(wins), "losses": len(losses), "wr": wr,
        "pf": pf, "pnl": tot_pnl, "capital": capital,
        "m_trades": len(morning), "m_wr": len(m_w)/len(morning)*100 if morning else 0, "m_pnl": m_pnl,
        "mid_trades": len(midday), "mid_wr": len(mid_w)/len(midday)*100 if midday else 0, "mid_pnl": mid_pnl,
        "a_trades": len(afternoon), "a_wr": len(a_w)/len(afternoon)*100 if afternoon else 0, "a_pnl": a_pnl,
        "trade_list": all_trades
    }

if __name__ == "__main__":
    experiments = [
        ("Current Code Baseline", {}),
        ("Exp 1: Afternoon BE Trail at +7% Gain", dict(afternoon_be_gain_pct=7.0, afternoon_be_floor_pct=1.0)),
        ("Exp 2: Midday Tighter Initial Stop (15% vs 25%)", dict(midday_stop_pct=15.0)),
        ("Exp 3: Midday Tighter Invalidation (15 pts vs 25 pts)", dict(midday_inval_pts=15.0)),
        ("Exp 4: Midday Stop at 13:00 (Avoid 13:00-13:15)", dict(midday_cutoff_time="13:00")),
        ("Exp 5: Midday 15% Stop + Afternoon BE at +7%", dict(midday_stop_pct=15.0, afternoon_be_gain_pct=7.0)),
        ("Exp 6: Midday Inval 15pts + Afternoon BE at +7%", dict(midday_inval_pts=15.0, afternoon_be_gain_pct=7.0)),
        ("Exp 7: Midday Cutoff 13:00 + Afternoon BE at +7%", dict(midday_cutoff_time="13:00", afternoon_be_gain_pct=7.0)),
        ("Exp 8: Stand Aside in Midday (Trade Morning + Aft)", dict(allow_midday=False, afternoon_be_gain_pct=7.0)),
        ("Exp 9: Trade Morning Only (09:30 - 11:30)", dict(allow_midday=False, allow_afternoon=False)),
        ("Exp 10: Full Optimized Combination (13:00 Cutoff, 15% Mid Stop, Aft BE 7%)", dict(midday_cutoff_time="13:00", midday_stop_pct=15.0, afternoon_be_gain_pct=7.0)),
    ]
    
    print(f"{'Experiment':45} | {'Tot':3} | {'WR %':5} | {'PF':4} | {'Net PnL':11} | {'Cap (₹)':10} | {'Mid PnL':10} | {'Aft PnL':10}")
    print("-" * 115)
    for name, kw in experiments:
        r_res = simulate_with_params(**kw)
        print(f"{name:45} | {r_res['trades']:2d}T | {r_res['wr']:4.1f}% | {r_res['pf']:4.2f} | Rs {r_res['pnl']:+9.2f} | Rs {r_res['capital']:9.2f} | Rs {r_res['mid_pnl']:+8.2f} | Rs {r_res['a_pnl']:+8.2f}")
