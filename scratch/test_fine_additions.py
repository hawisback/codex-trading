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
from trading.domain.market_data import exchange_time
from trading.domain.trailing import session_trigger, runner_trigger
from trading.strategies.macd_momentum import calculate_macd, MacdMomentumStrategy
import scratch.run_production_backtest_30_sessions as r

DATES = r.DATES

def test_fine_tuning():
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    base_strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    
    # Let's test combinations:
    # Option 1: VWAP Climax = 72 pts (Charter Rule 5) alone
    # Option 2: Option 1 + Midday 15m Range = 18.0 pts (Unlocks midday 5% scalps)
    # Option 3: Option 1 + Midday Range = 18.0 pts + VWAP Tol = 16.0 pts + Hist = 0.15
    # Option 4: Option 3 + Max Entries = 3 per day
    
    variations = [
        ("Base: Current Production", {}),
        ("Opt 1: Climax = 72 pts (Charter Rule 5)", {"vwap_climax_pts": 72.0}),
        ("Opt 2: Climax = 72 pts + Midday 15m Range = 18 pts", {"vwap_climax_pts": 72.0, "midday_dead_zone_filter": {"enabled": True, "start_minute": 135, "end_minute": 240, "min_15m_range_pts": 18.0}}),
        ("Opt 3: Opt 2 + VWAP Tol = 16 pts + Hist = 0.15", {"vwap_climax_pts": 72.0, "vwap_tolerance_pts": 16.0, "min_hist_threshold": 0.15, "midday_dead_zone_filter": {"enabled": True, "start_minute": 135, "end_minute": 240, "min_15m_range_pts": 18.0}}),
        ("Opt 4: Opt 3 + Max Daily Entries = 3 + Spacing = 8", {"max_daily_entries": 3, "min_spacing_bars": 8, "vwap_climax_pts": 72.0, "vwap_tolerance_pts": 16.0, "min_hist_threshold": 0.15, "midday_dead_zone_filter": {"enabled": True, "start_minute": 135, "end_minute": 240, "min_15m_range_pts": 18.0}}),
    ]
    
    for label, overrides in variations:
        import copy
        strat_cfg = copy.deepcopy(base_strat_cfg)
        strat_cfg["entry"].update(overrides)
        exit_cfg = strat_cfg["exit"]
        strategy = MacdMomentumStrategy(strat_cfg)
        consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
        
        all_trades = []
        max_entries = strat_cfg["entry"].get("max_daily_entries", 2)
        spacing = strat_cfg["entry"].get("min_spacing_bars", 10)
        
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
                        exit_bar_idx = m
                        break
                    elif direction == "PE" and sb["high"] >= inval_spot:
                        exit_p = m_close
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
        
        print(f"{label:<55} | Trades: {tot:2d} | Wins: {len(wins):2d} ({wr:4.1f}%) | Losses: {len(losses):2d} | PF: {pf:4.2f} | PnL: Rs {tot_pnl:+9.2f}")

if __name__ == "__main__":
    test_fine_tuning()
