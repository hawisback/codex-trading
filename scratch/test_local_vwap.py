import json
import sys

with open('data/spot_candles_20261013.json', 'r', encoding='utf-8') as f:
    candles = json.load(f)

def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema

# Evaluate at 12:42 IST (bar 207)
sub = candles[:208]
spot_typicals = [(c['high'] + c['low'] + c['close']) / 3.0 for c in sub]
spot_vwap = sum(spot_typicals) / len(spot_typicals)

closes = [c['close'] for c in sub]
bars_5m = [closes[i] for i in range(4, len(closes), 5)] or [sub[-1]['close']]
ema9 = calculate_ema(bars_5m, 9)
ema20 = calculate_ema(bars_5m, 20)

last_close = sub[-1]['close']
print(f"Spot:      {last_close}")
print(f"Spot VWAP: {spot_vwap:.2f}")
print(f"5m EMA9:   {ema9:.2f}")
print(f"5m EMA20:  {ema20:.2f}")
is_bull = (last_close > ema9 > ema20 > spot_vwap)
print(f"Bull trend? Spot > EMA9 > EMA20 > VWAP: {is_bull}")
