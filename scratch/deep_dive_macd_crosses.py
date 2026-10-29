import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()

with open("logs/backtest_audit/consultations_30_sessions.json", "r") as f:
    consultations = json.load(f)

with open("logs/backtest_audit/trades_30_sessions.json", "r") as f:
    trades = json.load(f)

trade_map = {t["date"] + "_" + t["entry_time"]: t for t in trades}

# Match consultations with executed trades
executed = []
for c in consultations:
    k = c["date"] + "_" + c["time"]
    if k in trade_map:
        t = trade_map[k]
        executed.append({
            "consultation": c,
            "trade": t,
            "is_win": t["pnl_pts"] > 0
        })

print(f"Matched {len(executed)} executed trades.")

# Now let's analyze features of Wins vs Losses
wins = [e for e in executed if e["is_win"]]
losses = [e for e in executed if not e["is_win"]]

print(f"Wins: {len(wins)}, Losses: {len(losses)}")

# Check time of day distribution
print("\n--- Time of Day Distribution ---")
def get_hour_bucket(t_str):
    hh = int(t_str[:2])
    return f"{hh}:00-{hh}:59"

win_hours = {}
for w in wins:
    b = get_hour_bucket(w["trade"]["entry_time"])
    win_hours[b] = win_hours.get(b, 0) + 1

loss_hours = {}
for l in losses:
    b = get_hour_bucket(l["trade"]["entry_time"])
    loss_hours[b] = loss_hours.get(b, 0) + 1

all_buckets = sorted(set(list(win_hours.keys()) + list(loss_hours.keys())))
print(f"{'Hour Bucket':<15} | {'Wins':<6} | {'Losses':<6} | {'Win Rate %':<10}")
print("-" * 45)
for b in all_buckets:
    w = win_hours.get(b, 0)
    l = loss_hours.get(b, 0)
    tot = w + l
    wr = (w / tot * 100.0) if tot > 0 else 0.0
    print(f"{b:<15} | {w:<6} | {l:<6} | {wr:>8.1f}%")

# Check Direction (CE vs PE)
print("\n--- Direction Win Rate ---")
win_ce = len([w for w in wins if w["trade"]["direction"] == "CE"])
loss_ce = len([l for l in losses if l["trade"]["direction"] == "CE"])
tot_ce = win_ce + loss_ce

win_pe = len([w for w in wins if w["trade"]["direction"] == "PE"])
loss_pe = len([l for l in losses if l["trade"]["direction"] == "PE"])
tot_pe = win_pe + loss_pe

print(f"CE: {win_ce} Wins / {loss_ce} Losses (Tot: {tot_ce}) -> Win Rate: {win_ce/tot_ce*100:.1f}%")
print(f"PE: {win_pe} Wins / {loss_pe} Losses (Tot: {tot_pe}) -> Win Rate: {win_pe/tot_pe*100:.1f}%")
