import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
from backtest_engine import bsm_price
from scratch.test_trap7_discriminators import run_discriminator_grid
from scratch.deep_dive_trap7 import load_data, resample_bars, calculate_ema, calculate_macd, calculate_sma, calculate_rsi, simulate_trade_raw, DATES
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
import json
from datetime import datetime, timedelta

def examine_rule4_trades():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    rule4_trades = []
    excluded_trades = []

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
                candle_aligned = (c_close > c_open) if direction == "CE" else (c_close < c_open)
                abs_slope = abs(dossier.vwap_slope_15m)

                item = {
                    "date": dt_str,
                    "time": f"{end_1m // 60 + 9:02d}:{end_1m % 60:02d}",
                    "dir": direction,
                    "spot": spot_price,
                    "vwap_dist": dossier.vwap_distance_pts,
                    "vwap_slope": dossier.vwap_slope_15m,
                    "abs_slope": abs_slope,
                    "candle_aligned": candle_aligned,
                    "fut_vr": f_vr,
                    "pnl_inr": tr_sim["pnl_inr"] if tr_sim else 0.0,
                    "peak_pct": tr_sim["peak_gain_pct"] if tr_sim else 0.0,
                    "exit_reason": tr_sim["exit_reason"] if tr_sim else "N/A"
                }

                if abs_slope <= 0.85 and candle_aligned and dossier.vwap_distance_pts <= 140.0:
                    rule4_trades.append(item)
                else:
                    excluded_trades.append(item)

    print("\n--- RULE 4 ACCEPTED TRADES (16 Trades) ---")
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'V-Dist':<6} | {'Slope':<7} | {'Fut-VR':<7} | {'Peak%':<6} | {'PnL (Rs)':<9} | {'Exit Reason'}")
    print("-" * 105)
    for t in sorted(rule4_trades, key=lambda x: x["pnl_inr"], reverse=True):
        print(f"{t['date']:<10} | {t['time']:<5} | {t['dir']:<3} | {t['vwap_dist']:<6.1f} | {t['vwap_slope']:<+7.3f} | {t['fut_vr']:<5.2f}x | +{t['peak_pct']:<5.1f}% | Rs {t['pnl_inr']:<8.1f} | {t['exit_reason']}")

    print("\n--- EXCLUDED BY RULE 4 (15 Trades) ---")
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'V-Dist':<6} | {'Slope':<7} | {'Fut-VR':<7} | {'Peak%':<6} | {'PnL (Rs)':<9} | {'Reason Excluded'}")
    print("-" * 105)
    for t in sorted(excluded_trades, key=lambda x: x["pnl_inr"], reverse=True):
        reasons = []
        if t["abs_slope"] > 0.85:
            reasons.append(f"Slope {t['abs_slope']:.2f} > 0.85")
        if not t["candle_aligned"]:
            reasons.append("Candle Opposed")
        if t["vwap_dist"] > 140.0:
            reasons.append(f"Dist {t['vwap_dist']:.1f} > 140")
        print(f"{t['date']:<10} | {t['time']:<5} | {t['dir']:<3} | {t['vwap_dist']:<6.1f} | {t['vwap_slope']:<+7.3f} | {t['fut_vr']:<5.2f}x | +{t['peak_pct']:<5.1f}% | Rs {t['pnl_inr']:<8.1f} | {', '.join(reasons)}")

if __name__ == "__main__":
    examine_rule4_trades()
