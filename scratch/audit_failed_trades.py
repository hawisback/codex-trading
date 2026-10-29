#!/usr/bin/env python3
"""
Forensic Audit of All Failed Trades:
Analyzes every losing trade across 30 and 60 sessions under:
1. Strategy 4 (AI Opportunity Radar & Dynamic Swings)
2. Strategy 3 (Institutional Pullback & ITM)
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from typing import List, Dict
from backtest_engine import BacktestEngine, StrategyConfig, HISTORICAL_DB_PATH, Trade
from ai_opportunity_radar import AIOpportunityRadar
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import run_ai_radar_simulation

def get_session_dates():
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT substr(start_time, 1, 10) "
        "FROM historical_candles "
        "WHERE instrument_id = 'INST-NIFTY-INDEX' AND start_time LIKE '%+00:00' "
        "ORDER BY 1"
    )
    all_dates = [r[0] for r in c.fetchall()]
    conn.close()
    return all_dates

def main():
    all_dates = get_session_dates()
    dates_30 = all_dates[-30:]
    dates_60 = all_dates[-60:] if len(all_dates) >= 60 else all_dates

    cfg_radar = StrategyConfig.load_from_config("ai_opportunity_radar")
    cfg_s3 = StrategyConfig.load_from_config("institutional_pullback")
    radar = AIOpportunityRadar()
    consultant = AIConsultant(mode="playbook")

    print("Running simulations across 30 and 60 sessions...")
    
    # 1. Collect all Strategy 4 trades across 30 sessions
    s4_trades_30: List[Trade] = []
    for d in dates_30:
        eng = BacktestEngine(d)
        if eng.spot_candles:
            t = run_ai_radar_simulation(eng, cfg_radar, radar, consultant)
            for tr in t:
                tr.target_date = d
            s4_trades_30.extend(t)

    # 2. Collect all Strategy 4 trades across 60 sessions
    s4_trades_60: List[Trade] = []
    for d in dates_60:
        eng = BacktestEngine(d)
        if eng.spot_candles:
            t = run_ai_radar_simulation(eng, cfg_radar, radar, consultant)
            for tr in t:
                tr.target_date = d
            s4_trades_60.extend(t)

    # 3. Collect Strategy 3 trades across 30 sessions
    s3_trades_30: List[Trade] = []
    for d in dates_30:
        eng = BacktestEngine(d)
        if eng.spot_candles:
            t = eng.run_simulation(cfg_s3)
            # Filter through AI consultant
            approved = []
            for tr in t:
                # generate dossier check
                from ai_context_dossier import generate_market_dossier
                dossier = generate_market_dossier(
                    target_date=d,
                    candles=eng.spot_candles,
                    current_bar_idx=tr.entry_bar,
                    direction=tr.direction,
                    symbol=tr.symbol,
                    strike=tr.strike,
                    option_entry_price=tr.entry_price,
                    trade_history=approved,
                    days_to_expiry=eng.get_expiry_days(),
                    is_expiry_0dte=(eng.get_expiry_days() <= 0.2)
                )
                verdict = consultant.evaluate(dossier)
                if verdict.is_approved:
                    tr.target_date = d
                    approved.append(tr)
            s3_trades_30.extend(approved)

    # Filter losing trades
    s4_losses_30 = [t for t in s4_trades_30 if (t.pnl or 0) <= 0]
    s4_losses_60 = [t for t in s4_trades_60 if (t.pnl or 0) <= 0]
    s3_losses_30 = [t for t in s3_trades_30 if (t.pnl or 0) <= 0]

    print("\n" + "=" * 115)
    print(f" 🔍 STRATEGY 4 (AI OPPORTUNITY RADAR): ALL LOSING TRADES IN LAST 30 SESSIONS ({len(s4_losses_30)} Losses / {len(s4_trades_30)} Trades)")
    print("=" * 115)
    print(f"{'#':<3} | {'Date':<10} | {'Time':<8} | {'Contract':<22} | {'Entry':<7} | {'Exit':<7} | {'Peak%':<6} | {'Loss (1L)':<10} | {'Loss (2L)':<10} | {'Exit Reason':<30}")
    print("-" * 115)

    loss_categories = {}

    for i, t in enumerate(s4_losses_30, 1):
        pnl_1l = t.pnl or 0.0
        pnl_2l = pnl_1l * 2.0
        reason = t.exit_reason or "UNKNOWN"
        # Categorize
        cat = "Initial Stop (-30%)"
        if "STRUCTURAL_WICK" in reason:
            cat = "Structural Wick Invalidation (-6% to -8%)"
        elif "MICRO_TRAIL" in reason or "TRAILING" in reason:
            cat = "Trailing Giveback (Scratch / Small Loss)"
        elif "EOD" in reason:
            cat = "EOD Square-off"
        loss_categories[cat] = loss_categories.get(cat, 0) + 1

        print(f"{i:<3} | {t.target_date:<10} | {t.entry_time:<8} | {t.symbol:<22} | ₹{t.entry_price:<6.2f} | ₹{t.exit_price:<6.2f} | {t.peak_gain_pct:>+5.1f}% | ₹{pnl_1l:>8.2f} | ₹{pnl_2l:>8.2f} | {reason[:30]:<30}")

    print("-" * 115)
    total_loss_1l = sum(t.pnl for t in s4_losses_30)
    total_loss_2l = total_loss_1l * 2
    avg_loss_2l = total_loss_2l / len(s4_losses_30) if s4_losses_30 else 0
    print(f"TOTAL LOSS (30 Sessions): ₹{total_loss_1l:,.2f} (1 Lot) | ₹{total_loss_2l:,.2f} (2 Lots) | Avg Loss / Trade: ₹{avg_loss_2l:,.2f}")
    print(f"Loss Breakdown by Mechanism: {loss_categories}")

    # Now let's see additional losses in the 60 session audit (i.e. June - August Summer Consolidation)
    older_losses = [t for t in s4_losses_60 if t.target_date not in dates_30]
    print("\n" + "=" * 115)
    print(f" 🔍 STRATEGY 4: ADDITIONAL LOSING TRADES IN SESSIONS 31-60 (Summer Consolidation: {len(older_losses)} Losses)")
    print("=" * 115)
    print(f"{'#':<3} | {'Date':<10} | {'Time':<8} | {'Contract':<22} | {'Entry':<7} | {'Exit':<7} | {'Peak%':<6} | {'Loss (1L)':<10} | {'Loss (2L)':<10} | {'Exit Reason':<30}")
    print("-" * 115)

    older_categories = {}
    for i, t in enumerate(older_losses, 1):
        pnl_1l = t.pnl or 0.0
        pnl_2l = pnl_1l * 2.0
        reason = t.exit_reason or "UNKNOWN"
        cat = "Initial Stop (-30%)"
        if "STRUCTURAL_WICK" in reason:
            cat = "Structural Wick Invalidation (-6% to -8%)"
        elif "MICRO_TRAIL" in reason or "TRAILING" in reason:
            cat = "Trailing Giveback (Scratch / Small Loss)"
        elif "EOD" in reason:
            cat = "EOD Square-off"
        older_categories[cat] = older_categories.get(cat, 0) + 1
        print(f"{i:<3} | {t.target_date:<10} | {t.entry_time:<8} | {t.symbol:<22} | ₹{t.entry_price:<6.2f} | ₹{t.exit_price:<6.2f} | {t.peak_gain_pct:>+5.1f}% | ₹{pnl_1l:>8.2f} | ₹{pnl_2l:>8.2f} | {reason[:30]:<30}")

    print("-" * 115)
    older_loss_1l = sum(t.pnl for t in older_losses)
    older_loss_2l = older_loss_1l * 2
    print(f"SUMMER REGIME LOSS: ₹{older_loss_1l:,.2f} (1 Lot) | ₹{older_loss_2l:,.2f} (2 Lots)")
    print(f"Summer Loss Breakdown: {older_categories}")

if __name__ == "__main__":
    main()
