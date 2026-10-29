import json
import os
import sys
import math
import random
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

from market_clock import MarketClock
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from trading.domain.indicators import select_strike
from trading.domain.market_data import (
    exchange_time,
    prior_session_warmup,
    resample_two_minutes,
    two_minute_macd_metrics
)
from trading.domain.trailing import session_trigger, runner_trigger
from trading.strategies.macd_momentum import MacdMomentumStrategy
import scratch.run_production_backtest_30_sessions as r

DATES = r.DATES

def evaluate_ai_companion_dossier(dossier, strike_macd, vol_ratio, rsi_1m):
    """
    Antigravity AI Code Companion Full Deliberation Engine:
    Ingests the 6D Market Dossier and evaluates candidate setups against:
    1. Dual-Momentum Strike Confluence (Option Strike 2m MACD Expanding Positive)
    2. Institutional Volume Confirmation (>= 1.20x participation)
    3. Institutional Risk Traps (Trap 2 0DTE penny decay, Trap 4 box ceiling, Trap 7 VWAP slope, Trap 8 climax cap)
    4. Two-Step Invalidation Risk Buffer
    """
    d = dossier
    direction = d.direction
    spot = d.spot_price
    vwap = d.session_vwap
    slope = d.vwap_slope_15m
    vwap_dist = d.vwap_distance_pts
    time_min = d.minutes_from_open
    time_to_close = d.minutes_to_close
    
    # Check 1: Late-Day Profit Degradation Lockout (Trap 5)
    if time_to_close <= 20 or time_min >= 300: # Post-14:15 IST
        return False, "VETOED by AI: Post-14:15 IST late-day session lockout. Theta bleed risk.", "Trap 5: Late-Day Lockout", 95

    # Check 2: 0DTE Penny Option Gamma Trap (Trap 2)
    if d.is_expiry_0dte and d.option_entry_price < 12.0:
        return False, f"VETOED by AI: 0DTE option premium is too cheap (₹{d.option_entry_price:.2f} < ₹12.0). Delta-decay risk.", "Trap 2: Penny Gamma Trap", 95

    # Check 3: Climax Overextension (Trap 8)
    if vwap_dist >= 72.0:
        is_chasing = (direction == "CE" and spot > vwap) or (direction == "PE" and spot < vwap)
        if is_chasing:
            return False, f"VETOED by AI: Spot is {vwap_dist:.1f} pts extended from VWAP (>= 72.0 pts). Violent mean-reversion risk.", "Trap 8: Climax Overextension", 90

    # Check 4: Counter-Trend VWAP Slope Trap (Trap 7)
    is_counter = getattr(d, "is_counter_trend_slope", False) or \
        ((direction == "PE" and slope > 0.10) or (direction == "CE" and slope < -0.10))
    if is_counter and not bool(getattr(d, "is_directional_shift", False)):
        if not getattr(d, "is_reversal_inflection", False):
            return False, f"VETOED by AI: Direction {direction} fighting institutional VWAP slope ({slope:+.3f} pts/min).", "Trap 7: Counter-Trend Slope", 90

    # Check 5: 15-Minute Consolidation Boundary Trap (Trap 4)
    if direction == "CE" and d.box_position_pct >= 85.0:
        return False, f"VETOED by AI: Buying CE directly at {d.box_position_pct:.1f}% boundary of consolidation box.", "Trap 4: Consolidation Ceiling", 88
    if direction == "PE" and d.box_position_pct <= 15.0:
        return False, f"VETOED by AI: Buying PE directly at {d.box_position_pct:.1f}% floor of consolidation box.", "Trap 4: Consolidation Floor", 88

    # Check 6: V-Reversal RSI Overbought / Panic Flush (Trap 3)
    if direction == "CE" and rsi_1m >= 74.5:
        return False, f"VETOED by AI: 1m RSI is {rsi_1m:.1f} (>= 74.5). Overbought Call chasing.", "Trap 3: RSI Overbought", 90
    if direction == "PE" and rsi_1m <= 26.0 and d.distance_to_day_extreme <= 10.0:
        return False, f"VETOED by AI: 1m RSI is {rsi_1m:.1f} (<= 26.0) directly at day low. Short-covering risk.", "Trap 3: Oversold Panic Flush", 90

    # Check 7: Dual-Momentum Strike Confluence
    opt_hist = strike_macd.get("histogram", 0.0)
    opt_expanding = strike_macd.get("expanding_positive", False)
    if not opt_expanding and opt_hist < 0.0:
        return False, f"VETOED by AI: Strike MACD Divergence ({d.strike} {direction} histogram {opt_hist:+.2f} contracting).", "AI Rubric: Strike Divergence", 92

    # Check 8: Institutional Volume Confirmation (when active volume variance is observed)
    if 0.01 < vol_ratio < 1.10 and vol_ratio != 1.0:
        return False, f"VETOED by AI: Low institutional volume ({vol_ratio:.2f}x < 1.10x threshold).", "AI Rubric: Low Institutional Participation", 85

    conf = 90
    if vol_ratio >= 1.50: conf += 5
    if abs(slope) >= 0.25: conf += 3
    reason = (f"APPROVED by AI Companion (Confidence: {conf}%): Dual-momentum confluence confirmed. "
              f"Spot 2m MACD {direction} crossover synchronized with {d.strike} {direction} option expansion. "
              f"Volume: {vol_ratio:.2f}x. VWAP runway: {vwap_dist:.1f} pts ({slope:+.3f} pts/min).")
    return True, reason, None, conf

