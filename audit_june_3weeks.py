#!/usr/bin/env python3
"""
Custom Multi-Week Forensic Audit: June 2026 (3 Weeks / 15 Trading Sessions)
Comparing Raw Strategy 3 vs AI-Assisted Strategy 3 across:
- Week 1: June 01 - 05, 2026
- Week 2: June 08 - 12, 2026
- Week 3: June 15 - 19, 2026
"""

import sys
from collections import defaultdict
from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

consultant = AIConsultant(mode="playbook")
s3_cfg = StrategyConfig.load_from_config("institutional_pullback")

june_weeks = [
    ("Week 1 (Jun 01 - 05)", ["2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05"]),
    ("Week 2 (Jun 08 - 12)", ["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]),
    ("Week 3 (Jun 15 - 19)", ["2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"]),
]

def calc_stats(tr):
    n = len(tr)
    w = len([t for t in tr if t.pnl > 0])
    gross = sum(t.pnl for t in tr)
    fee = n * 40.0
    net = gross - fee
    w_s = sum(t.pnl for t in tr if t.pnl > 0)
    l_s = abs(sum(t.pnl for t in tr if t.pnl <= 0))
    pf = (w_s / l_s) if l_s > 0 else 999.0
    wr = (w / n * 100) if n else 0.0
    return {
        "n": n, "w": w, "wr": wr,
        "gross": gross, "fee": fee, "net": net, "pf": pf,
        "w_sum": w_s, "l_sum": l_s
    }

def run_june_audit():
    print("=" * 105)
    print(" 🔬 COMPREHENSIVE 3-WEEK FORENSIC AUDIT: JUNE 2026 (15 TRADING SESSIONS)")
    print(" Evaluating: Raw Strategy 3 vs AI-Assisted Strategy 3 (Persistent Learning Playbook)")
    print("=" * 105)

    all_raw_trades = []
    all_ai_trades = []
    trap_counts = defaultdict(int)
    vetoed_loss_savings = 0.0
    vetoed_win_missed = 0.0
    daily_rows = []

    for w_name, dates in june_weeks:
        w_raw, w_ai = [], []
        print(f"\n>>> {w_name.upper()} <<<")
        print(f"{'Date':<12} {'Nifty Spot Range':<22} {'Raw Trds':<10} {'Raw Net':<14} {'AI Trds':<10} {'AI Net':<14} {'Alpha Generated'}")
        print("-" * 105)

        for d in dates:
            eng = BacktestEngine(d)
            if not eng.spot_candles:
                continue
            
            spot_o = eng.spot_candles[0]["open"]
            spot_c = eng.spot_candles[-1]["close"]
            spot_h = max(c["high"] for c in eng.spot_candles)
            spot_l = min(c["low"] for c in eng.spot_candles)
            range_str = f"{spot_l:.0f} - {spot_h:.0f} ({spot_c - spot_o:+.0f})"

            dte = eng.get_expiry_days()
            trades = eng.run_simulation(s3_cfg)
            d_raw = list(trades)
            d_ai = []

            for i, t in enumerate(trades, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(
                    target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
                    direction=t.direction, symbol=t.symbol, strike=t.strike,
                    option_entry_price=t.entry_price, trade_history=trades[:i-1],
                    days_to_expiry=dte, is_expiry_0dte=(dte <= 0.2)
                )
                v = consultant.evaluate(dos)
                if v.is_approved:
                    d_ai.append(t)
                else:
                    trap_name = v.trap_detected or "General Veto"
                    trap_counts[trap_name] += 1
                    if t.pnl < 0:
                        vetoed_loss_savings += abs(t.pnl) + 40.0
                    else:
                        vetoed_win_missed += t.pnl - 40.0

            w_raw.extend(d_raw)
            w_ai.extend(d_ai)
            all_raw_trades.extend(d_raw)
            all_ai_trades.extend(d_ai)

            ds_r = calc_stats(d_raw)
            ds_a = calc_stats(d_ai)
            d_alpha = ds_a["net"] - ds_r["net"]
            print(f"{d:<12} {range_str:<22} {ds_r['n']:<10} Rs {ds_r['net']:>9.2f}  {ds_a['n']:<10} Rs {ds_a['net']:>9.2f}  Rs {d_alpha:>+10.2f}")

        ws_r = calc_stats(w_raw)
        ws_a = calc_stats(w_ai)
        w_alpha = ws_a["net"] - ws_r["net"]
        print("-" * 105)
        print(f" SUB-TOTAL: {w_name:<16} | Raw Net: Rs {ws_r['net']:>9.2f} ({ws_r['wr']:4.1f}%) | AI Net: Rs {ws_a['net']:>9.2f} ({ws_a['wr']:4.1f}%) | Alpha: Rs {w_alpha:>+10.2f}")

    tot_r = calc_stats(all_raw_trades)
    tot_a = calc_stats(all_ai_trades)
    tot_alpha = tot_a["net"] - tot_r["net"]

    print("\n" + "=" * 105)
    print(" 🏆 JUNE 2026 3-WEEK GRAND SUMMARY (15 SESSIONS)")
    print("=" * 105)
    print(f"{'Strategy Variant':<32} {'Trades':<8} {'Win%':<8} {'Gross P&L':<15} {'Friction':<12} {'Real Net P&L':<15} {'PF'}")
    print("-" * 105)
    print(f"{'Raw Strategy 3 (Mechanical)':<32} {tot_r['n']:<8} {tot_r['wr']:<7.1f}% Rs {tot_r['gross']:>11.2f}  Rs {tot_r['fee']:>8.2f}  Rs {tot_r['net']:>11.2f}  {tot_r['pf']:.2f}")
    print(f"{'AI-Assisted Strategy 3':<32} {tot_a['n']:<8} {tot_a['wr']:<7.1f}% Rs {tot_a['gross']:>11.2f}  Rs {tot_a['fee']:>8.2f}  Rs {tot_a['net']:>11.2f}  {tot_a['pf']:.2f}")
    print("-" * 105)
    print(f" NET AI ALPHA GENERATED IN JUNE: Rs {tot_alpha:>+12.2f}")
    print(f" Friction (Brokerage & Taxes) Saved: Rs {tot_r['fee'] - tot_a['fee']:>10.2f}")
    print("=" * 105)

    print("\n🚫 TRAP PREVENTION BREAKDOWN IN JUNE 2026:")
    print("-" * 65)
    for trap, count in sorted(trap_counts.items(), key=lambda x: x[1], reverse=True):
        print(f"  • {trap:<45} : {count:>2} trades vetoed")
    print("-" * 65)
    print(f"  Gross Losses Averted by AI Vetoes       : +Rs {vetoed_loss_savings:>9.2f}")
    print(f"  Marginal Gains Forgone on Vetoed Trades : -Rs {vetoed_win_missed:>9.2f}")
    print(f"  Net Value Added by AI Filter Gateway   : +Rs {vetoed_loss_savings - vetoed_win_missed:>9.2f}")
    print("-" * 65)

if __name__ == "__main__":
    run_june_audit()
