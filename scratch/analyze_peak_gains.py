import os
import sys

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from backtest_engine import BacktestEngine, StrategyConfig

dates_w1_3 = [
    ("2026-08-31", "Mon Aug 31"),
    ("2026-09-01", "Tue Sep 01 (0DTE)"),
    ("2026-09-02", "Wed Sep 02"),
    ("2026-09-03", "Thu Sep 03"),
    ("2026-09-04", "Fri Sep 04"),
    ("2026-09-07", "Mon Sep 07"),
    ("2026-09-08", "Tue Sep 08 (0DTE)"),
    ("2026-09-09", "Wed Sep 09"),
    ("2026-09-10", "Thu Sep 10"),
    ("2026-09-11", "Fri Sep 11"),
    ("2026-09-15", "Tue Sep 15 (0DTE)"),
    ("2026-09-16", "Wed Sep 16"),
    ("2026-09-17", "Thu Sep 17"),
    ("2026-09-18", "Fri Sep 18"),
]

s3 = StrategyConfig.load_from_config("institutional_pullback")

all_trades = []
for d, label in dates_w1_3:
    eng = BacktestEngine(d)
    if not eng.spot_candles:
        continue
    tr = eng.run_simulation(s3)
    all_trades.extend(tr)

print("=" * 95)
print(f"PEAK GAIN DISTRIBUTION FOR ALL {len(all_trades)} TRADES IN WEEKS 1-3:")
print("=" * 95)

peak_ge_20 = [t for t in all_trades if t.peak_gain_pct >= 20.0]
peak_10_20 = [t for t in all_trades if 10.0 <= t.peak_gain_pct < 20.0]
peak_5_10 = [t for t in all_trades if 5.0 <= t.peak_gain_pct < 10.0]
peak_lt_5 = [t for t in all_trades if t.peak_gain_pct < 5.0]

print(f"Peak Gain >= +20.0%:  {len(peak_ge_20):>2} trades ({len(peak_ge_20)/len(all_trades)*100:.1f}%)")
print(f"Peak Gain 10.0-20.0%: {len(peak_10_20):>2} trades ({len(peak_10_20)/len(all_trades)*100:.1f}%)")
print(f"Peak Gain 5.0-10.0%:  {len(peak_5_10):>2} trades ({len(peak_5_10)/len(all_trades)*100:.1f}%)")
print(f"Peak Gain < +5.0%:    {len(peak_lt_5):>2} trades ({len(peak_lt_5)/len(all_trades)*100:.1f}%)")

print("\nLosing trades that reached >= +8% peak gain before stopping out:")
losses_with_gains = [t for t in all_trades if t.pnl <= 0 and t.peak_gain_pct >= 8.0]
for t in losses_with_gains:
    print(f"  {t.symbol} @ {t.entry_time[:5]} | Peak Gain: +{t.peak_gain_pct:.1f}% -> Final PnL: Rs {t.pnl:.2f} ({t.pnl_pct:.1f}%) | Exit: {t.exit_reason}")
