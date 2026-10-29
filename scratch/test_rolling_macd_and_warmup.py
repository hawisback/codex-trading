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
from trading.strategies.macd_momentum import calculate_macd
import scratch.run_production_backtest_30_sessions as r

DATES = r.DATES

def build_rolling_2m_bars(candles_1m):
    """
    Construct rolling 2-minute bars evaluated at every minute.
    Bar i (for i >= 1) combines candles_1m[i-1] and candles_1m[i].
    """
    bars_2m = []
    for i in range(1, len(candles_1m)):
        c0 = candles_1m[i - 1]
        c1 = candles_1m[i]
        bars_2m.append({
            "start_time": c0["start_time"],
            "end_time": c1["start_time"],
            "minute_idx": i,
            "open": c0["open"],
            "high": max(c0["high"], c1["high"]),
            "low": min(c0["low"], c1["low"]),
            "close": c1["close"],
            "volume": c0.get("volume", 0) + c1.get("volume", 0)
        })
    return bars_2m

def test_warmup_and_rolling():
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    exit_cfg = strat_cfg["exit"]
    trading_cfg = json.load(open("config/trading.json"))
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    # Load all dates with prior day candles
    all_trades = []
    
    for d_idx, dt_str in enumerate(DATES):
        spot_bars, opt_candles = r.load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60: continue
        
        # Load prior day's spot bars for warmup
        prior_bars = []
        if d_idx > 0:
            prior_bars, _ = r.load_session_data(DATES[d_idx - 1])
        if not prior_bars:
            # If no prior day, use earliest bars
            prior_bars = spot_bars[:60]
            
        # Use last 60 bars of prior day + today's bars so far
        warmup_bars = prior_bars[-60:]
        
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()) if target_d.weekday() <= 1 else (8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        session_trades_count = 0
        in_trade_until = -1
        
        # Opening range (first 15 bars: 09:15 - 09:30)
        orh = max(x["high"] for x in spot_bars[:15])
        orl = min(x["low"] for x in spot_bars[:15])
        
        # Start evaluation at 09:30 AM (minute 15 of today)
        for i in range(15, min(len(spot_bars) - 1, 300)):
            if i < in_trade_until: continue
            if session_trades_count >= 2: break
            
            bars_today = spot_bars[:i + 1]
            t_now = exchange_time(bars_today[-1]["start_time"]) + timedelta(minutes=1)
            time_hm = t_now.strftime("%H:%M")
            if time_hm >= "14:15": break
            
            # Combine warmup + today
            combined_1m = warmup_bars + bars_today
            rolling_2m = build_rolling_2m_bars(combined_1m)
            
            closes_2m = [x["close"] for x in rolling_2m]
            macd, sig, hist = calculate_macd(closes_2m)
            
            # Check fresh cross at latest bar
            pe_cross = (macd[-1] < sig[-1]) and (macd[-2] >= sig[-2])
            ce_cross = (macd[-1] > sig[-1]) and (macd[-2] <= sig[-2])
            if not (pe_cross or ce_cross): continue
            
            if abs(hist[-1]) < 0.20: continue
            
            direction = "PE" if pe_cross else "CE"
            spot_p = bars_today[-1]["close"]
            
            # 2m rolling candle body check
            latest_2m = rolling_2m[-1]
            body_2m = latest_2m["close"] - latest_2m["open"]
            if direction == "CE" and body_2m < 0: continue
            if direction == "PE" and body_2m > 0: continue
            
            vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_today) / len(bars_today)
            dist_vwap = abs(spot_p - vwap)
            
            # VWAP flow
            if direction == "CE" and spot_p < vwap - 12.0: continue
            if direction == "PE" and spot_p > vwap + 12.0: continue
            
            # VWAP climax (72 pts per Charter Rule 5)
            if dist_vwap >= 72.0: continue
            
            # Opening Range Filter (09:15 - 09:30)
            if direction == "PE" and 0.0 <= (spot_p - orl) <= 8.0: continue
            if direction == "CE" and 0.0 <= (orh - spot_p) <= 8.0: continue
            
            # Midday dead zone (11:30 - 13:15 with 15m range < 18 pts)
            if 135 <= i <= 240:
                box_15 = bars_today[max(0, i - 14): i + 1]
                box_spread = max(x["high"] for x in box_15) - min(x["low"] for x in box_15)
                if box_spread < 18.0: continue
                
            # Strike Selection: Strict ITM
            strike = select_strike(spot_p, direction, "STRICT_ITM")
            if strike == spot_p: strike += -50 if direction == "CE" else 50
            
            # Strike MACD Confluence Check
            strike_macd_data = r.compute_strike_macd(spot_bars, strike, direction, i, days_base, opt_candles)
            if not strike_macd_data.get("expanding_positive", True) and strike_macd_data.get("histogram", 0) < 0:
                continue
                
            # Production Risk Gatekeeper
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
    
    print("=" * 110)
    print("🚀 EMPIRICAL RESULT: ROLLING 2m MACD (EVERY MINUTE) + PRIOR DAY WARMUP (FROM 09:30 AM)")
    print("=" * 110)
    print(f" Total Trades Executed:                 {tot} ({tot/30:.1f} trades/session)")
    print(f" Winning Trades:                         {len(wins)} / {tot} ({wr:.1f}% Win Rate)")
    print(f" Losing Trades:                          {len(losses)} / {tot}")
    print(f" Profit Factor:                          {pf:.2f}")
    print(f" Net Realized PnL (Fixed 2 Lots):        Rs {tot_pnl:+,.2f} (+{tot_pnl/10000*100.0:.1f}% ROI)")
    print("=" * 110)
    
    # Check trades entered between 09:30 and 10:09 AM (previously impossible window!)
    early_trades = [t for t in all_trades if "09:30" <= t["entry_time"] < "10:09"]
    e_wins = [t for t in early_trades if t["is_win"]]
    e_losses = [t for t in early_trades if not t["is_win"]]
    e_wr = len(e_wins) / len(early_trades) * 100.0 if early_trades else 0.0
    e_pnl = sum(t["pnl_2lots"] for t in early_trades)
    print(f"\n⚡ Newly Unlocked Early Morning Window (09:30 - 10:09 AM):")
    print(f"  Trades: {len(early_trades)} | Wins: {len(e_wins)} / {len(early_trades)} ({e_wr:.1f}% WR) | Net PnL: Rs {e_pnl:+,.2f}")
    for t in early_trades:
        res = "WIN " if t["is_win"] else "LOSS"
        print(f"    {t['date']} {t['entry_time']} -> {t['exit_time']} | {res} | {t['direction']} {t['strike']} | Peak: +{t['peak_gain_pct']:4.1f}% | PnL: Rs {t['pnl_2lots']:+8.2f} | {t['exit_reason']}")

if __name__ == "__main__":
    test_warmup_and_rolling()
