#!/usr/bin/env python3
"""
Capital Compounding Backtest for NIFTY 50 Options:
Simulates account growth starting from ₹10,000 baseline capital under:
1. Fixed 2-Lot Sizing (Static Reference)
2. Milestone Step-Ladder Compounding (Prudent Institutional)
3. Dynamic Proportional Compounding (Full Available Margin Reinvestment)

Audited across:
- Last 30 Sessions (Aug 31 - Oct 16, 2026)
- Full 60 Sessions (Summer Consolidation + Autumn Expansion)
Strategies compared:
- Strategy 4: AI Opportunity Radar (Active Engine)
- Strategy 3: Institutional Pullback (Backup Engine)
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
from typing import List, Dict, Tuple
from backtest_engine import BacktestEngine, StrategyConfig, HISTORICAL_DB_PATH, Trade
from ai_opportunity_radar import AIOpportunityRadar
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import run_ai_radar_simulation
from ai_context_dossier import generate_market_dossier

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

def get_all_trades_s4(dates: List[str], cfg: StrategyConfig, radar: AIOpportunityRadar, consultant: AIConsultant) -> List[Trade]:
    all_trades = []
    for d in dates:
        eng = BacktestEngine(d)
        if eng.spot_candles:
            t = run_ai_radar_simulation(eng, cfg, radar, consultant)
            for tr in t:
                tr.target_date = d
            all_trades.extend(t)
    return all_trades

def get_all_trades_s3(dates: List[str], cfg: StrategyConfig, consultant: AIConsultant) -> List[Trade]:
    all_trades = []
    for d in dates:
        eng = BacktestEngine(d)
        if eng.spot_candles:
            raw_trades = eng.run_simulation(cfg)
            approved = []
            for tr in raw_trades:
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
                v = consultant.evaluate(dossier)
                if v.is_approved:
                    tr.target_date = d
                    approved.append(tr)
            all_trades.extend(approved)
    return all_trades

def simulate_compounding(
    trades: List[Trade],
    starting_capital: float = 10000.0,
    mode: str = "dynamic_proportional", # "fixed_2l", "step_ladder", "dynamic_proportional"
    max_lots_cap: int = 10
) -> Dict:
    capital = starting_capital
    peak_capital = starting_capital
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    history = []
    skipped_trades = 0

    for i, t in enumerate(trades, 1):
        cost_per_lot = round(t.entry_price * 65.0, 2)
        if cost_per_lot <= 0:
            continue

        if mode == "fixed_2l":
            lots = 2
        elif mode == "step_ladder":
            # Milestone scaling:
            # < ₹20,000: 2 lots
            # ₹20,000 - ₹40,000: 4 lots
            # ₹40,000 - ₹70,000: 6 lots
            # ₹70,000 - ₹100,000: 8 lots
            # > ₹100,000: 10 lots (cap)
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
            # Sizing cannot exceed what current cash can afford
            max_affordable = int(max(0.0, capital - 150.0) // cost_per_lot)
            lots = min(target_lots, max_affordable)
        elif mode == "dynamic_proportional":
            # Deploy up to available cash with ₹150 buffer, capped at max_lots_cap
            safe_cash = max(0.0, capital - 150.0)
            lots = int(safe_cash // cost_per_lot)
            lots = min(lots, max_lots_cap)
        else:
            lots = 2

        if lots < 1:
            skipped_trades += 1
            history.append({
                "trade_idx": i,
                "date": t.target_date,
                "time": t.entry_time,
                "symbol": t.symbol,
                "entry_price": t.entry_price,
                "exit_price": t.exit_price,
                "gain_pct": 0.0,
                "lots": 0,
                "pnl": 0.0,
                "capital": capital,
                "skipped": True
            })
            continue

        # Points captured
        pts = t.exit_price - t.entry_price
        gain_pct = round((pts / t.entry_price) * 100.0, 2)

        # Statutory friction & fees: flat ₹40 brokerage + ₹25/lot statutory charges (STT, GST, turnover, stamp)
        fees = 40.0 + (lots * 25.0)
        pnl = round((pts * lots * 65.0) - fees, 2)

        capital = round(capital + pnl, 2)

        if capital > peak_capital:
            peak_capital = capital
        dd = peak_capital - capital
        dd_pct = (dd / peak_capital) * 100.0 if peak_capital > 0 else 0.0
        if dd > max_drawdown:
            max_drawdown = dd
        if dd_pct > max_drawdown_pct:
            max_drawdown_pct = dd_pct

        history.append({
            "trade_idx": i,
            "date": t.target_date,
            "time": t.entry_time,
            "symbol": t.symbol,
            "entry_price": t.entry_price,
            "exit_price": t.exit_price,
            "gain_pct": gain_pct,
            "lots": lots,
            "pnl": pnl,
            "capital": capital,
            "skipped": False
        })

    net_profit = round(capital - starting_capital, 2)
    roi_pct = round((net_profit / starting_capital) * 100.0, 1)

    return {
        "mode": mode,
        "starting_capital": starting_capital,
        "final_capital": capital,
        "net_profit": net_profit,
        "roi_pct": roi_pct,
        "max_drawdown": max_drawdown,
        "max_drawdown_pct": max_drawdown_pct,
        "skipped_trades": skipped_trades,
        "history": history
    }

def main():
    all_dates = get_session_dates()
    dates_30 = all_dates[-30:]
    dates_60 = all_dates[-60:] if len(all_dates) >= 60 else all_dates

    import argparse
    parser = argparse.ArgumentParser(description="Capital Compounding Audit")
    parser.add_argument("--enforce-live-envelope", action="store_true",
                        help="Enforce live order ₹15-₹70 premium cap from trading.json")
    args, _ = parser.parse_known_args()

    cfg_radar = StrategyConfig.load_from_config("ai_opportunity_radar")
    cfg_s3 = StrategyConfig.load_from_config("institutional_pullback")
    radar = AIOpportunityRadar()
    if args.enforce_live_envelope:
        consultant = AIConsultant(mode="playbook")
    else:
        consultant = AIConsultant(
            mode="playbook",
            trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
        )

    print("Fetching and executing trades for 30 and 60 sessions...")
    s4_trades_30 = get_all_trades_s4(dates_30, cfg_radar, radar, consultant)
    s4_trades_60 = get_all_trades_s4(dates_60, cfg_radar, radar, consultant)
    s3_trades_30 = get_all_trades_s3(dates_30, cfg_s3, consultant)
    s3_trades_60 = get_all_trades_s3(dates_60, cfg_s3, consultant)

    print("\n" + "=" * 105)
    print(" 🚀 CAPITAL COMPOUNDING AUDIT: 30 SESSIONS (AUG 31 - OCT 16, 2026)")
    print(f" Starting Baseline Capital: ₹10,000.00 | Total Trades Evaluated: {len(s4_trades_30)}")
    print("=" * 105)
    print(f"{'Sizing / Compounding Model':<35} | {'Strategy 3 (Baseline)':<30} | {'Strategy 4 (AI Radar)':<30}")
    print("-" * 105)

    # 1. Fixed 2 Lots
    c_s3_fixed = simulate_compounding(s3_trades_30, 10000.0, "fixed_2l")
    c_s4_fixed = simulate_compounding(s4_trades_30, 10000.0, "fixed_2l")
    print(f"{'1. Fixed 2 Lots (Static Base)':<35} | ₹{c_s3_fixed['final_capital']:>10,.2f} ({c_s3_fixed['roi_pct']:>+6.1f}% ROI) | ₹{c_s4_fixed['final_capital']:>10,.2f} ({c_s4_fixed['roi_pct']:>+6.1f}% ROI)")

    # 2. Step Ladder Compounding
    c_s3_ladder = simulate_compounding(s3_trades_30, 10000.0, "step_ladder", max_lots_cap=10)
    c_s4_ladder = simulate_compounding(s4_trades_30, 10000.0, "step_ladder", max_lots_cap=10)
    print(f"{'2. Step-Ladder (2->4->6->8->10 Lots)':<35} | ₹{c_s3_ladder['final_capital']:>10,.2f} ({c_s3_ladder['roi_pct']:>+6.1f}% ROI) | ₹{c_s4_ladder['final_capital']:>10,.2f} ({c_s4_ladder['roi_pct']:>+6.1f}% ROI)")

    # 3. Dynamic Proportional (Full Cash Capped at 10 Lots)
    c_s3_prop = simulate_compounding(s3_trades_30, 10000.0, "dynamic_proportional", max_lots_cap=10)
    c_s4_prop = simulate_compounding(s4_trades_30, 10000.0, "dynamic_proportional", max_lots_cap=10)
    print(f"{'3. Dynamic Full Cash (Max 10 Lots)':<35} | ₹{c_s3_prop['final_capital']:>10,.2f} ({c_s3_prop['roi_pct']:>+6.1f}% ROI) | ₹{c_s4_prop['final_capital']:>10,.2f} ({c_s4_prop['roi_pct']:>+6.1f}% ROI)")

    print("-" * 105)
    print(f"Max Drawdown (Step-Ladder):          | ₹{c_s3_ladder['max_drawdown']:>10,.2f} ({c_s3_ladder['max_drawdown_pct']:>5.1f}%)        | ₹{c_s4_ladder['max_drawdown']:>10,.2f} ({c_s4_ladder['max_drawdown_pct']:>5.1f}%)")
    print(f"Max Drawdown (Dynamic Full Cash):    | ₹{c_s3_prop['max_drawdown']:>10,.2f} ({c_s3_prop['max_drawdown_pct']:>5.1f}%)        | ₹{c_s4_prop['max_drawdown']:>10,.2f} ({c_s4_prop['max_drawdown_pct']:>5.1f}%)")
    print("=" * 105)

    # 60 Sessions
    print("\n" + "=" * 105)
    print(" 🚀 CAPITAL COMPOUNDING AUDIT: FULL 60 SESSIONS (JUNE - OCTOBER 2026)")
    print(f" Starting Baseline Capital: ₹10,000.00 | Total Trades: {len(s4_trades_60)}")
    print("=" * 105)
    print(f"{'Sizing / Compounding Model':<35} | {'Strategy 3 (Baseline)':<30} | {'Strategy 4 (AI Radar)':<30}")
    print("-" * 105)

    c60_s3_fixed = simulate_compounding(s3_trades_60, 10000.0, "fixed_2l")
    c60_s4_fixed = simulate_compounding(s4_trades_60, 10000.0, "fixed_2l")
    print(f"{'1. Fixed 2 Lots (Static Base)':<35} | ₹{c60_s3_fixed['final_capital']:>10,.2f} ({c60_s3_fixed['roi_pct']:>+6.1f}% ROI) | ₹{c60_s4_fixed['final_capital']:>10,.2f} ({c60_s4_fixed['roi_pct']:>+6.1f}% ROI)")

    c60_s3_ladder = simulate_compounding(s3_trades_60, 10000.0, "step_ladder", max_lots_cap=10)
    c60_s4_ladder = simulate_compounding(s4_trades_60, 10000.0, "step_ladder", max_lots_cap=10)
    print(f"{'2. Step-Ladder (2->4->6->8->10 Lots)':<35} | ₹{c60_s3_ladder['final_capital']:>10,.2f} ({c60_s3_ladder['roi_pct']:>+6.1f}% ROI) | ₹{c60_s4_ladder['final_capital']:>10,.2f} ({c60_s4_ladder['roi_pct']:>+6.1f}% ROI)")

    c60_s3_prop = simulate_compounding(s4_trades_60, 10000.0, "dynamic_proportional", max_lots_cap=10)
    c60_s4_prop = simulate_compounding(s4_trades_60, 10000.0, "dynamic_proportional", max_lots_cap=10)
    print(f"{'3. Dynamic Full Cash (Max 10 Lots)':<35} | ₹{c60_s3_prop['final_capital']:>10,.2f} ({c60_s3_prop['roi_pct']:>+6.1f}% ROI) | ₹{c60_s4_prop['final_capital']:>10,.2f} ({c60_s4_prop['roi_pct']:>+6.1f}% ROI)")
    print("=" * 105)

    # Let's inspect milestones in Strategy 4 30-session step-ladder compounding
    print("\n📈 MILESTONE ACCELERATION TRAJECTORY (Strategy 4 - Step-Ladder):")
    print(f"{'Trade':<6} | {'Date':<10} | {'Time':<8} | {'Direction':<4} | {'Gain%':<7} | {'Lots':<5} | {'Trade PnL':<12} | {'Account Balance'}")
    print("-" * 80)
    milestone_targets = [15000, 25000, 40000, 60000, 100000, 150000, 200000]
    m_idx = 0
    for h in c_s4_ladder["history"]:
        if h["skipped"]:
            continue
        curr_cap = h["capital"]
        if m_idx < len(milestone_targets) and curr_cap >= milestone_targets[m_idx]:
            print(f"#{h['trade_idx']:<5} | {h['date']:<10} | {h['time']:<8} | {h['symbol'][-2:]:<4} | {h['gain_pct']:>+5.1f}% | {h['lots']:>2} lts | ₹{h['pnl']:>+10.2f} | 🎯 ₹{curr_cap:>10,.2f} (Milestone: ₹{milestone_targets[m_idx]:,})")
            m_idx += 1
    # print final trade
    last_h = c_s4_ladder["history"][-1]
    print(f"#{last_h['trade_idx']:<5} | {last_h['date']:<10} | {last_h['time']:<8} | {last_h['symbol'][-2:]:<4} | {last_h['gain_pct']:>+5.1f}% | {last_h['lots']:>2} lts | ₹{last_h['pnl']:>+10.2f} | 🏆 ₹{last_h['capital']:>10,.2f} (FINAL)")

if __name__ == "__main__":
    main()
