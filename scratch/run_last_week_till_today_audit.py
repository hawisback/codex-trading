from trading.bootstrap import configure_console
configure_console()

import os
import sys
import json
from datetime import datetime
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import AIOpportunityRadar, run_ai_radar_simulation

# Date list for "last week till today"
dates = [
    ("2026-10-12", "Mon Oct 12"),
    ("2026-10-13", "Tue Oct 13 (0DTE)"),
    ("2026-10-14", "Wed Oct 14"),
    ("2026-10-15", "Thu Oct 15"),
    ("2026-10-16", "Fri Oct 16"),
    ("2026-10-19", "Mon Oct 19"),
    ("2026-10-21", "Wed Oct 21"),
    ("2026-10-22", "Thu Oct 22")
]

print("=" * 110)
print(" FORENSIC BACKTEST AUDIT: LAST WEEK TILL TODAY (OCT 12 - OCT 22, 2026)")
print(" Comparing Strategy 3 (Institutional Pullback) & Strategy 4 (AI Opportunity Radar)")
print(" Enforcing Rule #1: AI Gatekeeper & 8 Institutional Traps")
print("=" * 110)

# 1. Evaluate Strategy 3 (Institutional Pullback with AI Gatekeeper)
print("\n" + "=" * 110)
print(" 🛡️ STRATEGY 3: INSTITUTIONAL PULLBACK (AI GATEKEEPER ENABLED)")
print("=" * 110)

cfg_s3 = StrategyConfig.load_from_config("institutional_pullback")
ai_s3 = AIConsultant(
    mode="playbook",
    trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
)

s3_approved_all = []
s3_vetoed_all = []
s3_raw_all = []

for dt, label in dates:
    engine = BacktestEngine(target_date=dt)
    if not engine.spot_candles:
        print(f"Skipping {dt} ({label}): No candles found.")
        continue
    
    is_0dte = (datetime.strptime(dt, "%Y-%m-%d").weekday() == 1)
    raw_trades = engine.run_simulation(cfg_s3)
    s3_raw_all.extend(raw_trades)
    
    day_approved = []
    day_vetoed = []
    
    for trade in raw_trades:
        hist_candles = engine.spot_candles[:trade.entry_bar + 1]
        dossier = generate_market_dossier(
            target_date=dt,
            candles=hist_candles,
            current_bar_idx=len(hist_candles) - 1,
            direction=trade.direction,
            symbol=trade.symbol,
            strike=trade.strike,
            option_entry_price=trade.entry_price,
            trade_history=day_approved,
            days_to_expiry=engine.get_expiry_days(),
            is_expiry_0dte=is_0dte
        )
        verdict = ai_s3.evaluate(dossier)
        trade.ai_verdict = verdict
        if verdict.is_approved:
            day_approved.append(trade)
            s3_approved_all.append(trade)
        else:
            day_vetoed.append(trade)
            s3_vetoed_all.append(trade)
            
    m_day = calculate_metrics(day_approved)
    fee_day = len(day_approved) * 40.0
    net_1l = m_day["net_pnl"] - fee_day
    net_2l = (m_day["net_pnl"] * 2) - fee_day
    
    print(f"[{dt}] {label:<18} | Raw: {len(raw_trades):>2} | AI Approved: {len(day_approved):>2} | AI Vetoed: {len(day_vetoed):>2} | "
          f"Wins: {m_day['wins']:>2} | Losses: {m_day['losses']:>2} | WinRate: {m_day['win_rate']:>5.1f}% | "
          f"Net PnL (1L): ₹{net_1l:>9,.2f} | Net PnL (2L): ₹{net_2l:>9,.2f}")

m_s3 = calculate_metrics(s3_approved_all)
fee_s3 = len(s3_approved_all) * 40.0
net_s3_1l = m_s3["net_pnl"] - fee_s3
net_s3_2l = (m_s3["net_pnl"] * 2) - fee_s3

print("-" * 110)
print(f"STRATEGY 3 TOTALS: Approved Trades: {len(s3_approved_all)} / {len(s3_raw_all)} | "
      f"Win Rate: {m_s3['win_rate']:.1f}% ({m_s3['wins']}W / {m_s3['losses']}L) | "
      f"Net PnL (1 Lot): ₹{net_s3_1l:+,.2f} | Net PnL (2 Lots): ₹{net_s3_2l:+,.2f} | "
      f"ROI (2 Lots on ₹10k): {(net_s3_2l / 10000.0)*100:+.1f}% | Profit Factor: {m_s3['profit_factor']:.2f}")
print("=" * 110)

# 2. Evaluate Strategy 4 (AI Opportunity Radar)
print("\n" + "=" * 110)
print(" 🏆 STRATEGY 4: AI OPPORTUNITY RADAR (ACTIVE PRODUCTION ENGINE)")
print("=" * 110)

radar = AIOpportunityRadar()
ai_s4 = AIConsultant(
    mode="playbook",
    trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
)

s4_trades_all = []

for dt, label in dates:
    engine = BacktestEngine(target_date=dt)
    if not engine.spot_candles:
        continue
    day_trades = run_ai_radar_simulation(engine, cfg_s3, radar, ai_s4)
    s4_trades_all.extend(day_trades)
    
    m_day = calculate_metrics(day_trades)
    fee_day = len(day_trades) * 40.0
    net_1l = m_day["net_pnl"] - fee_day
    net_2l = (m_day["net_pnl"] * 2) - fee_day
    
    print(f"[{dt}] {label:<18} | Radar Trades: {len(day_trades):>2} | "
          f"Wins: {m_day['wins']:>2} | Losses: {m_day['losses']:>2} | WinRate: {m_day['win_rate']:>5.1f}% | "
          f"Net PnL (1L): ₹{net_1l:>9,.2f} | Net PnL (2L): ₹{net_2l:>9,.2f}")

m_s4 = calculate_metrics(s4_trades_all)
fee_s4 = len(s4_trades_all) * 40.0
net_s4_1l = m_s4["net_pnl"] - fee_s4
net_s4_2l = (m_s4["net_pnl"] * 2) - fee_s4

print("-" * 110)
print(f"STRATEGY 4 TOTALS: Total Trades: {len(s4_trades_all)} | "
      f"Win Rate: {m_s4['win_rate']:.1f}% ({m_s4['wins']}W / {m_s4['losses']}L) | "
      f"Net PnL (1 Lot): ₹{net_s4_1l:+,.2f} | Net PnL (2 Lots): ₹{net_s4_2l:+,.2f} | "
      f"ROI (2 Lots on ₹10k): {(net_s4_2l / 10000.0)*100:+.1f}% | Profit Factor: {m_s4['profit_factor']:.2f}")
print("=" * 110)
