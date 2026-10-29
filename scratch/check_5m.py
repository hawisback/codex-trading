import urllib.request
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def fetch(path):
    url = f"http://127.0.0.1:8000/api/v1/ai{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "BacktestScript"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode())

c5m = fetch("/nifty/candles?interval=5m&limit=100")
candles = c5m.get("candles", [])
print(f"Total 5m candles: {len(candles)}")

for c in candles[:5]:
    dt_utc = datetime.fromisoformat(c["start_time"].replace("Z", "+00:00"))
    print("Early 5m candle:", dt_utc.astimezone(IST).strftime("%Y-%m-%d %H:%M"), "Close:", c["close"])

for c in candles[-5:]:
    dt_utc = datetime.fromisoformat(c["start_time"].replace("Z", "+00:00"))
    print("Recent 5m candle:", dt_utc.astimezone(IST).strftime("%Y-%m-%d %H:%M"), "Close:", c["close"])
