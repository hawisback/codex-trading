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

def evaluate_refined_playbook(dossier, ai_consultant, res_spot_candle, vr_fut) -> Tuple[bool, str, Optional[str]]:
    """
    Evaluates dossier through AIConsultant rules, but applies the Refined Trap 7 Discriminator:
    - Counter-trend is permitted as an 'Institutional Reversal Inflection' IF:
      1. |vwap_slope_15m| <= 0.85 pts/min (No avalanche / freight train)
      2. vwap_distance_pts <= 140.0 pts (No deep unhinged runaway)
      3. Candle close is aligned with trade direction (Green candle for CE, Red candle for PE)
    - Otherwise, Counter-trend is strictly VETOED.
    """
    c_open = res_spot_candle["open"]
    c_close = res_spot_candle["close"]
    is_candle_aligned = (c_close > c_open) if dossier.direction == "CE" else (c_close < c_open)
    abs_slope = abs(dossier.vwap_slope_15m)

    is_reversal_inflection = (
        abs_slope <= 0.85 and 
        dossier.vwap_distance_pts <= 140.0 and 
        is_candle_aligned
    )

    # Let's temporarily inject or override Trap 7 logic
    verdict: AIVerdict = ai_consultant.evaluate(dossier)

    # If it was vetoed specifically by Trap 7
    if not verdict.is_approved and verdict.trap_detected and "Trap 7" in verdict.trap_detected:
        if is_reversal_inflection:
            # Override Trap 7 with Reversal Inflection Approval!
            return True, "APPROVED_REVERSAL_INFLECTION", None
        else:
            return False, "VETOED", verdict.trap_detected

    if not verdict.is_approved:
        return False, "VETOED", verdict.trap_detected

    return True, "APPROVED", None

def run_full_system_comparison():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    baseline_trades = []
    refined_trades = []

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

            # 1. BASELINE EVALUATION (Strict Crude Trap 7)
            base_verdict = ai.evaluate(dossier)
            base_approved = base_verdict.is_approved

            # 2. REFINED EVALUATION (Inflection-Aware Trap 7)
            ref_approved, ref_action, ref_trap = evaluate_refined_playbook(dossier, ai, res_spot[i], f_vr)

            sim_tr = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)

            time_str = f"{end_1m // 60 + 9:02d}:{end_1m % 60:02d}"

            record = {
                "date": dt_str,
                "time": time_str,
                "dir": direction,
                "strike": target_strike,
                "spot": spot_price,
                "opt_price": est_opt_price,
                "pnl_inr": sim_tr["pnl_inr"] if sim_tr else 0.0,
                "ret_pct": sim_tr["ret_pct"] if sim_tr else 0.0,
                "peak_pct": sim_tr["peak_gain_pct"] if sim_tr else 0.0,
                "exit_reason": sim_tr["exit_reason"] if sim_tr else "N/A"
            }

            if base_approved:
                baseline_trades.append(record)
            if ref_approved:
                refined_trades.append(record)

    print("\n" + "=" * 100)
    print(" 📊 SYSTEM PERFORMANCE COMPARISON: BASELINE vs REFINED TRAP 7")
    print("=" * 100)

    def print_metrics(name, tr_list):
        n = len(tr_list)
        if n == 0:
            print(f"{name}: 0 trades taken.")
            return
        wins = [t for t in tr_list if t["pnl_inr"] > 0]
        losses = [t for t in tr_list if t["pnl_inr"] <= 0]
        w_pnl = sum(t["pnl_inr"] for t in wins)
        l_pnl = sum(abs(t["pnl_inr"]) for t in losses)
        net_pnl = w_pnl - l_pnl
        win_rate = (len(wins) / n) * 100.0
        pf = (w_pnl / l_pnl) if l_pnl > 0 else 99.99

        print(f"\n>>> {name.upper()} <<<")
        print(f"Total Trades Taken  : {n}")
        print(f"Win / Loss Count    : {len(wins)} Wins / {len(losses)} Losses")
        print(f"Win Rate            : {win_rate:.1f}%")
        print(f"Gross Win P&L       : Rs {w_pnl:,.2f}")
        print(f"Gross Loss P&L      : Rs {l_pnl:,.2f}")
        print(f"Net Realized P&L    : Rs {net_pnl:+,.2f}")
        print(f"Profit Factor       : {pf:.2f}")

    print_metrics("Baseline Engine (Crude Trap 7)", baseline_trades)
    print_metrics("Refined Engine (Inflection-Aware Trap 7)", refined_trades)

    print("\n" + "=" * 100)
    print(" 📋 ALL NEW TRADES UNLOCKED BY REFINED TRAP 7")
    print("=" * 100)
    unlocked = [t for t in refined_trades if t not in baseline_trades]
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'Strike':<6} | {'Opt Price':<10} | {'Peak Gain':<10} | {'PnL (Rs)':<10} | {'Exit Reason'}")
    print("-" * 100)
    for u in sorted(unlocked, key=lambda x: x["pnl_inr"], reverse=True):
        print(f"{u['date']:<10} | {u['time']:<5} | {u['dir']:<3} | {u['strike']:<6} | Rs {u['opt_price']:<7.2f} | +{u['peak_pct']:<8.1f}% | Rs {u['pnl_inr']:<8.1f} | {u['exit_reason']}")

if __name__ == "__main__":
    run_full_system_comparison()
