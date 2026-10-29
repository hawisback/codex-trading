#!/usr/bin/env python3
"""
Deep-Dive Day-by-Day Audit across Last Week (October 5 - 9, 2026)
Comparing:
- Raw Strategy 3
- Baseline AI Strategy 3
- Continuous 1% Incremental Trailing AI Strategy 3
"""

from test_incremental_trailing import IncrementalTrailingEngine, base_cfg
from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier, MarketDossier
from ai_consultant import AIConsultant, AIVerdict

class PreciseConsultant(AIConsultant):
    def _evaluate_playbook(self, d: MarketDossier) -> AIVerdict:
        now_ts = "test"
        is_reversal_expansion = bool(d.is_directional_shift)

        # Trap 1: VWAP Blender
        if d.vwap_blender_warning and not is_reversal_expansion:
            return AIVerdict(False, "VETOED", 95, "Trap 1: The VWAP Blender", "Chop", "tight_ema20", now_ts)
        if "MIDDAY_DEAD_ZONE" in d.session_phase and abs(d.vwap_slope_15m) < 0.08 and not is_reversal_expansion:
            return AIVerdict(False, "VETOED", 90, "Trap 1: Midday Chop", "Chop", "tight_ema20", now_ts)

        # Trap 2: 0DTE Cheap Option
        if d.is_expiry_0dte and (d.gamma_hazard_flag or d.option_entry_price < 30.0):
            return AIVerdict(False, "VETOED", 95, "Trap 2: 0DTE Cheap Option", "Gamma risk", "tight_ema20", now_ts)

        # Trap 3: V-Reversal / Knife with 28.0 RSI Floor
        is_strong_bull = (d.vwap_slope_15m >= 0.08 and d.ema_spread_5m >= 8.0)
        is_strong_bear = (d.vwap_slope_15m <= -0.08 and d.ema_spread_5m <= -8.0)

        if d.direction == "PE":
            if d.rsi_1m > 72.0:
                return AIVerdict(False, "VETOED", 85, "Trap 3: V-Reversal Counter-Trend", "Severe short squeeze", "tight_ema20", now_ts)
            elif d.rsi_1m > 55.0 and not is_strong_bear:
                return AIVerdict(False, "VETOED", 85, "Trap 3: V-Reversal Counter-Trend", "RSI bounce", "tight_ema20", now_ts)

        if d.direction == "CE":
            if d.rsi_1m < 28.0:
                return AIVerdict(False, "VETOED", 90, "Trap 3: Falling Knife Avalanche", "RSI crash < 28", "tight_ema20", now_ts)
            elif d.rsi_1m < 35.0 and not is_strong_bull:
                return AIVerdict(False, "VETOED", 85, "Trap 3: Falling Knife Trap", "RSI cascade", "tight_ema20", now_ts)

        # Trap 4: Ceiling / Floor
        if d.ceiling_floor_hazard and d.compression_hazard:
            return AIVerdict(False, "VETOED", 85, "Trap 4: Ceiling/Floor", "Boundary", "tight_ema20", now_ts)

        # Trap 5: Late Day (Post-14:15 IST / 75m to close)
        is_day_extreme_breakout = (d.distance_to_day_extreme <= 10.0)
        if d.capital_preservation_active:
            return AIVerdict(False, "VETOED", 90, "Trap 5: Capital Preservation", "Locked profit", "standard", now_ts)
        if d.minutes_to_close <= 75 and not (is_reversal_expansion or is_day_extreme_breakout):
            return AIVerdict(False, "VETOED", 85, "Trap 5: Late-Day Square-off", f"Post-14:15 IST ({d.minutes_to_close}m remaining)", "standard", now_ts)

        # Trap 6: Compressed Ribbon
        if d.ribbon_compression_hazard and not (d.is_directional_shift and d.distance_to_day_extreme >= 35.0):
            return AIVerdict(False, "VETOED", 85, "Trap 6: Compressed Ribbon", "Compression", "tight_ema20", now_ts)

        # Trap 7: Counter-trend slope
        is_counter_trend = (d.direction == "PE" and d.vwap_slope_15m > 0.10) or (d.direction == "CE" and d.vwap_slope_15m < -0.10)
        if is_counter_trend and not is_reversal_expansion:
            return AIVerdict(False, "VETOED", 90, "Trap 7: Counter-Trend Slope", "Counter slope", "tight_ema20", now_ts)

        # Trap 8: Climax
        if d.vwap_distance_pts > 80.0 and not is_reversal_expansion:
            return AIVerdict(False, "VETOED", 85, "Trap 8: Climax Exhaustion", "Overextended", "tight_ema20", now_ts)

        # Setup 1
        is_directional_aligned = (d.direction == "CE" and d.vwap_slope_15m > 0.05) or (d.direction == "PE" and d.vwap_slope_15m < -0.05)
        is_clean_pullback = (d.pullback_distance_pts <= 4.5)
        has_runway = (d.vwap_distance_pts >= 12.0)
        if is_directional_aligned and is_clean_pullback and has_runway:
            return AIVerdict(True, "APPROVED", 95, None, "Setup 1: Institutional Trend Runner", "runner_ema9", now_ts)

        return AIVerdict(True, "APPROVED", 80, None, "Standard Approved", "standard", now_ts)


