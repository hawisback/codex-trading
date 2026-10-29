import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

with open("data/today_actual_candles_20261015.json", "r", encoding="utf-8") as f:
    data = json.load(f)

spot = data["NIFTY 50"]
ce_22900 = data["NIFTY26O1922900CE"]

# Group spot into 5m candles
bars_5m = []
for i in range(0, len(spot), 5):
    chunk = spot[i:i+5]
    if chunk:
        bars_5m.append({
            "time": chunk[0]["date"][:16],
            "open": chunk[0]["open"],
            "high": max(c["high"] for c in chunk),
            "low": min(c["low"] for c in chunk),
            "close": chunk[-1]["close"]
        })

# Compute 5m EMA9 and EMA20 iteratively
k9 = 2.0 / 10.0
k20 = 2.0 / 21.0
ema9 = bars_5m[0]["close"]
ema20 = bars_5m[0]["close"]

for b in bars_5m:
    ema9 = b["close"] * k9 + ema9 * (1.0 - k9)
    ema20 = b["close"] * k20 + ema20 * (1.0 - k20)
    b["ema9"] = ema9
    b["ema20"] = ema20

print("--- 5m Spot & EMA9 / EMA20 Tracking ---")
for b in bars_5m:
    t_str = b["time"][11:16]
    if "11:00" <= t_str <= "15:25":
        opt_matches = [c for c in ce_22900 if c["date"][:16] == b["time"]]
        opt_close = opt_matches[0]["close"] if opt_matches else 0.0
        diff = b["close"] - b["ema9"]
        below_tag = "🔴 BELOW EMA9" if diff < 0 else "🟢 ABOVE"
        print(f"{b['time']} | Spot: {b['close']:8.2f} | 5m EMA9: {b['ema9']:8.2f} | Diff: {diff:+6.2f} pts {below_tag} | Opt Close: {opt_close:6.2f}")
