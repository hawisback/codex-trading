import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from scratch.backtest_5weeks_comparison import RefinedProductionConsultant
from ai_consultant import AIVerdict

class SolvedConsultant(RefinedProductionConsultant):
    def _evaluate_playbook(self, d) -> AIVerdict:
        v = super()._evaluate_playbook(d)
        if not v.is_approved:
            return v
        now_ts = "solved"
        
        # -------------------------------------------------------------
        # Rule 6: Overbought Call Spike Ceiling (Trap 3 Refinement)
        # Avoid buying Calls into parabolic vertical spikes (1m RSI >= 74.0)
        # -------------------------------------------------------------
        if d.direction == "CE" and d.rsi_1m >= 74.0:
            return AIVerdict(
                is_approved=False,
                action="VETOED",
                confidence_score=90,
                trap_detected="Trap 3: Overbought Call Spike Chasing (RSI >= 74)",
                reasoning=f"1m RSI is {d.rsi_1m:.1f} (>= 74.0). Chasing vertical call spikes into overbought territory.",
                recommended_trailing="tight_ema20",
                timestamp=now_ts
            )

        # -------------------------------------------------------------
        # Rule 7: Oversold Put Panic Flush Floor (Trap 3 Refinement)
        # Avoid shorting Puts directly into panic liquidation flushes at day low
        # (1m RSI <= 26.0 within 10 pts of day low)
        # -------------------------------------------------------------
        if d.direction == "PE" and d.rsi_1m <= 26.0 and d.distance_to_day_extreme <= 10.0:
            return AIVerdict(
                is_approved=False,
                action="VETOED",
                confidence_score=90,
                trap_detected="Trap 3: Oversold Put Panic Flush at Day Low",
                reasoning=f"1m RSI is {d.rsi_1m:.1f} (<= 26.0) directly at day low ({d.distance_to_day_extreme:.1f} pts). Severe snapback risk.",
                recommended_trailing="tight_ema20",
                timestamp=now_ts
            )

        # -------------------------------------------------------------
        # Rule 8: Weak Midday Reversal Filter (Trap 1 Refinement)
        # In Midday Dead Zone (11:30 - 13:15), a reversal expansion must have
        # confirmed momentum: slope >= 0.10 and ribbon spread >= 4.0 pts.
        # -------------------------------------------------------------
        if "MIDDAY" in d.session_phase:
            if abs(d.vwap_slope_15m) < 0.10 or abs(d.ema_spread_5m) < 4.0:
                return AIVerdict(
                    is_approved=False,
                    action="VETOED",
                    confidence_score=85,
                    trap_detected="Trap 1: Weak Midday Reversal Drift",
                    reasoning=f"Midday reversal lacks institutional expansion (slope={d.vwap_slope_15m:.4f} < 0.10 or spread={abs(d.ema_spread_5m):.1f} < 4.0 pts).",
                    recommended_trailing="tight_ema20",
                    timestamp=now_ts
                )

        return v

