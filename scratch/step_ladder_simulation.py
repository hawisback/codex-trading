from trading.bootstrap import configure_console
configure_console()

import os
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import AIOpportunityRadar, run_ai_radar_simulation

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

cfg_s3 = StrategyConfig.load_from_config("institutional_pullback")
radar = AIOpportunityRadar()
ai_s4 = AIConsultant(
    mode="playbook",
    trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
)

all_trades = []
for dt, label in dates:
    eng = BacktestEngine(target_date=dt)
    if not eng.spot_candles:
        continue
    trades = run_ai_radar_simulation(eng, cfg_s3, radar, ai_s4)
    for t in trades:
        t.date_str = dt
        t.day_label = label
    all_trades.extend(trades)

print(f"Total trades collected: {len(all_trades)}")

# Step-Ladder Compounding Simulation
START_CAPITAL = 10000.0
current_capital = START_CAPITAL
FEE_PER_LOT_TRADE = 40.0 # Brokerage & STT

def get_ladder_lots(capital, contract_price):
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
    
    # Zero-shortfall purchasing power check (minus 150 buffer)
    safe_cash = max(0.0, capital - 150.0)
    cost_per_lot = contract_price * 65.0
    if cost_per_lot > 0:
        affordable_lots = int(safe_cash // cost_per_lot)
        return max(1, min(target_lots, affordable_lots))
    return target_lots

trade_log = []
for idx, t in enumerate(all_trades, 1):
    active_lots = get_ladder_lots(current_capital, t.entry_price)
    qty = active_lots * 65
    gross_pnl = (t.exit_price - t.entry_price) * qty
    fee = FEE_PER_LOT_TRADE
    net_pnl = gross_pnl - fee
    start_cap = current_capital
    current_capital += net_pnl
    
    trade_log.append({
        "num": idx,
        "date": t.date_str,
        "time": t.entry_time,
        "symbol": t.symbol,
        "direction": t.direction,
        "regime": getattr(t, "setup_type", "TREND_PULLBACK"),
        "entry": t.entry_price,
        "exit": t.exit_price,
        "lots": active_lots,
        "qty": qty,
        "gross": gross_pnl,
        "net": net_pnl,
        "capital_before": start_cap,
        "capital_after": current_capital,
        "reason": t.exit_reason
    })

print("\n" + "=" * 130)
print(f"{'#':<3} | {'Date':<10} | {'Time':<8} | {'Type':<4} | {'Regime':<15} | {'Lots':<4} | {'Entry':<7} | {'Exit':<7} | {'Net PnL (₹)':<12} | {'Account Capital (₹)':<18} | {'Exit Reason':<30}")
print("=" * 130)

for r in trade_log:
    print(f"{r['num']:<3} | {r['date']:<10} | {r['time']:<8} | {r['direction']:<4} | {r['regime']:<15} | {r['lots']:<4} | {r['entry']:<7.2f} | {r['exit']:<7.2f} | {r['net']:>+12,.2f} | ₹{r['capital_after']:>16,.2f} | {r['reason']:<30}")

print("=" * 130)
print(f"Starting Capital:   ₹{START_CAPITAL:,.2f}")
print(f"Ending Capital:     ₹{current_capital:,.2f}")
print(f"Net Growth:         ₹{current_capital - START_CAPITAL:+,.2f}")
print(f"Compounded ROI:     {((current_capital - START_CAPITAL) / START_CAPITAL) * 100:+.1f}%")
print("=" * 130)
