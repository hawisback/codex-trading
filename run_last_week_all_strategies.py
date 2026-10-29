import os
import sys
import json
from datetime import datetime, timedelta
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def run_last_week_backtest():
    week_days = [
        ("Monday", "2026-10-05"),
        ("Tuesday (0DTE)", "2026-10-06"),
        ("Wednesday", "2026-10-07"),
        ("Thursday", "2026-10-08"),
        ("Friday", "2026-10-09")
    ]
    
    strategies = ["legacy_scalper", "structural_runner", "institutional_pullback"]
    ai_consultant = AIConsultant(mode="playbook")

    print("=" * 115)
    print(" 🔎 COMPREHENSIVE MULTI-STRATEGY AUDIT: LAST WEEK (OCTOBER 05 - OCTOBER 09, 2026)")
    print(" Using True Spot Session VWAP, Spot 5m EMAs, and AI Risk Consultation Gateway")
    print("=" * 115)

    # Store results per strategy across the week
    weekly_results = {
        s: {
            "name": "",
            "days": {},
            "all_raw_trades": [],
            "all_approved_trades": [],
            "all_vetoed_trades": []
        }
        for s in strategies
    }

    for day_label, target_date in week_days:
        engine = BacktestEngine(target_date=target_date)
        d_obj = datetime.strptime(target_date, "%Y-%m-%d")
        is_0dte = (d_obj.weekday() == 1)
        days_exp = engine.get_expiry_days()

        print(f"\n>>> Processing {day_label} ({target_date}) | Spot Bars: {len(engine.spot_candles)} | 0DTE: {is_0dte} | Days to Exp: {days_exp:.1f} <<<")

        for strat_key in strategies:
            cfg = StrategyConfig.load_from_config(strat_key)
            weekly_results[strat_key]["name"] = cfg.name

            # Run engine simulation
            raw_trades = engine.run_simulation(cfg)

            approved = []
            vetoed = []

            for idx, trade in enumerate(raw_trades, 1):
                bar_idx = trade.entry_bar
                historical_candles = engine.spot_candles[:bar_idx + 1]

                dossier = generate_market_dossier(
                    target_date=target_date,
                    candles=historical_candles,
                    current_bar_idx=len(historical_candles) - 1,
                    direction=trade.direction,
                    symbol=trade.symbol,
                    strike=trade.strike,
                    option_entry_price=trade.entry_price,
                    trade_history=approved,
                    days_to_expiry=days_exp,
                    is_expiry_0dte=is_0dte
                )

                verdict = ai_consultant.evaluate(dossier)
                trade.ai_verdict = verdict

                if verdict.is_approved:
                    approved.append(trade)
                else:
                    vetoed.append(trade)

            weekly_results[strat_key]["days"][target_date] = {
                "day_label": day_label,
                "raw_count": len(raw_trades),
                "app_count": len(approved),
                "veto_count": len(vetoed),
                "approved_trades": approved,
                "raw_trades": raw_trades,
                "raw_metrics": calculate_metrics(raw_trades),
                "ai_metrics": calculate_metrics(approved)
            }

            weekly_results[strat_key]["all_raw_trades"].extend(raw_trades)
            weekly_results[strat_key]["all_approved_trades"].extend(approved)
            weekly_results[strat_key]["all_vetoed_trades"].extend(vetoed)

    # -------------------------------------------------------------
    # 1. Day-by-Day Breakdown for Primary Strategy (Strategy 3)
    # -------------------------------------------------------------
    s3_data = weekly_results["institutional_pullback"]
    print("\n" + "=" * 115)
    print(" 📊 STRATEGY 3 (INSTITUTIONAL PULLBACK & STRICT ITM) - DAY-BY-DAY BREAKDOWN")
    print("=" * 115)
    print(f"{'Day & Date':<24} | {'Raw Cand':<9} | {'AI Appr':<8} | {'Win%':<7} | {'Net PnL (1 Lot)':<16} | {'Net PnL (2 Lots / 10k)':<22}")
    print("-" * 115)

    for day_label, target_date in week_days:
        day_info = s3_data["days"][target_date]
        m = day_info["ai_metrics"]
        app_c = day_info["app_count"]
        raw_c = day_info["raw_count"]
        win_rate = f"{m['win_rate']:.1f}%" if app_c > 0 else "N/A"
        fric = app_c * 40.0
        net1 = m["net_pnl"] - fric
        net2 = (m["net_pnl"] * 2) - fric
        print(f"{day_label:<24} | {raw_c:<9} | {app_c:<8} | {win_rate:<7} | ₹{net1:+14,.2f} | ₹{net2:+20,.2f}")
    print("-" * 115)

    s3_all_m = calculate_metrics(s3_data["all_approved_trades"])
    s3_app_tot = len(s3_data["all_approved_trades"])
    s3_raw_tot = len(s3_data["all_raw_trades"])
    s3_fric = s3_app_tot * 40.0
    s3_tot_net1 = s3_all_m["net_pnl"] - s3_fric
    s3_tot_net2 = (s3_all_m["net_pnl"] * 2) - s3_fric
    s3_tot_win = f"{s3_all_m['win_rate']:.1f}%" if s3_app_tot > 0 else "N/A"
    print(f"{'WEEK TOTAL':<24} | {s3_raw_tot:<9} | {s3_app_tot:<8} | {s3_tot_win:<7} | ₹{s3_tot_net1:+14,.2f} | ₹{s3_tot_net2:+20,.2f}")
    print("=" * 115)

    # -------------------------------------------------------------
    # 2. Complete Comparison Across All 3 Strategies
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print(" 🏆 FULL-WEEK STRATEGY BENCHMARK COMPARISON (OCTOBER 05 - 09, 2026)")
    print("=" * 115)
    print(f"{'Strategy Profile':<38} | {'Raw':<5} | {'AI':<4} | {'Win%':<7} | {'Net PnL (1 Lot)':<16} | {'Net PnL (2 Lots / 10k)':<20} | {'ROI on 10k'}")
    print("-" * 115)

    for k in strategies:
        res = weekly_results[k]
        name = res["name"]
        raw_c = len(res["all_raw_trades"])
        app_c = len(res["all_approved_trades"])
        m = calculate_metrics(res["all_approved_trades"])
        fric = app_c * 40.0
        net1 = m["net_pnl"] - fric
        net2 = (m["net_pnl"] * 2) - fric
        win_rate = f"{m['win_rate']:.1f}%" if app_c > 0 else "N/A"
        roi = f"{(net2 / 10000.0) * 100:+.1f}%" if net2 != 0 else "0.0%"
        print(f"{name:<38} | {raw_c:<5} | {app_c:<4} | {win_rate:<7} | ₹{net1:+14,.2f} | ₹{net2:+18,.2f} | {roi:>10}")
    print("=" * 115)

    # -------------------------------------------------------------
    # 3. AI Risk Gateway Protection Audit (Capital Saved)
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print(" 🛡️ AI RISK GATEWAY VETO IMPACT (CAPITAL SAVED ON VETOED SETUPS)")
    print("=" * 115)
    for k in strategies:
        res = weekly_results[k]
        raw_m = calculate_metrics(res["all_raw_trades"])
        ai_m = calculate_metrics(res["all_approved_trades"])
        raw_net = raw_m["net_pnl"] - (len(res["all_raw_trades"]) * 40.0)
        ai_net = ai_m["net_pnl"] - (len(res["all_approved_trades"]) * 40.0)
        saved = ai_net - raw_net
        vetoed_count = len(res["all_vetoed_trades"])
        print(f"• {res['name']}:")
        print(f"  - Total Candidate Signals: {len(res['all_raw_trades'])} | AI Vetoed: {vetoed_count} | AI Approved: {len(res['all_approved_trades'])}")
        print(f"  - Raw Net PnL (Unprotected): ₹{raw_net:+10,.2f}")
        print(f"  - AI Net PnL (Protected):   ₹{ai_net:+10,.2f}")
        print(f"  - Net Capital Preserved by AI Risk Gateway: ₹{saved:+10,.2f}")
    print("=" * 115)

    # -------------------------------------------------------------
    # 4. Strategy 3 Detailed Trade Log (All Approved Trades)
    # -------------------------------------------------------------
    print("\n" + "=" * 115)
    print(" 📜 STRATEGY 3 APPROVED TRADE JOURNAL (LAST WEEK)")
    print("=" * 115)
    print(f"{'Date':<11} | {'Entry':<8} | {'Contract':<25} | {'Fill':<8} | {'Exit':<8} | {'Exit Price':<10} | {'PnL (1 Lot)':<12} | {'Exit Reason'}")
    print("-" * 115)

    for t in s3_data["all_approved_trades"]:
        pnl_1lot = (t.pnl or 0.0) - 40.0
        # Determine date from symbol or entry_bar
        sym = t.symbol
        trade_date = sym.split("_")[1] if "_" in sym else "2026-10-05"
        print(f"{trade_date:<11} | {t.entry_time:<8} | {t.symbol:<25} | ₹{t.entry_price:<7.2f} | {t.exit_time:<8} | ₹{t.exit_price:<9.2f} | ₹{pnl_1lot:+10.2f} | {t.exit_reason}")
    print("=" * 115)

if __name__ == "__main__":
    run_last_week_backtest()
