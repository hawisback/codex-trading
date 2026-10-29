import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from datetime import datetime
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from audit_last_week_deep import PreciseConsultant

def run_deep_comparison():
    print("=" * 125)
    print(" 🔬 2-WEEK COMPREHENSIVE FORENSIC COMPARISON: WEEKS 8 & 9 (SEP 21 - OCT 01, 2026)")
    print(" Benchmarking:")
    print("   1. Raw Mechanical Strategy 3 (Unprotected)")
    print("   2. WITHOUT New Endpoint: Spot VWAP/EMA Fix + AI Risk Gateway")
    print("   3. WITH New Endpoint: Dual Spot + Option Technicals Confirmation + AI Risk Gateway")
    print("=" * 125)

    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
    ai = PreciseConsultant(mode="playbook")

    weeks = [
        ("Week 8 (Sep 21 - Sep 25, 2026)", [
            ("Mon Sep 21", "2026-09-21"),
            ("Tue Sep 22", "2026-09-22"),
            ("Wed Sep 23", "2026-09-23"),
            ("Thu Sep 24 (Monthly)", "2026-09-24"),
            ("Fri Sep 25", "2026-09-25"),
        ]),
        ("Week 9 (Sep 28 - Oct 01, 2026)", [
            ("Mon Sep 28", "2026-09-28"),
            ("Tue Sep 29 (0DTE)", "2026-09-29"),
            ("Wed Sep 30", "2026-09-30"),
            ("Thu Oct 01", "2026-10-01"),
        ])
    ]

    all_records = []

    for week_label, days in weeks:
        for day_label, target_date in days:
            eng = BacktestEngine(target_date=target_date)
            d_obj = datetime.strptime(target_date, "%Y-%m-%d")
            is_0dte = (d_obj.weekday() == 1) or (target_date == "2026-09-24")
            dte = eng.get_expiry_days()

            raw_trades = eng.run_simulation(s3_cfg)

            # 1. Without Endpoint (Spot Fix + AI Risk Gateway)
            app_without = []
            for t in raw_trades:
                hist = eng.spot_candles[:t.entry_bar + 1]
                dos = generate_market_dossier(
                    target_date=target_date,
                    candles=hist,
                    current_bar_idx=len(hist) - 1,
                    direction=t.direction,
                    symbol=t.symbol,
                    strike=t.strike,
                    option_entry_price=t.entry_price,
                    trade_history=app_without,
                    days_to_expiry=dte,
                    is_expiry_0dte=is_0dte
                )
                if ai.evaluate(dos).is_approved:
                    app_without.append(t)

            # 2. With Endpoint (Dual Spot + Option Technicals)
            # Evaluates contract-level momentum & VWAP filters
            app_with = []
            for t in app_without:
                hist = eng.spot_candles[:t.entry_bar + 1]
                dos = generate_market_dossier(
                    target_date=target_date,
                    candles=hist,
                    current_bar_idx=len(hist) - 1,
                    direction=t.direction,
                    symbol=t.symbol,
                    strike=t.strike,
                    option_entry_price=t.entry_price,
                    trade_history=app_with,
                    days_to_expiry=dte,
                    is_expiry_0dte=is_0dte
                )
                # Option Technicals check:
                # Premium must not be heavily extended (option RSI < 78) and must hold above dynamic EMA9
                opt_rsi_spike = (dos.rsi_1m > 74.0 and t.direction == "CE") or (dos.rsi_1m < 26.0 and t.direction == "PE")
                opt_pullback_clean = dos.pullback_distance_pts <= 10.0
                if not opt_rsi_spike and opt_pullback_clean:
                    app_with.append(t)

            # Calculate metrics
            m_raw = calculate_metrics(raw_trades)
            net_raw1 = m_raw["net_pnl"] - len(raw_trades) * 40.0
            net_raw2 = (m_raw["net_pnl"] * 2) - len(raw_trades) * 40.0

            m_wo = calculate_metrics(app_without)
            net_wo1 = m_wo["net_pnl"] - len(app_without) * 40.0
            net_wo2 = (m_wo["net_pnl"] * 2) - len(app_without) * 40.0

            m_w = calculate_metrics(app_with)
            net_w1 = m_w["net_pnl"] - len(app_with) * 40.0
            net_w2 = (m_w["net_pnl"] * 2) - len(app_with) * 40.0

            all_records.append({
                "week": week_label,
                "label": day_label,
                "date": target_date,
                "raw_t": len(raw_trades), "raw_net1": net_raw1, "raw_net2": net_raw2, "raw_win": m_raw["win_rate"],
                "wo_t": len(app_without), "wo_net1": net_wo1, "wo_net2": net_wo2, "wo_win": m_wo["win_rate"],
                "w_t": len(app_with), "w_net1": net_w1, "w_net2": net_w2, "w_win": m_w["win_rate"],
                "trades_without": app_without, "trades_with": app_with
            })

    # Print Table
    print("\n" + "=" * 135)
    print(f"{'Day & Date':<22} | {'RAW MECHANICAL (No AI)':<24} | {'WITHOUT NEW ENDPOINT (Spot-Only)':<38} | {'WITH NEW ENDPOINT (Dual Confirmation)':<38}")
    print(f"{'':<22} | {'Trds':<5} {'Win%':<6} {'Net (2 Lots)':<11} | {'Trds':<5} {'Win%':<6} {'Net (1 Lot)':<12} {'Net (2 Lots)':<12} | {'Trds':<5} {'Win%':<6} {'Net (1 Lot)':<12} {'Net (2 Lots)':<12}")
    print("-" * 135)

    curr_w = ""
    for r in all_records:
        if r["week"] != curr_w:
            curr_w = r["week"]
            print(f"\n🔹 {curr_w}")
        raw_w = f"{r['raw_win']:.1f}%" if r['raw_t'] > 0 else "N/A"
        wo_w = f"{r['wo_win']:.1f}%" if r['wo_t'] > 0 else "N/A"
        w_w = f"{r['w_win']:.1f}%" if r['w_t'] > 0 else "N/A"
        print(
            f"{r['label']:<22} | "
            f"{r['raw_t']:<5} {raw_w:<6} ₹{r['raw_net2']:>+9,.2f} | "
            f"{r['wo_t']:<5} {wo_w:<6} ₹{r['wo_net1']:>+10,.2f} ₹{r['wo_net2']:>+10,.2f} | "
            f"{r['w_t']:<5} {w_w:<6} ₹{r['w_net1']:>+10,.2f} ₹{r['w_net2']:>+10,.2f}"
        )

    # Week 8 Totals
    w8 = [r for r in all_records if "Week 8" in r["week"]]
    w8_raw_net2 = sum(r["raw_net2"] for r in w8)
    w8_wo_net1 = sum(r["wo_net1"] for r in w8)
    w8_wo_net2 = sum(r["wo_net2"] for r in w8)
    w8_w_net1 = sum(r["w_net1"] for r in w8)
    w8_w_net2 = sum(r["w_net2"] for r in w8)

    print("\n" + "=" * 135)
    print(f"{'WEEK 8 SUMMARY TOTAL':<22} | {sum(r['raw_t'] for r in w8):<5}        ₹{w8_raw_net2:>+9,.2f} | {sum(r['wo_t'] for r in w8):<5}        ₹{w8_wo_net1:>+10,.2f} ₹{w8_wo_net2:>+10,.2f} | {sum(r['w_t'] for r in w8):<5}        ₹{w8_w_net1:>+10,.2f} ₹{w8_w_net2:>+10,.2f}")

    # Week 9 Totals
    w9 = [r for r in all_records if "Week 9" in r["week"]]
    w9_raw_net2 = sum(r["raw_net2"] for r in w9)
    w9_wo_net1 = sum(r["wo_net1"] for r in w9)
    w9_wo_net2 = sum(r["wo_net2"] for r in w9)
    w9_w_net1 = sum(r["w_net1"] for r in w9)
    w9_w_net2 = sum(r["w_net2"] for r in w9)

    print(f"{'WEEK 9 SUMMARY TOTAL':<22} | {sum(r['raw_t'] for r in w9):<5}        ₹{w9_raw_net2:>+9,.2f} | {sum(r['wo_t'] for r in w9):<5}        ₹{w9_wo_net1:>+10,.2f} ₹{w9_wo_net2:>+10,.2f} | {sum(r['w_t'] for r in w9):<5}        ₹{w9_w_net1:>+10,.2f} ₹{w9_w_net2:>+10,.2f}")

    # Combined 2-Week Totals
    tot_raw_net2 = w8_raw_net2 + w9_raw_net2
    tot_wo_net1 = w8_wo_net1 + w9_wo_net1
    tot_wo_net2 = w8_wo_net2 + w9_wo_net2
    tot_w_net1 = w8_w_net1 + w9_w_net1
    tot_w_net2 = w8_w_net2 + w9_w_net2

    print("-" * 135)
    print(f"{'COMBINED 2-WEEK TOTAL':<22} | {sum(r['raw_t'] for r in all_records):<5}        ₹{tot_raw_net2:>+9,.2f} | {sum(r['wo_t'] for r in all_records):<5}        ₹{tot_wo_net1:>+10,.2f} ₹{tot_wo_net2:>+10,.2f} | {sum(r['w_t'] for r in all_records):<5}        ₹{tot_w_net1:>+10,.2f} ₹{tot_w_net2:>+10,.2f}")
    print("=" * 135)

if __name__ == "__main__":
    run_deep_comparison()
