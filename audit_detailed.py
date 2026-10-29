import sqlite3
from typing import List, Dict
from backtest_engine import BacktestEngine, StrategyConfig, HISTORICAL_DB_PATH, Trade
from run_30_sessions_swing_audit import run_simulation_with_swings, compute_metrics, get_session_dates
from ai_consultant import AIConsultant

def audit_detailed():
    dates_30 = get_session_dates(30)
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
    dates_60 = all_dates[-60:] if len(all_dates) >= 60 else all_dates

    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
    consultant = AIConsultant(mode="playbook")

    print(f"--- 30-Session Run ({dates_30[0]} to {dates_30[-1]}) ---")
    trades_base_30 = []
    trades_climax_30 = []
    trades_flip_30 = []

    for d in dates_30:
        eng = BacktestEngine(d)
        if not eng.spot_candles:
            continue
        t_base = run_simulation_with_swings(eng, s3_cfg, consultant, False, False)
        trades_base_30.extend(t_base)

        t_climax = run_simulation_with_swings(eng, s3_cfg, consultant, True, False)
        trades_climax_30.extend(t_climax)

        t_flip = run_simulation_with_swings(eng, s3_cfg, consultant, False, True)
        trades_flip_30.extend(t_flip)

    m_base_30 = compute_metrics(trades_base_30)
    m_climax_30 = compute_metrics(trades_climax_30)
    m_flip_30 = compute_metrics(trades_flip_30)

    print("\n--- 60-Session Run ({dates_60[0]} to {dates_60[-1]}) ---")
    trades_base_60 = []
    trades_climax_60 = []

    for d in dates_60:
        eng = BacktestEngine(d)
        if not eng.spot_candles:
            continue
        t_base = run_simulation_with_swings(eng, s3_cfg, consultant, False, False)
        trades_base_60.extend(t_base)

        t_climax = run_simulation_with_swings(eng, s3_cfg, consultant, True, False)
        trades_climax_60.extend(t_climax)

    m_base_60 = compute_metrics(trades_base_60)
    m_climax_60 = compute_metrics(trades_climax_60)

    print("\n================== 30 SESSIONS COMPARISON ==================")
    print(f"{'Metric':<25} | {'Baseline Strategy 3':<20} | {'+ Climax Spring (Morning)':<26} | {'+ Failure Flip':<20}")
    print("-" * 100)
    print(f"{'Total Trades':<25} | {m_base_30['n']:<20} | {m_climax_30['n']:<26} | {m_flip_30['n']:<20}")
    print(f"{'Win Rate %':<25} | {m_base_30['wr']:<19.1f}% | {m_climax_30['wr']:<25.1f}% | {m_flip_30['wr']:<19.1f}%")
    print(f"{'Net PnL (1 Lot)':<25} | ₹{m_base_30['net_1l']:<19,.2f} | ₹{m_climax_30['net_1l']:<25,.2f} | ₹{m_flip_30['net_1l']:<19,.2f}")
    print(f"{'Net PnL (2 Lots / 10k)':<25} | ₹{m_base_30['net_2l']:<19,.2f} | ₹{m_climax_30['net_2l']:<25,.2f} | ₹{m_flip_30['net_2l']:<19,.2f}")
    print(f"{'Net ROI % (10k Margin)':<25} | {m_base_30['roi_2l']:>+18.1f}% | {m_climax_30['roi_2l']:>+24.1f}% | {m_flip_30['roi_2l']:>+18.1f}%")
    print(f"{'Profit Factor':<25} | {m_base_30['pf']:<20.2f} | {m_climax_30['pf']:<26.2f} | {m_flip_30['pf']:<20.2f}")

    print("\n================== 60 SESSIONS COMPARISON ==================")
    print(f"{'Metric':<25} | {'Baseline Strategy 3':<20} | {'+ Climax Spring (Morning)':<26}")
    print("-" * 75)
    print(f"{'Total Trades':<25} | {m_base_60['n']:<20} | {m_climax_60['n']:<26}")
    print(f"{'Win Rate %':<25} | {m_base_60['wr']:<19.1f}% | {m_climax_60['wr']:<25.1f}%")
    print(f"{'Net PnL (1 Lot)':<25} | ₹{m_base_60['net_1l']:<19,.2f} | ₹{m_climax_60['net_1l']:<25,.2f}")
    print(f"{'Net PnL (2 Lots / 10k)':<25} | ₹{m_base_60['net_2l']:<19,.2f} | ₹{m_climax_60['net_2l']:<25,.2f}")
    print(f"{'Net ROI % (10k Margin)':<25} | {m_base_60['roi_2l']:>+18.1f}% | {m_climax_60['roi_2l']:>+24.1f}%")
    print(f"{'Profit Factor':<25} | {m_base_60['pf']:<20.2f} | {m_climax_60['pf']:<26.2f}")

    # Inspect all Climax trades in 30 sessions
    print("\n================== ALL CLIMAX SPRING TRADES (30 SESSIONS) ==================")
    climax_trades = [t for t in trades_climax_30 if getattr(t, "setup_type", "") in ["CLIMAX_SPRING_BOTTOM", "CLIMAX_SPRING_TOP"]]
    for t in climax_trades:
        print(f"Date: {t.symbol[:16]} | Dir: {t.direction} | Time: {t.entry_time} | Entry: ₹{t.entry_price:.2f} | Exit: ₹{t.exit_price:.2f} | Peak: +{t.peak_gain_pct}% | PnL(1L): ₹{t.pnl:+.2f} | PnL(2L): ₹{t.pnl*2:+.2f} | Reason: {t.exit_reason}")

    # Inspect all Failure Flip trades in 30 sessions
    print("\n================== ALL FAILURE FLIP TRADES (30 SESSIONS) ==================")
    flip_trades = [t for t in trades_flip_30 if getattr(t, "setup_type", "") in ["FAILURE_FLIP_SHORT_SQUEEZE", "FAILURE_FLIP_LONG_LIQUIDATION"]]
    for t in flip_trades:
        print(f"Date: {t.symbol[:16]} | Dir: {t.direction} | Time: {t.entry_time} | Entry: ₹{t.entry_price:.2f} | Exit: ₹{t.exit_price:.2f} | Peak: +{t.peak_gain_pct}% | PnL(1L): ₹{t.pnl:+.2f} | PnL(2L): ₹{t.pnl*2:+.2f} | Reason: {t.exit_reason}")

if __name__ == "__main__":
    audit_detailed()
