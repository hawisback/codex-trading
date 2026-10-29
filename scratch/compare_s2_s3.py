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

s2_cfg = StrategyConfig.load_from_config("structural_runner")
s3_cfg = StrategyConfig.load_from_config("institutional_pullback")

print("COMPARING S2 vs S3 TRADES ON LOSING DAYS:")
for d, label in dates_w1_3:
    eng = BacktestEngine(d)
    if not eng.spot_candles:
        continue
    t2 = eng.run_simulation(s2_cfg)
    t3 = eng.run_simulation(s3_cfg)
    net2 = sum(t.pnl for t in t2) - len(t2)*40
    net3 = sum(t.pnl for t in t3) - len(t3)*40
    if net2 > net3 + 500:
        print(f"\n>>> {label}: S2 Net=Rs {net2:.2f} ({len(t2)} tr) vs S3 Net=Rs {net3:.2f} ({len(t3)} tr) | S2 Alpha = Rs {net2 - net3:+.2f}")
        print("  S2 Trades:")
        for t in t2:
            print(f"    S2: {t.direction} @ {t.entry_time[:5]} | Strike: {t.strike} | PnL: Rs {t.pnl:>+8.2f} ({t.pnl_pct:+.1f}%) | Exit: {t.exit_reason}")
        print("  S3 Trades:")
        for t in t3:
            print(f"    S3: {t.direction} @ {t.entry_time[:5]} | Strike: {t.strike} | PnL: Rs {t.pnl:>+8.2f} ({t.pnl_pct:+.1f}%) | Exit: {t.exit_reason}")
