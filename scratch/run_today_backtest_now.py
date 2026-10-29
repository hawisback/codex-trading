#!/usr/bin/env python3
"""
Forensic AI Backtest for Today's Market (2026-10-21 as of 12:18 IST)
Evaluates:
- Strategy 1: Legacy Scalper (6-min stopwatch, 6% SL, 7% Target, No AI)
- Strategy 2: Structural Runner (Range Box, VWAP/EMA20 stops, 5m EMA9 trailing runner)
- Strategy 3: Institutional Pullback (Pullback to EMA9, Strict ITM, V-reversal filters, AI Gatekeeper)
- Strategy 4: AI Opportunity Radar (Dynamic Swings, Climax Spring + Trend Pullback, Dynamic Trailing Ratchet, AI Gatekeeper)
- Compares with Real Live Broker Trades executed today.
"""

import sys
import os
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import json
from datetime import datetime
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import AIOpportunityRadar, run_ai_radar_simulation, compute_metrics

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

def run():
    target_date = "2026-10-21"
    engine = BacktestEngine(target_date=target_date)
    # Calibrate premium envelope for realistic ITM contract evaluation (avoiding OTM penny traps)
    backtest_trading_cfg = {
        "option_selection": {
            "min_option_premium": 10.0,
            "max_option_premium": 500.0,
        }
    }
    consultant = AIConsultant(mode="playbook", trading_config=backtest_trading_cfg)
    radar = AIOpportunityRadar()

    n_bars = len(engine.spot_candles)
    start_spot = engine.spot_candles[0]["open"]
    current_spot = engine.spot_candles[-1]["close"]
    high_spot = max(c["high"] for c in engine.spot_candles)
    low_spot = min(c["low"] for c in engine.spot_candles)
    change_pct = ((current_spot - start_spot) / start_spot) * 100

    print("=" * 95)
    print(f"📊 INTRADAY FORENSIC AI BACKTEST REPORT: {target_date} (TODAY AS OF {datetime.now().strftime('%H:%M:%S')} IST)")
    print(f"Dataset: {n_bars} 1-minute bars (09:15 Open to 12:18 Midday)")
    print(f"Session Context: Open: {start_spot:.1f} | High: {high_spot:.1f} | Low: {low_spot:.1f} | Current: {current_spot:.1f} ({change_pct:+.2f}%)")
    print("=" * 95)

    # 1. Evaluate Strategies 1, 2, 3
    strategies = ["legacy_scalper", "structural_runner", "institutional_pullback"]
    results = {}

    for strat_key in strategies:
        cfg = StrategyConfig.load_from_config(strat_key)
        all_trades = engine.run_simulation(cfg)
        
        approved_trades = []
        vetoed_trades = []

        if strat_key == "legacy_scalper":
            # Strategy 1 is mechanical (No AI Gatekeeper)
            approved_trades = all_trades
        else:
            for trade in all_trades:
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
                    trade_history=approved_trades,
                    days_to_expiry=engine.get_expiry_days(),
                    is_expiry_0dte=False
                )

                verdict = consultant.evaluate(dossier)
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
            "metrics": calculate_metrics(approved_trades)
        }

    # 2. Evaluate Strategy 4: AI Opportunity Radar
    strat4_cfg = StrategyConfig.load_from_config("ai_opportunity_radar")
    strat4_trades = run_ai_radar_simulation(engine, strat4_cfg, radar, consultant)
    strat4_metrics = calculate_metrics(strat4_trades)
    results["ai_opportunity_radar"] = {
        "name": "Strategy 4: AI Opportunity Radar (Active Engine)",
        "total_candidates": len(strat4_trades),
        "approved": strat4_trades,
        "vetoed": [],
        "metrics": strat4_metrics
    }

    # 3. Print Strategy Comparison Table
    print("\n" + "=" * 95)
    print("📈 STRATEGY COMPARISON MATRIX (TODAY'S 183 INTRADAY BARS)")
    print("=" * 95)
    print(f"{'Strategy Architecture':<42} | {'Trades':<8} | {'Win%':<7} | {'Gross PnL':<11} | {'Fees':<8} | {'Net PnL':<11}")
    print("-" * 95)

    for k, res in results.items():
        m = res["metrics"]
        name = res["name"]
        t_count = f"{m['total_trades']}" if k in ("legacy_scalper", "ai_opportunity_radar") else f"{m['total_trades']}/{res['total_candidates']}"
        win_pct = f"{m['win_rate']:.1f}%"
        gross = f"₹{m['gross_profit'] - m['gross_loss']:+,.2f}"
        fees = f"₹{m['total_trades'] * 40:,.2f}"
        net = f"₹{m['net_pnl'] - (m['total_trades'] * 40):+,.2f}"
        print(f"{name:<42} | {t_count:<8} | {win_pct:<7} | {gross:<11} | {fees:<8} | {net:<11}")
    print("=" * 95)

    # 4. Detailed Trade Logs & AI Verdicts
    for k in ["legacy_scalper", "institutional_pullback", "ai_opportunity_radar"]:
        res = results[k]
        print(f"\n>>> DETAILED AUDIT FOR: {res['name']} <<<")
        if not res["approved"] and not res.get("vetoed"):
            print("  (No trades triggered or approved during this session)")
        for t in res["approved"]:
            v = getattr(t, "ai_verdict", None)
            conf = f" | AI Conf: {v.confidence_score}%" if v else ""
            setup = f" [{getattr(t, 'setup_type', '')}]" if getattr(t, 'setup_type', '') else ""
            print(f"  ✅ [EXECUTED]{setup} Trade #{t.trade_id}: {t.direction} {t.strike} @ {t.entry_time} -> Exit {t.exit_time} ({t.exit_reason}) | PnL: ₹{t.pnl:+,.2f} ({t.pnl_pct:+,.1f}%){conf}")
        for t in res.get("vetoed", []):
            v = t.ai_verdict
            trap = v.trap_detected or "VETO"
            print(f"  🚫 [VETOED BY AI] Trade #{t.trade_id}: {t.direction} {t.strike} @ {t.entry_time} | Trap: {trap} | Reason: {v.reasoning}")

if __name__ == "__main__":
    run()
