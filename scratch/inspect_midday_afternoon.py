import json
import os
import sys

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

import scratch.verify_implemented_changes as v

# Let's run and capture all midday and afternoon trades
trading_cfg = json.load(open("config/trading.json"))
strats_cfg = json.load(open("config/strategies.json"))
strat_cfg = strats_cfg["strategies"]["macd_momentum"]
exit_cfg = strat_cfg["exit"]

from trading.strategies.macd_momentum import MacdMomentumStrategy
from ai_consultant import AIConsultant
import scratch.run_production_backtest_30_sessions as r
from market_clock import MarketClock
from trading.domain.indicators import select_strike
from trading.domain.market_data import exchange_time
from trading.domain.trailing import session_trigger, runner_trigger
from datetime import datetime, timedelta

strategy = MacdMomentumStrategy(strat_cfg)
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
        
        direction = candidate.signal.replace("BUY_", "")
        spot_p = bars_so_far[-1]["close"]
        strike = select_strike(spot_p, direction, "STRICT_ITM")
        if strike == spot_p: strike += -50 if direction == "CE" else 50
        
        strike_macd_data = r.compute_strike_macd(spot_bars, strike, direction, idx, days_base, opt_candles)
        if not strike_macd_data.get("expanding_positive", True) and strike_macd_data.get("histogram", 0) < 0:
            continue
            
        from ai_context_dossier import generate_market_dossier
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
        
        # Track max drawdown (trough)
        trough_bid = entry_p
        
        for m in range(next_idx + 1, min(len(spot_bars), 365)):
            sb = spot_bars[m]
            now_hm = exchange_time(sb["start_time"]).strftime("%H:%M")
            if now_hm >= "15:15":
                exit_p = r.get_option_price(sb["open"], strike, direction, m, days_base, opt_candles, spot_bars)[0]
                exit_bar_idx = m
                break
                
            m_open, m_high, m_low, m_close = r.get_option_price(sb["close"], strike, direction, m, days_base, opt_candles, spot_bars)
            if m_high > peak_bid: peak_bid = m_high
            if m_low < trough_bid: trough_bid = m_low
            gain_pct = ((peak_bid - entry_p) / entry_p) * 100.0
            loss_pct = ((trough_bid - entry_p) / entry_p) * 100.0
            
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
        duration_mins = exit_bar_idx - next_idx
        
        all_trades.append({
            "date": dt_str, "entry_time": entry_time_str, "exit_time": exit_time_str,
            "duration": duration_mins, "direction": direction, "strike": strike,
            "entry_p": entry_p, "exit_p": exit_p, "peak_gain_pct": gain_pct,
            "max_drawdown_pct": loss_pct, "pnl_2lots": pnl_2lots, "is_win": pnl_pts > 0,
            "exit_reason": exit_reason
        })
        session_trades_count += 1
        in_trade_until = exit_bar_idx + 10

print("=" * 110)
print("🔍 DEEP FORENSIC ANALYSIS: MIDDAY (11:30 - 13:15) & AFTERNOON (13:15 - 14:15) TRADES")
print("=" * 110)

non_morning = [t for t in all_trades if t["entry_time"] >= "11:30"]
for t in non_morning:
    status = "WIN " if t["is_win"] else "LOSS"
    window = "MIDDAY   " if t["entry_time"] < "13:15" else "AFTERNOON"
    print(f"{window} | {t['date']} {t['entry_time']} -> {t['exit_time']} ({t['duration']:2d}m) | {status} | {t['direction']} {t['strike']} "
          f"| Entry: ₹{t['entry_p']:5.1f} Exit: ₹{t['exit_p']:5.1f} | Peak: +{t['peak_gain_pct']:4.1f}% MaxDD: {t['max_drawdown_pct']:5.1f}% | PnL: Rs {t['pnl_2lots']:+8.2f} | {t['exit_reason']}")
