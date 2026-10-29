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

def test_trade_expansion_matrix():
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    base_strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    
    # We will test variations:
    # 0. Current Baseline (max_entries: 2, spacing: 10, climax: 50, vwap_tol: 12, hist: 0.20)
    # 1. Increase max_daily_entries to 3 (allow the 3rd winning impulse)
    # 2. Reduce min_spacing_bars to 5 (allow quick re-entries)
    # 3. Widen vwap_climax_pts from 50 to 70 (Align with AGENTS.md Charter Rule #5 Trap 8)
    # 4. Widen vwap_tolerance_pts from 12 to 18 (Allow momentum pullbacks near VWAP)
    # 5. Combined Expansion A: max_entries: 3, spacing: 6, climax: 65, vwap_tol: 16
    # 6. Combined Expansion B: max_entries: 4, spacing: 5, climax: 70, vwap_tol: 18
    
    variations = [
        ("0. Current Production Baseline", {"max_daily_entries": 2, "min_spacing_bars": 10, "vwap_climax_pts": 50.0, "vwap_tolerance_pts": 12.0, "min_hist_threshold": 0.20}),
        ("1. Max Daily Entries = 3", {"max_daily_entries": 3, "min_spacing_bars": 10, "vwap_climax_pts": 50.0, "vwap_tolerance_pts": 12.0, "min_hist_threshold": 0.20}),
        ("2. Min Spacing Bars = 5 (Quick Re-entry)", {"max_daily_entries": 2, "min_spacing_bars": 5, "vwap_climax_pts": 50.0, "vwap_tolerance_pts": 12.0, "min_hist_threshold": 0.20}),
        ("3. VWAP Climax = 70 pts (Charter Rule #5)", {"max_daily_entries": 2, "min_spacing_bars": 10, "vwap_climax_pts": 70.0, "vwap_tolerance_pts": 12.0, "min_hist_threshold": 0.20}),
        ("4. VWAP Tolerance = 18 pts", {"max_daily_entries": 2, "min_spacing_bars": 10, "vwap_climax_pts": 50.0, "vwap_tolerance_pts": 18.0, "min_hist_threshold": 0.20}),
        ("5. Combined Expansion A (3 Entries, 6m Spacing, 65pt Climax, 16pt VWAP)", {"max_daily_entries": 3, "min_spacing_bars": 6, "vwap_climax_pts": 65.0, "vwap_tolerance_pts": 16.0, "min_hist_threshold": 0.18}),
        ("6. Combined Expansion B (3 Entries, 5m Spacing, 70pt Climax, 18pt VWAP)", {"max_daily_entries": 3, "min_spacing_bars": 5, "vwap_climax_pts": 70.0, "vwap_tolerance_pts": 18.0, "min_hist_threshold": 0.15}),
    ]
    
    for label, overrides in variations:
        import copy
        strat_cfg = copy.deepcopy(base_strat_cfg)
        strat_cfg["entry"].update(overrides)
        exit_cfg = strat_cfg["exit"]
        strategy = MacdMomentumStrategy(strat_cfg)
        consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
        
        all_trades = []
        compounding_capital = 10000.0
        peak_capital = 10000.0
        max_dd = 0.0
        
        max_entries = overrides["max_daily_entries"]
        spacing = overrides["min_spacing_bars"]
        
        for dt_str in DATES:
            spot_bars, opt_candles = r.load_session_data(dt_str)
            if not spot_bars or len(spot_bars) < 60: continue
            
            target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
            days_base = max(0.1, float((expiry_d - target_d).days))
            is_0dte = (target_d.weekday() == 1)
            
            session_trades_count = 0
            in_trade_until = -1
            
            for idx in range(53, len(spot_bars), 2):
                if idx < in_trade_until or idx > 300: continue
                if session_trades_count >= max_entries: break
                
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
                
                inval_spot = candidate.invalidation_level
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
                    elif not session_window and exit_cfg.get("runner_trailing_enabled", True) and gain_pct >= exit_cfg.get("runner_activation_pct", 15.0):
                        runner_stop = runner_trigger(entry_p, peak_bid, exit_cfg)
                        known_floor = max(known_floor, runner_stop)
                        
                    if m_low <= known_floor:
                        exit_p = known_floor
                        exit_reason = "DYNAMIC_STOP" if known_floor > initial_stop_p else "INITIAL_STOP"
                        exit_bar_idx = m
                        break
                        
                pnl_pts = exit_p - entry_p
                pnl_2lots = pnl_pts * 130 - 40.0
                all_trades.append({"pnl_2lots": pnl_2lots, "is_win": pnl_pts > 0, "date": dt_str})
                session_trades_count += 1
                in_trade_until = exit_bar_idx + spacing
                
        tot = len(all_trades)
        wins = [t for t in all_trades if t["is_win"]]
        losses = [t for t in all_trades if not t["is_win"]]
        wr = len(wins) / tot * 100.0 if tot else 0.0
        tot_pnl = sum(t["pnl_2lots"] for t in all_trades)
        gross_w = sum(t["pnl_2lots"] for t in wins)
        gross_l = abs(sum(t["pnl_2lots"] for t in losses))
        pf = (gross_w / gross_l) if gross_l > 0 else 999.0
        
        print("=" * 105)
        print(f"📊 {label}")
        print("=" * 105)
        print(f"  Total Trades:           {tot} ({tot/30:.1f} trades/session)")
        print(f"  Win / Loss Record:      {len(wins)} Wins / {len(losses)} Losses")
        print(f"  Win Rate:               {wr:.1f}%")
        print(f"  Profit Factor:          {pf:.2f}")
        print(f"  Net Realized PnL (2L):  Rs {tot_pnl:+,.2f} (+{tot_pnl/10000*100.0:.1f}% ROI)")

if __name__ == "__main__":
    test_trade_expansion_matrix()
