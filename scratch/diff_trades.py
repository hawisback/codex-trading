import json

base_trades = json.load(open('scratch/production_backtest_30_sessions_results.json'))['trades']
opt2_trades = json.load(open('scratch/opt2_trades.json'))

base_keys = set(f"{t['date']} {t['entry_time']}" for t in base_trades)
print("=" * 110)
print("TRADES ADDED IN OPT 2 (Aligning Climax to 72 pts & Midday Range to 18 pts):")
print("=" * 110)

added_wins = 0
added_losses = 0
added_pnl = 0.0

for t in opt2_trades:
    k = f"{t['date']} {t['entry_time']}"
    if k not in base_keys:
        res = "WIN " if t['is_win'] else "LOSS"
        if t['is_win']: added_wins += 1
        else: added_losses += 1
        added_pnl += t['pnl_2lots']
        print(f"{t['date']} {t['entry_time']} -> {t['exit_time']} | {res} | {t['direction']} {t['strike']} | Peak: +{t['peak_gain_pct']:4.1f}% | PnL: Rs {t['pnl_2lots']:+8.2f} | {t['exit_reason']}")

print("=" * 110)
print(f"Summary of Added Trades: {added_wins} Wins / {added_losses} Losses | Net PnL Added: Rs {added_pnl:+,.2f}")
print("=" * 110)
