import os
import sys
import copy
import json
import sqlite3
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from scratch.test_hybrid_spot_trailing import HybridSpotTrailingEngine
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

consultant = AIConsultant(mode="playbook")

DATES_10 = [
    "2026-10-01",
    "2026-10-05",
    "2026-10-06",
    "2026-10-07",
    "2026-10-08",
    "2026-10-09",
    "2026-10-12",
    "2026-10-13",
    "2026-10-14",
    "2026-10-15"
]

def run_10day_audit():
    cfg3 = StrategyConfig.load_from_config("institutional_pullback")
    cfg2 = StrategyConfig.load_from_config("structural_runner")

    models = [
        ("Strat 3: Baseline (10% Option Trail)", lambda d: BacktestEngine(d), cfg3),
        ("Strat 3: Hybrid Spot 5m EMA20", lambda d: HybridSpotTrailingEngine(d, "ema20"), cfg3),
        ("Strat 3: Hybrid Spot 5m EMA9 (+4pt buffer)", lambda d: HybridSpotTrailingEngine(d, "ema9_buffer", 4.0), cfg3),
        ("Strat 2: Structural Runner (Hybrid EMA20)", lambda d: HybridSpotTrailingEngine(d, "ema20"), cfg2),
    ]

    all_results = {}

    for name, eng_factory, cfg in models:
        all_results[name] = {
            "daily": {},
            "all_trades": [],
            "approved_trades": []
        }
        for d in DATES_10:
            eng = eng_factory(d)
            if not eng.spot_candles:
                continue
            trades = eng.run_simulation(cfg)
            
            # Filter through AI Risk Gateway (AI Playbook)
            approved = []
            dte = eng.get_expiry_days()
            for t in trades:
                idx = 0
                for k, c in enumerate(eng.spot_candles):
                    if t.entry_time in c["start_time"]:
                        idx = k
                        break
                dossier = generate_market_dossier(
                    target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
                    direction=t.direction, symbol=t.symbol, strike=t.strike,
                    option_entry_price=t.entry_price, trade_history=approved,
                    days_to_expiry=dte, is_expiry_0dte=(dte <= 0.2)
                )
                v = consultant.evaluate(dossier)
                t.ai_verdict = v
                if v.is_approved:
                    approved.append(t)
            
            all_results[name]["daily"][d] = approved
            all_results[name]["approved_trades"].extend(approved)

    # 1. Print Day-by-Day Matrix
    print("\n" + "=" * 130)
    print(f" 10-DAY COMPREHENSIVE BACKTEST AUDIT (2026-10-01 to 2026-10-15)")
    print(f" Datasets: 10 Full Sessions (09:15 to 15:30 IST) | Real 1M Kite Candles where available")
    print("=" * 130)

    header_cols = [f"{m[0][:26]:<27}" for m in models]
    print(f"{'Date':<12} | " + " | ".join(header_cols))
    print("-" * 130)

    for d in DATES_10:
        day_name = datetime.strptime(d, "%Y-%m-%d").strftime("%a")
        row_str = f"{d} ({day_name}) | "
        cols = []
        for name, _, _ in models:
            tr_list = all_results[name]["daily"].get(d, [])
            m = calculate_metrics(tr_list)
            fee = m["total_trades"] * 40.0
            real_net = m["net_pnl"] - fee
            col_text = f"{m['total_trades']:<2}tr (₹{real_net:>+8,.0f})"
            cols.append(f"{col_text:<27}")
        row_str += " | ".join(cols)
        print(row_str)

    # 2. Print Summary Scorecards for all 4 models
    print("\n" + "=" * 130)
    print(" 10-DAY CONSOLIDATED SCORECARDS (NET POST-BROKERAGE & TAXES)")
    print("=" * 130)
    print(f"{'Strategy Model':<42} | {'Trades':<8} | {'Win Rate':<9} | {'Gross P&L':<13} | {'Friction':<11} | {'Real Net (₹)':<14} | {'Max Win':<11} | {'Profit Factor'}")
    print("-" * 130)

    for name, _, _ in models:
        tr_list = all_results[name]["approved_trades"]
        m = calculate_metrics(tr_list)
        fee = m["total_trades"] * 40.0
        real_net = m["net_pnl"] - fee
        pf_str = f"{m['profit_factor']:.2f}" if m['profit_factor'] < 99 else "99.00"
        print(f"{name:<42} | {m['total_trades']:<8} | {m['win_rate']:<8.1f}% | ₹{m['net_pnl']:<11,.2f} | ₹{fee:<9,.2f} | ₹{real_net:<12,.2f} | ₹{m['max_win']:<9,.2f} | {pf_str}")
    print("=" * 130 + "\n")

    return all_results

if __name__ == "__main__":
    run_10day_audit()
