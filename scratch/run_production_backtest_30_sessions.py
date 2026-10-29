#!/usr/bin/env python3
"""
Production 30-Session Backtesting Engine for Strategy 5 (Fast 2m MACD Momentum).
Directly executes our actual codebase:
- MacdMomentumStrategy from trading.strategies.macd_momentum
- session_trigger and runner_trigger from trading.domain.trailing
- select_strike from trading.domain.indicators
- AIConsultant from ai_consultant
- Real market data from data/spot_candles_*.json and data/opt_*.json
"""

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
from trading.strategies.macd_momentum import MacdMomentumStrategy

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

def run_production_backtest():
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    exit_cfg = strat_cfg["exit"]
    
    # 1. Instantiate Production Strategy & Risk Consultant
    strategy = MacdMomentumStrategy(strat_cfg)
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    all_trades = []
    session_logs = []
    
    compounding_capital = 10000.0
    peak_compounding_capital = 10000.0
    max_compounding_drawdown = 0.0
    
    for dt_str in DATES:
        spot_bars, opt_candles = load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60: continue
        
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        session_trades_count = 0
        session_pnl_2lots = 0.0
        session_pnl_comp = 0.0
        in_trade_until = -1
        
        # 15m Opening range
        orh = max(x["high"] for x in spot_bars[:15])
        orl = min(x["low"] for x in spot_bars[:15])
        
        # Iterate over completed 2m candle boundaries (odd 1m indices: 53, 55, 57, ...)
        for idx in range(53, len(spot_bars), 2):
            if idx < in_trade_until or idx > 300: continue
            if session_trades_count >= 2: break # max 2 daily entries
            
            bars_so_far = spot_bars[:idx + 1]
            t_now = exchange_time(bars_so_far[-1]["start_time"]) + timedelta(minutes=1)
            time_hm = t_now.strftime("%H:%M")
            if time_hm >= "14:15": break
            
            vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
            
            with MarketClock.at(t_now):
                ctx = {
                    "candles_1m": bars_so_far,
                    "spot": bars_so_far[-1]["close"],
                    "session_vwap": vwap,
                }
                candidate = strategy.evaluate(ctx)
                
            if candidate.signal == "NEUTRAL": continue
            
            direction = candidate.signal.replace("BUY_", "")
            spot_p = bars_so_far[-1]["close"]
            
            # Strike Selection: Strict ITM
            strike = select_strike(spot_p, direction, "STRICT_ITM")
            if strike == spot_p:
                strike += -50 if direction == "CE" else 50
                
            # Option Strike 2m MACD Confluence Check
            strike_macd_data = compute_strike_macd(spot_bars, strike, direction, idx, days_base, opt_candles)
            if not strike_macd_data.get("expanding_positive", True) and strike_macd_data.get("histogram", 0) < 0:
                continue
                
            # Mandatory Production Risk Gatekeeper Evaluation
            dossier = generate_market_dossier(
                target_date=dt_str, candles=bars_so_far, current_bar_idx=idx,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=100.0, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dossier)
            if not v.is_approved: continue
            
            # Fill trade at next minute open
            next_idx = idx + 1
            if next_idx >= len(spot_bars) - 1: continue
            entry_p = get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
            if entry_p <= 5.0: continue
            
            inval_spot = candidate.invalidation_level
            initial_stop_pct = exit_cfg.get("initial_stop_pct", 25.0)
            initial_stop_p = entry_p * (1.0 - initial_stop_pct / 100.0)
            
            known_floor = initial_stop_p
            peak_bid = entry_p
            exit_p = entry_p
            exit_reason = "1515_HARD_SQUAREOFF"
            exit_bar_idx = next_idx
            
            # Manage trade bar by bar until exit
            for m in range(next_idx + 1, min(len(spot_bars), 365)):
                sb = spot_bars[m]
                bar_time = exchange_time(sb["start_time"])
                now_hm = bar_time.strftime("%H:%M")
                
                if now_hm >= "15:15":
                    exit_p = get_option_price(sb["open"], strike, direction, m, days_base, opt_candles, spot_bars)[0]
                    exit_reason = "1515_HARD_SQUAREOFF"
                    exit_bar_idx = m
                    break
                    
                m_open, m_high, m_low, m_close = get_option_price(sb["close"], strike, direction, m, days_base, opt_candles, spot_bars)
                if m_high > peak_bid: peak_bid = m_high
                gain_pct = ((peak_bid - entry_p) / entry_p) * 100.0
                
                # 1. Structural Spot Invalidation Stop
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
                    
                # 2. Session Trailing Hierarchy (Using production session_trigger & runner_trigger)
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
                    
                # Check option low breach against known floor
                if m_low <= known_floor:
                    exit_p = known_floor
                    exit_reason = f"{trigger_label} ({known_floor:.2f})" if known_floor > initial_stop_p else "INITIAL_STOP"
                    exit_bar_idx = m
                    break
                    
            pnl_pts = exit_p - entry_p
            pnl_2lots = pnl_pts * 130 - 40.0
            
            # Step-ladder compounding tier
            if compounding_capital < 20000.0:
                step_lots = 2
            elif compounding_capital < 40000.0:
                step_lots = 4
            elif compounding_capital < 70000.0:
                step_lots = 6
            elif compounding_capital < 100000.0:
                step_lots = 8
            else:
                step_lots = 10
                
            pnl_comp = pnl_pts * (step_lots * 65) - 40.0
            compounding_capital += pnl_comp
            if compounding_capital > peak_compounding_capital:
                peak_compounding_capital = compounding_capital
            dd = peak_compounding_capital - compounding_capital
            if dd > max_compounding_drawdown:
                max_compounding_drawdown = dd
                
            entry_time_str = exchange_time(spot_bars[next_idx]["start_time"]).strftime("%H:%M")
            exit_time_str = exchange_time(spot_bars[exit_bar_idx]["start_time"]).strftime("%H:%M")
            
            # Time of day segment
            if entry_time_str < "11:30":
                segment = "MORNING"
            elif entry_time_str < "13:15":
                segment = "MIDDAY"
            else:
                segment = "AFTERNOON"
                
            trade_record = {
                "date": dt_str,
                "entry_time": entry_time_str,
                "exit_time": exit_time_str,
                "segment": segment,
                "direction": direction,
                "strike": strike,
                "entry_price": round(entry_p, 2),
                "exit_price": round(exit_p, 2),
                "peak_bid": round(peak_bid, 2),
                "peak_gain_pct": round(gain_pct, 1),
                "pnl_points": round(pnl_pts, 2),
                "pnl_2lots": round(pnl_2lots, 2),
                "step_lots": step_lots,
                "pnl_comp": round(pnl_comp, 2),
                "equity_after": round(compounding_capital, 2),
                "is_win": pnl_pts > 0,
                "exit_reason": exit_reason
            }
            all_trades.append(trade_record)
            session_trades_count += 1
            session_pnl_2lots += pnl_2lots
            session_pnl_comp += pnl_comp
            in_trade_until = exit_bar_idx + 10 # 10 bars spacing cooldown
            
        session_logs.append({
            "date": dt_str,
            "trades": session_trades_count,
            "pnl_2lots": session_pnl_2lots,
            "pnl_comp": session_pnl_comp,
            "ending_equity": compounding_capital
        })

    # Summary Statistics
    tot = len(all_trades)
    wins = [t for t in all_trades if t["is_win"]]
    losses = [t for t in all_trades if not t["is_win"]]
    wr = len(wins) / tot * 100.0 if tot else 0.0
    tot_pnl_2lots = sum(t["pnl_2lots"] for t in all_trades)
    gross_win = sum(t["pnl_2lots"] for t in wins)
    gross_loss = abs(sum(t["pnl_2lots"] for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 999.0
    
    morn = [t for t in all_trades if t["segment"] == "MORNING"]
    morn_w = [t for t in morn if t["is_win"]]
    morn_wr = len(morn_w) / len(morn) * 100.0 if morn else 0.0
    morn_pnl = sum(t["pnl_2lots"] for t in morn)
    
    mid = [t for t in all_trades if t["segment"] == "MIDDAY"]
    mid_w = [t for t in mid if t["is_win"]]
    mid_wr = len(mid_w) / len(mid) * 100.0 if mid else 0.0
    mid_pnl = sum(t["pnl_2lots"] for t in mid)
    
    aft = [t for t in all_trades if t["segment"] == "AFTERNOON"]
    aft_w = [t for t in aft if t["is_win"]]
    aft_wr = len(aft_w) / len(aft) * 100.0 if aft else 0.0
    aft_pnl = sum(t["pnl_2lots"] for t in aft)

    print("=" * 115)
    print(" 🏆 PRODUCTION BACKTEST RESULTS: STRATEGY 5 (FAST 2M MACD) ACROSS 30 SESSIONS")
    print("=" * 115)
    print(f" Total Trades Executed:                 {tot} ({tot/30:.1f} trades/session)")
    print(f" Winning Trades:                         {len(wins)} / {tot} ({wr:.1f}% Win Rate)")
    print(f" Losing Trades:                          {len(losses)} / {tot}")
    print(f" Profit Factor:                          {pf:.2f}")
    print("-" * 115)
    print(f" Morning Window (09:15 - 11:30 IST):     {len(morn_w)} / {len(morn)} ({morn_wr:.1f}% WR) | Net PnL: Rs {morn_pnl:+,.2f}")
    print(f" Midday Window (11:30 - 13:15 IST):      {len(mid_w)} / {len(mid)} ({mid_wr:.1f}% WR) | Net PnL: Rs {mid_pnl:+,.2f}")
    print(f" Afternoon Window (13:15 - 15:15 IST):   {len(aft_w)} / {len(aft)} ({aft_wr:.1f}% WR) | Net PnL: Rs {aft_pnl:+,.2f}")
    print("-" * 115)
    print(f" Net Realized PnL (Fixed 2 Lots / 10k):  Rs {tot_pnl_2lots:+,.2f} (+{tot_pnl_2lots/10000*100.0:,.1f}% ROI)")
    print(f" Compounding Ending Capital:             Rs {compounding_capital:,.2f} ({compounding_capital/10000:.1f}x from Rs 10,000)")
    print(f" Max Compounding Drawdown:               Rs {max_compounding_drawdown:,.2f} ({max_compounding_drawdown/peak_compounding_capital*100:.1f}% of peak)")
    print("=" * 115)

    # Save to JSON
    with open("scratch/production_backtest_30_sessions_results.json", "w") as fp:
        json.dump({
            "metrics": {
                "total_trades": tot, "wins": len(wins), "losses": len(losses), "win_rate": wr,
                "profit_factor": pf, "pnl_2lots": tot_pnl_2lots, "ending_equity": compounding_capital,
                "max_drawdown": max_compounding_drawdown,
                "morning": {"trades": len(morn), "wins": len(morn_w), "wr": morn_wr, "pnl": morn_pnl},
                "midday": {"trades": len(mid), "wins": len(mid_w), "wr": mid_wr, "pnl": mid_pnl},
                "afternoon": {"trades": len(aft), "wins": len(aft_w), "wr": aft_wr, "pnl": aft_pnl}
            },
            "trades": all_trades,
            "session_logs": session_logs
        }, fp, indent=2)

if __name__ == "__main__":
    run_production_backtest()