def test_all():
    s3 = StrategyConfig.load_from_config("institutional_pullback")
    c_refined = RefinedProductionConsultant(mode="playbook")
    c_solved = SolvedConsultant(mode="playbook")

    all_weeks = [
        ("Week 6 (Sep 07 - Sep 11, 2026)", [
            ("Mon Sep 07", "2026-09-07"),
            ("Tue Sep 08 (0DTE)", "2026-09-08"),
            ("Wed Sep 09", "2026-09-09"),
            ("Thu Sep 10", "2026-09-10"),
            ("Fri Sep 11", "2026-09-11"),
        ]),
        ("Week 7 (Sep 14 - Sep 18, 2026)", [
            ("Tue Sep 15 (0DTE)", "2026-09-15"),
            ("Wed Sep 16", "2026-09-16"),
            ("Thu Sep 17", "2026-09-17"),
            ("Fri Sep 18", "2026-09-18"),
        ]),
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
        ]),
        ("Week 11 - Current (Oct 12 - Oct 13)", [
            ("Mon Oct 12", "2026-10-12"),
            ("Tue Oct 13 (0DTE)", "2026-10-13"),
        ])
    ]

    print("=" * 115)
    print(" 🧪 TESTING SEP 09 & 10 SOLUTIONS ACROSS ALL 25 SESSIONS")
    print("=" * 115)

    ref_grand_w = 0; ref_grand_l = 0; ref_grand_net1 = 0
    sol_grand_w = 0; sol_grand_l = 0; sol_grand_net1 = 0

    for w_name, days in all_weeks:
        ref_w_net = 0; sol_w_net = 0
        ref_w_cnt = 0; sol_w_cnt = 0
        ref_wins = 0; sol_wins = 0
        for day_label, d in days:
            eng = BacktestEngine(d)
            raw = eng.run_simulation(s3)
            dte = eng.get_expiry_days()

            # Refined
            app_ref = []
            for i, t in enumerate(raw, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(d, eng.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, (dte<=0.2))
                if c_refined.evaluate(dos).is_approved:
                    app_ref.append(t)
            m_ref = calculate_metrics(app_ref)
            net_ref = m_ref["net_pnl"] - len(app_ref)*40.0
            ref_w_net += net_ref; ref_w_cnt += len(app_ref); ref_wins += m_ref["wins"]

            # Solved
            app_sol = []
            for i, t in enumerate(raw, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(d, eng.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, (dte<=0.2))
                if c_solved.evaluate(dos).is_approved:
                    app_sol.append(t)
            m_sol = calculate_metrics(app_sol)
            net_sol = m_sol["net_pnl"] - len(app_sol)*40.0
            sol_w_net += net_sol; sol_w_cnt += len(app_sol); sol_wins += m_sol["wins"]

            if net_sol != net_ref or d in ["2026-09-09", "2026-09-10"]:
                print(f"  {day_label:<22} | Refined: {len(app_ref)} trds (₹{net_ref:>+8.2f}) | Solved: {len(app_sol)} trds (₹{net_sol:>+8.2f}) | Delta: ₹{net_sol - net_ref:>+8.2f}")

        print(f"--> {w_name:<30} | Refined (2 Lots): ₹{ref_w_net*2:>+10.2f} | Solved (2 Lots): ₹{sol_w_net*2:>+10.2f} | Delta: ₹{(sol_w_net - ref_w_net)*2:>+10.2f}")
        ref_grand_net1 += ref_w_net; ref_grand_w += ref_wins; ref_grand_l += (ref_w_cnt - ref_wins)
        sol_grand_net1 += sol_w_net; sol_grand_w += sol_wins; sol_grand_l += (sol_w_cnt - sol_wins)

    print("\n" + "=" * 115)
    print(f"🏆 GRAND 25-SESSION CONSOLIDATED RESULT:")
    print(f"• Refined Engine (2 Lots): ₹{(ref_grand_net1*2):>+10.2f} ({ref_grand_w + ref_grand_l} trds | {ref_grand_w} Wins / {ref_grand_l} Losses | Win Rate: {(ref_grand_w/(ref_grand_w+ref_grand_l)*100):.1f}%)")
    print(f"• Solved Engine  (2 Lots): ₹{(sol_grand_net1*2):>+10.2f} ({sol_grand_w + sol_grand_l} trds | {sol_grand_w} Wins / {sol_grand_l} Losses | Win Rate: {(sol_grand_w/(sol_grand_w+sol_grand_l)*100):.1f}%)")
    print(f"• TOTAL ALPHA BOOST:       ₹{((sol_grand_net1 - ref_grand_net1)*2):>+10.2f} EXTRA PROFIT!")
    print(f"• WINNING TRADES CHECK:    Refined Wins: {ref_grand_w}  ──>  Solved Wins: {sol_grand_w}")
    print("=" * 115)

if __name__ == "__main__":
    test_all()
