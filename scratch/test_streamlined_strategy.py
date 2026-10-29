import os
import sys
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")

from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict

ALL_DATES = [
    # Week 5 (Aug 31 - Sep 04)
    "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    # Week 6 (Sep 07 - Sep 11)
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    # Week 7 (Sep 14 - Sep 18)
    "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    # Week 8 (Sep 21 - Sep 25)
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
    # Week 9 (Sep 28 - Oct 01)
    "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01",
    # Week 10 (Oct 05 - Oct 09)
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
    # Week 11 (Oct 12 - Oct 13)
    "2026-10-12", "2026-10-13"
]

def test_streamlined_strategy():
    # Streamlined Strategy 3:
    # 1. Tight Pullback: 4.0 pts tolerance (true pullback, no chasing)
    # 2. Strict ITM strike selection (essential)
    # 3. 15m Range Box filter (essential)
    # 4. Pure Option Stop + Dynamic Incremental Trailing Ratchet (No premature spot structural cutoffs)
    cfg_streamlined = StrategyConfig(
        key="institutional_pullback_streamlined",
        name="Strategy 3: Streamlined Institutional Pullback",
        require_pullback=True,
        pullback_ema_tolerance_pts=4.0,
        enable_range_box_filter=True,
        range_box_spread_min=28.0,
        value_proximity_pts=24.0,
        strike_selection="STRICT_ITM",
        prevent_v_reversal_counter_trades=False,
        min_spacing_bars=10,
        max_hold_minutes=360,
        initial_stop_pct=30.0,
        target_pct=50.0,
        enable_structural_stops=False, # Rely on pure option protective stop + dynamic ratchet
        enable_runner_trailing=True,
        runner_activation_pct=20.0,
        ema9_trailing_buffer=4.0,
        peak_pullback_pct=10.0,
        lock_breakeven_on_runner=True
    )

    # Streamlined AI Consultant:
    # Keep ESSENTIAL gatekeepers:
    # - Trap 1: The VWAP Blender (saves ₹15.7k)
    # - Trap 8: Climax Overextension (saves ₹1.3k)
    # - Trap 3: Overbought Call Top Chasing & Oversold Put Low Flush (saves ₹3.7k)
    # - Trap 5: Daily Alpha Preservation (saves ₹895)
    # Remove HARMFUL gatekeepers:
    # - Trap 5 Late-day lockout post-14:15 (freed afternoon runners)
    # - Trap 6 Compressed ribbon drift (freed initial squeeze breakouts)
    # - Trap 2 0DTE cheap option blanket veto (freed expiry afternoon multi-baggers)
    # - Trap 3 Falling knife on Call dips (freed V-reversal dips)
    consultant = AIConsultant(mode="playbook")
    disabled_traps = [
        "Late-Day Square-off Volatility",
        "Non-Expiry Late-Day Lockout",
        "Compressed Ribbon Drift",
        "Dead Midday Compressed Ribbon",
        "0DTE Cheap Option & Gamma Whipsaw",
        "Falling Knife Trap",
        "Falling Knife Avalanche"
    ]

    all_trades = []
    weekly_breakdown = {}

    for d in ALL_DATES:
        eng = BacktestEngine(target_date=d)
        if not eng.spot_candles:
            continue
        raw_trades = eng.run_simulation(cfg_streamlined)
        dte = eng.get_expiry_days()
        is_0dte = (dte <= 0.2)

        approved = []
        for i, t in enumerate(raw_trades, 1):
            idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
            dos = generate_market_dossier(
                target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
                direction=t.direction, symbol=t.symbol, strike=t.strike,
                option_entry_price=t.entry_price, trade_history=raw_trades[:i-1],
                days_to_expiry=dte, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dos)
            if not v.is_approved and v.trap_detected:
                for dt in disabled_traps:
                    if dt.lower() in v.trap_detected.lower():
                        v = AIVerdict(
                            is_approved=True, action="APPROVED", confidence_score=85,
                            trap_detected=None, reasoning=f"Harmful rule relaxed: {dt}",
                            recommended_trailing="standard", timestamp=""
                        )
                        break
            if v.is_approved:
                approved.append(t)
        all_trades.extend(approved)

    m = calculate_metrics(all_trades)
    n = len(all_trades)
    fee = n * 40.0
    net_1lot = m["net_pnl"] - fee
    net_2lots = (m["net_pnl"] * 2) - fee
    wr = m["win_rate"]

    print("=" * 90)
    print(" 🎯 STREAMLINED STRATEGY 3 RESULTS (HARMFUL RULES REMOVED, ESSENTIAL PRESERVED)")
    print("=" * 90)
    print(f" Total Trades (30 Sessions):  {n} (Wins: {m['wins']}, Losses: {m['losses']})")
    print(f" Win Rate:                    {wr:.1f}%")
    print(f" Gross P&L (1 Lot):           ₹{m['net_pnl']:+,.2f}")
    print(f" Broker Friction:             ₹{fee:,.2f} (@ ₹40/trade)")
    print(f" Real Net P&L (1 Lot):        ₹{net_1lot:+,.2f}")
    print(f" Real Net P&L (2 Lots / ₹10k):₹{net_2lots:+,.2f} (+{net_2lots/10000*100:.1f}% ROI)")
    print(f" Profit Factor:               {m['profit_factor']:.2f}")
    print(f" Max Drawdown (1 Lot):        ₹{m['max_drawdown']:,.2f}")
    print(f" Avg Win / Avg Loss:          ₹{m['avg_win']:+,.2f} / ₹{m['avg_loss']:+,.2f}")
    weeks_def = [
        ("Week 5 (Aug 31 - Sep 04)", ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]),
        ("Week 6 (Sep 07 - Sep 11)", ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]),
        ("Week 7 (Sep 14 - Sep 18)", ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]),
        ("Week 8 (Sep 21 - Sep 25)", ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]),
        ("Week 9 (Sep 28 - Oct 01)", ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]),
        ("Week 10 (Oct 05 - Oct 09)", ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]),
        ("Week 11 (Oct 12 - Oct 13)", ["2026-10-12", "2026-10-13"])
    ]

    print("\nWEEK-BY-WEEK BREAKDOWN:")
    print(f"{'Week':<28} | {'Trades':<7} | {'Win%':<6} | {'Net (1 Lot)':<12} | {'Net (2 Lots)':<14}")
    print("-" * 75)

    for w_name, w_dates in weeks_def:
        w_trades = [t for t in all_trades if any(d in t.symbol or d in t.entry_time for d in w_dates)]
        wm = calculate_metrics(w_trades)
        wn = len(w_trades)
        w_fee = wn * 40.0
        w_net1 = wm["net_pnl"] - w_fee
        w_net2 = (wm["net_pnl"] * 2) - w_fee
        print(f"{w_name:<28} | {wn:<7} | {wm['win_rate']:<5.1f}% | ₹{w_net1:>+10,.2f} | ₹{w_net2:>+12,.2f}")

    print("=" * 90)

if __name__ == "__main__":
    test_streamlined_strategy()
