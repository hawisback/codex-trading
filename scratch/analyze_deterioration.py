import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from test_incremental_trailing import IncrementalTrailingEngine
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from audit_last_week_deep import PreciseConsultant

def analyze_deterioration():
    print("=" * 115)
    print(" 🔎 ROOT-CAUSE ANALYSIS OF TRADE CAPTURE DETERIORATION")
    print("=" * 115)

    s3 = StrategyConfig.load_from_config("institutional_pullback")

    weeks = {
        "Week 9 (Sep 28 - Oct 01, 2026)": [
            ("Monday, Sep 28", "2026-09-28"),
            ("Tuesday, Sep 29 (0DTE)", "2026-09-29"),
            ("Wednesday, Sep 30", "2026-09-30"),
            ("Thursday, Oct 01", "2026-10-01"),
        ],
        "Week 10 (Oct 05 - Oct 09, 2026)": [
            ("Monday, Oct 05", "2026-10-05"),
            ("Tuesday, Oct 06 (0DTE)", "2026-10-06"),
            ("Wednesday, Oct 07", "2026-10-07"),
            ("Thursday, Oct 08", "2026-10-08"),
            ("Friday, Oct 09", "2026-10-09")
        ]
    }

    c_base = AIConsultant(mode="playbook")
    c_precise = PreciseConsultant(mode="playbook")

    for w_name, days in weeks.items():
        print(f"\n=======================================================")
        print(f" {w_name.upper()}")
        print(f"=======================================================")
        
        # Test 1: Degraded (Standard BacktestEngine + Baseline AIConsultant)
        tot_deg_1lot = 0.0
        tot_deg_trades = 0
        
        # Test 2: Golden (IncrementalTrailingEngine + PreciseConsultant)
        tot_gold_1lot = 0.0
        tot_gold_trades = 0

        print(f"{'Date':<15} | {'Degraded Net (1 Lot)':<22} | {'Golden Net (1 Lot)':<22} | {'Variance'}")
        print("-" * 80)

        for label, d in days:
            eng_deg = BacktestEngine(d)
            eng_gold = IncrementalTrailingEngine(d, activation_pct=20.0, trail_offset_pct=10.0)
            
            tr_deg = eng_deg.run_simulation(s3)
            tr_gold = eng_gold.run_simulation(s3)
            dte = eng_deg.get_expiry_days()

            # Degraded AI filter
            app_deg = []
            for t in tr_deg:
                idx = [k for k, c in enumerate(eng_deg.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(d, eng_deg.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, app_deg, dte, (dte <= 0.2))
                if c_base.evaluate(dos).is_approved:
                    app_deg.append(t)
            m_deg = calculate_metrics(app_deg)
            net_deg = m_deg["net_pnl"] - len(app_deg) * 40.0
            tot_deg_1lot += net_deg
            tot_deg_trades += len(app_deg)

            # Golden AI filter
            app_gold = []
            for t in tr_gold:
                idx = [k for k, c in enumerate(eng_gold.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(d, eng_gold.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, app_gold, dte, (dte <= 0.2))
                if c_precise.evaluate(dos).is_approved:
                    app_gold.append(t)
            m_gold = calculate_metrics(app_gold)
            net_gold = m_gold["net_pnl"] - len(app_gold) * 40.0
            tot_gold_1lot += net_gold
            tot_gold_trades += len(app_gold)

            diff = net_gold - net_deg
            print(f"{d:<15} | ₹{net_deg:>+10,.2f} ({len(app_deg)} trds)  | ₹{net_gold:>+10,.2f} ({len(app_gold)} trds)  | ₹{diff:>+10,.2f}")

        print("-" * 80)
        print(f"TOTAL:          | ₹{tot_deg_1lot:>+10,.2f} ({tot_deg_trades} trds)  | ₹{tot_gold_1lot:>+10,.2f} ({tot_gold_trades} trds)  | ₹{tot_gold_1lot - tot_deg_1lot:>+10,.2f}")
        print(f"2 Lots Net:     | ₹{(tot_deg_1lot * 2):>+10,.2f}              | ₹{(tot_gold_1lot * 2):>+10,.2f}              | ₹{((tot_gold_1lot - tot_deg_1lot)*2):>+10,.2f}")

if __name__ == "__main__":
    analyze_deterioration()
