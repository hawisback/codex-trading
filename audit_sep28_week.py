#!/usr/bin/env python3
"""
Deep-Dive Day-by-Day Forensic Audit: Week of September 28, 2026 (Sep 28 - Oct 01)
Comparing:
- Raw Strategy 3
- Baseline AI Strategy 3
- Continuous 1% Incremental Trailing AI Strategy 3
"""

from backtest_engine import BacktestEngine, StrategyConfig
from test_incremental_trailing import IncrementalTrailingEngine, base_cfg
from audit_last_week_deep import PreciseConsultant
from ai_context_dossier import generate_market_dossier

consultant = PreciseConsultant(mode="playbook")
s3 = StrategyConfig.load_from_config("institutional_pullback")

sep28_week = [
    ("Monday, Sep 28, 2026", "2026-09-28"),
    ("Tuesday, Sep 29, 2026 (0DTE)", "2026-09-29"),
    ("Wednesday, Sep 30, 2026", "2026-09-30"),
    ("Thursday, Oct 01, 2026", "2026-10-01"),
]

def run_sep28_audit():
    print("=" * 110)
    print(" 🔬 COMPREHENSIVE FORENSIC AUDIT: WEEK OF SEPTEMBER 28, 2026")
    print(" (Sep 28 - Oct 01, 2026 - 4 Sessions | Oct 02 National Holiday)")
    print("=" * 110)

    tot_raw_trades = 0
    tot_raw_net = 0.0

    tot_base_trades = 0
    tot_base_net = 0.0

    tot_inc_trades = 0
    tot_inc_net = 0.0

    daily_summaries = []

    for label, d in sep28_week:
        eng_b = BacktestEngine(d)
        eng_i = IncrementalTrailingEngine(d, activation_pct=20.0, trail_offset_pct=10.0)
        
        spot_o = eng_b.spot_candles[0]["open"]
        spot_c = eng_b.spot_candles[-1]["close"]
        spot_h = max(c["high"] for c in eng_b.spot_candles)
        spot_l = min(c["low"] for c in eng_b.spot_candles)
        range_pts = spot_h - spot_l
        move_pts = spot_c - spot_o

        tr_b = eng_b.run_simulation(s3)
        tr_i = eng_i.run_simulation(s3)
        dte = eng_b.get_expiry_days()

        print(f"\n>>> {label.upper()} <<<")
        print(f"NIFTY Spot: Open={spot_o:.2f} | High={spot_h:.2f} | Low={spot_l:.2f} | Close={spot_c:.2f} (Range: {range_pts:.1f} pts, Move: {move_pts:+.1f} pts)")
        print(f"Total Raw Trades Generated: {len(tr_b)}")
        print("-" * 110)
        print(f"{'Trd':<4} {'Dir':<4} {'Entry':<6} {'Exit':<6} {'Opt Entry':<10} {'Peak%':<7} {'Base PnL':<12} {'Inc PnL':<12} {'AI Verdict & Trap'}")
        print("-" * 110)

        app_b = []
        app_i = []

        for i, (tb, ti) in enumerate(zip(tr_b, tr_i), 1):
            idx = [k for k, c in enumerate(eng_b.spot_candles) if tb.entry_time in c["start_time"]][0]
            dos = generate_market_dossier(d, eng_b.spot_candles, idx, tb.direction, tb.symbol, tb.strike, tb.entry_price, tr_b[:i-1], dte, (dte <= 0.2))
            v = consultant.evaluate(dos)

            status_icon = "✅ APPROVED" if v.is_approved else "🚫 VETOED"
            trap_note = v.trap_detected or "Setup 1 / Standard"

            if v.is_approved:
                app_b.append(tb)
                app_i.append(ti)

            print(f"#{i:<3} {tb.direction:<4} {tb.entry_time[:5]:<6} {tb.exit_time[:5]:<6} Rs {tb.entry_price:>6.2f}   {tb.peak_gain_pct:>5.1f}%  Rs {tb.pnl:>8.2f}  Rs {ti.pnl:>8.2f}  {status_icon:<10} ({trap_note})")

        # Daily stats
        raw_net = sum(t.pnl for t in tr_b) - len(tr_b) * 40.0
        nb = sum(t.pnl for t in app_b) - len(app_b) * 40.0
        ni = sum(t.pnl for t in app_i) - len(app_i) * 40.0

        tot_raw_trades += len(tr_b)
        tot_raw_net += raw_net
        tot_base_trades += len(app_b)
        tot_base_net += nb
        tot_inc_trades += len(app_i)
        tot_inc_net += ni

        print("-" * 110)
        print(f"  DAY SUMMARY: Raw: {len(tr_b)} trds (Net Rs {raw_net:>8.2f}) | Baseline AI: {len(app_b)} trds (Net Rs {nb:>8.2f}) | Continuous 1% AI: {len(app_i)} trds (Net Rs {ni:>8.2f}) | Surge: Rs {ni - nb:>+8.2f}")
        daily_summaries.append((label, len(tr_b), raw_net, len(app_b), nb, len(app_i), ni))

    print("\n" + "=" * 110)
    print(" 🏆 WEEK OF SEPTEMBER 28, 2026: CONSOLIDATED RECAP")
    print("=" * 110)
    print(f"{'Day & Date':<28} {'Raw Net (Trds)':<20} {'Baseline AI Net (Trds)':<24} {'Continuous 1% Net (Trds)':<24} {'Surge'}")
    print("-" * 110)
    for label, r_n, r_net, b_n, b_net, i_n, i_net in daily_summaries:
        print(f"{label:<28} Rs {r_net:>8.2f} ({r_n}t)     Rs {b_net:>8.2f} ({b_n}t)          Rs {i_net:>8.2f} ({i_n}t)          Rs {i_net - b_net:>+8.2f}")
    print("-" * 110)
    print(f"{'TOTAL WEEK':<28} Rs {tot_raw_net:>8.2f} ({tot_raw_trades}t)     Rs {tot_base_net:>8.2f} ({tot_base_trades}t)          Rs {tot_inc_net:>8.2f} ({tot_inc_trades}t)          Rs {tot_inc_net - tot_base_net:>+8.2f}")
    print(f"Net AI Alpha vs Raw Mechanical: Rs {tot_inc_net - tot_raw_net:>+10.2f}")
    print("=" * 110)

if __name__ == "__main__":
    run_sep28_audit()
