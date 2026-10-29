import json

# Let's test what happens if:
# 1. Afternoon gets a Micro-Trailing rule (e.g. at +8% gain, lock breakeven or trail)
# 2. Or if Afternoon entry window is restricted to 13:30 - 14:15 (avoiding the 13:15 - 13:30 European open churn)

with open('scratch/production_backtest_30_sessions_results.json') as f:
    d = json.load(f)

trades = d['trades']

# Test 1: If Afternoon has +8% trail (Trade 12 on Sep 28 had +9.8% peak and lost -2585. If it locked +1% or +4%, what would total PnL be?)
trade12_saving = 2585.4 + (80.48 * 0.04 * 130 - 40) # turns from -2585 to +378
print(f"If Afternoon has +8% trail, Trade 12 saves: Rs {trade12_saving:,.2f}")
print(f"Total Net PnL would jump from Rs 10,113.20 to Rs {10113.20 + trade12_saving:,.2f}")

# Test 2: If we skip trades between 13:15 and 13:30:
# Trade 12 (13:23): -2585
# Trade 14 (13:21): +584
# Trade 19 (13:27): -2542
# Trade 30 (13:15): -1873
# Total pnl of 13:15 - 13:30: -2585 + 584 - 2542 - 1873 = -6416!
pnl_1315_1330 = sum(t['pnl_2lots'] for t in trades if "13:15" <= t['entry_time'] < "13:30")
print(f"Total PnL of all entries between 13:15 and 13:30: Rs {pnl_1315_1330:,.2f}!")
