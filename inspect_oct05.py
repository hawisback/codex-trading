#!/usr/bin/env python3
from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier, MarketDossier
from ai_consultant import AIConsultant, AIVerdict

class Oct5RefinedConsultant(AIConsultant):
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

        # Trap 3: V-Reversal / Falling Knife REFINED
        is_strong_bull = (d.vwap_slope_15m >= 0.08 and d.ema_spread_5m >= 8.0)
        is_strong_bear = (d.vwap_slope_15m <= -0.08 and d.ema_spread_5m <= -8.0)

        if d.direction == "PE" and d.rsi_1m > 55.0 and not is_strong_bear:
            return AIVerdict(False, "VETOED", 85, "Trap 3: V-Reversal Counter-Trend", "RSI bounce", "tight_ema20", now_ts)
        if d.direction == "CE" and d.rsi_1m < 35.0 and not is_strong_bull:
            return AIVerdict(False, "VETOED", 85, "Trap 3: Falling Knife Trap", "RSI cascade", "tight_ema20", now_ts)

        # Trap 4: Ceiling / Floor
        if d.ceiling_floor_hazard and d.compression_hazard:
            return AIVerdict(False, "VETOED", 85, "Trap 4: Ceiling/Floor", "Boundary", "tight_ema20", now_ts)

        # Trap 5: Late Day REFINED (Post-14:15 IST / 75m to close)
        is_day_extreme_breakout = (d.distance_to_day_extreme <= 10.0)
        if d.capital_preservation_active:
            return AIVerdict(False, "VETOED", 90, "Trap 5: Capital Preservation", "Locked profit", "standard", now_ts)
        if d.minutes_to_close <= 70 and not (is_reversal_expansion or is_day_extreme_breakout):
            return AIVerdict(False, "VETOED", 85, "Trap 5: Late-Day Square-off", f"Post-14:20 IST ({d.minutes_to_close}m remaining)", "standard", now_ts)

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

def run_oct05_audit():
    consultant = Oct5RefinedConsultant(mode="playbook")
    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
    eng = BacktestEngine("2026-10-05")
    trades = eng.run_simulation(s3_cfg)
    dte = eng.get_expiry_days()

    print("=" * 80)
    print(" 🔎 DETAILED AUDIT: MONDAY, OCTOBER 5, 2026")
    print("=" * 80)
    ai_approved = []
    for i, t in enumerate(trades, 1):
        idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
        dos = generate_market_dossier(
            target_date="2026-10-05", candles=eng.spot_candles, current_bar_idx=idx,
            direction=t.direction, symbol=t.symbol, strike=t.strike,
            option_entry_price=t.entry_price, trade_history=trades[:i-1],
            days_to_expiry=dte, is_expiry_0dte=(dte <= 0.2)
        )
        v = consultant.evaluate(dos)
        status_icon = "✅ APPROVED" if v.is_approved else "🚫 VETOED"
        trap_str = v.trap_detected or "None"
        print(f"Trade #{i}: {t.direction} {t.entry_time[:5]} | Actual: Rs {t.pnl:>8.2f} ({t.exit_reason[:22]}) | AI: {status_icon} -> {trap_str}")
        if v.is_approved:
            ai_approved.append(t)

    g = sum(t.pnl for t in ai_approved)
    f = len(ai_approved) * 40.0
    net = g - f
    print("-" * 80)
    print(f"Total AI Approved: {len(ai_approved)}/5 trades")
    print(f"AI Gross P&L: Rs {g:,.2f} | Fee: Rs {f:,.2f} | Real Net P&L: Rs {net:,.2f}")
    print("=" * 80)



def run_week10_comparison():
    old_c = AIConsultant(mode="playbook")
    new_c = Oct5RefinedConsultant(mode="playbook")
    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
    oct_dates = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]

    def eval_week(dates_list, consultant_inst):
        day_res = []
        for d in dates_list:
            eng = BacktestEngine(d)
            trades = eng.run_simulation(s3_cfg)
            dte = eng.get_expiry_days()
            approved = []
            for i, t in enumerate(trades, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(
                    target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
                    direction=t.direction, symbol=t.symbol, strike=t.strike,
                    option_entry_price=t.entry_price, trade_history=trades[:i-1],
                    days_to_expiry=dte, is_expiry_0dte=(dte <= 0.2)
                )
                if consultant_inst.evaluate(dos).is_approved:
                    approved.append(t)
            g = sum(t.pnl for t in approved)
            f = len(approved) * 40.0
            net = g - f
            day_res.append((d, len(trades), len(approved), g, f, net))
        return day_res

    old_res = eval_week(oct_dates, old_c)
    new_res = eval_week(oct_dates, new_c)

    print("\n" + "=" * 75)
    print(" 📅 WEEK 10 PREVIEW (OCT 05 - 09, 2026) COMPARISON")
    print("=" * 75)
    print(f"{'Date':<12} {'Raw Trds':<10} {'Initial AI Net':<16} {'Refined AI Net':<16} {'Delta'}")
    print("-" * 75)
    tot_o_net = 0
    tot_n_net = 0
    for (d, r_n, o_n, o_g, o_f, o_net), (_, _, n_n, n_g, n_f, n_net) in zip(old_res, new_res):
        tot_o_net += o_net
        tot_n_net += n_net
        print(f"{d:<12} {r_n:<10} Rs {o_net:>9.2f} ({o_n}t)  Rs {n_net:>9.2f} ({n_n}t)  Rs {n_net - o_net:>+9.2f}")
    print("-" * 75)
    print(f"Total Week Net: Initial = Rs {tot_o_net:>9.2f} | Refined = Rs {tot_n_net:>9.2f} | Net Improvement = Rs {tot_n_net - tot_o_net:>+9.2f}")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    run_week10_comparison()
