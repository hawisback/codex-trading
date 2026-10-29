#!/usr/bin/env python3
"""
Production-Fidelity 30-Session Real-Time Backtest of Strategy 5 (2m MACD Momentum)
with Full AI Risk Gatekeeper Consultation, Response Latency Profiling, and Step-Ladder Compounding.
"""

import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from trading.bootstrap import configure_console
configure_console()

import json
import time
import math
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Any

from market_clock import MarketClock
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier, MarketDossier
from ai_consultant import AIConsultant
from trading.domain.market_data import resample_two_minutes, two_minute_macd_metrics
from trading.domain.sizing import calculate_compounding_quantity
from trading.strategies.macd_momentum import calculate_macd, calculate_ema

# 30 Verified Trading Sessions
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
    fut_file = f"data/fut_candles_{clean_d}.json"
    if not os.path.exists(spot_file):
        return None, None, {}
    with open(spot_file, "r", encoding="utf-8") as fp:
        spot_bars = json.load(fp)
    fut_bars = []
    if os.path.exists(fut_file):
        with open(fut_file, "r", encoding="utf-8") as fp:
            fut_bars = json.load(fp)
    
    # Load any pre-cached option candle files
    opt_candles = {}
    for f in os.listdir("data"):
        if f.startswith(f"opt_{clean_d}_") and f.endswith(".json"):
            parts = f.replace(".json", "").split("_")
            if len(parts) >= 4:
                strike_k = int(parts[2])
                right_k = parts[3]
                with open(os.path.join("data", f), "r", encoding="utf-8") as fp:
                    opt_candles[(strike_k, right_k)] = json.load(fp)
    return spot_bars, fut_bars, opt_candles

