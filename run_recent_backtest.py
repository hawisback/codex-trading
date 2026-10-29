#!/usr/bin/env python3
"""
Forensic Backtest Audit: Last Week Till Today
Covers recent trading sessions up to yesterday's close (Oct 12 to Oct 22, 2026).
Compares:
1. Strategy 1 (Legacy Scalper - Mechanical Baseline)
2. Strategy 3 (Institutional Pullback - AI Gatekeeper)
3. Strategy 4 (AI Opportunity Radar - Active Engine + AI Gatekeeper)
With Fixed 2 Lots and Dynamic Step-Ladder Milestone Compounding.
"""

import os
import sys
import json
import argparse
import sqlite3
from datetime import datetime
from typing import List, Dict

from trading.bootstrap import configure_console
configure_console()

from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics, HISTORICAL_DB_PATH, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import AIOpportunityRadar, run_ai_radar_simulation

DEFAULT_START = "2026-10-12"
DEFAULT_END = "2026-10-22"

def get_available_dates(start_date: str, end_date: str) -> List[str]:
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    query = """
        SELECT DISTINCT substr(start_time, 1, 10) as dt
        FROM historical_candles
        WHERE instrument_id = 'INST-NIFTY-INDEX' AND interval = '1m'
          AND start_time >= ? AND start_time <= ?
        ORDER BY dt ASC
    """
    rows = [r[0] for r in conn.execute(query, (f"{start_date}T00:00:00", f"{end_date}T23:59:59")).fetchall()]
    conn.close()
    return rows

