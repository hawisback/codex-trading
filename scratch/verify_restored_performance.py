import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from backtest_engine import StrategyConfig, calculate_metrics
from test_incremental_trailing import IncrementalTrailingEngine
from ai_context_dossier import generate_market_dossier
from audit_last_week_deep import PreciseConsultant

def run_restored_audit():
    print("=" * 115)
    print(" 🚀 VERIFICATION OF RESTORED PERFORMANCE ACROSS WEEKS 8, 9, 10")
    print(" Engine: IncrementalTrailingEngine (Ratchet First) + PreciseConsultant (Reversal Memory Active)")
    print("=" * 115)

    s3 = StrategyConfig.load_from_config("institutional_pullback")
    consultant = PreciseConsultant(mode="playbook")

    all_weeks = [
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
        ]),
        ("Week 10 (Oct 05 - Oct 09, 2026)", [
            ("Mon Oct 05", "2026-10-05"),
            ("Tue Oct 06 (0DTE)", "2026-10-06"),
            ("Wed Oct 07", "2026-10-07"),
            ("Thu Oct 08", "2026-10-08"),
            ("Fri Oct 09", "2026-10-09"),
        ])
    ]

    grand_net1 = 0.0
    grand_net2 = 0.0
    grand_trades = 0
    grand_wins = 0

    for w_name, days in all_weeks:
        print(f"\n🔹 {w_name}")
        w_net1 = 0.0
        w_trades = 0
        w_wins = 0

        for day_label, d in days:
            eng = IncrementalTrailingEngine(d, activation_pct=20.0, trail_offset_pct=10.0)
            raw_trades = eng.run_simulation(s3)
            dte = eng.get_expiry_days()

            approved = []
            for i, t in enumerate(raw_trades, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(
                    d, eng.spot_candles, idx, t.direction, t.symbol, t.strike,
                    t.entry_price, raw_trades[:i-1], dte, (dte <= 0.2)
                )
                if consultant.evaluate(dos).is_approved:
                    approved.append(t)

            m = calculate_metrics(approved)
            fric = len(approved) * 40.0
            net1 = m["net_pnl"] - fric
            net2 = (m["net_pnl"] * 2) - fric

            w_net1 += net1
            w_trades += len(approved)
            w_wins += m["wins"]
            wr_str = f"{m['win_rate']:.1f}%" if approved else "N/A"
            print(f"  {day_label:<24} | {len(approved):<2} trds | Win {wr_str:<6} | Net (1 Lot): ₹{net1:>+10,.2f} | Net (2 Lots): ₹{net2:>+10,.2f}")

        w_wr = (w_wins / w_trades * 100.0) if w_trades else 0.0
        print(f"  --> {w_name} TOTAL: {w_trades} trds | Win {w_wr:.1f}% | Net (1 Lot): ₹{w_net1:>+10,.2f} | Net (2 Lots / 10k): ₹{(w_net1*2):>+10,.2f}")
        grand_net1 += w_net1
        grand_trades += w_trades
        grand_wins += w_wins

    grand_wr = (grand_wins / grand_trades * 100.0) if grand_trades else 0.0
    print("\n" + "=" * 115)
    print(f"🏆 GRAND 3-WEEK CONSOLIDATED TOTAL (14 TRADING SESSIONS)")
    print(f"• Total Approved Trades: {grand_trades}")
    print(f"• Overall Win Rate:      {grand_wr:.1f}% ({grand_wins} Wins / {grand_trades - grand_wins} Losses)")
    print(f"• Total Net PnL (1 Lot): ₹{grand_net1:>+12,.2f}")
    print(f"• Total Net PnL (2 Lots / ₹10k capital): ₹{(grand_net1 * 2):>+12,.2f} ({(grand_net1*2/10000)*100:+.1f}% ROI)")
    print("=" * 115)

if __name__ == "__main__":
    run_restored_audit()
