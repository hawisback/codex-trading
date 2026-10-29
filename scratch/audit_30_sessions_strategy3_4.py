#!/usr/bin/env python3
"""
Full 30-Session Forensic Audit: Strategy 3 (Institutional Pullback) vs Strategy 4 (Radar)
Period: 2026-09-11 to 2026-10-27 (30 Sessions)
"""

import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")

from trading.bootstrap import configure_console
configure_console()

import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict

DATES = [
    "2026-09-11", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
    "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-05",
    "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12",
    "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19",
    "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"
]

def run_30_session_audit(strategy_key: str):
    cfg = StrategyConfig.load_from_config(strategy_key)
    c_prod = AIConsultant(mode="rules")
    
    all_approved_trades = []
    total_raw_trades = 0
    total_vetoed = 0
    
    for dt_str in DATES:
        try:
            eng = BacktestEngine(dt_str)
            raw = eng.run_simulation(cfg)
            dte = eng.get_expiry_days()
            is_0dte = (dte <= 0.2)
            
            total_raw_trades += len(raw)
            app = []
            for i, t in enumerate(raw, 1):
                matches = [k for k, x in enumerate(eng.spot_candles) if t.entry_time in x["start_time"]]
                if not matches:
                    continue
                idx = matches[0]
                dos = generate_market_dossier(
                    dt_str, eng.spot_candles, idx, t.direction, t.symbol, t.strike,
                    t.entry_price, raw[:i-1], dte, is_0dte
                )
                verdict = c_prod.evaluate(dos)
                if verdict.is_approved:
                    app.append(t)
                else:
                    total_vetoed += 1
            all_approved_trades.extend(app)
        except Exception as e:
            continue
            
    m = calculate_metrics(all_approved_trades)
    fric = len(all_approved_trades) * 40.0
    net1 = m["net_pnl"] - fric
    net2 = (m["net_pnl"] * 2) - fric
    
    print("=" * 105)
    print(f" 🏆 30-SESSION AUDIT: {cfg.name}")
    print("=" * 105)
    print(f" Total Raw Setups Proposed:               {total_raw_trades}")
    print(f" Vetoed by AI Risk Gatekeeper:            {total_vetoed} ({(total_vetoed/total_raw_trades*100.0 if total_raw_trades else 0):.1f}%)")
    print(f" Total Approved & Executed Trades:        {len(all_approved_trades)} (averaging {len(all_approved_trades)/30:.1f} trades/day)")
    print(f" Winning Trades:                          {m['wins']} / {len(all_approved_trades)} ({m['win_rate']:.1f}% Win Rate)")
    print(f" Losing Trades:                           {m['losses']} / {len(all_approved_trades)}")
    print(f" Profit Factor:                           {m.get('profit_factor', 0.0):.2f}")
    print(f" Net Realized PnL (Fixed 1 Lot):          Rs {net1:+,.2f}")
    print(f" Net Realized PnL (Fixed 2 Lots / 10k):   Rs {net2:+,.2f} (+{net2/10000*100.0:,.1f}% ROI)")
    print("=" * 105)

if __name__ == "__main__":
    print("\nAuditing Strategy 3 (Institutional Pullback)...")
    run_30_session_audit("institutional_pullback")
    print("\nAuditing Strategy 4 (AI Opportunity Radar)...")
    run_30_session_audit("ai_opportunity_radar")
