import urllib.request
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def fetch(path):
    url = f"http://127.0.0.1:8000/api/v1/ai{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "BacktestScript"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())

c1m = fetch("/nifty/candles?interval=1m&limit=500")
candles = c1m.get("candles", [])
print(f"Total 1m candles: {len(candles)}")

for c in candles[:3]:
    dt_utc = datetime.fromisoformat(c["start_time"].replace("Z", "+00:00"))
    print("Early 1m candle:", dt_utc.astimezone(IST).strftime("%Y-%m-%d %H:%M"), "Close:", c["close"])

for c in candles[-3:]:
    dt_utc = datetime.fromisoformat(c["start_time"].replace("Z", "+00:00"))
    print("Recent 1m candle:", dt_utc.astimezone(IST).strftime("%Y-%m-%d %H:%M"), "Close:", c["close"])
