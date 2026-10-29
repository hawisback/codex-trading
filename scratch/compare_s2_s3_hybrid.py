import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from scratch.test_hybrid_spot_trailing import HybridSpotTrailingEngine
from backtest_engine import StrategyConfig, calculate_metrics

dates = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-14", "2026-10-15"]
cfg2 = StrategyConfig.load_from_config("structural_runner")
cfg3 = StrategyConfig.load_from_config("institutional_pullback")

print("=" * 110)
print(f"{'Date':<12} | {'Strategy 2: Structural Runner (Hybrid)':<45} | {'Strategy 3: Institutional Pullback (Hybrid)':<45}")
print(f"{'':<12} | {'Trades':<8} {'Win%':<8} {'P&L (₹)':<14} {'Max Win':<10} | {'Trades':<8} {'Win%':<8} {'P&L (₹)':<14} {'Max Win':<10}")
print("=" * 110)

pnl_s2 = 0.0
pnl_s3 = 0.0

for d in dates:
    eng_s2 = HybridSpotTrailingEngine(d, "ema20")
    eng_s3 = HybridSpotTrailingEngine(d, "ema20")
    t_s2 = eng_s2.run_simulation(cfg2)
    t_s3 = eng_s3.run_simulation(cfg3)
    m_s2 = calculate_metrics(t_s2)
    m_s3 = calculate_metrics(t_s3)
    pnl_s2 += m_s2["net_pnl"]
    pnl_s3 += m_s3["net_pnl"]

    s2_str = f"{m_s2['total_trades']:<8} {m_s2['win_rate']:<8.1f}% ₹{m_s2['net_pnl']:<13,.2f} ₹{m_s2['max_win']:<9,.2f}"
    s3_str = f"{m_s3['total_trades']:<8} {m_s3['win_rate']:<8.1f}% ₹{m_s3['net_pnl']:<13,.2f} ₹{m_s3['max_win']:<9,.2f}"

    print(f"{d:<12} | {s2_str:<45} | {s3_str:<45}")

print("=" * 110)
print(f"{'TOTAL':<12} | {'P&L: ₹' + f'{pnl_s2:,.2f}':<45} | {'P&L: ₹' + f'{pnl_s3:,.2f}':<45}")
print("=" * 110)
