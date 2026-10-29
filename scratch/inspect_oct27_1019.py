import json
from datetime import datetime

with open("data/spot_candles_20261027.json", "r") as f:
    candles = json.load(f)

for idx, c in enumerate(candles):
    t = c["start_time"]
    if "10:10" <= t[11:16] <= "10:26":
        print(f"[{idx}] {t[11:19]} | Open: {c['open']}, High: {c['high']}, Low: {c['low']}, Close: {c['close']}")
