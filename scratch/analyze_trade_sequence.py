import json

with open("logs/backtest_audit/trades_30_sessions.json", "r") as f:
    trades = json.load(f)

# Group trades by date
day_trades = {}
for t in trades:
    d = t["date"]
    day_trades.setdefault(d, []).append(t)

# Track win rate by trade number of the day (1st trade, 2nd trade, 3rd trade, etc.)
seq_stats = {}
for d, tr_list in day_trades.items():
    for idx, t in enumerate(tr_list, 1):
        seq = min(idx, 6) # 1, 2, 3, 4, 5, 6+
        seq_stats.setdefault(seq, {"trades": 0, "wins": 0, "pnl": 0.0})
        seq_stats[seq]["trades"] += 1
        if t["pnl_pts"] > 0:
            seq_stats[seq]["wins"] += 1
        seq_stats[seq]["pnl"] += t["pnl_1lot"]

print(f"{'Trade # of Day':<15} | {'Trades':<8} | {'Wins':<6} | {'Losses':<6} | {'Win Rate %':<10} | {'Total PnL (1 Lot)':<18}")
print("-" * 75)
for seq in sorted(seq_stats.keys()):
    st = seq_stats[seq]
    tot = st["trades"]
    w = st["wins"]
    l = tot - w
    wr = w / tot * 100 if tot else 0
    pnl = st["pnl"]
    label = f"Trade #{seq}" if seq < 6 else "Trade #6+"
    print(f"{label:<15} | {tot:<8} | {w:<6} | {l:<6} | {wr:>8.1f}% | Rs {pnl:>+12,.2f}")
