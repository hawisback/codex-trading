import os
import sys
import copy
from typing import List, Dict, Any

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

def run_eval(cfg: StrategyConfig, disabled_traps: List[str] = None):
    disabled_traps = disabled_traps or []
    consultant = AIConsultant(mode="playbook")
    all_trades = []

    for d in ALL_DATES:
        eng = BacktestEngine(target_date=d)
        if not eng.spot_candles:
            continue
        raw_trades = eng.run_simulation(cfg)
        dte = eng.get_expiry_days()
        is_0dte = (dte <= 0.2)

        approved_trades = []
        for i, t in enumerate(raw_trades, 1):
            idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
            dos = generate_market_dossier(
                target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
                direction=t.direction, symbol=t.symbol, strike=t.strike,
                option_entry_price=t.entry_price, trade_history=raw_trades[:i-1],
                days_to_expiry=dte, is_expiry_0dte=is_0dte
            )

            verdict = consultant.evaluate(dos)

            # Check if veto was caused by an ablated/disabled trap
            if not verdict.is_approved and verdict.trap_detected:
                for dt in disabled_traps:
                    if dt.lower() in verdict.trap_detected.lower():
                        # Override veto: this rule is disabled
                        verdict = AIVerdict(
                            is_approved=True, action="APPROVED", confidence_score=75,
                            trap_detected=None, reasoning=f"Trap disabled for ablation: {dt}",
                            recommended_trailing="standard", timestamp=""
                        )
                        break

            if verdict.is_approved:
                approved_trades.append(t)

        all_trades.extend(approved_trades)

    m = calculate_metrics(all_trades)
    n = len(all_trades)
    fee = n * 40.0
    net_1lot = m["net_pnl"] - fee
    net_2lots = (m["net_pnl"] * 2) - (n * 40.0) # 2 lots with round-trip fee
    wr = m["win_rate"]
    pf = m["profit_factor"]
    return {
        "trades": n, "wins": m["wins"], "losses": m["losses"],
        "win_rate": wr, "gross": m["net_pnl"], "friction": fee,
        "net_1lot": net_1lot, "net_2lots": net_2lots, "pf": pf
    }

