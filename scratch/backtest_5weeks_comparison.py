import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict

class RefinedProductionConsultant(AIConsultant):
    def _evaluate_playbook(self, d) -> AIVerdict:
        v = super()._evaluate_playbook(d)
        if not v.is_approved:
            return v
        now_ts = "refined"
        
        # 1. Climax Overextension Cap (>= 75 pts from VWAP)
        if d.vwap_distance_pts >= 75.0:
            return AIVerdict(False, "VETOED", 90, "Trap 8: Climax Overextension (>= 75 pts)", "Rubber band stretched", "tight_ema20", now_ts)
            
        # 2. Overbought Call Exhaustion at Day High (RSI >= 70 within 12 pts of high)
        if d.direction == "CE" and d.rsi_1m >= 70.0 and d.distance_to_day_extreme <= 12.0:
            return AIVerdict(False, "VETOED", 90, "Trap 3: Overbought Call Top Chasing", "Buying CE at day high with RSI >= 70", "tight_ema20", now_ts)
            
        # 3. Dead Ribbon Compression in Midday on Non-Expiry Days (< 2 pts)
        if not d.is_expiry_0dte and abs(d.ema_spread_5m) < 2.0 and "MIDDAY" in d.session_phase:
            return AIVerdict(False, "VETOED", 85, "Trap 6: Dead Midday Ribbon Compression (< 2 pts)", "5m EMA spread < 2 pts", "tight_ema20", now_ts)
            
        # 4. Non-Expiry Late-Day Lockout (Post-14:30)
        if not d.is_expiry_0dte and d.minutes_to_close <= 60:
            return AIVerdict(False, "VETOED", 90, "Trap 5: Non-Expiry Late-Day Lockout (Post-14:30)", "Post-14:30 on non-expiry day", "standard", now_ts)
            
        # 5. Protect Alpha on First Loss after Big Win (>= ₹1,800)
        if d.realized_pnl_today >= 1800.0 and d.consecutive_losses_today >= 1 and d.minutes_from_open >= 195:
            return AIVerdict(False, "VETOED", 95, "Trap 5: Alpha Preservation After Loss", "Protect locked alpha", "standard", now_ts)
            
        return v

