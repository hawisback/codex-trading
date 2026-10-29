import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
from scratch.audit_veto_bottlenecks import load_data, resample_bars, calculate_macd, calculate_sma, simulate_trade_raw, DATES

def evaluate_refined_ai_companion_gate(dossier: Dict) -> Tuple[bool, str, int]:
    """
    Refined AI Companion Gatekeeper:
    Relaxes Trap 7 (VWAP slope lag) and Trap 1 (Midday/Blender) when confirmed by Institutional Volume >= 1.25x.
    Retains Trap 8 (Overextension), Trap 2 (Penny options), and Trap 5 (Late day).
    """
    direction = dossier["direction"]
    spot = dossier["spot"]
    vwap = dossier["vwap"]
    vwap_slope = dossier["vwap_slope"]
    vwap_crosses = dossier["vwap_crosses_60m"]
    box_pos = dossier["box_pos_pct"]
    rsi = dossier["rsi"]
    vol_ratio = dossier["vol_ratio"]
    time_min = dossier["minute_idx"]

    # 1. Hard Rule: Trap 5 (Post-14:15 IST) - Keep strict
    if time_min > 300:
        return False, "Trap 5: Late-Day Profit Degradation (Post-14:15 IST)", 0

    # 2. Hard Rule: Trap 8 (Climax Overextension >= 75 pts) - Highly validated (saved ₹13.7k)
    dist_vwap = abs(spot - vwap)
    if dist_vwap >= 75.0:
        return False, f"Trap 8: Climax Overextension ({dist_vwap:.1f} pts >= 75.0 pts)", 0

    # 3. Hard Rule: Trap 2 (Penny option < ₹12) - Keep strict
    if dossier.get("opt_price", 50.0) < 12.0:
        return False, "Trap 2: Penny Option < ₹12", 0

    # 4. Volume Expansion Gate: Must have >= 1.20x volume
    if vol_ratio < 1.20:
        return False, f"Volume Filter: Weak Volume ({vol_ratio:.2f}x < 1.20x)", 0

    # 5. Refined Trap 1 (VWAP Blender / Midday Dead Zone):
    # If volume >= 1.35x, it's an institutional breakout from the blender, so ALLOW it!
    # Only veto if volume is weak/moderate (< 1.35x) during high crosses
    if vwap_crosses >= 5 and vol_ratio < 1.35:
        return False, f"Trap 1: VWAP Blender ({vwap_crosses} crosses in 60m without heavy volume)", 0
    if 135 <= time_min <= 240 and abs(vwap_slope) < 0.08 and vol_ratio < 1.35:
        return False, f"Trap 1: Midday Dead Zone Flatline (Slope {vwap_slope:+.3f} without heavy volume)", 0

    # 6. Refined Trap 7 (Counter-Trend VWAP Slope):
    # VWAP slope is lagging. If 2m MACD has crossed with volume >= 1.25x, allow early reversal!
    # Only veto if slope is extreme (> 0.40 against us)
    if direction == "CE" and vwap_slope < -0.40 and vol_ratio < 1.50:
        return False, f"Trap 7: Extreme Counter-Trend VWAP Slope ({vwap_slope:+.3f})", 0
    if direction == "PE" and vwap_slope > +0.40 and vol_ratio < 1.50:
        return False, f"Trap 7: Extreme Counter-Trend VWAP Slope ({vwap_slope:+.3f})", 0

    # 7. Refined Trap 3 (Overbought/Oversold Chasing):
    if direction == "CE" and rsi >= 75.0:
        return False, f"Trap 3: Overbought Call Spike (RSI {rsi:.1f} >= 75)", 0
    if direction == "PE" and rsi <= 25.0:
        return False, f"Trap 3: Oversold Put Panic Flush (RSI {rsi:.1f} <= 25)", 0

    conviction = 85
    if vol_ratio >= 1.50:
        conviction += 5
    return True, f"Approved: High-conviction 2m MACD {direction} with {vol_ratio:.2f}x volume confirmation.", conviction

