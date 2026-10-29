import urllib.request
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

c5m = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ai/nifty/candles?interval=5m&limit=100").read().decode())
candles = c5m.get("candles", [])

def calc_ema_backend(prices, span):
    if len(prices) < span:
        return prices[-1]
    k = 2.0 / (span + 1)
    e = sum(prices[:span]) / span
    for p in prices[span:]:
        e = p * k + e * (1 - k)
    return round(e, 2)

# For each 5m candle today, compute the EMA9 and EMA20 from the 50 bars preceding it
print(f"Total 5m candles in history: {len(candles)}")
print("\n--- 5-Minute Bars and EMAs for Today (Method 3: 50-bar rolling) ---")
for i in range(50, len(candles)):
    c = candles[i]
    st = c["start_time"]
    dt_utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
    dt_ist = dt_utc.astimezone(IST)
    time_str = dt_ist.strftime("%H:%M")
    date_str = dt_ist.strftime("%Y-%m-%d")

    if date_str == "2026-10-15":
        # Window of 50 bars ending at this candle
        window_50 = [bar["close"] for bar in candles[i-49 : i+1]]
        ema9 = calc_ema_backend(window_50, 9)
        ema20 = calc_ema_backend(window_50, 20)
        ema50 = calc_ema_backend(window_50, 50)
        print(f"5m Bar {time_str} | Close: {c['close']:.2f} | EMA9: {ema9:.2f} | EMA20: {ema20:.2f} | Diff: {ema9 - ema20:+.2f}")
