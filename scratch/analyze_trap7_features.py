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
from scratch.deep_dive_trap7 import load_data, resample_bars, calculate_ema, calculate_macd, calculate_sma, calculate_rsi, simulate_trade_raw, DATES

def analyze_option_volume_and_features():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    all_trap7 = []

    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_data(dt_str)
        if not spot_bars or not fut_bars or len(spot_bars) < 60:
            continue

        res_spot = resample_bars(spot_bars, 2)
        res_fut = resample_bars(fut_bars, 2)

        closes = [b["close"] for b in res_spot]
        macd, sig, hist = calculate_macd(closes)
        rsi_2m = calculate_rsi(closes, 14)
        fut_vols = [b["volume"] for b in res_fut]
        fut_sma_vols = calculate_sma(fut_vols, 20)

        # Build 2m resampled option candles if available
        res_opt = {}
        opt_sma_vols = {}
        for key in opt_candles.contracts:
            bars = opt_candles.series(*key)
            if len(bars) >= 60:
                res_opt[key] = resample_bars(bars, 2)
                opt_sma_vols[key] = calculate_sma([b["volume"] for b in res_opt[key]], 20)

        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        if target_d.weekday() <= 1:
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
        else:
            expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]

            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])

            if not (pe_cross or ce_cross):
                continue

            direction = "PE" if pe_cross else "CE"
            spot_price = res_spot[i]["close"]
            target_strike = int(round(spot_price / 50.0)) * 50
            f_vr = fut_vols[i] / fut_sma_vols[i] if (i < len(fut_sma_vols) and fut_sma_vols[i] > 0) else 1.0
            
            # Option volume ratio
            o_vr = 0.0
            key = (target_strike, direction)
            if key in res_opt:
                oi = next((j for j, b in enumerate(res_opt[key])
                           if b["start_time"] == res_spot[i]["start_time"]), None)
                if oi is not None and opt_sma_vols[key][oi] > 0:
                    o_vr = res_opt[key][oi]["volume"] / opt_sma_vols[key][oi]

            days_rem = days_base - (end_1m / 375.0) * 0.25

            selected_bar = opt_candles.bar(target_strike, direction, spot_bars[end_1m]["start_time"])
            if selected_bar is None:
                continue  # Never substitute a different strike or synthetic option price.
            est_opt_price = selected_bar["close"]

            dossier = generate_market_dossier(
                target_date=dt_str,
                candles=spot_bars,
                current_bar_idx=end_1m,
                direction=direction,
                symbol=f"NIFTY_{target_strike}_{direction}",
                strike=target_strike,
                option_entry_price=est_opt_price,
                trade_history=[],
                days_to_expiry=days_rem,
                is_expiry_0dte=is_0dte
            )

            verdict: AIVerdict = ai.evaluate(dossier)

            if verdict.trap_detected and "Trap 7" in verdict.trap_detected:
                tr_sim = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)
                hh = end_1m // 60 + 9
                mm = end_1m % 60
                time_str = f"{hh:02d}:{mm:02d}"

                # Calculate candle body / rejection wick
                c_open = res_spot[i]["open"]
                c_close = res_spot[i]["close"]
                c_high = res_spot[i]["high"]
                c_low = res_spot[i]["low"]
                c_range = max(0.01, c_high - c_low)
                
                # Bullish candle confirmation for CE, bearish candle for PE
                candle_aligned = (c_close > c_open) if direction == "CE" else (c_close < c_open)
                lower_wick = (min(c_open, c_close) - c_low) / c_range
                upper_wick = (c_high - max(c_open, c_close)) / c_range
                reversal_wick = lower_wick if direction == "CE" else upper_wick

                all_trap7.append({
                    "date": dt_str,
                    "time": time_str,
                    "dir": direction,
                    "spot": spot_price,
                    "vwap_dist": dossier.vwap_distance_pts,
                    "vwap_slope": dossier.vwap_slope_15m,
                    "abs_slope": abs(dossier.vwap_slope_15m),
                    "fut_vr": round(f_vr, 2),
                    "opt_vr": round(o_vr, 2),
                    "candle_aligned": candle_aligned,
                    "reversal_wick": round(reversal_wick, 2),
                    "macd_val": round(macd[i], 2),
                    "macd_hist": round(hist[i], 2),
                    "rsi_1m": round(dossier.rsi_1m, 1),
                    "rsi_2m": round(rsi_2m[i], 1) if i < len(rsi_2m) else 50.0,
                    "pnl_inr": tr_sim["pnl_inr"] if tr_sim else 0.0,
                    "ret_pct": tr_sim["ret_pct"] if tr_sim else 0.0,
                    "peak_pct": tr_sim["peak_gain_pct"] if tr_sim else 0.0,
                    "exit_reason": tr_sim["exit_reason"] if tr_sim else "N/A"
                })

    winners = [t for t in all_trap7 if t["pnl_inr"] > 0]
    losers = [t for t in all_trap7 if t["pnl_inr"] <= 0]

    print("\n" + "=" * 120)
    print(" DETAILED TRAP 7 FEATURE MATRIX: 14 WINNERS vs 17 LOSERS")
    print("=" * 120)
    print("--- WINNERS ---")
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'V-Dist':<6} | {'Slope':<7} | {'Fut-VR':<7} | {'Opt-VR':<7} | {'Candle':<6} | {'Wick':<5} | {'MACD':<6} | {'RSI1m':<5} | {'RSI2m':<5} | {'Peak%':<6} | {'PnL (Rs)':<9}")
    print("-" * 120)
    for w in sorted(winners, key=lambda x: x["pnl_inr"], reverse=True):
        c_str = "ALIGN" if w['candle_aligned'] else "AGAINST"
        print(f"{w['date']:<10} | {w['time']:<5} | {w['dir']:<3} | {w['vwap_dist']:<6.1f} | {w['vwap_slope']:<+7.3f} | {w['fut_vr']:<5.2f}x | {w['opt_vr']:<5.2f}x | {c_str:<6} | {w['reversal_wick']:<5.2f} | {w['macd_val']:<+6.1f} | {w['rsi_1m']:<5.1f} | {w['rsi_2m']:<5.1f} | +{w['peak_pct']:<5.1f}% | Rs {w['pnl_inr']:<8.1f}")

    print("\n--- LOSERS ---")
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'V-Dist':<6} | {'Slope':<7} | {'Fut-VR':<7} | {'Opt-VR':<7} | {'Candle':<6} | {'Wick':<5} | {'MACD':<6} | {'RSI1m':<5} | {'RSI2m':<5} | {'Peak%':<6} | {'PnL (Rs)':<9}")
    print("-" * 120)
    for l in sorted(losers, key=lambda x: x["pnl_inr"]):
        c_str = "ALIGN" if l['candle_aligned'] else "AGAINST"
        print(f"{l['date']:<10} | {l['time']:<5} | {l['dir']:<3} | {l['vwap_dist']:<6.1f} | {l['vwap_slope']:<+7.3f} | {l['fut_vr']:<5.2f}x | {l['opt_vr']:<5.2f}x | {c_str:<6} | {l['reversal_wick']:<5.2f} | {l['macd_val']:<+6.1f} | {l['rsi_1m']:<5.1f} | {l['rsi_2m']:<5.1f} | +{l['peak_pct']:<5.1f}% | Rs {l['pnl_inr']:<8.1f}")

if __name__ == "__main__":
    analyze_option_volume_and_features()
