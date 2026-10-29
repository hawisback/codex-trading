import sys
import os
sys.path.insert(0, os.path.abspath("."))
import json
from trading.adapters.gateways.kite import KiteExecutionGateway

kg = KiteExecutionGateway()
kg.is_connected()
print("Connected to Kite. Fetching tokens for options...")

symbols = [
    "NIFTY26OCT22600CE",
    "NIFTY26OCT22650CE",
    "NIFTY26OCT22700CE",
    "NIFTY26OCT22600PE"
]
keys = [f"NFO:{s}" for s in symbols]
quotes = kg._request("GET", "/quote", params={"i": keys})
data = quotes.get("data", {})

option_candles = {}
for sym in symbols:
    q = data.get(f"NFO:{sym}", {})
    tok = q.get("instrument_token")
    print(f"{sym} -> token: {tok}, ltp: {q.get('last_price')}")
    if tok:
        res = kg._request("GET", f"/instruments/historical/{tok}/minute", params={"from": "2026-10-26 09:15:00", "to": "2026-10-26 15:30:00", "oi": 1})
        candles = res.get("data", {}).get("candles", [])
        print(f"  Fetched {len(candles)} 1m candles for {sym}")
        # Format as standard candles dict
        formatted = []
        for c in candles:
            # Kite returns [timestamp, open, high, low, close, volume, oi]
            formatted.append({
                "start_time": c[0],
                "open": c[1],
                "high": c[2],
                "low": c[3],
                "close": c[4],
                "volume": c[5],
                "oi": c[6] if len(c) > 6 else 0
            })
        option_candles[sym] = formatted

with open("data/option_candles_20261026.json", "w", encoding="utf-8") as f:
    json.dump(option_candles, f, indent=2)

print("Saved all option candles to data/option_candles_20261026.json successfully!")
