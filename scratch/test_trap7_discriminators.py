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

def run_discriminator_grid():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    candidates = []

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
                c_open = res_spot[i]["open"]
                c_close = res_spot[i]["close"]
                c_high = res_spot[i]["high"]
                c_low = res_spot[i]["low"]
                
                # Prior 3 candles trend
                prior_3_closes = [res_spot[k]["close"] for k in range(max(0, i-3), i)]
                
                candle_aligned = (c_close > c_open) if direction == "CE" else (c_close < c_open)
                hist_expanding = (hist[i] > hist[i-1]) if direction == "CE" else (hist[i] < hist[i-1])
                
                # Check if price has crossed 2m EMA9 or EMA20
                ema9_2m = calculate_ema(closes[:i+1], 9)[-1]
                above_ema9 = (c_close > ema9_2m) if direction == "CE" else (c_close < ema9_2m)

                candidates.append({
                    "date": dt_str,
                    "time": f"{end_1m // 60 + 9:02d}:{end_1m % 60:02d}",
                    "dir": direction,
                    "spot": spot_price,
                    "vwap_dist": dossier.vwap_distance_pts,
                    "vwap_slope": dossier.vwap_slope_15m,
                    "abs_slope": abs(dossier.vwap_slope_15m),
                    "fut_vr": f_vr,
                    "candle_aligned": candle_aligned,
                    "hist_expanding": hist_expanding,
                    "above_ema9": above_ema9,
                    "rsi_1m": dossier.rsi_1m,
                    "rsi_2m": rsi_2m[i] if i < len(rsi_2m) else 50.0,
                    "pnl_inr": tr_sim["pnl_inr"] if tr_sim else 0.0,
                    "ret_pct": tr_sim["ret_pct"] if tr_sim else 0.0,
                    "peak_pct": tr_sim["peak_gain_pct"] if tr_sim else 0.0,
                    "sim": tr_sim
                })

    print(f"Total Trap 7 candidates isolated: {len(candidates)}")
    print(f"Total raw PnL if all 31 taken: Rs {sum(c['pnl_inr'] for c in candidates):,.2f}")

    # Now let's test various candidate refinement rules
    rules = [
        (
            "Rule 0 (Current Baseline - Blanket Veto)",
            lambda c: False # Never approve any counter-trend
        ),
        (
            "Rule 1 (Permit All Counter-Trend - No Trap 7)",
            lambda c: True # Approve all
        ),
        (
            "Rule 2 (Slope Cap: |Slope| <= 0.85)",
            lambda c: c["abs_slope"] <= 0.85
        ),
        (
            "Rule 3 (Slope Cap <= 0.85 AND Candle Aligned)",
            lambda c: c["abs_slope"] <= 0.85 and c["candle_aligned"]
        ),
        (
            "Rule 4 (Slope Cap <= 0.85 AND Candle Aligned AND Dist <= 140 pts)",
            lambda c: c["abs_slope"] <= 0.85 and c["candle_aligned"] and c["vwap_dist"] <= 140.0
        ),
        (
            "Rule 5 (Slope Cap <= 0.85 AND Dist <= 100 pts)",
            lambda c: c["abs_slope"] <= 0.85 and c["vwap_dist"] <= 100.0
        ),
        (
            "Rule 6 (Candle Aligned AND Dist <= 100 pts AND |Slope| <= 0.85)",
            lambda c: c["candle_aligned"] and c["vwap_dist"] <= 100.0 and c["abs_slope"] <= 0.85
        ),
        (
            "Rule 7 (Candle Aligned AND Dist <= 100 pts AND |Slope| <= 0.85 AND 2m RSI in [35, 65])",
            lambda c: c["candle_aligned"] and c["vwap_dist"] <= 100.0 and c["abs_slope"] <= 0.85 and 35.0 <= c["rsi_2m"] <= 65.0
        ),
        (
            "Rule 8 (Candle Aligned AND Dist <= 100 pts AND |Slope| <= 0.85 AND Hist Expanding)",
            lambda c: c["candle_aligned"] and c["vwap_dist"] <= 100.0 and c["abs_slope"] <= 0.85 and c["hist_expanding"]
        ),
        (
            "Rule 9 (Candle Aligned AND Above 2m EMA9 AND |Slope| <= 0.85 AND Dist <= 100 pts)",
            lambda c: c["candle_aligned"] and c["above_ema9"] and c["abs_slope"] <= 0.85 and c["vwap_dist"] <= 100.0
        ),
        (
            "Rule 10 (Gentle Slope |Slope| <= 0.35 OR (Candle Aligned AND Dist <= 80 pts))",
            lambda c: (c["abs_slope"] <= 0.35 and c["candle_aligned"]) or (c["candle_aligned"] and c["vwap_dist"] <= 80.0 and c["abs_slope"] <= 0.85)
        ),
    ]

    print("\n" + "=" * 110)
    print(f"{'Rule Configuration':<65} | {'Trades':<6} | {'Wins':<4} | {'Loss':<4} | {'Win%':<6} | {'Net PnL (Rs)':<12} | {'Profit Factor'}")
    print("=" * 110)

    for name, predicate in rules:
        selected = [c for c in candidates if predicate(c)]
        n_trades = len(selected)
        if n_trades == 0:
            print(f"{name:<65} | {0:<6} | {0:<4} | {0:<4} | {'0.0%':<6} | Rs {0.0:<10.2f} | N/A")
            continue
        wins = [c for c in selected if c["pnl_inr"] > 0]
        losses = [c for c in selected if c["pnl_inr"] <= 0]
        win_pnl = sum(c["pnl_inr"] for c in wins)
        loss_pnl = sum(abs(c["pnl_inr"]) for c in losses)
        net_pnl = win_pnl - loss_pnl
        win_rate = (len(wins) / n_trades) * 100.0
        pf = (win_pnl / loss_pnl) if loss_pnl > 0 else 99.99

        print(f"{name:<65} | {n_trades:<6} | {len(wins):<4} | {len(losses):<4} | {win_rate:<5.1f}% | Rs {net_pnl:<10.2f} | {pf:<5.2f}")

if __name__ == "__main__":
    run_discriminator_grid()