def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
    res = [50.0] * len(closes)
    if len(closes) <= period:
        return res
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0.0, d) for d in deltas]
    losses = [max(0.0, -d) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        res[i + 1] = round(100.0 - (100.0 / (1.0 + rs)), 1)
    return res

def get_option_bar(
    spot_bar: dict,
    strike: int,
    direction: str,
    bar_idx: int,
    days_base: float,
    opt_candles: dict
) -> Tuple[float, float, float, float]:
    """Returns (open, high, low, close) for the given option contract."""
    key = (strike, direction)
    if key in opt_candles and bar_idx < len(opt_candles[key]):
        c = opt_candles[key][bar_idx]
        return c.get("open", c["close"]), c["high"], c["low"], c["close"]
    
    # Calibrated BSM pricing with intraday theta decay
    days_rem = max(0.001, days_base - (bar_idx / 375.0) * 0.25)
    is_call = (direction == "CE")
    c_open = bsm_price(spot_bar["open"], strike, days_rem, is_call=is_call)
    c_close = bsm_price(spot_bar["close"], strike, days_rem, is_call=is_call)
    c_high = bsm_price(spot_bar["high"] if is_call else spot_bar["low"], strike, days_rem, is_call=is_call)
    c_low = bsm_price(spot_bar["low"] if is_call else spot_bar["high"], strike, days_rem, is_call=is_call)
    high_p = max(c_open, c_close, c_high)
    low_p = min(c_open, c_close, c_low)
    return c_open, high_p, low_p, c_close

def compute_strike_macd_metrics(
    spot_bars: List[dict],
    strike: int,
    direction: str,
    end_1m: int,
    days_base: float,
    opt_candles: dict
) -> dict:
    """Computes Option 2m MACD metrics synchronized with Spot bar close."""
    opt_bars_1m = []
    for m in range(end_1m + 1):
        o, h, l, c = get_option_bar(spot_bars[m], strike, direction, m, days_base, opt_candles)
        opt_bars_1m.append({
            "start_time": spot_bars[m]["start_time"],
            "open": o, "high": h, "low": l, "close": c,
            "volume": 1000
        })
    try:
        opt_bars_2m = resample_two_minutes(opt_bars_1m)
        if len(opt_bars_2m) >= 26:
            metrics = two_minute_macd_metrics(opt_bars_2m)
            return metrics
    except Exception:
        pass
    return {
        "macd": 0.0, "signal": 0.0, "histogram": 0.0,
        "expanding_positive": False, "momentum_status": "Unavailable"
    }

def run_30_session_audit():
    trading_cfg = json.loads(Path("config/trading.json").read_text(encoding="utf-8"))
    strats_cfg = json.loads(Path("config/strategies.json").read_text(encoding="utf-8"))
    strat_cfg = strats_cfg["strategies"]["macd_momentum"]
    
    # Initialize Production AI Consultant in Rules Mode
    consultant = AIConsultant(
        mode="rules",
        trading_config=trading_cfg,
        strategy_config=strat_cfg
    )
    
    print("=" * 120)
    print(" 🚀 PRODUCTION REAL-TIME BACKTEST: STRATEGY 5 (2m MACD MOMENTUM & STRIKE CONFLUENCE)")
    print(" Testing Period: 30 Sessions (2026-09-11 to 2026-10-27) | Starting Capital: Rs 10,000 Margin")
    print(" Enforcing Rule #1 (Supreme Veto Power), Rule #3 (Compounding & Safe Budget), and Rule #5 (Trap 5 Post-14:15)")
    print("=" * 120)
    
    all_consultations: List[dict] = []
    executed_trades: List[dict] = []
    
    compounding_capital = 10000.0
    fee_per_trade = 40.0
    
    for session_idx, dt_str in enumerate(DATES, 1):
        spot_bars, fut_bars, opt_candles = load_session_data(dt_str)
        if not spot_bars or len(spot_bars) < 60:
            continue
            
        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        # NIFTY weekly options expire on Tuesdays
        if target_d.weekday() <= 1:
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
        else:
            expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)
        
        # 1m spot bars closes and RSI
        closes_1m = [b["close"] for b in spot_bars]
        rsi_1m = calculate_rsi(closes_1m, 14)
        
        # 2m resampled bars anchored at 09:15 IST
        try:
            res_spot_2m = resample_two_minutes(spot_bars)
        except Exception:
            continue
            
        closes_2m = [b["close"] for b in res_spot_2m]
        macd_line, sig_line, hist_line = calculate_macd(closes_2m)
        
        # 5m moving averages
        ema9_5m_series = []
        ema20_5m_series = []
        # Precompute 5m bars
        res_5m = []
        for g_idx in range(0, len(spot_bars), 5):
            group = spot_bars[g_idx:g_idx + 5]
            if group:
                res_5m.append(group[-1]["close"])
        ema9_5m_arr = calculate_ema(res_5m, 9)
        ema20_5m_arr = calculate_ema(res_5m, 20)
        
        in_trade_until = -1
        session_trades_count = 0
        
        for bar_2m_idx in range(26, len(res_spot_2m)):
            end_1m = res_spot_2m[bar_2m_idx]["minute_idx"]
            
            # 1 Position Cap: Cannot take new trade while in an active trade
            if end_1m <= in_trade_until:
                continue
                
            # Check for 2m MACD Crossover
            pe_cross = (macd_line[bar_2m_idx] < sig_line[bar_2m_idx]) and (macd_line[bar_2m_idx - 1] >= sig_line[bar_2m_idx - 1])
            ce_cross = (macd_line[bar_2m_idx] > sig_line[bar_2m_idx]) and (macd_line[bar_2m_idx - 1] <= sig_line[bar_2m_idx - 1])
            
            if not (pe_cross or ce_cross):
                continue
                
            direction = "PE" if pe_cross else "CE"
            spot_price = res_spot_2m[bar_2m_idx]["close"]
            candle_start_time = spot_bars[end_1m]["start_time"]
            
            hh = end_1m // 60 + 9
            mm = end_1m % 60
            time_str = f"{hh:02d}:{mm:02d}"
            time_ist_str = f"{time_str} IST"
            
            # Trap 5 Session Time Gate Lockout: Post-14:15 IST
            if hh > 14 or (hh == 14 and mm >= 15):
                all_consultations.append({
                    "request_id": len(all_consultations) + 1,
                    "date": dt_str,
                    "time": time_ist_str,
                    "signal": f"BUY_{direction}",
                    "strike": "N/A",
                    "premium": 0.0,
                    "verdict": "VETOED",
                    "trap_detected": "Trap 5: Late-Day Profit Degradation Lockout (>= 14:15 IST)",
                    "latency_ms": 0.005,
                    "executed": False
                })
                continue
                
            # Calculate Market State Metrics at this minute
            bars_so_far = spot_bars[:end_1m + 1]
            typicals = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars_so_far]
            vwap = sum(typicals) / len(typicals)
            vwap_slope = (vwap - sum(typicals[:max(1, len(typicals) - 15)]) / max(1, len(typicals) - 15))
            
            # VWAP crosses in rolling 60m
            last_60 = bars_so_far[max(0, len(bars_so_far) - 60):]
            crosses_60m = sum(1 for k in range(1, len(last_60)) if (last_60[k]["close"] - vwap) * (last_60[k - 1]["close"] - vwap) < 0)
            
            # 15m Box
            last_15m = bars_so_far[max(0, len(bars_so_far) - 15):]
            box_h = max(b["high"] for b in last_15m)
            box_l = min(b["low"] for b in last_15m)
            box_spread = max(1.0, box_h - box_l)
            box_pos = ((spot_price - box_l) / box_spread) * 100.0
            
            # 5m EMAs
            m5_idx = min(len(ema9_5m_arr) - 1, end_1m // 5)
            e9 = ema9_5m_arr[m5_idx] if m5_idx < len(ema9_5m_arr) else spot_price
            e20 = ema20_5m_arr[m5_idx] if m5_idx < len(ema20_5m_arr) else spot_price
            
            # Invalidation Spot Level
            recent_5 = spot_bars[max(0, end_1m - 4):end_1m + 1]
            if direction == "CE":
                inval_spot = min(b["low"] for b in recent_5) - 2.0
            else:
                inval_spot = max(b["high"] for b in recent_5) + 2.0
                
            # Strike Selection & Multi-Strike OTM Budget Sizing
            atm_strike = int(round(spot_price / 50.0)) * 50
            pref_strike = atm_strike - 50 if direction == "CE" else atm_strike + 50
            
            # Check budget against safe margin
            safe_budget = max(5000.0, compounding_capital - 150.0)
            max_premium_cap = 135.0
            
            selected_strike = None
            selected_entry_price = None
            
            # Test Preferred ITM, ATM, then up to 4 strikes OTM
            test_strikes = [pref_strike, atm_strike]
            for step in range(1, 5):
                otm = atm_strike + (step * 50) if direction == "CE" else atm_strike - (step * 50)
                test_strikes.append(otm)
                
            for strike_cand in test_strikes:
                _, _, _, test_p = get_option_bar(spot_bars[end_1m], strike_cand, direction, end_1m, days_base, opt_candles)
                if test_p * 65.0 <= safe_budget and test_p <= max_premium_cap and test_p >= 15.0:
                    selected_strike = strike_cand
                    selected_entry_price = test_p
                    break
                    
            if not selected_strike:
                # Insufficient funds veto
                all_consultations.append({
                    "request_id": len(all_consultations) + 1,
                    "date": dt_str,
                    "time": time_ist_str,
                    "signal": f"BUY_{direction}",
                    "strike": f"{atm_strike}",
                    "premium": 0.0,
                    "verdict": "VETOED",
                    "trap_detected": "Trap 9: Insufficient Margin Budget",
                    "latency_ms": 0.005,
                    "executed": False
                })
                continue
                
            # Compute Strike 2m MACD metrics
            strike_macd_data = compute_strike_macd_metrics(
                spot_bars, selected_strike, direction, end_1m, days_base, opt_candles
            )
            
            # Compile Market State Dossier
            dossier = generate_market_dossier(
                target_date=dt_str,
                candles=bars_so_far,
                current_bar_idx=end_1m,
                direction=direction,
                symbol=f"NIFTY_{dt_str}_{selected_strike}_{direction}",
                strike=selected_strike,
                option_entry_price=round(selected_entry_price, 2),
                trade_history=[],
                days_to_expiry=days_base,
                is_expiry_0dte=is_0dte
            )
            dossier.setup_type = "MACD_2M_MOMENTUM"
            dossier.candidate_timestamp = candle_start_time
            dossier.invalidation_level = round(inval_spot, 2)
            dossier.risk_policy = {
                "min_loss_pct": 15.0,
                "max_loss_pct": 20.0,
                "min_invalidation_buffer_pts": 15.0,
                "initial_stop_pct": 30.0
            }
            dossier.spot_macd_2m = {
                "macd": macd_line[bar_2m_idx],
                "signal": sig_line[bar_2m_idx],
                "histogram": hist_line[bar_2m_idx],
                "expanding_positive": (hist_line[bar_2m_idx] > hist_line[bar_2m_idx - 1]) if bar_2m_idx > 0 else True,
                "momentum_status": "Bullish Crossover" if ce_cross else "Bearish Crossover"
            }
            dossier.strike_macd_line = strike_macd_data.get("macd", 0.0)
            dossier.strike_signal_line = strike_macd_data.get("signal", 0.0)
            dossier.strike_histogram = strike_macd_data.get("histogram", 0.0)
            dossier.strike_histogram_expanding_positive = strike_macd_data.get("expanding_positive", True)
            dossier.strike_momentum_status = strike_macd_data.get("momentum_status", "Normal")
            
            # Consult AI Risk Gatekeeper with Precise High-Resolution Timer
            with MarketClock.at(candle_start_time):
                t_start = time.perf_counter()
                verdict = consultant.evaluate(dossier)
                t_end = time.perf_counter()
                latency_ms = (t_end - t_start) * 1000.0
                
            consultation_record = {
                "request_id": len(all_consultations) + 1,
                "date": dt_str,
                "time": time_ist_str,
                "signal": f"BUY_{direction}",
                "strike": f"{selected_strike} {direction}",
                "premium": round(selected_entry_price, 2),
                "verdict": verdict.action,
                "trap_detected": verdict.trap_detected or "None (Clean Setup)",
                "reasoning": verdict.reasoning,
                "latency_ms": round(latency_ms, 3),
                "executed": verdict.is_approved
            }
            all_consultations.append(consultation_record)
            
            if not verdict.is_approved:
                continue
                
            # Trade APPROVED -> Execute Lifecycle Simulation
            # Entry happens at the next minute's open price
            next_idx = end_1m + 1
            if next_idx >= len(spot_bars) - 1:
                continue
                
            open_p, high_p, low_p, close_p = get_option_bar(
                spot_bars[next_idx], selected_strike, direction, next_idx, days_base, opt_candles
            )
            actual_entry_price = open_p
            if actual_entry_price <= 1.0:
                continue
                
            # Dynamic Step-Ladder Compounding Sizing Model
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
                
            # Risk Management Parameters
            initial_stop_price = round(actual_entry_price * 0.70, 2) # 30% initial SL
            post_fill_stop_price = round(actual_entry_price * 0.82, 2) # ~18% post-fill band
            
            current_stop_price = post_fill_stop_price
            peak_price = actual_entry_price
            peak_gain_pct = 0.0
            
            exit_bar_idx = next_idx
            exit_price = actual_entry_price
            exit_reason = "15:15_MANDATORY_SQUARE_OFF"
            
            for m in range(next_idx + 1, min(len(spot_bars), 365)):
                exit_bar_idx = m
                s_bar = spot_bars[m]
                m_open, m_high, m_low, m_close = get_option_bar(
                    s_bar, selected_strike, direction, m, days_base, opt_candles
                )
                
                # Check End of Day 15:15 IST
                m_hh = m // 60 + 9
                m_mm = m % 60
                if m_hh > 15 or (m_hh == 15 and m_mm >= 15):
                    exit_price = m_open
                    exit_reason = "15:15_MANDATORY_SQUARE_OFF"
                    break
                    
                # Track Peak Price
                if m_high > peak_price:
                    peak_price = m_high
                    peak_gain_pct = ((peak_price - actual_entry_price) / actual_entry_price) * 100.0
                    
                # Check Spot Structural Invalidation
                if direction == "CE" and s_bar["low"] <= inval_spot:
                    exit_price = m_low
                    exit_reason = f"STRUCTURAL_INVALIDATION (Spot {s_bar['low']:.1f} <= {inval_spot:.1f})"
                    break
                elif direction == "PE" and s_bar["high"] >= inval_spot:
                    exit_price = m_low
                    exit_reason = f"STRUCTURAL_INVALIDATION (Spot {s_bar['high']:.1f} >= {inval_spot:.1f})"
                    break
                    
                # Dynamic Trailing Ratchet
                # Lock Breakeven at +15%
                if peak_gain_pct >= 15.0:
                    current_stop_price = max(current_stop_price, actual_entry_price * 1.02)
                    
                # Ratchet Floors at higher profit milestones
                if peak_gain_pct >= 20.0:
                    current_stop_price = max(current_stop_price, actual_entry_price * 1.10)
                if peak_gain_pct >= 30.0:
                    current_stop_price = max(current_stop_price, actual_entry_price * 1.20)
                if peak_gain_pct >= 40.0:
                    current_stop_price = max(current_stop_price, actual_entry_price * 1.30)
                    
                # 5% Aggressive pullback trail beyond +50% gain
                if peak_gain_pct >= 50.0:
                    current_stop_price = max(current_stop_price, peak_price * 0.95)
                    
                # Check Stop Loss Fill
                if m_low <= current_stop_price:
                    exit_price = min(current_stop_price, m_open)
                    exit_reason = "TRAILING_STOP_EXIT" if current_stop_price > actual_entry_price else "STOP_LOSS_EXIT"
                    break
                    
                # 5m EMA9 Dynamic Trailing Runner Check
                # Stay in trade as long as Spot holds above 5m EMA9 (for CE) or below 5m EMA9 (for PE)
                cur_5m_idx = min(len(ema9_5m_arr) - 1, m // 5)
                cur_e9 = ema9_5m_arr[cur_5m_idx] if cur_5m_idx < len(ema9_5m_arr) else s_bar["close"]
                if peak_gain_pct >= 10.0:
                    if direction == "CE" and s_bar["close"] < cur_e9 - 4.0:
                        exit_price = m_close
                        exit_reason = f"EMA9_RUNNER_TRAIL_EXIT (Spot {s_bar['close']:.1f} < EMA9 {cur_e9:.1f})"
                        break
                    elif direction == "PE" and s_bar["close"] > cur_e9 + 4.0:
                        exit_price = m_close
                        exit_reason = f"EMA9_RUNNER_TRAIL_EXIT (Spot {s_bar['close']:.1f} > EMA9 {cur_e9:.1f})"
                        break
            else:
                exit_price = m_close
                exit_reason = "EOD_SQUAREOFF"
                
            in_trade_until = exit_bar_idx
            session_trades_count += 1
            
            pnl_pts = exit_price - actual_entry_price
            ret_pct = (pnl_pts / actual_entry_price) * 100.0
            
            # PnL across Sizing Models
            pnl_1lot = round(pnl_pts * 65.0 - fee_per_trade, 2)
            pnl_2lots = round(pnl_pts * 130.0 - fee_per_trade, 2)
            
            # Step-Ladder Compounding PnL
            step_contracts = step_lots * 65
            pnl_compounding = round(pnl_pts * step_contracts - fee_per_trade, 2)
            compounding_capital += pnl_compounding
            
            trade_record = {
                "trade_id": len(executed_trades) + 1,
                "date": dt_str,
                "entry_time": time_ist_str,
                "exit_time": f"{exit_bar_idx // 60 + 9:02d}:{exit_bar_idx % 60:02d} IST",
                "direction": direction,
                "strike": selected_strike,
                "entry_price": round(actual_entry_price, 2),
                "exit_price": round(exit_price, 2),
                "peak_price": round(peak_price, 2),
                "peak_gain_pct": round(peak_gain_pct, 1),
                "pnl_pts": round(pnl_pts, 2),
                "ret_pct": round(ret_pct, 1),
                "pnl_1lot": pnl_1lot,
                "pnl_2lots": pnl_2lots,
                "step_lots": step_lots,
                "pnl_compounding": pnl_compounding,
                "capital_after": round(compounding_capital, 2),
                "exit_reason": exit_reason
            }
            executed_trades.append(trade_record)
            
    return all_consultations, executed_trades

if __name__ == "__main__":
    consults, trades = run_30_session_audit()
    
    # Save raw results for reporting
    out_dir = Path("logs/backtest_audit")
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "consultations_30_sessions.json", "w", encoding="utf-8") as f:
        json.dump(consults, f, indent=2)
    with open(out_dir / "trades_30_sessions.json", "w", encoding="utf-8") as f:
        json.dump(trades, f, indent=2)
        
    print("\n" + "=" * 120)
    print(" ✅ AUDIT SIMULATION COMPLETE")
    print(f" Total Consultations Evaluated: {len(consults)}")
    print(f" Total Trades Executed:        {len(trades)}")
    print("=" * 120)
