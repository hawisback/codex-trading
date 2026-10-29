from trading.bootstrap import configure_console
configure_console()

import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import AIOpportunityRadar, run_ai_radar_simulation

cfg = StrategyConfig.load_from_config("institutional_pullback")
radar = AIOpportunityRadar()
ai = AIConsultant(
    mode="playbook",
    trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
)

print("=" * 110)
print(" FORENSIC DRILL-DOWN: THE LAST 2 DAYS (OCT 21 & OCT 22) - LOSS ANALYSIS")
print("=" * 110)

for dt in ["2026-10-21", "2026-10-22"]:
    eng = BacktestEngine(target_date=dt)
    trades = run_ai_radar_simulation(eng, cfg, radar, ai)
    print(f"\n--- {dt} ({len(trades)} Trades Taken) ---")
    for t in trades:
        res = "WIN" if t.pnl > 0 else "LOSS"
        print(f"  [{res}] #{t.trade_id} {t.entry_time} {t.direction} {t.symbol} | Setup: {getattr(t, 'setup_type', 'PULLBACK')} | "
              f"Entry: ₹{t.entry_price:.2f} -> Exit: ₹{t.exit_price:.2f} ({t.exit_reason}) | PnL (2L): ₹{t.pnl*2:+,.2f} ({t.pnl_pct:+.1f}%)")

