import json
from datetime import datetime

with open("data/today_actual_candles_20261015.json", "r", encoding="utf-8") as f:
    data = json.load(f)

ce_22900 = data["NIFTY26O1922900CE"]
spot = data["NIFTY 50"]

entry_price = 144.90
entry_time = "2026-10-15T11:10:00"

# Find entry candle index
entry_idx = None
for i, c in enumerate(ce_22900):
    if "11:10" in c["date"]:
        entry_idx = i
        break

print(f"Entry Index: {entry_idx} ({ce_22900[entry_idx]['date']}) Entry Price: {entry_price}")

# Track price evolution from 11:10 onwards
peak_price = entry_price
peak_time = entry_time
max_gain_pct = 0.0

print("\n--- Minute-by-Minute Candle Trajectory (11:10 to 12:30) ---")
for i in range(entry_idx, len(ce_22900)):
    c = ce_22900[i]
    dt_str = c["date"]
    high = c["high"]
    low = c["low"]
    close = c["close"]

    if high > peak_price:
        peak_price = high
        peak_time = dt_str
        max_gain_pct = ((peak_price - entry_price) / entry_price) * 100.0

    gain_pct = ((close - entry_price) / entry_price) * 100.0

    # Print first 45 minutes or notable bars
    if i <= entry_idx + 45 or "12:00" in dt_str or "12:30" in dt_str or "13:00" in dt_str or "14:00" in dt_str or "15:20" in dt_str:
        print(f"[{i}] {dt_str[:19]} | O:{c['open']:6.2f} H:{c['high']:6.2f} L:{c['low']:6.2f} C:{c['close']:6.2f} | Gain:{gain_pct:+5.1f}% | Peak:{peak_price:6.2f} (+{max_gain_pct:4.1f}%)")

print(f"\nOverall Max Peak for Trade 1 Contract: {peak_price:.2f} (+{max_gain_pct:.1f}%) at {peak_time}")
