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

def run_today_audit():
    target_date = "2026-10-12"
    engine = BacktestEngine(target_date=target_date)
    ai_consultant = AIConsultant(mode="playbook")

    strategies = ["legacy_scalper", "structural_runner", "institutional_pullback"]
    results = {}

    print("=" * 80)
    print(f" FULL FORENSIC AI BACKTEST REPORT: {target_date} (TODAY'S MARKET)")
    print(f" Dataset: {len(engine.spot_candles)} 1-minute bars (09:15 Open to 14:37 Afternoon)")
    print("=" * 80)

    for strat_key in strategies:
        cfg = StrategyConfig.load_from_config(strat_key)
        all_trades = engine.run_simulation(cfg)
        
        # Evaluate each trade through the AI Risk Gateway
        approved_trades = []
        vetoed_trades = []
        
        for idx, trade in enumerate(all_trades, 1):
            bar_idx = trade.entry_bar
            # Provide full candle history up to entry bar
            historical_candles = engine.spot_candles[:bar_idx + 1]
            
            dossier = generate_market_dossier(
                target_date=target_date,
                candles=historical_candles,
                current_bar_idx=len(historical_candles) - 1,
                direction=trade.direction,
                symbol=trade.symbol,
                strike=trade.strike,
                option_entry_price=trade.entry_price,
                trade_history=approved_trades,
                days_to_expiry=engine.get_expiry_days(),
                is_expiry_0dte=False
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
    print("\n" + "=" * 90)
    print(" STRATEGY PERFORMANCE MATRIX WITH FULL AI CONSULTATION GATE")
    print("=" * 90)
    print(f"{'Strategy Name':<38} | {'Trades':<8} | {'Win%':<7} | {'Gross PnL':<11} | {'Friction':<9} | {'Net PnL':<11}")
    print("-" * 90)
    
    for k, res in results.items():
        m = res["ai_metrics"]
        name = res["name"]
        t_count = f"{m['total_trades']}/{res['total_candidates']}"
        win_pct = f"{m['win_rate']:.1f}%"
        gross = f"₹{m['gross_profit'] - m['gross_loss']:+,.2f}"
        friction = f"₹{m['total_trades'] * 40:,.2f}"
        net = f"₹{m['net_pnl'] - (m['total_trades'] * 40):+,.2f}"
        print(f"{name:<38} | {t_count:<8} | {win_pct:<7} | {gross:<11} | {friction:<9} | {net:<11}")
    print("=" * 90)

    # Detailed Breakdown for Strategy 2 and Strategy 3
    for s_key in ["structural_runner", "institutional_pullback"]:
        res = results[s_key]
        print(f"\n>>> DETAILED AI VERDICTS FOR: {res['name']} <<<")
        for t in res["approved"]:
            v = t.ai_verdict
            print(f"  [APPROVED] Trade #{t.trade_id}: {t.direction} Strike {t.strike} @ {t.entry_time} -> Exit {t.exit_time} ({t.exit_reason}) | PnL: ₹{t.pnl:+,.2f} ({t.pnl_pct:+,.1f}%) | Confidence: {v.confidence_score}%")
        for t in res["vetoed"]:
            v = t.ai_verdict
            print(f"  [VETOED]   Trade #{t.trade_id}: {t.direction} Strike {t.strike} @ {t.entry_time} | Trap: {v.trap_detected} | Reason: {v.reasoning}")

if __name__ == "__main__":
    from trading.bootstrap import configure_console
    configure_console()
    run_today_audit()
