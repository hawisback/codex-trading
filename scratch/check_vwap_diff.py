import sys
sys.path.append('.')
from backtest_engine import BacktestEngine

eng = BacktestEngine('2026-10-13')
for idx, b in enumerate(eng.spot_candles):
    t = b['start_time'][11:19]
    if t in ['07:12:00', '07:37:00', '08:03:00']: # UTC 07:12 = 12:42 IST
        sub = eng.spot_candles[:idx+1]
        spot_vwap = sum((c['high'] + c['low'] + c['close'])/3.0 for c in sub) / len(sub)
        closes = [c['close'] for c in sub]
        bars_5m = [closes[i] for i in range(4, len(closes), 5)] or [b['close']]
        ema9 = eng.calculate_ema(bars_5m, 9)
        ema20 = eng.calculate_ema(bars_5m, 20)
        print(f"Bar {idx} @ {t} UTC ({(int(t[:2])+5):02d}:{(int(t[3:5])+30):02d} IST):")
        print(f"  Spot: {b['close']} | Backtest Spot VWAP: {spot_vwap:.2f} | 5m EMA9: {ema9:.2f} | 5m EMA20: {ema20:.2f}")
        print(f"  Spot > Backtest VWAP? {b['close'] > spot_vwap}")