def run_5weeks_comparison():
    s3 = StrategyConfig.load_from_config("institutional_pullback")
    c_base = AIConsultant(mode="playbook")
    c_refined = RefinedProductionConsultant(mode="playbook")

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
            ("Thu Sep 17", "2026-10-17" if False else "2026-09-17"),
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

    print("=" * 125)
    print(" 🔬 COMPREHENSIVE 5-WEEK FORENSIC BACKTEST: EXISTING RULES vs. REFINED RULES")
    print(" Strategy: Strategy 3 (Institutional Pullback & ITM) + Dynamic Incremental Trailing Ratchet")
    print(" Capital: ₹10,000 Margin (2 Lots / 130 Contracts), ₹40 Round-Trip Slippage/Brokerage Deducted")
    print("=" * 125)

    base_grand_trades = 0; base_grand_wins = 0; base_grand_losses = 0; base_grand_net1 = 0.0
    ref_grand_trades = 0; ref_grand_wins = 0; ref_grand_losses = 0; ref_grand_net1 = 0.0

    weekly_summaries = []

    for w_idx, (w_name, days) in enumerate(all_weeks, 1):
        print(f"\n=============================================================================================")
        print(f" 📅 {w_name.upper()}")
        print(f"=============================================================================================")
        print(f"{'Date':<22} | {'Existing Rule (Trades / Net)':<30} | {'Refined Rule (Trades / Net)':<30} | {'Variance'}")
        print("-" * 105)

        base_w_trades = 0; base_w_wins = 0; base_w_losses = 0; base_w_net1 = 0.0
        ref_w_trades = 0; ref_w_wins = 0; ref_w_losses = 0; ref_w_net1 = 0.0

        for day_label, target_date in days:
            eng = BacktestEngine(target_date)
            raw = eng.run_simulation(s3)
            dte = eng.get_expiry_days()
            is_0dte = (dte <= 0.2)

            # 1. Existing Rules
            app_base = []
            for i, t in enumerate(raw, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(target_date, eng.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, is_0dte)
                if c_base.evaluate(dos).is_approved:
                    app_base.append(t)
            m_base = calculate_metrics(app_base)
            fric_base = len(app_base) * 40.0
            net_base = m_base["net_pnl"] - fric_base

            # 2. Refined Rules
            app_ref = []
            for i, t in enumerate(raw, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(target_date, eng.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, is_0dte)
                if c_refined.evaluate(dos).is_approved:
                    app_ref.append(t)
            m_ref = calculate_metrics(app_ref)
            fric_ref = len(app_ref) * 40.0
            net_ref = m_ref["net_pnl"] - fric_ref

            base_w_trades += len(app_base); base_w_wins += m_base["wins"]; base_w_losses += (len(app_base) - m_base["wins"]); base_w_net1 += net_base
            ref_w_trades += len(app_ref); ref_w_wins += m_ref["wins"]; ref_w_losses += (len(app_ref) - m_ref["wins"]); ref_w_net1 += net_ref

            diff = net_ref - net_base
            diff_str = f"₹{diff:>+9,.2f}" if diff != 0 else "    -    "
            b_cell = f"{len(app_base)} trds (₹{net_base:>+9,.2f})"
            r_cell = f"{len(app_ref)} trds (₹{net_ref:>+9,.2f})"
            print(f"{day_label:<22} | {b_cell:<30} | {r_cell:<30} | {diff_str}")

        b_wr = (base_w_wins / base_w_trades * 100.0) if base_w_trades else 0.0
        r_wr = (ref_w_wins / ref_w_trades * 100.0) if ref_w_trades else 0.0
        print("-" * 105)
        print(f"WEEK TOTAL (1 Lot):    | {base_w_trades} trds, {b_wr:4.1f}% WR (₹{base_w_net1:>+9,.2f})  | {ref_w_trades} trds, {r_wr:4.1f}% WR (₹{ref_w_net1:>+9,.2f})  | ₹{ref_w_net1 - base_w_net1:>+9,.2f}")
        print(f"WEEK TOTAL (2 Lots):   | 2 Lots Net: ₹{(base_w_net1 * 2):>+10,.2f}          | 2 Lots Net: ₹{(ref_w_net1 * 2):>+10,.2f}          | ₹{((ref_w_net1 - base_w_net1)*2):>+10,.2f}")

        weekly_summaries.append({
            "week": w_name,
            "base_trades": base_w_trades, "base_wins": base_w_wins, "base_wr": b_wr, "base_net1": base_w_net1,
            "ref_trades": ref_w_trades, "ref_wins": ref_w_wins, "ref_wr": r_wr, "ref_net1": ref_w_net1,
        })

        base_grand_trades += base_w_trades; base_grand_wins += base_w_wins; base_grand_losses += base_w_losses; base_grand_net1 += base_w_net1
        ref_grand_trades += ref_w_trades; ref_grand_wins += ref_w_wins; ref_grand_losses += ref_w_losses; ref_grand_net1 += ref_w_net1

    # Consolidated Multi-Week Table
    b_g_wr = (base_grand_wins / base_grand_trades * 100.0) if base_grand_trades else 0.0
    r_g_wr = (ref_grand_wins / ref_grand_trades * 100.0) if ref_grand_trades else 0.0

    print("\n" + "=" * 125)
    print(" 🏆 CONSOLIDATED 5-WEEK (+ CURRENT WEEK) EXECUTIVE SCORECARD")
    print("=" * 125)
    print(f"{'Week / Period':<32} | {'Existing Rule (2 Lots)':<25} | {'Refined Rule (2 Lots)':<25} | {'Alpha Gain'}")
    print("-" * 125)
    for ws in weekly_summaries:
        b_str = f"₹{(ws['base_net1']*2):>+10,.2f} ({ws['base_trades']} trds, {ws['base_wr']:.1f}%)"
        r_str = f"₹{(ws['ref_net1']*2):>+10,.2f} ({ws['ref_trades']} trds, {ws['ref_wr']:.1f}%)"
        diff = (ws['ref_net1'] - ws['base_net1']) * 2
        print(f"{ws['week']:<32} | {b_str:<25} | {r_str:<25} | ₹{diff:>+9,.2f}")

    print("-" * 125)
    b_tot_str = f"₹{(base_grand_net1*2):>+10,.2f} ({base_grand_trades} trds, {b_g_wr:.1f}%)"
    r_tot_str = f"₹{(ref_grand_net1*2):>+10,.2f} ({ref_grand_trades} trds, {r_g_wr:.1f}%)"
    tot_diff = (ref_grand_net1 - base_grand_net1) * 2
    print(f"{'GRAND TOTAL (25 SESSIONS)':<32} | {b_tot_str:<25} | {r_tot_str:<25} | ₹{tot_diff:>+9,.2f}")
    print("=" * 125)
    print(f"🎯 1-LOT NET PnL:  Existing: ₹{base_grand_net1:>+10,.2f}  ──>  Refined: ₹{ref_grand_net1:>+10,.2f}  (Delta: +₹{ref_grand_net1 - base_grand_net1:,.2f})")
    print(f"🎯 2-LOT NET PnL:  Existing: ₹{(base_grand_net1*2):>+10,.2f}  ──>  Refined: ₹{(ref_grand_net1*2):>+10,.2f}  (Delta: +₹{tot_diff:,.2f})")
    print(f"🎯 WIN RATE:       Existing: {b_g_wr:.1f}%              ──>  Refined: {r_g_wr:.1f}%              (Delta: +{(r_g_wr - b_g_wr):.1f}%)")
    print(f"🎯 CAPITAL ROI:    Existing: +{((base_grand_net1*2)/10000)*100:.1f}%          ──>  Refined: +{((ref_grand_net1*2)/10000)*100:.1f}%          (Delta: +{(tot_diff/10000)*100:.1f}%)")
    print("=" * 125)

if __name__ == "__main__":
    run_5weeks_comparison()
