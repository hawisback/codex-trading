import urllib.request
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

req = urllib.request.Request('http://localhost:8000/api/v1/ai/nifty/candles?interval=1m&limit=375')
candles = json.loads(urllib.request.urlopen(req).read().decode()).get('candles', [])
print(f'Total candles: {len(candles)}')

# Convert candle start_time to IST
ist_candles = []
for c in candles:
    st = c.get('start_time')
    # Parse isoformat
    dt = datetime.fromisoformat(st)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt_ist = dt.astimezone(IST)
    ist_candles.append((dt_ist, c))

print("=" * 70)
print(f"Session Start (IST): {ist_candles[0][0].strftime('%Y-%m-%d %H:%M:%S')} | Open: {ist_candles[0][1]['open']}")
print(f"Session End   (IST): {ist_candles[-1][0].strftime('%Y-%m-%d %H:%M:%S')} | Close: {ist_candles[-1][1]['close']}")
print("=" * 70)

target_ist_times = [
    '09:15', '09:30', '10:00', '10:30', '11:00', '11:12', '11:30',
    '12:00', '12:15', '12:30', '12:45', '12:55', '13:00', '13:05',
    '13:10', '13:15', '13:20', '13:30', '13:39', '13:41', '13:45',
    '14:00', '14:12', '14:25', '14:29', '14:45', '15:00', '15:15',
    '15:25', '15:29'
]

print(f"{'IST Time':<10} | {'Open':<9} | {'High':<9} | {'Low':<9} | {'Close':<9} | {'Volume'}")
print("-" * 65)

for target in target_ist_times:
    matched = [c for dt_ist, c in ist_candles if dt_ist.strftime('%H:%M') == target]
    if matched:
        c = matched[0]
        print(f"{target:<10} | {c['open']:<9.2f} | {c['high']:<9.2f} | {c['low']:<9.2f} | {c['close']:<9.2f} | {c.get('volume', 0)}")
