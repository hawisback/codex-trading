import urllib.request
import json
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

c1m_resp = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ai/nifty/candles?interval=1m&limit=500").read().decode())
c5m_resp = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ai/nifty/candles?interval=5m&limit=100").read().decode())

all_1m = c1m_resp.get("candles", [])
all_5m = c5m_resp.get("candles", [])

today_1m = []
for c in all_1m:
    st = c.get("start_time", "")
    dt_utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
    dt_ist = dt_utc.astimezone(IST)
    if dt_ist.strftime("%Y-%m-%d") == "2026-10-15":
        c_copy = dict(c)
        c_copy["time_str"] = dt_ist.strftime("%H:%M")
        today_1m.append(c_copy)

prev_5m = [c for c in all_5m if datetime.fromisoformat(c["start_time"].replace("Z", "+00:00")).astimezone(IST).strftime("%Y-%m-%d") < "2026-10-15"]
today_5m_all = [c for c in all_5m if datetime.fromisoformat(c["start_time"].replace("Z", "+00:00")).astimezone(IST).strftime("%Y-%m-%d") == "2026-10-15"]

def calc_ema_backend(prices, span):
    if len(prices) < span:
        return prices[-1]
    k = 2.0 / (span + 1)
    e = sum(prices[:span]) / span
    for p in prices[span:]:
        e = p * k + e * (1 - k)
    return round(e, 2)

def calculate_rsi(prices, period=14):
    if len(prices) <= period:
        return 50.0
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    recent_gains = [max(0.0, d) for d in deltas[-period:]]
    recent_losses = [max(0.0, -d) for d in deltas[-period:]]
    avg_gain = sum(recent_gains) / period
    avg_loss = sum(recent_losses) / period
    if avg_loss == 0.0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 1)

spot_prices = []
spot_typicals = []

print("=== DEEP DIVE INTO 09:35 - 09:55 BARS ===")
for idx, bar in enumerate(today_1m):
    spot = bar["close"]
    high = bar["high"]
    low = bar["low"]
    time_str = bar["time_str"]

    spot_prices.append(spot)
    spot_typicals.append((high + low + spot) / 3.0)
    session_vwap = round(sum(spot_typicals) / len(spot_typicals), 2)

    completed_5m_count = idx // 5
    active_5m_slice = prev_5m + today_5m_all[:completed_5m_count]
    closes_5m = [c["close"] for c in active_5m_slice[-50:]]
    ema9 = calc_ema_backend(closes_5m, 9)
    ema20 = calc_ema_backend(closes_5m, 20)
    rsi = calculate_rsi(spot_prices, 14)

    recent_15m = today_1m[max(0, idx - 14): idx + 1]
    box_high = max(c["high"] for c in recent_15m)
    box_low = min(c["low"] for c in recent_15m)
    box_spread = round(box_high - box_low, 2)
    is_box = box_spread < 28.0 and len(recent_15m) >= 10

    if "09:40" <= time_str <= "09:50":
        trend_aligned = (spot > ema9) and (ema9 > ema20) and (spot > session_vwap)
        box_ceiling_blocked = is_box and spot < (box_high + 2.0) and spot >= (box_high - 6.0)
        overextended = (spot - ema9) > 24.0 or rsi > 78.0
        pullback_strict = (low <= ema9 + 4.0)
        pullback_vwap = (low <= session_vwap + 6.0)

        print(f"\n--- Bar [{time_str}] (idx={idx}) ---")
        print(f"  Spot: O={bar['open']}, H={high}, L={low}, C={spot}")
        print(f"  Indicators: EMA9={ema9}, EMA20={ema20}, VWAP={session_vwap}, RSI={rsi}")
        print(f"  Trend Aligned: {trend_aligned} (Spot > EMA9: {spot > ema9}, EMA9 > EMA20: {ema9 > ema20}, Spot > VWAP: {spot > session_vwap})")
        print(f"  15m Box: Low={box_low}, High={box_high}, Spread={box_spread} (is_box={is_box}, ceiling_blocked={box_ceiling_blocked})")
        print(f"  Overextended (Value Prox): {overextended} (Dist={spot - ema9:.1f} pts, max=24.0, RSI={rsi})")
        print(f"  Pullback Strict (Low <= EMA9+4): {pullback_strict} (Low={low} vs {ema9+4.0})")
        print(f"  Pullback VWAP (Low <= VWAP+6): {pullback_vwap} (Low={low} vs {session_vwap+6.0})")
