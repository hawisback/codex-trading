import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
import json
from trading.adapters.market_data import create_market_data
from trading.adapters.market_sources import ReadBudget, SPOT

md = create_market_data('kite')
ist = timezone(timedelta(hours=5, minutes=30))

if md.source._spot_token is None:
    md.source.quotes([SPOT], ReadBudget(10.0))
spot_token = md.source._spot_token

days = ['2026-10-19', '2026-10-21', '2026-10-22', '2026-10-23', '2026-10-26', '2026-10-27']

for day_str in days:
    dt = datetime.strptime(day_str, '%Y-%m-%d').replace(tzinfo=ist)
    start = dt.replace(hour=9, minute=15, second=0)
    end = dt.replace(hour=15, minute=30, second=0)
    raw_bars = md.source._history(spot_token, 'minute', start, end, ReadBudget(15.0))
    print(f"{day_str}: Fetched {len(raw_bars)} raw spot bars")
    formatted = [{
        'open': float(b[1]),
        'high': float(b[2]),
        'low': float(b[3]),
        'close': float(b[4]),
        'start_time': b[0],
        'volume': float(b[5])
    } for b in raw_bars]
    fname = f"data/spot_candles_{day_str.replace('-', '')}.json"
    with open(fname, 'w') as f:
        json.dump(formatted, f, indent=2)
    print(f"Saved {fname} with {len(formatted)} bars")