def run_week10_audit():
    consultant = PreciseConsultant(mode="playbook")
    s3 = StrategyConfig.load_from_config("institutional_pullback")
    week10 = [
        ("Monday, Oct 05", "2026-10-05"),
        ("Tuesday, Oct 06 (0DTE)", "2026-10-06"),
        ("Wednesday, Oct 07", "2026-10-07"),
        ("Thursday, Oct 08", "2026-10-08"),
        ("Friday, Oct 09", "2026-10-09")
    ]

    print("=" * 105)
    print(" 🔎 COMPLETE DAY-BY-DAY COMPARATIVE AUDIT: LAST WEEK (OCTOBER 05 - 09, 2026)")
    print("=" * 105)
    print(f"{'Day & Date':<24} {'Raw Trds':<10} {'AI Trds':<9} {'Raw Net':<14} {'Baseline AI Net':<18} {'Continuous 1% Net':<20} {'Surge'}")
    print("-" * 105)

    tot_raw = 0.0
    tot_base = 0.0
    tot_inc = 0.0

    for label, d in week10:
        eng_b = BacktestEngine(d)
        eng_i = IncrementalTrailingEngine(d, activation_pct=20.0, trail_offset_pct=10.0)
        tr_b = eng_b.run_simulation(s3)
        tr_i = eng_i.run_simulation(s3)
        dte = eng_b.get_expiry_days()

        # Raw stats
        raw_net = sum(t.pnl for t in tr_b) - len(tr_b) * 40.0
        tot_raw += raw_net

        # Baseline AI stats
        app_b = []
        for i, t in enumerate(tr_b, 1):
            idx = [k for k, c in enumerate(eng_b.spot_candles) if t.entry_time in c["start_time"]][0]
            dos = generate_market_dossier(d, eng_b.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, tr_b[:i-1], dte, (dte <= 0.2))
            if consultant.evaluate(dos).is_approved:
                app_b.append(t)
        nb = sum(t.pnl for t in app_b) - len(app_b) * 40.0
        tot_base += nb

        # Incremental AI stats
        app_i = []
        for i, t in enumerate(tr_i, 1):
            idx = [k for k, c in enumerate(eng_i.spot_candles) if t.entry_time in c["start_time"]][0]
            dos = generate_market_dossier(d, eng_i.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, tr_i[:i-1], dte, (dte <= 0.2))
            if consultant.evaluate(dos).is_approved:
                app_i.append(t)
        ni = sum(t.pnl for t in app_i) - len(app_i) * 40.0
        tot_inc += ni

        surge = ni - nb
        print(f"{label:<24} {len(tr_b):<10} {len(app_i):<9} Rs {raw_net:>9.2f}   Rs {nb:>10.2f}        Rs {ni:>10.2f}         Rs {surge:>+9.2f}")

    print("-" * 105)
    print(f"{'TOTAL WEEK 10':<24} 34 trades  12 trades Rs {tot_raw:>9.2f}   Rs {tot_base:>10.2f}        Rs {tot_inc:>10.2f}         Rs {tot_inc - tot_base:>+9.2f}")
    print("=" * 105)

if __name__ == "__main__":
    run_week10_audit()
