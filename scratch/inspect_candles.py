import urllib.request
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def fetch(path):
    url = f"http://127.0.0.1:8000/api/v1/ai{path}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "BacktestScript"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}

c1m = fetch("/nifty/candles?interval=1m&limit=200")
candles = c1m.get("candles", [])

today_candles = []
for c in candles:
    st = c.get("start_time", "")
    if st.startswith("2026-10-15"):
        # Convert UTC string to IST
        dt_utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
        dt_ist = dt_utc.astimezone(IST)
        today_candles.append({
            "utc": st,
            "ist": dt_ist.strftime("%H:%M"),
            "open": c.get("open"),
            "high": c.get("high"),
            "low": c.get("low"),
            "close": c.get("close"),
            "volume": c.get("volume", 0)
        })

print(f"Total today candles: {len(today_candles)}")
if today_candles:
    print(f"First candle IST: {today_candles[0]['ist']} | O: {today_candles[0]['open']} H: {today_candles[0]['high']} L: {today_candles[0]['low']} C: {today_candles[0]['close']}")
    print(f"Last candle IST: {today_candles[-1]['ist']} | O: {today_candles[-1]['open']} H: {today_candles[-1]['high']} L: {today_candles[-1]['low']} C: {today_candles[-1]['close']}")

# Let's check candles around 09:40 - 09:55
print("\n--- Candles 09:40 to 09:55 IST ---")
for c in today_candles:
    if "09:40" <= c["ist"] <= "09:55":
        print(f"{c['ist']} | O: {c['open']:.1f} | H: {c['high']:.1f} | L: {c['low']:.1f} | C: {c['close']:.1f}")
