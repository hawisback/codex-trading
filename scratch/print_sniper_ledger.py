import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
from scratch.grid_search_macd_rsi_volume import precompute_market_data
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
from scratch.deep_dive_trap7 import simulate_trade_raw
from types import SimpleNamespace

def print_sniper_ledger():
    sessions = precompute_market_data()
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    capital = 10000.0
    print("=" * 125)
    print(" ðŸŽ¯ PARADIGM B: SNIPER (2m MACD + DUAL VOLUME >= 1.15x) TRADE-BY-TRADE LEDGER")
    print("=" * 125)
    print(f"{'#':<3} | {'Date':<10} | {'Time':<11} | {'Setup':<10} | {'Entry':<8} | {'Exit':<8} | {'Peak%':<6} | {'Lots':<4} | {'Net PnL (â‚¹)':<12} | {'Account Balance':<15} | {'Exit Reason'}")
    print("-" * 125)

    trade_num = 0
    for s in sessions:
        dt_str = s["date"]
        spot_bars = s["spot_bars"]
        opt_candles = s["opt_candles"]
        res_spot = s["res_spot"]
        macd = s["macd"]
        sig = s["sig"]
        fut_vols = s["fut_vols"]
        fut_sma_vols = s["fut_sma_vols"]
        res_opt = s["res_opt"]
        opt_sma_vols = s["opt_sma_vols"]
        days_base = s["days_base"]
        is_0dte = s["is_0dte"]

        daily_trades = []
        busy_until = -1

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]
            if end_1m < busy_until:
                continue

            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
            if not (pe_cross or ce_cross):
                continue

            direction = "PE" if pe_cross else "CE"
            f_vr = fut_vols[i] / fut_sma_vols[i] if (i < len(fut_sma_vols) and fut_sma_vols[i] > 0) else 1.0
            target_strike = int(round(res_spot[i]["close"] / 50.0)) * 50
            o_vr = 0.0
            key = (target_strike, direction)
            if key in res_opt:
                oi = next((j for j, b in enumerate(res_opt[key])
                           if b["start_time"] == res_spot[i]["start_time"]), None)
                if oi is not None and opt_sma_vols[key][oi] > 0:
                    o_vr = res_opt[key][oi]["volume"] / opt_sma_vols[key][oi]

            if f_vr < 1.15 and o_vr < 1.15:
                continue

            spot_price = res_spot[i]["close"]
            target_strike = int(round(spot_price / 50.0)) * 50
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
                trade_history=daily_trades,
                days_to_expiry=days_rem,
                is_expiry_0dte=is_0dte
            )

            verdict: AIVerdict = ai.evaluate(dossier)
            if verdict.is_approved:
                tr_sim = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)
                if tr_sim:
                    busy_until = tr_sim["exit_idx"]
                    daily_trades.append(SimpleNamespace(
                        direction=direction,
                        pnl=tr_sim["pnl_inr"],
                        exit_price=tr_sim["exit_price"]
                    ))

                    # Sizing
                    cost = tr_sim["entry_price"] * 65.0
                    target_lots = 2 if capital < 20000 else (4 if capital < 40000 else (6 if capital < 70000 else (8 if capital < 100000 else 10)))
                    lots = min(target_lots, int(max(0.0, capital - 150.0) // cost))
                    if lots < 1:
                        continue

                    qty = lots * 65
                    pts = tr_sim["exit_price"] - tr_sim["entry_price"]
                    gross_pnl = pts * qty
                    fees = 40.0 + (lots * 25.0)
                    net_pnl = gross_pnl - fees
                    capital += net_pnl
                    trade_num += 1

                    hh_en = end_1m // 60 + 9
                    mm_en = end_1m % 60
                    hh_ex = tr_sim["exit_idx"] // 60 + 9
                    mm_ex = tr_sim["exit_idx"] % 60
                    time_w = f"{hh_en:02d}:{mm_en:02d}-{hh_ex:02d}:{mm_ex:02d}"

                    print(f"{trade_num:<3} | {dt_str:<10} | {time_w:<11} | {direction} {target_strike:<5} | Rs {tr_sim['entry_price']:<5.2f} | Rs {tr_sim['exit_price']:<5.2f} | +{tr_sim['peak_gain_pct']:<5.1f}% | {lots:<4} | Rs {net_pnl:<+10,.2f} | Rs {capital:<12,.2f} | {tr_sim['exit_reason']}")

if __name__ == "__main__":
    print_sniper_ledger()
