import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
from types import SimpleNamespace
from datetime import datetime, timedelta
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
from scratch.deep_dive_trap7 import load_data, resample_bars, calculate_ema, calculate_macd, calculate_sma, calculate_rsi, simulate_trade_raw, DATES

def simulate_with_trap1_setting(disable_trap1=False):
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    all_executed_trades = []

    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_data(dt_str)
        if not spot_bars or not fut_bars or len(spot_bars) < 60:
            continue

        res_spot = resample_bars(spot_bars, 2)
        res_fut = resample_bars(fut_bars, 2)

        closes = [b["close"] for b in res_spot]
        macd, sig, hist = calculate_macd(closes)
        fut_vols = [b["volume"] for b in res_fut]
        fut_sma_vols = calculate_sma(fut_vols, 20)

        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        if target_d.weekday() <= 1:
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
        else:
            expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)

        daily_trades = []
        busy_until_1m_idx = -1
        realized_pnl_today = 0.0

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]

            if end_1m < busy_until_1m_idx:
                continue

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
                trade_history=daily_trades,
                days_to_expiry=days_rem,
                is_expiry_0dte=is_0dte
            )

            # If simulating disabling Trap 1, we can temporarily clear blender warning and set session phase to MORNING_TREND
            if disable_trap1:
                dossier.vwap_blender_warning = False
                if "MIDDAY_DEAD_ZONE" in dossier.session_phase:
                    dossier.session_phase = "ACTIVE_EXPANSION"

            verdict: AIVerdict = ai.evaluate(dossier)

            if verdict.is_approved:
                tr_sim = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)
                if tr_sim:
                    busy_until_1m_idx = tr_sim["exit_idx"]
                    realized_pnl_today += tr_sim["pnl_inr"]

                    hh_en = end_1m // 60 + 9
                    mm_en = end_1m % 60
                    hh_ex = tr_sim["exit_idx"] // 60 + 9
                    mm_ex = tr_sim["exit_idx"] % 60

                    trade_record = {
                        "date": dt_str,
                        "entry_time": f"{hh_en:02d}:{mm_en:02d}",
                        "exit_time": f"{hh_ex:02d}:{mm_ex:02d}",
                        "dir": direction,
                        "strike": target_strike,
                        "spot": spot_price,
                        "entry_price": tr_sim["entry_price"],
                        "exit_price": tr_sim["exit_price"],
                        "peak_gain_pct": tr_sim["peak_gain_pct"],
                        "pnl_inr": tr_sim["pnl_inr"],
                        "ret_pct": tr_sim["ret_pct"],
                        "exit_reason": tr_sim["exit_reason"]
                    }
                    daily_trades.append(SimpleNamespace(direction=direction, pnl=tr_sim["pnl_inr"], exit_price=tr_sim["exit_price"]))
                    all_executed_trades.append(trade_record)

    return all_executed_trades

if __name__ == "__main__":
    with_trap1 = simulate_with_trap1_setting(disable_trap1=False)
    without_trap1 = simulate_with_trap1_setting(disable_trap1=True)

    print("=" * 110)
    print(" 🔬 IMPACT ANALYSIS: WITH TRAP 1 vs WITHOUT TRAP 1 (SEQUENTIAL PORTFOLIO)")
    print("=" * 110)

    for name, trs in [("WITH TRAP 1 (Midday Dead Zone & Blender Active)", with_trap1), ("WITHOUT TRAP 1 (Trap 1 Removed)", without_trap1)]:
        n = len(trs)
        wins = [t for t in trs if t["pnl_inr"] > 0]
        losses = [t for t in trs if t["pnl_inr"] <= 0]
        win_pnl = sum(t["pnl_inr"] for t in wins)
        loss_pnl = sum(abs(t["pnl_inr"]) for t in losses)
        net_pnl = win_pnl - loss_pnl
        wr = (len(wins) / n * 100) if n > 0 else 0
        pf = (win_pnl / loss_pnl) if loss_pnl > 0 else 99.9

        print(f"\n>>> {name} <<<")
        print(f"Total Trades Taken  : {n}")
        print(f"Win / Loss Count    : {len(wins)} Wins / {len(losses)} Losses")
        print(f"Win Rate            : {wr:.1f}%")
        print(f"Gross Profit        : Rs {win_pnl:,.2f}")
        print(f"Gross Loss          : Rs {loss_pnl:,.2f}")
        print(f"Net Realized P&L    : Rs {net_pnl:+,.2f}")
        print(f"Profit Factor       : {pf:.2f}")

    print("\n" + "=" * 110)
    print(" NEW TRADES EXECUTED WHEN TRAP 1 IS REMOVED:")
    print("=" * 110)
    new_trades = [t for t in without_trap1 if t not in with_trap1]
    if not new_trades:
        print("No new trades executed.")
    else:
        print(f"{'Date':<10} | {'Entry':<5} | {'Exit':<5} | {'Dir':<3} | {'Strike':<6} | {'Entry (Rs)':<10} | {'Exit (Rs)':<10} | {'Peak%':<6} | {'PnL (Rs)':<10} | {'Exit Reason'}")
        print("-" * 110)
        for t in new_trades:
            print(f"{t['date']:<10} | {t['entry_time']:<5} | {t['exit_time']:<5} | {t['dir']:<3} | {t['strike']:<6} | Rs {t['entry_price']:<7.2f} | Rs {t['exit_price']:<7.2f} | +{t['peak_gain_pct']:<5.1f}% | Rs {t['pnl_inr']:<8.1f} | {t['exit_reason']}")
