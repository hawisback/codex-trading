import urllib.request
import json

c5m = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ai/nifty/candles?interval=5m&limit=50").read().decode())
candles = c5m.get("candles", [])
closes = [c["close"] for c in candles]
print(f"Total closes: {len(closes)}, first: {closes[0]}, last: {closes[-1]}")

# Method 1: Iterative EMA with prices[0] as seed
def ema_m1(prices, span):
    k = 2.0 / (span + 1)
    e = prices[0]
    for p in prices[1:]:
        e = p * k + e * (1 - k)
    return e

# Method 2: Pandas adjust=False (same as Method 1)
# Method 3: First 'span' values SMA, then EMA
def ema_m3(prices, span):
    if len(prices) < span:
        return prices[-1]
    k = 2.0 / (span + 1)
    e = sum(prices[:span]) / span
    for p in prices[span:]:
        e = p * k + e * (1 - k)
    return e

print("Method 1 (seed=prices[0]):", ema_m1(closes, 9), ema_m1(closes, 20), ema_m1(closes, 50))
print("Method 3 (seed=SMA[span]):", ema_m3(closes, 9), ema_m3(closes, 20), ema_m3(closes, 50))

# Compare with backend metrics
tech = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ai/nifty/technicals?interval=5m&limit=50").read().decode())
m = tech.get("metrics", {})
print("Backend metrics:          ", m.get("ema_9"), m.get("ema_20"), m.get("ema_50"))
