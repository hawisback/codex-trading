import sys
import os
sys.path.insert(0, os.path.abspath("."))
import json
from trading.adapters.market_data import create_market_data

md = create_market_data("kite")
res = md.get_candles("1m", limit=375)
candles = res["candles"]
print(f"Fetched {len(candles)} candles for today!")
if candles:
    print(f"First candle: {candles[0]['start_time']} Open: {candles[0]['open']}")
    print(f"Last candle:  {candles[-1]['start_time']} Close: {candles[-1]['close']}")

with open("data/spot_candles_20261026.json", "w", encoding="utf-8") as f:
    json.dump(candles, f, indent=2)

print("Saved to data/spot_candles_20261026.json successfully.")
