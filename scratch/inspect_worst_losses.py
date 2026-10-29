import json

with open("logs/backtest_audit/trades_30_sessions.json", "r") as f:
    trades = json.load(f)

losses = [t for t in trades if t["pnl_pts"] <= 0]

print(f"Total losses to analyze: {len(losses)}")

# 1. Analyze loss magnitude
losses_sorted = sorted(losses, key=lambda x: x["pnl_pts"])
print("\n--- Top 15 Worst Losses ---")
for t in losses_sorted[:15]:
    print(f"Date: {t['date']} | Time: {t['entry_time']} | Dir: {t['direction']} | Entry: {t['entry_price']} | Exit: {t['exit_price']} | Ret: {t['ret_pct']}% | PnL (pts): {t['pnl_pts']:.2f} | Reason: {t['exit_reason']}")

# 2. Check hold duration of losses
hold_minutes = []
for t in losses:
    # calculate hold from entry and exit time
    eh, em = map(int, t["entry_time"].split()[0].split(":"))
    xh, xm = map(int, t["exit_time"].split()[0].split(":"))
    mins = (xh * 60 + xm) - (eh * 60 + em)
    hold_minutes.append(mins)

print(f"\nAverage hold duration of losses: {sum(hold_minutes)/len(hold_minutes):.1f} minutes")
print(f"Losses stopped out in <= 5 minutes: {len([m for m in hold_minutes if m <= 5])} ({len([m for m in hold_minutes if m <= 5])/len(losses)*100:.1f}%)")
print(f"Losses stopped out in <= 10 minutes: {len([m for m in hold_minutes if m <= 10])} ({len([m for m in hold_minutes if m <= 10])/len(losses)*100:.1f}%)")
