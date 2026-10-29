from trading.bootstrap import configure_console
configure_console()

from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

target_date = "2026-10-22"
engine = BacktestEngine(target_date=target_date)
cfg = StrategyConfig.load_from_config("ai_opportunity_radar")
ai_consultant = AIConsultant(mode="playbook")

raw_trades = engine.run_simulation(cfg)
print(f"Total raw trades generated on {target_date}: {len(raw_trades)}")

approved = []
vetoed = []

for idx, trade in enumerate(raw_trades, 1):
    hist_candles = engine.spot_candles[:trade.entry_bar + 1]
    dossier = generate_market_dossier(
        target_date=target_date,
        candles=hist_candles,
        current_bar_idx=len(hist_candles) - 1,
        direction=trade.direction,
        symbol=trade.symbol,
        strike=trade.strike,
        option_entry_price=trade.entry_price,
        trade_history=approved,
        days_to_expiry=engine.get_expiry_days(),
        is_expiry_0dte=False
    )
    verdict = ai_consultant.evaluate(dossier)
    trade.ai_verdict = verdict
    if verdict.is_approved:
        approved.append(trade)
        print(f"APPROVED Trade #{trade.trade_id}: {trade.direction} @ {trade.entry_time} -> PnL: ₹{trade.pnl:+,.2f} ({trade.exit_reason})")
    else:
        vetoed.append(trade)
        print(f"VETOED   Trade #{trade.trade_id}: {trade.direction} @ {trade.entry_time} | Trap: {verdict.trap_detected} | Raw PnL would have been: ₹{trade.pnl:+,.2f} | Reason: {verdict.reasoning[:70]}")

m_raw = calculate_metrics(raw_trades)
m_app = calculate_metrics(approved)
print("\n--- Summary ---")
print(f"Raw Trades: {len(raw_trades)} | Net PnL: ₹{m_raw['net_pnl'] - len(raw_trades)*40:,.2f} | Win Rate: {m_raw['win_rate']:.1f}%")
print(f"AI Approved: {len(approved)} | Net PnL: ₹{m_app['net_pnl'] - len(approved)*40:,.2f} | Win Rate: {m_app['win_rate']:.1f}%")