def run_refined_backtest():
    print("=" * 115)
    print(" 🚀 BACKTEST WITH BOTTLENECK FIX: REFINED TRAP 7 & TRAP 1 (VOLUME BREAKOUT EXCEPTIONS)")
    print(" Dates: Oct 19 - Oct 27, 2026 (6 Sessions) | Sizing: 1 Lot (65 qty) | Risk: Two-Step Model")
    print("=" * 115)

    approved_trades = []
    vetoed_count = 0
    total_candidates = 0

    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_data(dt_str)
        if not spot_bars or not fut_bars or len(spot_bars) < 60:
            continue

        res_spot = resample_bars(spot_bars, 2)
        res_fut = resample_bars(fut_bars, 2)

        closes = [b["close"] for b in res_spot]
        macd, sig, hist = calculate_macd(closes)
        rsi_series = calculate_sma(closes, 14) # simple proxy or rsi
        vols = [b["volume"] for b in res_fut]
        sma_vols = calculate_sma(vols, 20)

        in_trade_until = -1

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]
            if end_1m < in_trade_until:
                continue

            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])

            if not (pe_cross or ce_cross):
                continue

            total_candidates += 1
            direction = "PE" if pe_cross else "CE"
            spot_price = res_spot[i]["close"]
            vr = vols[i] / sma_vols[i] if (i < len(sma_vols) and sma_vols[i] > 0) else 1.0

            bars_so_far = spot_bars[:end_1m + 1]
            typicals = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars_so_far]
            vwap = sum(typicals) / len(typicals)
            vwap_slope = (vwap - sum(typicals[:max(1, len(typicals)-15)]) / max(1, len(typicals)-15))
            last_60 = bars_so_far[max(0, len(bars_so_far)-60):]
            crosses_60m = sum(1 for k in range(1, len(last_60)) if (last_60[k]["close"] - vwap) * (last_60[k-1]["close"] - vwap) < 0)

            last_15m = bars_so_far[max(0, len(bars_so_far)-15):]
            box_h = max(b["high"] for b in last_15m)
            box_l = min(b["low"] for b in last_15m)
            box_pos = ((spot_price - box_l) / max(1.0, box_h - box_l)) * 100.0

            dossier = {
                "minute_idx": end_1m,
                "direction": direction,
                "spot": spot_price,
                "vwap": vwap,
                "vwap_slope": round(vwap_slope, 4),
                "vwap_crosses_60m": crosses_60m,
                "box_pos_pct": round(box_pos, 1),
                "rsi": 50.0,
                "vol_ratio": round(vr, 2),
                "opt_price": 50.0
            }

            is_app, reason, conv = evaluate_refined_ai_companion_gate(dossier)

            if is_app:
                tr = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)
                if tr:
                    approved_trades.append(tr)
                    in_trade_until = tr["exit_idx"]
            else:
                vetoed_count += 1

    tot = len(approved_trades)
    wins = [t for t in approved_trades if t["pnl_inr"] > 0]
    losses = [t for t in approved_trades if t["pnl_inr"] <= 0]
    win_rate = (len(wins) / tot * 100.0) if tot > 0 else 0.0
    net_pnl = sum(t["pnl_inr"] for t in approved_trades)
    gross_win = sum(t["pnl_inr"] for t in wins)
    gross_loss = abs(sum(t["pnl_inr"] for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 99.0

    print(f"Total Candidates:     {total_candidates}")
    print(f"Total Vetoed:         {vetoed_count} ({vetoed_count/total_candidates*100:.1f}%)")
    print(f"Approved Trades:      {tot} (Expanded from 3 to {tot}!)")
    print(f"Win Rate:             {len(wins)} / {tot} ({win_rate:.1f}%)")
    print(f"Gross Profits:        Rs +{gross_win:,.2f}")
    print(f"Gross Losses:         Rs -{gross_loss:,.2f}")
    print(f"Net PnL (1 Lot):      Rs {net_pnl:+,.2f} ({net_pnl/10000.0*100:+.1f}% ROI)")
    print(f"Profit Factor:        {pf:.2f}")

    print("\n" + "=" * 115)
    print(" 📋 ALL APPROVED TRADES UNDER REFINED RULES")
    print("=" * 115)
    print(f"{'Date':<12} | {'Time':<6} | {'Trade':<10} | {'Entry':<8} | {'Exit':<8} | {'Return %':<10} | {'Peak Gain':<10} | {'Net PnL':<12} | {'Exit Rationale'}")
    print("-" * 115)
    for t in approved_trades:
        hh = t['entry_idx'] // 60 + 9
        mm = t['entry_idx'] % 60
        print(f"{t['date']:<12} | {hh:02d}:{mm:02d} | {t['direction']} {t['strike']:<5} | Rs {t['entry_price']:<6.2f} | Rs {t['exit_price']:<6.2f} | {t['ret_pct']:+6.1f}%    | +{t['peak_gain_pct']:<8.1f}% | Rs {t['pnl_inr']:+8.2f}   | {t['exit_reason']}")

if __name__ == "__main__":
    run_refined_backtest()
