import sys
import os

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from scratch.test_hybrid_spot_trailing import HybridSpotTrailingEngine
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics

dates = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-14", "2026-10-15"]
cfg = StrategyConfig.load_from_config("institutional_pullback")

print("=" * 105)
print(f"{'Date':<12} | {'Baseline Strategy 3 (10% Option Trail)':<40} | {'Hybrid Spot EMA20 Trailing':<40}")
print(f"{'':<12} | {'Trades':<8} {'Win%':<8} {'P&L (₹)':<12} {'MaxWin':<10} | {'Trades':<8} {'Win%':<8} {'P&L (₹)':<12} {'MaxWin':<10}")
print("=" * 105)

total_base_pnl = 0.0
total_hyb_pnl = 0.0
total_base_trades = 0
total_hyb_trades = 0

for d in dates:
    eng_base = BacktestEngine(d)
    eng_hyb = HybridSpotTrailingEngine(d, "ema20")

    t_base = eng_base.run_simulation(cfg)
    t_hyb = eng_hyb.run_simulation(cfg)

    m_base = calculate_metrics(t_base)
    m_hyb = calculate_metrics(t_hyb)

    total_base_pnl += m_base["net_pnl"]
    total_hyb_pnl += m_hyb["net_pnl"]
    total_base_trades += m_base["total_trades"]
    total_hyb_trades += m_hyb["total_trades"]

    base_str = f"{m_base['total_trades']:<8} {m_base['win_rate']:<8.1f}% ₹{m_base['net_pnl']:<11,.2f} ₹{m_base['max_win']:<9,.2f}"
    hyb_str = f"{m_hyb['total_trades']:<8} {m_hyb['win_rate']:<8.1f}% ₹{m_hyb['net_pnl']:<11,.2f} ₹{m_hyb['max_win']:<9,.2f}"

    print(f"{d:<12} | {base_str:<40} | {hyb_str:<40}")

print("=" * 105)
print(f"{'TOTAL':<12} | {'Trades: ' + str(total_base_trades):<17} {'P&L: ₹' + f'{total_base_pnl:,.2f}':<22} | {'Trades: ' + str(total_hyb_trades):<17} {'P&L: ₹' + f'{total_hyb_pnl:,.2f}':<22}")
print("=" * 105)
