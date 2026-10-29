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

def run_today_all_strategies(target_date: str = "2026-10-14"):
    if len(sys.argv) > 1:
        target_date = sys.argv[1]
    engine = BacktestEngine(target_date=target_date)
    ai_consultant = AIConsultant(mode="playbook")

    strategies = ["legacy_scalper", "structural_runner", "institutional_pullback"]
    results = {}

    print("=" * 105)
    print(f" FULL FORENSIC BACKTEST REPORT: {target_date} (REAL 1M OPTION CANDLES: {not engine.is_synthetic_options})")
    print(f" Dataset: {len(engine.spot_candles)} 1-minute bars (09:15 Open to 15:29 Close)")
    print("=" * 105)

    for strat_key in strategies:
        cfg = StrategyConfig.load_from_config(strat_key)
        all_trades = engine.run_simulation(cfg)
        
        approved_trades = []
        vetoed_trades = []
        
        for idx, trade in enumerate(all_trades, 1):
            bar_idx = trade.entry_bar
            historical_candles = engine.spot_candles[:bar_idx + 1]
            days_exp = engine.get_expiry_days()
            
            dossier = generate_market_dossier(
                target_date=target_date,
                candles=historical_candles,
                current_bar_idx=len(historical_candles) - 1,
                direction=trade.direction,
                symbol=trade.symbol,
                strike=trade.strike,
                option_entry_price=trade.entry_price,
                trade_history=approved_trades,
                days_to_expiry=days_exp,
                is_expiry_0dte=(days_exp <= 0.2)
            )
            
            verdict = ai_consultant.evaluate(dossier)
            trade.ai_verdict = verdict
            
            if verdict.is_approved:
                approved_trades.append(trade)
            else:
                vetoed_trades.append(trade)
                
        results[strat_key] = {
            "name": cfg.name,
            "total_candidates": len(all_trades),
            "approved": approved_trades,
            "vetoed": vetoed_trades,
            "raw_metrics": calculate_metrics(all_trades),
            "ai_metrics": calculate_metrics(approved_trades)
        }

    # Print Comparison Table
    print("\n" + "=" * 105)
    print(f" STRATEGY PERFORMANCE COMPARISON ON TODAY'S TAPE ({target_date})")
    print("=" * 105)
    print(f"{'Strategy Profile':<38} | {'Raw Cand':<8} | {'AI Appr':<7} | {'Win%':<7} | {'Net PnL (1 Lot)':<16} | {'Net PnL (2 Lots / 10k)':<20}")
    print("-" * 105)
    
    for k, res in results.items():
        m = res["ai_metrics"]
        name = res["name"]
        raw_c = res["total_candidates"]
        app_c = len(res["approved"])
        win_pct = f"{m['win_rate']:.1f}%" if app_c > 0 else "N/A"
        friction_1 = app_c * 40
        friction_2 = app_c * 40
        net_1 = m["net_pnl"] - friction_1
        net_2 = (m["net_pnl"] * 2) - friction_2
        print(f"{name:<38} | {raw_c:<8} | {app_c:<7} | {win_pct:<7} | ₹{net_1:+14,.2f} | ₹{net_2:+18,.2f}")
    print("=" * 105)

    # Raw Performance Comparison (Without AI Gateway)
    print("\n" + "=" * 105)
    print(" RAW STRATEGY PERFORMANCE (UNPROTECTED WITHOUT AI RISK GATEWAY)")
    print("=" * 105)
    print(f"{'Strategy Profile':<38} | {'Trades':<8} | {'Win Rate':<9} | {'Gross PnL':<13} | {'Friction':<10} | {'Raw Net (1 Lot)':<16}")
    print("-" * 105)
    for k, res in results.items():
        m = res["raw_metrics"]
        name = res["name"]
        t_count = m["total_trades"]
        win_pct = f"{m['win_rate']:.1f}%" if t_count > 0 else "N/A"
        gross = m["gross_profit"] - m["gross_loss"]
        friction = t_count * 40
        net = m["net_pnl"] - friction
        print(f"{name:<38} | {t_count:<8} | {win_pct:<9} | ₹{gross:+11,.2f} | ₹{friction:8,.2f} | ₹{net:+14,.2f}")
    print("=" * 105)

    # Detailed Trade Logs for each strategy
    for s_key in strategies:
        res = results[s_key]
        print(f"\n{'='*105}")
        print(f" DETAILED TRADES FOR: {res['name']}")
        print(f"{'='*105}")
        if not res["approved"]:
            print("  [AI GATEWAY RESULT]: 0 trades approved. 100% of candidate signals were vetoed to protect capital.")
        else:
            print(f"  >>> APPROVED TRADES ({len(res['approved'])}):")
            for t in res["approved"]:
                v = t.ai_verdict
                print(f"    * Trade #{t.trade_id}: {t.direction} Strike {t.strike} @ {t.entry_time} (Entry: ₹{t.entry_price:.2f}) -> Exit: {t.exit_time} @ ₹{t.exit_price:.2f} ({t.exit_reason})")
                print(f"      PnL (1 Lot): ₹{t.pnl:+,.2f} ({t.pnl_pct:+.1f}%) | PnL (2 Lots): ₹{t.pnl * 2:+,.2f} | Confidence: {v.confidence_score}%")
                print(f"      AI Reasoning: {v.reasoning}")

        if res["vetoed"]:
            print(f"\n  >>> SAMPLE VETOED CANDIDATES ({len(res['vetoed'])} Total Vetoed):")
            for t in res["vetoed"][:8]:
                v = t.ai_verdict
                print(f"    * Candidate #{t.trade_id}: {t.direction} Strike {t.strike} @ {t.entry_time} (Entry: ₹{t.entry_price:.2f}) | Trap: {v.trap_detected} | Reason: {v.reasoning}")
            if len(res["vetoed"]) > 8:
                print(f"    ... and {len(res['vetoed']) - 8} more candidates vetoed by AI.")

if __name__ == "__main__":
    run_today_all_strategies()
