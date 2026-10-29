import json

with open('scratch/production_backtest_30_sessions_results.json') as f:
    d = json.load(f)

trades = d['trades']

print("ANALYSIS OF AFTERNOON TRADES:")
aft_trades = [t for t in trades if t['segment'] == 'AFTERNOON']
for t in aft_trades:
    status = "WIN " if t['is_win'] else "LOSS"
    print(f"{t['date']} {t['entry_time']} -> {t['exit_time']} | {status} | {t['direction']} {t['strike']} | Entry: {t['entry_price']} Exit: {t['exit_price']} | Peak: +{t['peak_gain_pct']}% | PnL: Rs {t['pnl_2lots']} | {t['exit_reason']}")

print("\nANALYSIS OF 4 MORNING LOSSES:")
morn_losses = [t for t in trades if t['segment'] == 'MORNING' and not t['is_win']]
for t in morn_losses:
    print(f"{t['date']} {t['entry_time']} -> {t['exit_time']} | {t['direction']} {t['strike']} | Entry: {t['entry_price']} Exit: {t['exit_price']} | Peak: +{t['peak_gain_pct']}% | PnL: Rs {t['pnl_2lots']} | {t['exit_reason']}")
