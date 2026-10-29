import sys
import os
sys.path.insert(0, os.path.abspath("."))
import json
import glob
from dataclasses import dataclass
from typing import List, Dict, Any

from trading.bootstrap import configure_console
configure_console()

from backtest_engine import BacktestEngine, StrategyConfig, Trade
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import AIOpportunityRadar, run_ai_radar_simulation

def get_last_30_dates():
    spot_files = sorted(glob.glob("data/spot_candles_*.json"))
    dates = [os.path.basename(f).replace("spot_candles_", "").replace(".json", "") for f in spot_files]
    valid_dates = []
    for d in dates:
        path = f"data/spot_candles_{d}.json"
        if os.path.getsize(path) > 1000:
            with open(path, "r", encoding="utf-8") as f:
                candles = json.load(f)
            if len(candles) >= 100:
                valid_dates.append(f"{d[:4]}-{d[4:6]}-{d[6:]}")
    return valid_dates[-30:]

def main():
    dates = get_last_30_dates()
    print("=" * 105)
    print(f" 🚀 COMPREHENSIVE 30-DAY BACKTEST: AI OPPORTUNITY RADAR (STRATEGY 4)")
    print(f" Period: {dates[0]} to {dates[-1]} ({len(dates)} Verified Trading Days)")
    print(f" Includes Today: {dates[-1] == '2026-10-26'}")
    print("=" * 105)

    cfg = StrategyConfig.load_from_config("ai_opportunity_radar")
    radar = AIOpportunityRadar()
    consultant = AIConsultant(
        mode="rules",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    all_trades: List[Trade] = []
    session_summaries = []

    for d in dates:
        eng = BacktestEngine(d)
        if not eng.spot_candles:
            continue
        day_trades = run_ai_radar_simulation(eng, cfg, radar, consultant)
        all_trades.extend(day_trades)
        
        day_pnl_1l = sum(t.pnl for t in day_trades) - (len(day_trades) * 40.0 if day_trades else 0.0)
        day_w = sum(1 for t in day_trades if t.pnl > 0)
        day_l = sum(1 for t in day_trades if t.pnl <= 0)
        session_summaries.append({
            "date": d,
            "trades_count": len(day_trades),
            "wins": day_w,
            "losses": day_l,
            "pnl_1l": day_pnl_1l,
            "trades": day_trades
        })

    # Metrics calculation
    n = len(all_trades)
    w = sum(1 for t in all_trades if t.pnl > 0)
    l = sum(1 for t in all_trades if t.pnl <= 0)
    wr = (w / n * 100.0) if n else 0.0

    fee_per_trade = 40.0
    net_1l = sum(t.pnl for t in all_trades) - (n * fee_per_trade)
    net_2l = sum(t.pnl * 2 for t in all_trades) - (n * fee_per_trade)
    roi_2l = (net_2l / 10000.0) * 100.0

    w_sum = sum(t.pnl for t in all_trades if t.pnl > 0)
    l_sum = abs(sum(t.pnl for t in all_trades if t.pnl <= 0))
    pf = (w_sum / l_sum) if l_sum > 0 else 999.0

    # Step-Ladder Compounding Simulation (Rule #3 Model)
    # Starting Capital: ₹10,000
    capital = 10000.0
    peak_capital = capital
    max_drawdown = 0.0
    compounding_log = []

    for t in all_trades:
        # Sizing Tiers based on current capital
        if capital < 20000.0:
            lots = 2
        elif capital < 40000.0:
            lots = 4
        elif capital < 70000.0:
            lots = 6
        elif capital < 100000.0:
            lots = 8
        else:
            lots = 10  # Cap at 10 lots

        trade_pnl = (t.pnl * lots) - fee_per_trade
        capital += trade_pnl
        if capital > peak_capital:
            peak_capital = capital
        dd = peak_capital - capital
        if dd > max_drawdown:
            max_drawdown = dd
        
        compounding_log.append({
            "trade_id": t.trade_id,
            "date": t.entry_time[:10] if len(t.entry_time) >= 10 else "",
            "lots": lots,
            "trade_pnl": trade_pnl,
            "capital": capital
        })

    comp_roi = ((capital - 10000.0) / 10000.0) * 100.0
    max_dd_pct = (max_drawdown / peak_capital * 100.0) if peak_capital > 0 else 0.0

    print("\n" + "=" * 105)
    print(" 📊 EXECUTIVE AUDIT SUMMARY: 30 TRADING SESSIONS (SEP 10 - OCT 26, 2026)")
    print("=" * 105)
    print(f" {'Metric':<38} | {'Fixed 1 Lot':<18} | {'Fixed 2 Lots (₹10k)':<20} | {'Step-Ladder (2-10L)':<20}")
    print("-" * 105)
    print(f" {'Total Trades Taken':<38} | {n:<18} | {n:<20} | {n:<20}")
    print(f" {'Winning Trades':<38} | {w:<18} | {w:<20} | {w:<20}")
    print(f" {'Losing Trades':<38} | {l:<18} | {l:<20} | {l:<20}")
    print(f" {'Win Rate %':<38} | {wr:<17.1f}% | {wr:<19.1f}% | {wr:<19.1f}%")
    print(f" {'Profit Factor':<38} | {pf:<18.2f} | {pf:<20.2f} | {'—':<20}")
    print(f" {'Net Realized PnL':<38} | ₹{net_1l:<17,.2f} | ₹{net_2l:<19,.2f} | ₹{capital - 10000.0:<19,.2f}")
    print(f" {'Starting Capital':<38} | {'—':<18} | ₹10,000.00          | ₹10,000.00")
    print(f" {'Final Account Equity':<38} | {'—':<18} | ₹{10000.0 + net_2l:<19,.2f} | ₹{capital:<19,.2f}")
    print(f" {'Net ROI %':<38} | {'—':<18} | {roi_2l:>+18.1f}% | {comp_roi:>+18.1f}%")
    print(f" {'Max Compounding Drawdown':<38} | {'—':<18} | {'—':<20} | ₹{max_drawdown:,.2f} ({max_dd_pct:.1f}%)")
    print("=" * 105)

    # Weekly / Session breakdown
    print("\n📅 Weekly Session Breakdown:")
    print("-" * 75)
    print(f" {'Date':<14} | {'Trades':<8} | {'W / L':<10} | {'Day PnL (1L)':<16} | {'Trades Detail'}")
    print("-" * 75)
    for s in session_summaries:
        detail = ", ".join([f"{t.direction} {t.setup_type[:6]} ({t.pnl:+.0f})" for t in s["trades"]]) if s["trades"] else "No Trades (Cash)"
        print(f" {s['date']:<14} | {s['trades_count']:<8} | {s['wins']}W / {s['losses']}L   | ₹{s['pnl_1l']:>+12,.2f}  | {detail[:40]}")
    print("-" * 75)

if __name__ == "__main__":
    main()
