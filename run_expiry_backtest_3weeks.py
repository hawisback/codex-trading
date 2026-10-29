import os
import sys
import json
from datetime import datetime
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def run_expiry_backtest():
    # The last 3 NIFTY weekly expiry Tuesdays (+ optional 4th week)
    expiry_dates = [
        ("2026-10-06", "Week 1 Expiry (Last Week)"),
        ("2026-09-29", "Week 2 Expiry (2 Weeks Ago)"),
        ("2026-09-22", "Week 3 Expiry (3 Weeks Ago)"),
        ("2026-09-15", "Week 4 Expiry (Reference Baseline)")
    ]

    ai_consultant = AIConsultant(mode="playbook")
    strategy_keys = ["institutional_pullback", "structural_runner", "legacy_scalper"]

    print("=" * 105)
    print(" NIFTY 0DTE WEEKLY EXPIRY BACKTEST: 3-WEEK DEEP FORENSIC AUDIT")
    print(" Evaluating Strategy 3 (Active Institutional Pullback) vs Strategy 2 & Strategy 1")
    print(" Powered by Institutional AI Risk Gateway & Full Session Feeds")
    print("=" * 105)

    all_strat_aggregate = {
        k: {
            "name": "",
            "total_candidates": 0,
            "approved_trades": [],
            "vetoed_trades": [],
            "day_breakdowns": {}
        }
        for k in strategy_keys
    }

    for target_date, date_label in expiry_dates:
        print(f"\n{'='*105}")
        print(f" EXPIRY DATE: {target_date} (Tuesday) — {date_label}")
        print(f"{'='*105}")

        engine = BacktestEngine(target_date=target_date)
        bars_count = len(engine.spot_candles)
        print(f"Loaded {bars_count} 1-minute spot candles (09:15 to 15:30 IST). Days to Expiry: {engine.get_expiry_days():.1f} (0DTE).")

        for strat_key in strategy_keys:
            cfg = StrategyConfig.load_from_config(strat_key)
            all_strat_aggregate[strat_key]["name"] = cfg.name

            # Run baseline strategy execution
            raw_trades = engine.run_simulation(cfg)
            all_strat_aggregate[strat_key]["total_candidates"] += len(raw_trades)

            approved_today = []
            vetoed_today = []

            for trade in raw_trades:
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
                    trade_history=approved_today,
                    days_to_expiry=engine.get_expiry_days(),
                    is_expiry_0dte=True  # Tuesday is 0DTE
                )

                verdict = ai_consultant.evaluate(dossier)
                trade.ai_verdict = verdict

                if verdict.is_approved:
                    approved_today.append(trade)
                    all_strat_aggregate[strat_key]["approved_trades"].append(trade)
                else:
                    vetoed_today.append(trade)
                    all_strat_aggregate[strat_key]["vetoed_trades"].append(trade)

            m_app = calculate_metrics(approved_today)
            all_strat_aggregate[strat_key]["day_breakdowns"][target_date] = {
                "label": date_label,
                "candidates": len(raw_trades),
                "approved": approved_today,
                "vetoed": vetoed_today,
                "metrics": m_app
            }

            net_1lot = m_app["net_pnl"] - (len(approved_today) * 40)
            net_2lot = (m_app["net_pnl"] * 2) - (len(approved_today) * 40)
            win_r = f"{m_app['win_rate']:.1f}%" if approved_today else "N/A"

            print(f"  • {cfg.name:<38} | Candidates: {len(raw_trades):<2} | Approved: {len(approved_today):<2} | Win%: {win_r:<6} | Net (1 Lot): ₹{net_1lot:+,.2f} | Net (2 Lots): ₹{net_2lot:+,.2f}")

    # Aggregated 3-Week (and 4-Week) Summary Matrix
    print("\n" + "=" * 105)
    print(" 3-WEEK AGGREGATED EXPIRY PERFORMANCE MATRIX (WITH AI RISK GATE)")
    print("=" * 105)
    print(f"{'Strategy Name':<38} | {'Candidates':<11} | {'Approved':<9} | {'Win Rate':<9} | {'Net PnL (1 Lot)':<16} | {'Net PnL (2 Lots)':<16}")
    print("-" * 105)

    for strat_key in strategy_keys:
        agg = all_strat_aggregate[strat_key]
        app_trades = agg["approved_trades"]
        m = calculate_metrics(app_trades)
        t_cand = agg["total_candidates"]
        t_app = len(app_trades)
        win_pct = f"{m['win_rate']:.1f}%" if t_app > 0 else "N/A"
        friction_1 = t_app * 40
        friction_2 = t_app * 40
        net_pnl_1 = m["net_pnl"] - friction_1
        net_pnl_2 = (m["net_pnl"] * 2) - friction_2

        print(f"{agg['name']:<38} | {t_cand:<11} | {t_app:<9} | {win_pct:<9} | ₹{net_pnl_1:+14,.2f} | ₹{net_pnl_2:+14,.2f}")
    print("=" * 105)

    # Detailed Expiry Trade Log for Active Strategy 3
    s3_agg = all_strat_aggregate["institutional_pullback"]
    print(f"\n>>> DETAILED 0DTE EXPIRY TRADE LOG: {s3_agg['name']} <<<")
    for target_date, date_label in expiry_dates:
        day_info = s3_agg["day_breakdowns"].get(target_date, {})
        print(f"\n--- {target_date} ({date_label}) ---")
        if not day_info.get("approved") and not day_info.get("vetoed"):
            print("  No trade setups discovered (Disciplined Cash Preservation).")
            continue
        
        for t in day_info.get("approved", []):
            v = t.ai_verdict
            print(f"  [AI APPROVED] Trade #{t.trade_id}: {t.direction} Strike {t.strike} @ {t.entry_time} (Entry: ₹{t.entry_price:.2f}) -> Exit: {t.exit_time} @ ₹{t.exit_price:.2f} ({t.exit_reason})")
            print(f"                PnL (1 Lot): ₹{t.pnl:+,.2f} ({t.pnl_pct:+.1f}%) | PnL (2 Lots): ₹{t.pnl * 2:+,.2f} | Confidence: {v.confidence_score}%")
            print(f"                AI Note: {v.reasoning}")

        for t in day_info.get("vetoed", []):
            v = t.ai_verdict
            print(f"  [AI VETOED]   Trade #{t.trade_id}: {t.direction} Strike {t.strike} @ {t.entry_time} | Trap: {v.trap_detected} | Reason: {v.reasoning}")

if __name__ == "__main__":
    run_expiry_backtest()
