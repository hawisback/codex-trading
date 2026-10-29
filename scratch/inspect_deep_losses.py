import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest_engine import BacktestEngine

dates_and_times = [
    ('2026-10-07', '05:51:00', 'CE'),
    ('2026-10-14', '06:55:00', 'CE'),
    ('2026-10-05', '06:51:00', 'PE'),
    ('2026-09-10', '07:18:00', 'CE')
]

for target_date, trade_time, direction in dates_and_times:
    eng = BacktestEngine(target_date)
    print("=" * 80)
    print(f"SESSION: {target_date} | TRADE: {direction} @ {trade_time} UTC")
    print("=" * 80)
    target_idx = None
    for idx, b in enumerate(eng.spot_candles):
        if trade_time in b["start_time"]:
            target_idx = idx
            break
    if target_idx is not None:
        # Print 5 bars before and 10 bars after
        start = max(0, target_idx - 5)
        end = min(len(eng.spot_candles), target_idx + 15)
        print(f"{'Idx':<4} | {'Time (UTC)':<10} | {'Open':<8} | {'High':<8} | {'Low':<8} | {'Close':<8} | Note")
        print("-" * 75)
        for i in range(start, end):
            b = eng.spot_candles[i]
            t_str = b["start_time"][11:19]
            note = "<-- ENTRY BAR" if i == target_idx else ""
            print(f"{i:<4} | {t_str:<10} | {b['open']:<8.2f} | {b['high']:<8.2f} | {b['low']:<8.2f} | {b['close']:<8.2f} | {note}")
