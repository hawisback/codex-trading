import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, timezone, timedelta
import json
from trading.adapters.market_data import create_market_data
from trading.adapters.market_sources import ReadBudget

md = create_market_data('kite')
ist = timezone(timedelta(hours=5, minutes=30))
fut_token = 12468226 # NIFTY26OCTFUT

start = datetime.strptime('2026-10-19 09:15:00', '%Y-%m-%d %H:%M:%S').replace(tzinfo=ist)
end = datetime.strptime('2026-10-27 15:30:00', '%Y-%m-%d %H:%M:%S').replace(tzinfo=ist)

raw_fut = md.source._history(fut_token, 'minute', start, end, ReadBudget(20.0))
print(f"Fetched {len(raw_fut)} raw futures candles.")

# Organize by date
by_date = {}
for b in raw_fut:
    dt_str = b[0][:10]
    if dt_str not in by_date:
        by_date[dt_str] = []
    by_date[dt_str].append({
        "start_time": b[0],
        "open": float(b[1]),
        "high": float(b[2]),
        "low": float(b[3]),
        "close": float(b[4]),
        "volume": float(b[5]),
        "oi": float(b[6]) if len(b) > 6 else 0.0
    })

for d, bars in sorted(by_date.items()):
    print(f"Date {d}: {len(bars)} futures bars")
    out_file = f"data/fut_candles_{d.replace('-', '')}.json"
    with open(out_file, "w") as fp:
        json.dump(bars, fp, indent=2)
    print(f"Saved {out_file}")