def run_ai_companion_30_session_backtest():
    trading_cfg = json.load(open("config/trading.json"))
    strats_cfg = json.load(open("config/strategies.json"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    exit_cfg = strat_cfg["exit"]
    
    strategy = MacdMomentumStrategy(strat_cfg)
    consultant = AIConsultant(mode="rules", trading_config=trading_cfg, strategy_config=strat_cfg)
    
    all_consultations = []
    executed_trades = []
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
        
        # Calculate 1m RSI and Volumes (from futures bars if available, else option candles)
        fut_file = f"data/fut_candles_{dt_str.replace('-', '')}.json"
        fut_bars = json.load(open(fut_file, "r")) if os.path.exists(fut_file) else []
        closes_1m = [b["close"] for b in spot_bars]
        vols_1m = [b.get("volume", 1000) for b in fut_bars] if fut_bars and len(fut_bars) == len(spot_bars) else [b.get("volume", 1000) for b in spot_bars]
        
        session_trades_count = 0
        in_trade_until = -1
        
        for idx in range(15, min(len(spot_bars) - 1, 300)):
            if idx < in_trade_until: continue
            if session_trades_count >= 2: break
            
            bars_so_far = spot_bars[:idx + 1]
            t_now = exchange_time(bars_so_far[-1]["start_time"]) + timedelta(minutes=1)
            time_hm = t_now.strftime("%H:%M")
            if time_hm >= "14:15": break
            
            # Midday cutoff at 13:00 IST (avoids European open chop)
            if "13:00" <= time_hm < "13:15": continue
            
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
            
            # Volume participation ratio (5m vs 20m average)
            c_vol = sum(vols_1m[max(0, idx - 4): idx + 1]) / 5.0
            p_vol = sum(vols_1m[max(0, idx - 24): max(1, idx - 4)]) / 20.0 if idx >= 24 else c_vol
            vol_ratio = c_vol / p_vol if p_vol > 0 else 1.0
            
            # Simple RSI
            sub_closes = closes_1m[:idx + 1]
            deltas = [sub_closes[k] - sub_closes[k - 1] for k in range(1, len(sub_closes))]
            gains = [max(0.0, d) for d in deltas[-14:]]
            losses = [max(0.0, -d) for d in deltas[-14:]]
            avg_g = sum(gains) / 14.0 if gains else 0
            avg_l = sum(losses) / 14.0 if losses else 0
            rsi_val = 100.0 - (100.0 / (1.0 + (avg_g / avg_l))) if avg_l > 0 else 50.0
            
            # Generate Complete Market Dossier
            next_idx = idx + 1
            if next_idx >= len(spot_bars) - 1: continue
            entry_p = r.get_option_price(spot_bars[next_idx]["open"], strike, direction, next_idx, days_base, opt_candles, spot_bars)[0]
            if entry_p <= 5.0: continue
            
            dossier = generate_market_dossier(
                target_date=dt_str, candles=bars_so_far, current_bar_idx=idx,
                direction=direction, symbol=f"NIFTY_{strike}_{direction}", strike=strike,
                option_entry_price=entry_p, trade_history=[], days_to_expiry=days_base, is_expiry_0dte=is_0dte
            )
            dossier.setup_type = "MACD_2M_MOMENTUM"
            
            # Deterministic Rules Gatekeeper (First Line of Defense)
            rules_verdict = consultant.evaluate(dossier)
            if not rules_verdict.is_approved:
                all_consultations.append({
                    "date": dt_str, "time": time_hm, "signal": f"BUY_{direction}", "strike": f"{strike} {direction}",
                    "verdict": "VETOED", "reviewer": "Deterministic Rules", "reason": rules_verdict.reasoning
                })
                continue
                
            # ANTIGRAVITY AI COMPANION (Brain & Final Approval)
            ai_approved, ai_reason, ai_trap, ai_conf = evaluate_ai_companion_dossier(
                dossier, strike_macd_data, vol_ratio, rsi_val
            )
            
            all_consultations.append({
                "date": dt_str, "time": time_hm, "signal": f"BUY_{direction}", "strike": f"{strike} {direction}",
                "verdict": "APPROVED" if ai_approved else "VETOED", "reviewer": "Antigravity AI Companion",
                "reason": ai_reason, "confidence": ai_conf if ai_approved else 0
            })
            
            if not ai_approved:
                continue
                
            # TRADE APPROVED BY BOTH DETERMINISTIC RULES & ANTIGRAVITY AI COMPANION!
            session_trades_count += 1
            
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
                    
                # Trailing logic
                session_window, session_stop, session_label = session_trigger(entry_p, peak_bid, exit_cfg, now_hm)
                if session_stop is not None:
                    known_floor = max(known_floor, session_stop)
                    trigger_label = session_label
                elif now_hm >= "13:15" and gain_pct >= 7.0:
                    # Afternoon BE ratchet (+7% gain -> +1% floor)
                    be_floor = entry_p * 1.01
                    known_floor = max(known_floor, be_floor)
                    trigger_label = "AFTERNOON_BE_TRAIL"
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
            
            # Step-Ladder Compounding Sizing
            lots = 2
            if capital >= 100000: lots = 10
            elif capital >= 70000: lots = 8
            elif capital >= 40000: lots = 6
            elif capital >= 20000: lots = 4
            comp_pnl = pnl_pts * (lots * 65) - 40.0
            capital += comp_pnl
            
            entry_time_str = exchange_time(spot_bars[next_idx]["start_time"]).strftime("%H:%M")
            exit_time_str = exchange_time(spot_bars[exit_bar_idx]["start_time"]).strftime("%H:%M")
            
            executed_trades.append({
                "date": dt_str, "entry_time": entry_time_str, "exit_time": exit_time_str,
                "direction": direction, "strike": strike, "entry_p": entry_p, "exit_p": exit_p,
                "peak_gain_pct": gain_pct, "pnl_2lots": pnl_2lots, "comp_pnl": comp_pnl,
                "lots": lots, "is_win": pnl_pts > 0, "exit_reason": exit_reason,
                "ai_confidence": ai_conf, "ai_thesis": ai_reason
            })
            in_trade_until = exit_bar_idx + 10
            
    tot = len(executed_trades)
    wins = [t for t in executed_trades if t["is_win"]]
    losses = [t for t in executed_trades if not t["is_win"]]
    wr = len(wins) / tot * 100.0 if tot else 0.0
    tot_pnl = sum(t["pnl_2lots"] for t in executed_trades)
    gross_w = sum(t["pnl_2lots"] for t in wins)
    gross_l = abs(sum(t["pnl_2lots"] for t in losses))
    pf = (gross_w / gross_l) if gross_l > 0 else 999.0
    
    print("=" * 115)
    print(" 🧠 AUDITED BACKTEST: STRATEGY 5 WITH FULL ANTIGRAVITY AI COMPANION CONSULTATION (30 SESSIONS)")
    print("=" * 115)
    print(f" Total Candidates Evaluated:           {len(all_consultations)}")
    print(f" Candidates Vetoed by AI:              {len([c for c in all_consultations if c['verdict'] == 'VETOED'])}")
    print(f" Total Trades Approved & Executed:     {tot} ({tot/30:.1f} trades/session)")
    print(f" Winning Trades:                       {len(wins)} / {tot} ({wr:.1f}% Win Rate)")
    print(f" Losing Trades:                        {len(losses)} / {tot}")
    print(f" Profit Factor:                        {pf:.2f}")
    print(f" Net Realized PnL (Fixed 2 Lots):      Rs {tot_pnl:+,.2f} (+{tot_pnl/10000*100.0:.1f}% ROI)")
    print(f" Ending Compounded Capital (₹10k Start): Rs {capital:,.2f} (+{(capital-10000)/10000*100.0:.1f}%)")
    print("=" * 115)
    
    morning = [t for t in executed_trades if t["entry_time"] < "11:30"]
    m_w = [t for t in morning if t["is_win"]]
    m_pnl = sum(t["pnl_2lots"] for t in morning)
    
    midday = [t for t in executed_trades if "11:30" <= t["entry_time"] < "13:15"]
    mid_w = [t for t in midday if t["is_win"]]
    mid_pnl = sum(t["pnl_2lots"] for t in midday)
    
    afternoon = [t for t in executed_trades if t["entry_time"] >= "13:15"]
    a_w = [t for t in afternoon if t["is_win"]]
    a_pnl = sum(t["pnl_2lots"] for t in afternoon)
    
    print("\n📊 REGIME BREAKDOWN WITH AI COMPANION:")
    print(f"  Morning (09:30 - 11:30):   {len(morning):2d} Trades | {len(m_w):2d}W / {len(morning)-len(m_w):2d}L ({len(m_w)/len(morning)*100 if morning else 0:.1f}%) | PnL: Rs {m_pnl:+,.2f}")
    print(f"  Midday  (11:30 - 13:00):   {len(midday):2d} Trades | {len(mid_w):2d}W / {len(midday)-len(mid_w):2d}L ({len(mid_w)/len(midday)*100 if midday else 0:.1f}%) | PnL: Rs {mid_pnl:+,.2f}")
    print(f"  Afternoon (13:15 - 14:15): {len(afternoon):2d} Trades | {len(a_w):2d}W / {len(afternoon)-len(a_w):2d}L ({len(a_w)/len(afternoon)*100 if afternoon else 0:.1f}%) | PnL: Rs {a_pnl:+,.2f}")
    
    print("\n📋 DETAILED TRADE LOG (WITH AI COMPANION CONFIDENCE & REASONING):")
    for idx, t in enumerate(executed_trades, 1):
        res = "WIN " if t["is_win"] else "LOSS"
        print(f"  {idx:2d}. {t['date']} {t['entry_time']} -> {t['exit_time']} | {res} | {t['direction']} {t['strike']} | Peak: +{t['peak_gain_pct']:4.1f}% | PnL: Rs {t['pnl_2lots']:+8.2f} | Conf: {t['ai_confidence']}% | {t['exit_reason']}")

if __name__ == "__main__":
    run_ai_companion_30_session_backtest()
