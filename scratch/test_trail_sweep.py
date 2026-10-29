import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

with open("data/today_actual_candles_20261015.json", "r", encoding="utf-8") as f:
    data = json.load(f)

ce_22900 = data["NIFTY26O1922900CE"]
entry_price = 144.90
target_50pct = entry_price * 1.50 # 217.35

print("=" * 85)
print("SENSITIVITY ANALYSIS: TRAIL DISTANCE VS. MAXIMUM RUNNER RECOVERY")
print("=" * 85)

for trail_pct in [5.0, 8.0, 10.0, 12.0, 15.0, 18.0, 20.0]:
    peak_price = entry_price
    exit_info = None
    for i, c in enumerate(ce_22900):
        if c["date"][:16] < "2026-10-15T11:10":
            continue
        if c["high"] > peak_price:
            peak_price = c["high"]
        peak_gain = ((peak_price - entry_price) / entry_price) * 100.0

        if c["high"] >= target_50pct:
            exit_info = ("PROFIT TARGET HIT (+50.0%)", c["date"][:19], target_50pct, 50.0)
            break
        if peak_gain >= 20.0:
            trail_stop = peak_price * (1.0 - trail_pct / 100.0)
            if c["low"] <= trail_stop:
                exit_info = (f"TRAIL STOP HIT (-{trail_pct}%)", c["date"][:19], trail_stop, ((trail_stop-entry_price)/entry_price)*100.0)
                break
    if not exit_info:
        exit_info = ("EOD SQUAREOFF", ce_22900[-1]["date"][:19], ce_22900[-1]["close"], ((ce_22900[-1]["close"]-entry_price)/entry_price)*100.0)

    pnl = (exit_info[2] - entry_price) * 65
    print(f"Trail {trail_pct:4.1f}%: Exit at {exit_info[1][:16]} | Price: ₹{exit_info[2]:6.2f} ({exit_info[3]:+5.1f}%) | {exit_info[0]:<25} | P&L: ₹{pnl:+8,.2f}")
