import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
from backtest_engine import bsm_price
from scratch.deep_dive_trap7 import load_data, resample_bars, calculate_ema, calculate_macd, calculate_sma, calculate_rsi, simulate_trade_raw, DATES
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
import json
from datetime import datetime, timedelta

def compare_rule4_winners_losers():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    items = []

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

                if abs_slope <= 0.85 and candle_aligned and dossier.vwap_distance_pts <= 140.0:
                    # Let's inspect additional indicators:
                    # 1. 2m MACD line level
                    macd_val = macd[i]
                    # 2. 5m EMA9 distance from spot
                    ema9_5m = dossier.ema9_5m
                    spot_dist_ema9 = spot_price - ema9_5m
                    # 3. 15m Box range
                    box_15m = dossier.box_range_15m
                    # 4. ADX / Trend strength proxy (EMA spread)
                    ema_spread = dossier.ema_spread_5m
                    # 5. Volatility (High - Low of last 5 bars)
                    recent_range = max(b["high"] for b in res_spot[i-4:i+1]) - min(b["low"] for b in res_spot[i-4:i+1])

                    items.append({
                        "date": dt_str,
                        "time": f"{end_1m // 60 + 9:02d}:{end_1m % 60:02d}",
                        "dir": direction,
                        "spot": spot_price,
                        "vwap_dist": dossier.vwap_distance_pts,
                        "vwap_slope": dossier.vwap_slope_15m,
                        "abs_slope": abs_slope,
                        "ema_spread": ema_spread,
                        "spot_dist_ema9": spot_dist_ema9,
                        "box_15m": box_15m,
                        "recent_range": recent_range,
                        "rsi_1m": dossier.rsi_1m,
                        "rsi_2m": rsi_2m[i] if i < len(rsi_2m) else 50.0,
                        "macd_val": macd_val,
                        "fut_vr": f_vr,
                        "pnl_inr": tr_sim["pnl_inr"] if tr_sim else 0.0,
                        "peak_pct": tr_sim["peak_gain_pct"] if tr_sim else 0.0,
                        "exit_reason": tr_sim["exit_reason"] if tr_sim else "N/A"
                    })

    wins = [x for x in items if x["pnl_inr"] > 0]
    losses = [x for x in items if x["pnl_inr"] <= 0]

    print("WINNERS (9):")
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'V-Dist':<6} | {'Slope':<7} | {'EMA-Sprd':<8} | {'Dist-EMA9':<9} | {'Box15m':<7} | {'Rng5':<6} | {'RSI1m':<5} | {'RSI2m':<5} | {'MACD':<6} | {'PnL':<8}")
    print("-" * 115)
    for w in wins:
        print(f"{w['date']:<10} | {w['time']:<5} | {w['dir']:<3} | {w['vwap_dist']:<6.1f} | {w['vwap_slope']:<+7.3f} | {w['ema_spread']:<+8.1f} | {w['spot_dist_ema9']:<+9.1f} | {w['box_15m']:<7.1f} | {w['recent_range']:<6.1f} | {w['rsi_1m']:<5.1f} | {w['rsi_2m']:<5.1f} | {w['macd_val']:<+6.1f} | Rs {w['pnl_inr']:<7.1f}")

    print("\nLOSSES (7):")
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'V-Dist':<6} | {'Slope':<7} | {'EMA-Sprd':<8} | {'Dist-EMA9':<9} | {'Box15m':<7} | {'Rng5':<6} | {'RSI1m':<5} | {'RSI2m':<5} | {'MACD':<6} | {'PnL':<8}")
    print("-" * 115)
    for l in losses:
        print(f"{l['date']:<10} | {l['time']:<5} | {l['dir']:<3} | {l['vwap_dist']:<6.1f} | {l['vwap_slope']:<+7.3f} | {l['ema_spread']:<+8.1f} | {l['spot_dist_ema9']:<+9.1f} | {l['box_15m']:<7.1f} | {l['recent_range']:<6.1f} | {l['rsi_1m']:<5.1f} | {l['rsi_2m']:<5.1f} | {l['macd_val']:<+6.1f} | Rs {l['pnl_inr']:<7.1f}")

if __name__ == "__main__":
    compare_rule4_winners_losers()
