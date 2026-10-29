import os
import sys
import json
import urllib.request
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

target_date = "2026-10-14"
expiry_str = "2026-10-19"
strikes = [22450, 22500, 22550, 22600, 22650, 22700, 22750, 22800]
types = ["CE", "PE"]

output_file = f"data/option_candles_{target_date.replace('-', '')}.json"
options_data = {}

print("=" * 70)
print(f"FETCHING ALL TRUE 1M OPTION CANDLES FOR {target_date} (EXPIRY: {expiry_str})")
print("=" * 70)

base_url = "http://localhost:8000/api/v1/market/candles"

for strike in strikes:
    for opt_type in types:
        sym_key = f"NIFTY_{target_date}_{strike}_{opt_type}"
        inst_id = f"INST-NIFTY-{expiry_str}-{strike}-{opt_type}"
        url = f"{base_url}?instrument_id={inst_id}&interval=1m&limit=375"
        
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw_candles = json.loads(resp.read().decode("utf-8"))
            
            # Format candles for BacktestEngine
            formatted = []
            for c in raw_candles:
                formatted.append({
                    "start_time": c.get("start_time"),
                    "open": float(c.get("open", 0)),
                    "high": float(c.get("high", 0)),
                    "low": float(c.get("low", 0)),
                    "close": float(c.get("close", 0)),
                    "volume": int(c.get("volume", 0))
                })
            
            options_data[sym_key] = formatted
            print(f"  [OK] {inst_id:<32} -> {len(formatted)} candles | Open: ₹{formatted[0]['open']:.2f} -> Close: ₹{formatted[-1]['close']:.2f}")
        except Exception as e:
            print(f"  [ERROR] {inst_id}: {e}")

print("\n" + "=" * 70)
print(f"Saving {len(options_data)} contracts to {output_file}...")
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(options_data, f, indent=2)
print("Option candle dataset successfully created!")
