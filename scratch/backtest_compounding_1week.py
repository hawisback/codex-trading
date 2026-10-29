import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
from types import SimpleNamespace
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
from scratch.deep_dive_trap7 import load_data, resample_bars, calculate_ema, calculate_macd, calculate_sma, calculate_rsi, simulate_trade_raw, DATES

def extract_approved_signals():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    all_raw_trades = []

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

        daily_trades = []
        busy_until_1m_idx = -1

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

            # Native evaluation: Refined Trap 7 active, Trap 1 removed
            verdict: AIVerdict = ai.evaluate(dossier)

            if verdict.is_approved:
                tr_sim = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)
                if tr_sim:
                    busy_until_1m_idx = tr_sim["exit_idx"]

                    hh_en = end_1m // 60 + 9
                    mm_en = end_1m % 60
                    hh_ex = tr_sim["exit_idx"] // 60 + 9
                    mm_ex = tr_sim["exit_idx"] % 60

                    trade_record = {
                        "date": dt_str,
                        "entry_time": f"{hh_en:02d}:{mm_en:02d}",
                        "exit_time": f"{hh_ex:02d}:{mm_ex:02d}",
                        "direction": direction,
                        "strike": target_strike,
                        "spot": spot_price,
                        "entry_price": tr_sim["entry_price"],
                        "exit_price": tr_sim["exit_price"],
                        "peak_gain_pct": tr_sim["peak_gain_pct"],
                        "exit_reason": tr_sim["exit_reason"],
                        "cost_per_lot": tr_sim["entry_price"] * 65.0,
                        "pts": tr_sim["exit_price"] - tr_sim["entry_price"]
                    }
                    daily_trades.append(SimpleNamespace(
                        direction=direction,
                        pnl=tr_sim["pnl_inr"],
                        exit_price=tr_sim["exit_price"]
                    ))
                    all_raw_trades.append(trade_record)

    return all_raw_trades

