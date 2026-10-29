#!/usr/bin/env python3
"""
Trade Dossier Inspector & AI Consultation Tool
==============================================
Generates and displays the Market State Dossier for any historical trade,
allowing interactive AI consultation and trap verification.

Usage:
    python audit_trade_dossier.py --date 2026-09-24 --trade 4
    python audit_trade_dossier.py --date 2026-09-17 --all
"""

import argparse
from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier


def audit_date(target_date: str, trade_filter: int = None):
    cfg = StrategyConfig.load_from_config("institutional_pullback")
    engine = BacktestEngine(target_date)
    trades = engine.run_simulation(cfg)
    
    if not trades:
        print(f"No trades executed on {target_date}.")
        return

    print(f"\n========================================================================================")
    print(f" AUDITING AI MARKET DOSSIERS FOR: {target_date} (Total Trades: {len(trades)})")
    print(f"========================================================================================\n")

    for i, t in enumerate(trades, 1):
        if trade_filter is not None and i != trade_filter:
            continue
            
        # Find candle index
        idx = 0
        for k, c in enumerate(engine.spot_candles):
            if t.entry_time in c["start_time"]:
                idx = k
                break
                
        dossier = generate_market_dossier(
            target_date=target_date,
            candles=engine.spot_candles,
            current_bar_idx=idx,
            direction=t.direction,
            symbol=t.symbol,
            strike=t.strike,
            option_entry_price=t.entry_price,
            trade_history=trades[:i-1],
            days_to_expiry=engine.get_expiry_days(),
            is_expiry_0dte=(engine.get_expiry_days() == 0.0)
        )
        
        outcome_tag = "🏆 WINNER" if t.pnl > 0 else "❌ FAILED"
        print(f"--- TRADE #{i}: {t.direction} {t.symbol} | Actual Outcome: {outcome_tag} (₹{t.pnl:+,.2f}, {t.pnl_pct:+.1f}%) ---")
        print(f"Hold: {t.exit_bar - t.entry_bar} mins | Exit: {t.exit_reason}\n")
        print(dossier.to_markdown())
        print("-" * 88 + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit Trade Dossiers for AI Consultation")
    parser.add_argument("--date", type=str, default="2026-09-24", help="Target date YYYY-MM-DD")
    parser.add_argument("--trade", type=int, default=None, help="Specific trade number to audit")
    parser.add_argument("--all", action="store_true", help="Audit all trades on that date")
    args = parser.parse_args()

    audit_date(args.date, args.trade)