def simulate_step_ladder(trades: List[Trade], start_capital: float = 10000.0) -> Dict:
    capital = start_capital
    fee_per_trade = 40.0
    compounded_trades = []
    
    for t in trades:
        # Determine target lots based on verified margin milestone brackets
        if capital < 20000.0:
            target_lots = 2
        elif capital < 40000.0:
            target_lots = 4
        elif capital < 70000.0:
            target_lots = 6
        elif capital < 100000.0:
            target_lots = 8
        else:
            target_lots = 10
            
        # Zero-shortfall purchasing power check (minus ₹150 buffer for fees/STT)
        safe_cash = max(0.0, capital - 150.0)
        cost_per_lot = t.entry_price * 65.0
        if cost_per_lot > 0:
            affordable_lots = int(safe_cash // cost_per_lot)
            active_lots = max(1, min(target_lots, affordable_lots))
        else:
            active_lots = target_lots
            
        qty = active_lots * 65
        gross_pnl = (t.exit_price - t.entry_price) * qty
        net_pnl = gross_pnl - fee_per_trade
        capital_before = capital
        capital += net_pnl
        
        compounded_trades.append({
            "trade": t,
            "lots": active_lots,
            "qty": qty,
            "net_pnl": net_pnl,
            "capital_after": capital
        })
        
    return {
        "start_capital": start_capital,
        "end_capital": capital,
        "net_growth": capital - start_capital,
        "roi_pct": ((capital - start_capital) / start_capital) * 100.0,
        "trade_log": compounded_trades
    }

def run_backtest(start_date: str = DEFAULT_START, end_date: str = DEFAULT_END, verbose: bool = False):
    dates = get_available_dates(start_date, end_date)
    if not dates:
        print(f"No market data found for {start_date} to {end_date}.")
        return

    print("=" * 115)
    print(f" 📈 FORENSIC BACKTEST: LAST WEEK TILL TODAY ({dates[0]} to {dates[-1]})")
    print(f" Auditing {len(dates)} Trading Sessions | Rule #1 AI Risk Gatekeeper Enforced")
    print("=" * 115)

    # 1. Strategy 1: Legacy Scalper (Mechanical, Zero AI - Benchmark for comparison)
    s1_cfg = StrategyConfig.load_from_config("legacy_scalper")
    s1_trades = []
    for d in dates:
        eng = BacktestEngine(target_date=d)
        if eng.spot_candles:
            s1_trades.extend(eng.run_simulation(s1_cfg))
    m_s1 = calculate_metrics(s1_trades)
    fee_s1 = len(s1_trades) * 40.0
    net_s1_2l = (m_s1["net_pnl"] * 2) - fee_s1
    roi_s1_2l = (net_s1_2l / 10000.0) * 100.0

    # 2. Strategy 3: Institutional Pullback (with AI Gatekeeper)
    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
    ai_consultant = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )
    s3_approved = []
    s3_vetoed = []
    for d in dates:
        eng = BacktestEngine(target_date=d)
        if not eng.spot_candles:
            continue
        is_0dte = (datetime.strptime(d, "%Y-%m-%d").weekday() == 1)
        raw_trades = eng.run_simulation(s3_cfg)
        day_approved = []
        for t in raw_trades:
            hist_candles = eng.spot_candles[:t.entry_bar + 1]
            dossier = generate_market_dossier(
                target_date=d,
                candles=hist_candles,
                current_bar_idx=len(hist_candles) - 1,
                direction=t.direction,
                symbol=t.symbol,
                strike=t.strike,
                option_entry_price=t.entry_price,
                trade_history=day_approved,
                days_to_expiry=eng.get_expiry_days(),
                is_expiry_0dte=is_0dte
            )
            verdict = ai_consultant.evaluate(dossier)
            t.ai_verdict = verdict
            if verdict.is_approved:
                day_approved.append(t)
                s3_approved.append(t)
            else:
                s3_vetoed.append(t)
    m_s3 = calculate_metrics(s3_approved)
    fee_s3 = len(s3_approved) * 40.0
    net_s3_2l = (m_s3["net_pnl"] * 2) - fee_s3
    roi_s3_2l = (net_s3_2l / 10000.0) * 100.0

    # 3. Strategy 4: AI Opportunity Radar (Active Engine)
    radar = AIOpportunityRadar()
    s4_trades = []
    for d in dates:
        eng = BacktestEngine(target_date=d)
        if not eng.spot_candles:
            continue
        trades = run_ai_radar_simulation(eng, s3_cfg, radar, ai_consultant)
        for t in trades:
            t.target_date = d
        s4_trades.extend(trades)
    m_s4 = calculate_metrics(s4_trades)
    fee_s4 = len(s4_trades) * 40.0
    net_s4_2l = (m_s4["net_pnl"] * 2) - fee_s4
    roi_s4_2l = (net_s4_2l / 10000.0) * 100.0

    # Step-Ladder Compounding on Strategy 4
    comp_s4 = simulate_step_ladder(s4_trades, start_capital=10000.0)

    # Print Comparative Matrix
    print(f"\n{'Configuration':<44} | {'Trades':<8} | {'Win Rate':<10} | {'Net PnL (₹10k Start)':<22} | {'Net ROI %':<12} | {'Profit Factor':<13}")
    print("-" * 115)
    print(f"{'Strategy 1: Mechanical Scalper (No AI)':<44} | {m_s1['total_trades']:<8} | {m_s1['win_rate']:<9.1f}% | ₹{net_s1_2l:<21,.2f} | {roi_s1_2l:>+10.1f}% | {m_s1['profit_factor']:.2f}")
    print(f"{'Strategy 3: Institutional Pullback (AI Gate)':<44} | {m_s3['total_trades']:<8} | {m_s3['win_rate']:<9.1f}% | ₹{net_s3_2l:<21,.2f} | {roi_s3_2l:>+10.1f}% | {m_s3['profit_factor']:.2f}")
    print(f"{'Strategy 4: AI Radar Active (Fixed 2 Lots)':<44} | {m_s4['total_trades']:<8} | {m_s4['win_rate']:<9.1f}% | ₹{net_s4_2l:<21,.2f} | {roi_s4_2l:>+10.1f}% | {m_s4['profit_factor']:.2f}")
    print(f"{'Strategy 4: AI Radar (Step-Ladder Compounding)':<44} | {len(s4_trades):<8} | {m_s4['win_rate']:<9.1f}% | ₹{comp_s4['net_growth']:<21,.2f} | {comp_s4['roi_pct']:>+10.1f}% | {m_s4['profit_factor']:.2f}")
    print("=" * 115)

    print("\n📅 Session-by-Session Breakdown (Strategy 4: AI Opportunity Radar):")
    for d in dates:
        day_t = [t for t in s4_trades if getattr(t, "target_date", "") == d]
        w = len([t for t in day_t if t.pnl > 0])
        l = len([t for t in day_t if t.pnl <= 0])
        pnl_2l = sum(t.pnl * 2 for t in day_t) - len(day_t) * 40.0
        dt_obj = datetime.strptime(d, "%Y-%m-%d")
        weekday = dt_obj.strftime("%A")
        print(f"  • {d} ({weekday:<9}): {len(day_t):>2} trades | {w}W / {l}L | Net PnL (2L): ₹{pnl_2l:>+10,.2f}")
        if verbose:
            for t in day_t:
                reg = getattr(t, "setup_type", "TREND_PULLBACK")
                print(f"      - {t.entry_time} {t.direction} {t.symbol} ({reg}) | Entry: ₹{t.entry_price:.2f} -> Exit: ₹{t.exit_price:.2f} ({t.exit_reason}) | PnL: ₹{t.pnl*2:+,.2f}")

    print(f"\n💡 Summary: Starting with ₹10,000, Strategy 4 grew the account to ₹{comp_s4['end_capital']:,.2f} (+₹{comp_s4['net_growth']:,.2f} / {comp_s4['roi_pct']:+.1f}%).")

def main():
    parser = argparse.ArgumentParser(description="Run recent backtest for last week till today")
    parser.add_argument("--start-date", default=DEFAULT_START, help=f"Start date YYYY-MM-DD (default: {DEFAULT_START})")
    parser.add_argument("--end-date", default=DEFAULT_END, help=f"End date YYYY-MM-DD (default: {DEFAULT_END})")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print detailed individual trade entries")
    args = parser.parse_args()
    run_backtest(args.start_date, args.end_date, args.verbose)

if __name__ == "__main__":
    main()