if __name__ == "__main__":
    print("=" * 110)
    print(" 🔬 COMPREHENSIVE 30-SESSION ABLATION STUDY: EVALUATING EVERY STRATEGY & AI RULE")
    print(" Dataset: Aug 31 - Oct 13, 2026 (30 Sessions) | Baseline Capital: ₹10,000 (2 Lots)")
    print("=" * 110)

    # 1. Active Baseline (Current Production Strategy 3 + All AI Playbook Traps)
    base_cfg = StrategyConfig.load_from_config("institutional_pullback")
    base_res = run_eval(base_cfg)

    print(f"\n📍 CURRENT BASELINE (All Rules Active):")
    print(f"   Trades: {base_res['trades']} | WR: {base_res['win_rate']:.1f}% | Net 1-Lot: ₹{base_res['net_1lot']:+,.2f} | Net 2-Lots: ₹{base_res['net_2lots']:+,.2f} | PF: {base_res['pf']:.2f}")

    # -------------------------------------------------------------
    # PART 1: STRATEGY 3 CORE PARAMETERS ABLATION
    # -------------------------------------------------------------
    print("\n" + "=" * 110)
    print(" PART 1: STRATEGY 3 CORE STRUCTURAL RULES ABLATION")
    print(f"{'Rule Tested / Variation':<42} | {'Trades':<7} | {'Win%':<6} | {'Net (2 Lots)':<14} | {'Alpha vs Base':<15} | {'Verdict'}")
    print("-" * 110)

    tests_s3 = [
        ("Base: Current Production Rules", base_cfg),
        ("Remove Pullback Requirement (Chasing Allowed)", StrategyConfig(
            key="s3_no_pullback", require_pullback=False,
            enable_range_box_filter=base_cfg.enable_range_box_filter,
            strike_selection=base_cfg.strike_selection,
            prevent_v_reversal_counter_trades=base_cfg.prevent_v_reversal_counter_trades,
            enable_structural_stops=base_cfg.enable_structural_stops,
            enable_runner_trailing=base_cfg.enable_runner_trailing
        )),
        ("Tight Pullback (4.0 pts tolerance)", StrategyConfig(
            key="s3_tight_pb", require_pullback=True, pullback_ema_tolerance_pts=4.0,
            enable_range_box_filter=base_cfg.enable_range_box_filter,
            strike_selection=base_cfg.strike_selection,
            prevent_v_reversal_counter_trades=base_cfg.prevent_v_reversal_counter_trades,
            enable_structural_stops=base_cfg.enable_structural_stops,
            enable_runner_trailing=base_cfg.enable_runner_trailing
        )),
        ("Wide Pullback (18.0 pts tolerance)", StrategyConfig(
            key="s3_wide_pb", require_pullback=True, pullback_ema_tolerance_pts=18.0,
            enable_range_box_filter=base_cfg.enable_range_box_filter,
            strike_selection=base_cfg.strike_selection,
            prevent_v_reversal_counter_trades=base_cfg.prevent_v_reversal_counter_trades,
            enable_structural_stops=base_cfg.enable_structural_stops,
            enable_runner_trailing=base_cfg.enable_runner_trailing
        )),
        ("Remove 15m Range Box Filter", StrategyConfig(
            key="s3_no_box", require_pullback=base_cfg.require_pullback,
            pullback_ema_tolerance_pts=base_cfg.pullback_ema_tolerance_pts,
            enable_range_box_filter=False,
            strike_selection=base_cfg.strike_selection,
            prevent_v_reversal_counter_trades=base_cfg.prevent_v_reversal_counter_trades,
            enable_structural_stops=base_cfg.enable_structural_stops,
            enable_runner_trailing=base_cfg.enable_runner_trailing
        )),
        ("Use ATM Option Strikes (vs STRICT_ITM)", StrategyConfig(
            key="s3_atm_strikes", require_pullback=base_cfg.require_pullback,
            pullback_ema_tolerance_pts=base_cfg.pullback_ema_tolerance_pts,
            enable_range_box_filter=base_cfg.enable_range_box_filter,
            strike_selection="ATM_ROUNDED",
            prevent_v_reversal_counter_trades=base_cfg.prevent_v_reversal_counter_trades,
            enable_structural_stops=base_cfg.enable_structural_stops,
            enable_runner_trailing=base_cfg.enable_runner_trailing
        )),
        ("Allow V-Reversal Counter Trades", StrategyConfig(
            key="s3_allow_counter", require_pullback=base_cfg.require_pullback,
            pullback_ema_tolerance_pts=base_cfg.pullback_ema_tolerance_pts,
            enable_range_box_filter=base_cfg.enable_range_box_filter,
            strike_selection=base_cfg.strike_selection,
            prevent_v_reversal_counter_trades=False,
            enable_structural_stops=base_cfg.enable_structural_stops,
            enable_runner_trailing=base_cfg.enable_runner_trailing
        )),
        ("Disable Structural Stops (Fixed 30% only)", StrategyConfig(
            key="s3_no_struct_stops", require_pullback=base_cfg.require_pullback,
            pullback_ema_tolerance_pts=base_cfg.pullback_ema_tolerance_pts,
            enable_range_box_filter=base_cfg.enable_range_box_filter,
            strike_selection=base_cfg.strike_selection,
            prevent_v_reversal_counter_trades=base_cfg.prevent_v_reversal_counter_trades,
            enable_structural_stops=False,
            enable_runner_trailing=base_cfg.enable_runner_trailing
        )),
        ("Disable Dynamic Runner Trailing", StrategyConfig(
            key="s3_no_trailing", require_pullback=base_cfg.require_pullback,
            pullback_ema_tolerance_pts=base_cfg.pullback_ema_tolerance_pts,
            enable_range_box_filter=base_cfg.enable_range_box_filter,
            strike_selection=base_cfg.strike_selection,
            prevent_v_reversal_counter_trades=base_cfg.prevent_v_reversal_counter_trades,
            enable_structural_stops=base_cfg.enable_structural_stops,
            enable_runner_trailing=False
        ))
    ]

    for label, cfg in tests_s3:
        r = run_eval(cfg)
        diff = r["net_2lots"] - base_res["net_2lots"]
        if label.startswith("Base:"):
            verdict = "BASELINE"
        elif diff < -500.0:
            verdict = "KEEP (Essential)"
        elif diff > +500.0:
            verdict = "IMPROVES (Review)"
        else:
            verdict = "NEUTRAL"
        print(f"{label:<42} | {r['trades']:<7} | {r['win_rate']:<5.1f}% | ₹{r['net_2lots']:>+11,.2f} | ₹{diff:>+12,.2f} | {verdict}")

    # -------------------------------------------------------------
    # PART 2: AI PLAYBOOK TRAP GATEKEEPERS ABLATION
    # -------------------------------------------------------------
    print("\n" + "=" * 110)
    print(" PART 2: AI CONSULTANT TRAP RULES ABLATION (Disable One Trap At A Time)")
    print(f"{'Ablated / Disabled Trap':<42} | {'Trades':<7} | {'Win%':<6} | {'Net (2 Lots)':<14} | {'Alpha vs Base':<15} | {'Verdict'}")
    print("-" * 110)

    traps_to_test = [
        ("Base: All Traps Active", []),
        ("Disable Trap 1: The VWAP Blender", ["Trap 1: The VWAP Blender"]),
        ("Disable Trap 1: Midday Flat-VWAP Chop", ["Trap 1: Midday Flat-VWAP Chop"]),
        ("Disable Trap 2: 0DTE Cheap Option / Gamma", ["Trap 2: 0DTE Cheap Option"]),
        ("Disable Trap 3: Call Overbought Spike (RSI 74.5)", ["Overbought Call Spike Chasing"]),
        ("Disable Trap 3: Call Top Chasing near Day High", ["Overbought Call Top Chasing"]),
        ("Disable Trap 3: Falling Knife / Panic Drop", ["Falling Knife"]),
        ("Disable Trap 3: Put Oversold Low Flush", ["Oversold Put Flush at Day Low", "Oversold Put Panic Flush"]),
        ("Disable Trap 4: Range Box Ceiling/Floor", ["Trap 4: 15-Minute Consolidation Ceiling"]),
        ("Disable Trap 5: Midday/Afternoon Alpha Lock", ["Trap 5: Daily Alpha Preservation After Loss", "Trap 5: Capital Preservation Mode"]),
        ("Disable Trap 5: Late-Day Cutoffs (Post 14:15)", ["Trap 5: Late-Day Square-off Volatility", "Trap 5: Non-Expiry Late-Day Lockout"]),
        ("Disable Trap 6: Compressed Ribbon Drift", ["Trap 6: Compressed Ribbon Drift Trap", "Trap 6: Dead Midday Compressed Ribbon"]),
        ("Disable Trap 7: Counter-Trend VWAP Slope", ["Trap 7: Counter-Trend VWAP Slope"]),
        ("Disable Trap 8: Climax Overextension (>=75pt)", ["Trap 8: Climax Overextension Cap", "Trap 8: Climax Overextension Trap"])
    ]

    for label, dt in traps_to_test:
        r = run_eval(base_cfg, disabled_traps=dt)
        diff = r["net_2lots"] - base_res["net_2lots"]
        if label.startswith("Base:"):
            verdict = "BASELINE"
        elif diff < -500.0:
            verdict = "KEEP (Protects Capital)"
        elif diff > +500.0:
            verdict = "REMOVE (Unnecessary Drag)"
        else:
            verdict = "NEUTRAL / REDUNDANT"
        print(f"{label:<42} | {r['trades']:<7} | {r['win_rate']:<5.1f}% | ₹{r['net_2lots']:>+11,.2f} | ₹{diff:>+12,.2f} | {verdict}")

    print("=" * 110 + "\n")
