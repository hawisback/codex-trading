import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
import urllib.request, csv, io
from datetime import datetime, timezone, timedelta
from trading.adapters.market_data import create_market_data
from trading.adapters.market_sources import ReadBudget

md = create_market_data('kite')
ist = timezone(timedelta(hours=5, minutes=30))

# Fetch all NFO instruments to find option tokens
req = urllib.request.Request('https://api.kite.trade/instruments/NFO')
with urllib.request.urlopen(req) as resp:
    content = resp.read().decode('utf-8-sig')

reader = csv.DictReader(io.StringIO(content))
options_dict = {}
for r in reader:
    if r.get('name') == 'NIFTY' and r.get('segment') == 'NFO-OPT':
        # key: (expiry, strike, right)
        options_dict[(r['expiry'], float(r['strike']), r['instrument_type'])] = {
            'symbol': r['tradingsymbol'],
            'token': int(r['instrument_token'])
        }

print(f"Loaded {len(options_dict)} NFO options from master.")

# Days and target ATM strikes
day_atm = [
    ("2026-10-19", "2026-10-20", 23150),
    ("2026-10-21", "2026-10-27", 22900),
    ("2026-10-22", "2026-10-27", 22700),
    ("2026-10-23", "2026-10-27", 22600),
    ("2026-10-26", "2026-10-27", 22500),
    ("2026-10-27", "2026-10-27", 22750)
]

for d_str, expiry_str, strike in day_atm:
    for right in ['CE', 'PE']:
        opt_info = options_dict.get((expiry_str, float(strike), right))
        if not opt_info:
            print(f"Missing option for {d_str} {expiry_str} {strike} {right}")
            continue
        token = opt_info['token']
        sym = opt_info['symbol']
        dt = datetime.strptime(d_str, '%Y-%m-%d').replace(tzinfo=ist)
        start = dt.replace(hour=9, minute=15, second=0)
        end = dt.replace(hour=15, minute=30, second=0)
        try:
            bars = md.source._history(token, 'minute', start, end, ReadBudget(15.0))
            fname = f"data/opt_{d_str.replace('-', '')}_{strike}_{right}.json"
            formatted = [{
                "start_time": b[0],
                "open": float(b[1]),
                "high": float(b[2]),
                "low": float(b[3]),
                "close": float(b[4]),
                "volume": float(b[5]),
                "oi": float(b[6]) if len(b) > 6 else 0.0
            } for b in bars]
            with open(fname, 'w') as fp:
                json.dump(formatted, fp, indent=2)
            # Record the actual fetched expiry; never infer it later from direction alone.
            with open(fname.replace(".json", ".meta.json"), "w", encoding="utf-8") as meta_fp:
                json.dump({"session": d_str, "expiry": expiry_str, "strike": strike,
                           "right": right, "symbol": sym}, meta_fp, indent=2)
            print(f"Saved {fname} with {len(formatted)} bars")
        except Exception as e:
            print(f"Error fetching {sym} for {d_str}: {e}")
