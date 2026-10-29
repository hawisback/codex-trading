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

prev_day_5m = []
today_5m = []

for c in candles:
    st = c["start_time"]
    dt_utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
    dt_ist = dt_utc.astimezone(IST)
    c["ist_dt"] = dt_ist
    c["ist_time"] = dt_ist.strftime("%Y-%m-%d %H:%M")
    if dt_ist.strftime("%Y-%m-%d") == "2026-10-15":
        today_5m.append(c)
    else:
        prev_day_5m.append(c)

print(f"Previous 5m candles: {len(prev_day_5m)}")
print(f"Today 5m candles: {len(today_5m)}")
print("Last 3 prev day 5m:", [(c["ist_time"], c["close"]) for c in prev_day_5m[-3:]])
print("First 3 today 5m:", [(c["ist_time"], c["close"]) for c in today_5m[:3]])
