import json
from trading.domain.market_data import resample_two_minutes
from trading.strategies.macd_momentum import calculate_macd, MacdMomentumStrategy

spot = json.load(open('data/spot_candles_20261027.json'))
fut = json.load(open('data/fut_candles_20261027.json'))

res_spot = resample_two_minutes(spot)
closes = [b['close'] for b in res_spot]
macd, sig, hist = calculate_macd(closes)

print(f"Total 2m candles: {len(res_spot)}")
candidates = []
for i in range(26, len(res_spot)):
    pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
    ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
    if pe_cross or ce_cross:
        end_1m = res_spot[i]['minute_idx']
        direction = 'PE' if pe_cross else 'CE'
        hh = end_1m // 60 + 9
        mm = end_1m % 60
        t_str = f"{hh:02d}:{mm:02d}"
        candidates.append((i, end_1m, t_str, direction, res_spot[i]['close'], hist[i], hist[i-1]))
        print(f"[{t_str} IST] Bar {i} (1m idx {end_1m}): BUY_{direction} @ Spot {res_spot[i]['close']:.2f} | Hist: {hist[i]:+.2f} (prev {hist[i-1]:+.2f})")
print(f"Total 2m MACD candidates on 2026-10-27: {len(candidates)}")
