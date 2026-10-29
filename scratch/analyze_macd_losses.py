import json

with open("logs/backtest_audit/trades_30_sessions.json", "r") as f:
    trades = json.load(f)

wins = [t for t in trades if t["pnl_pts"] > 0]
losses = [t for t in trades if t["pnl_pts"] <= 0]

print(f"Total trades: {len(trades)}, Wins: {len(wins)}, Losses: {len(losses)}")

# Analyze hold duration
win_hold = [t.get("peak_gain_pct", 0) for t in wins]
loss_hold = [t.get("peak_gain_pct", 0) for t in losses]

print(f"Wins average peak gain: {sum(win_hold)/len(win_hold):.1f}%")
print(f"Losses average peak gain: {sum(loss_hold)/len(loss_hold):.1f}%")

# Analyze exit reasons of losses
loss_reasons = {}
for t in losses:
    r = t["exit_reason"]
    # categorize
    cat = r.split("(")[0].strip()
    loss_reasons[cat] = loss_reasons.get(cat, 0) + 1

print("\nLoss Exit Reasons:")
for r, c in sorted(loss_reasons.items(), key=lambda x: -x[1]):
    print(f"  {r}: {c}")

# Check peak gain distribution of losses
reached_10 = [t for t in losses if t.get("peak_gain_pct", 0) >= 10.0]
reached_15 = [t for t in losses if t.get("peak_gain_pct", 0) >= 15.0]
reached_20 = [t for t in losses if t.get("peak_gain_pct", 0) >= 20.0]
print(f"\nLosses that reached +10% peak gain before reversing: {len(reached_10)} ({len(reached_10)/len(losses)*100:.1f}%)")
print(f"Losses that reached +15% peak gain before reversing: {len(reached_15)} ({len(reached_15)/len(losses)*100:.1f}%)")
print(f"Losses that reached +20% peak gain before reversing: {len(reached_20)} ({len(reached_20)/len(losses)*100:.1f}%)")