def run_compounding_backtest(trades: List[Dict], mode: str, starting_capital: float = 10000.0) -> Dict:
    capital = starting_capital
    peak_capital = starting_capital
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    ledger = []
    skipped_count = 0

    for i, t in enumerate(trades, 1):
        cost_per_lot = t["cost_per_lot"]

        if mode == "fixed_2l":
            lots = 2
        elif mode == "step_ladder":
            # Milestone model:
            # < ₹20,000: 2 lots
            # ₹20,000 - ₹40,000: 4 lots
            # ₹40,000 - ₹70,000: 6 lots
            # ₹70,000 - ₹100,000: 8 lots
            # > ₹100,000: 10 lots (institutional cap)
            if capital < 20000.0:
                target_lots = 2
            elif capital < 40000.0:
                target_lots = 4
            elif capital < 70000.0:
                target_lots = 6
            elif capital < 100000.0:
                target_lots = 8
            else:
                target_lots = 10

            # Purchasing power buffer: Available cash minus ₹150 buffer
            max_affordable = int(max(0.0, capital - 150.0) // cost_per_lot)
            lots = min(target_lots, max_affordable)
        elif mode == "dynamic_margin":
            # Deploy available cash minus ₹150 buffer, capped at 10 lots
            max_affordable = int(max(0.0, capital - 150.0) // cost_per_lot)
            lots = min(10, max_affordable)
        else:
            lots = 2

        if lots < 1:
            skipped_count += 1
            ledger.append({
                "trade_idx": i,
                "date": t["date"],
                "entry_time": t["entry_time"],
                "exit_time": t["exit_time"],
                "trade_str": f"{t['direction']} {t['strike']}",
                "entry_price": t["entry_price"],
                "exit_price": t["exit_price"],
                "peak_gain_pct": t["peak_gain_pct"],
                "lots": 0,
                "qty": 0,
                "gross_pnl": 0.0,
                "fees": 0.0,
                "net_pnl": 0.0,
                "ending_capital": capital,
                "skipped": True,
                "exit_reason": "SKIPPED_INSUFFICIENT_MARGIN"
            })
            continue

        qty = lots * 65
        gross_pnl = round(t["pts"] * qty, 2)
        # Brokerage (₹40 round trip) + statutory charges (~₹25/lot for STT, GST, stamp, turnover)
        fees = round(40.0 + (lots * 25.0), 2)
        net_pnl = round(gross_pnl - fees, 2)

        capital = round(capital + net_pnl, 2)

        if capital > peak_capital:
            peak_capital = capital
        dd = peak_capital - capital
        dd_pct = (dd / peak_capital) * 100.0 if peak_capital > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd
        if dd_pct > max_drawdown_pct:
            max_drawdown_pct = dd_pct

        ledger.append({
            "trade_idx": i,
            "date": t["date"],
            "entry_time": t["entry_time"],
            "exit_time": t["exit_time"],
            "trade_str": f"{t['direction']} {t['strike']}",
            "entry_price": t["entry_price"],
            "exit_price": t["exit_price"],
            "peak_gain_pct": t["peak_gain_pct"],
            "lots": lots,
            "qty": qty,
            "gross_pnl": gross_pnl,
            "fees": fees,
            "net_pnl": net_pnl,
            "ending_capital": capital,
            "skipped": False,
            "exit_reason": t["exit_reason"]
        })

    executed = [x for x in ledger if not x["skipped"]]
    wins = [x for x in executed if x["net_pnl"] > 0]
    losses = [x for x in executed if x["net_pnl"] <= 0]
    gross_wins = sum(x["net_pnl"] for x in wins)
    gross_losses = sum(abs(x["net_pnl"]) for x in losses)
    total_net = round(capital - starting_capital, 2)
    roi_pct = round((total_net / starting_capital) * 100.0, 1)
    pf = (gross_wins / gross_losses) if gross_losses > 0 else 99.9

    return {
        "mode": mode,
        "starting_capital": starting_capital,
        "final_capital": capital,
        "net_pnl": total_net,
        "roi_pct": roi_pct,
        "total_trades": len(executed),
        "skipped_trades": skipped_count,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(executed) * 100.0, 1) if executed else 0.0,
        "gross_wins": gross_wins,
        "gross_losses": gross_losses,
        "profit_factor": round(pf, 2),
        "max_drawdown": round(max_drawdown, 2),
        "max_drawdown_pct": round(max_drawdown_pct, 1),
        "ledger": ledger
    }

def main():
    raw_trades = extract_approved_signals()
    print(f"\nExtracted {len(raw_trades)} sequential approved trades across Oct 19 - Oct 27, 2026.\n")

    res_fixed = run_compounding_backtest(raw_trades, mode="fixed_2l", starting_capital=10000.0)
    res_ladder = run_compounding_backtest(raw_trades, mode="step_ladder", starting_capital=10000.0)
    res_margin = run_compounding_backtest(raw_trades, mode="dynamic_margin", starting_capital=10000.0)

    print("=" * 115)
    print(" 🚀 1-WEEK COMPOUNDING BACKTEST COMPARISON (OCT 19 - OCT 27, 2026)")
    print("=" * 115)
    print(f"{'Compounding Model':<30} | {'Trades':<7} | {'Win%':<6} | {'Final Capital':<15} | {'Net Profit (₹)':<16} | {'Net ROI %':<10} | {'Max DD %':<9} | {'PF':<5}")
    print("-" * 115)
    for r in [res_fixed, res_ladder, res_margin]:
        m_name = {
            "fixed_2l": "1. Fixed 2 Lots (Baseline)",
            "step_ladder": "2. Step-Ladder Milestone",
            "dynamic_margin": "3. Dynamic Margin (Max 10L)"
        }[r["mode"]]
        print(f"{m_name:<30} | {r['total_trades']:<7} | {r['win_rate']:<5.1f}% | ₹{r['final_capital']:<14,.2f} | ₹{r['net_pnl']:<15,.2f} | {r['roi_pct']:<+9.1f}% | {r['max_drawdown_pct']:<8.1f}% | {r['profit_factor']:<5.2f}")

    print("\n" + "=" * 130)
    print(" 📖 STEP-LADDER COMPOUNDING TRADE-BY-TRADE AUDIT LEDGER")
    print("=" * 130)
    print(f"{'#':<3} | {'Date':<10} | {'Time':<11} | {'Setup':<10} | {'Entry':<8} | {'Exit':<8} | {'Peak%':<6} | {'Lots':<4} | {'Qty':<4} | {'Net P&L (₹)':<12} | {'Account Balance':<15} | {'Exit Reason'}")
    print("-" * 130)

    for item in res_ladder["ledger"]:
        if item["skipped"]:
            print(f"{item['trade_idx']:<3} | {item['date']:<10} | {item['entry_time']:<5}       | {item['trade_str']:<10} | Rs {item['entry_price']:<5.2f} | --     | --     | 0    | 0    | SKIPPED      | Rs {item['ending_capital']:<12,.2f} | INSUFFICIENT CASH")
        else:
            time_window = f"{item['entry_time']}-{item['exit_time']}"
            pnl_str = f"{item['net_pnl']:+,.2f}"
            print(f"{item['trade_idx']:<3} | {item['date']:<10} | {time_window:<11} | {item['trade_str']:<10} | Rs {item['entry_price']:<5.2f} | Rs {item['exit_price']:<5.2f} | +{item['peak_gain_pct']:<5.1f}% | {item['lots']:<4} | {item['qty']:<4} | Rs {pnl_str:<9} | Rs {item['ending_capital']:<12,.2f} | {item['exit_reason']}")

if __name__ == "__main__":
    main()
