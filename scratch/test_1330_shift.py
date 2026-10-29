import json

# Let's test the impact of shifting midday end from 13:15 to 13:30:
with open('scratch/production_backtest_30_sessions_results.json') as f:
    d = json.load(f)

trades = d['trades']
print("Trades entered between 13:15 and 13:30:")
for t in trades:
    if "13:15" <= t['entry_time'] < "13:30":
        print(f"  {t['date']} {t['entry_time']} {t['direction']} {t['strike']} | Peak: +{t['peak_gain_pct']}% | PnL: Rs {t['pnl_2lots']:+8.2f} | {t['exit_reason']}")
