import os
import sys
import json
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
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

def run_audit():
    strat_keys = ["legacy_scalper", "structural_runner", "institutional_pullback"]
    configs = {k: StrategyConfig.load_from_config(k) for k in strat_keys}

    results_raw = {k: {"daily": {}, "trades": []} for k in strat_keys}
    results_ai = {k: {"daily": {}, "trades": []} for k in strat_keys}

    for d in DATES_10:
        eng = BacktestEngine(d)
        if not eng.spot_candles:
            continue
        dte = eng.get_expiry_days()

        for k in strat_keys:
            cfg = configs[k]
            raw_trades = eng.run_simulation(cfg)
            results_raw[k]["daily"][d] = raw_trades
            results_raw[k]["trades"].extend(raw_trades)

            # AI Gateway filtering
            approved = []
            for t in raw_trades:
                idx = 0
                for i_c, c in enumerate(eng.spot_candles):
                    if t.entry_time in c["start_time"]:
                        idx = i_c
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
            
            results_ai[k]["daily"][d] = approved
            results_ai[k]["trades"].extend(approved)

    # 1. Day-by-day table for AI Approved
    print("\n" + "=" * 125)
    print(" LAST 10 SESSIONS: ORIGINAL 3 STRATEGIES COMPARISON (WITH AI PLAYBOOK GATEWAY)")
    print("=" * 125)
    print(f"{'Date':<12} | {'Strategy 1: Legacy Scalper':<32} | {'Strategy 2: Structural Runner':<32} | {'Strategy 3: Institutional Pullback':<32}")
    print(f"{'':<12} | {'Trades':<8} {'Win%':<7} {'Net P&L (₹)':<14} | {'Trades':<8} {'Win%':<7} {'Net P&L (₹)':<14} | {'Trades':<8} {'Win%':<7} {'Net P&L (₹)':<14}")
    print("-" * 125)

    for d in DATES_10:
        day_name = datetime.strptime(d, "%Y-%m-%d").strftime("%a")
        row = f"{d} ({day_name}) | "
        cols = []
        for k in strat_keys:
            t_list = results_ai[k]["daily"].get(d, [])
            m = calculate_metrics(t_list)
            fee = m["total_trades"] * 40.0
            net = m["net_pnl"] - fee
            col_str = f"{m['total_trades']:<2}tr   {m['win_rate']:>5.1f}%  ₹{net:>+9,.0f}"
            cols.append(f"{col_str:<32}")
        row += " | ".join(cols)
        print(row)

    print("=" * 125)

    # 2. Consolidated Scorecards
    print("\n" + "=" * 125)
    print(" 10-SESSION CONSOLIDATED SCORECARD: AI PROTECTED (POST-FEE & STATUTORY TAXES)")
    print("=" * 125)
    print(f"{'Strategy Profile':<38} | {'Trades':<8} | {'Win Rate':<9} | {'Gross P&L':<13} | {'Friction':<11} | {'Real Net (₹)':<14} | {'Max Win':<11} | {'Profit Factor'}")
    print("-" * 125)

    for k in strat_keys:
        t_list = results_ai[k]["trades"]
        m = calculate_metrics(t_list)
        fee = m["total_trades"] * 40.0
        net = m["net_pnl"] - fee
        pf_str = f"{m['profit_factor']:.2f}" if m['profit_factor'] < 99 else "99.00"
        name = configs[k].name
        print(f"{name:<38} | {m['total_trades']:<8} | {m['win_rate']:<8.1f}% | ₹{m['net_pnl']:<11,.2f} | ₹{fee:<9,.2f} | ₹{net:<12,.2f} | ₹{m['max_win']:<9,.2f} | {pf_str}")
    print("=" * 125)

    # 3. Consolidated Scorecards RAW (Unprotected)
    print("\n" + "=" * 125)
    print(" 10-SESSION CONSOLIDATED SCORECARD: RAW UNPROTECTED (WITHOUT AI GATEWAY)")
    print("=" * 125)
    print(f"{'Strategy Profile':<38} | {'Trades':<8} | {'Win Rate':<9} | {'Gross P&L':<13} | {'Friction':<11} | {'Real Net (₹)':<14} | {'Max Win':<11} | {'Profit Factor'}")
    print("-" * 125)

    for k in strat_keys:
        t_list = results_raw[k]["trades"]
        m = calculate_metrics(t_list)
        fee = m["total_trades"] * 40.0
        net = m["net_pnl"] - fee
        pf_str = f"{m['profit_factor']:.2f}" if m['profit_factor'] < 99 else "99.00"
        name = configs[k].name
        print(f"{name:<38} | {m['total_trades']:<8} | {m['win_rate']:<8.1f}% | ₹{m['net_pnl']:<11,.2f} | ₹{fee:<9,.2f} | ₹{net:<12,.2f} | ₹{m['max_win']:<9,.2f} | {pf_str}")
    print("=" * 125 + "\n")

if __name__ == "__main__":
    run_audit()
