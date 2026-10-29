import sys
import os
sys.path.insert(0, os.path.abspath("."))

from trading.bootstrap import configure_console
configure_console()

from backtest_engine import BacktestEngine, StrategyConfig
from ai_consultant import AIConsultant
from backtest_ai_opportunity_radar import AIOpportunityRadar, run_ai_radar_simulation, compute_metrics

engine = BacktestEngine("2026-10-26")
print(f"Loaded {len(engine.spot_candles)} spot candles for today.")

cfg = StrategyConfig.load_from_config("ai_opportunity_radar")
radar = AIOpportunityRadar()
consultant = AIConsultant(
    mode="rules",
    trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
)

trades = run_ai_radar_simulation(engine, cfg, radar, consultant)
print(f"\nTotal Trades Generated for Today: {len(trades)}")
for t in trades:
    print(f"\nTrade #{t.trade_id}: {t.direction} {t.strike} ({getattr(t, 'setup_type', '')})")
    print(f"  Entry: {t.entry_time} @ ₹{t.entry_price:.2f}")
    print(f"  Exit:  {t.exit_time} @ ₹{t.exit_price:.2f} ({t.exit_reason})")
    print(f"  Peak Gain: +{t.peak_gain_pct:.1f}% | PnL (1 Lot): ₹{t.pnl:+.2f}")

metrics = compute_metrics(trades)
print("\n" + "=" * 60)
print(f"Win Rate: {metrics['wr']:.1f}% ({metrics['w']}W / {metrics['l']}L)")
print(f"Net PnL (1 Lot / 65 Qty): ₹{metrics['net_1l']:+,.2f}")
print("=" * 60)
