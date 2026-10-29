import json
import sys
sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()
from trading.domain.market_data import resample_two_minutes
from trading.strategies.macd_momentum import calculate_macd

with open("data/spot_candles_20261027.json", "r") as f:
    candles = json.load(f)

bars_2m = resample_two_minutes(candles)
closes = [b["close"] for b in bars_2m]
macd, sig, hist = calculate_macd(closes)

for i in range(len(bars_2m)):
    t = bars_2m[i]["start_time"]
    if "10:06" <= t[11:16] <= "10:26":
        pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
        ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
        cross_str = "PE CROSS!" if pe_cross else ("CE CROSS!" if ce_cross else "")
        print(f"2m Bar [{i}] {t[11:19]} | Close: {closes[i]:.2f} | MACD: {macd[i]:.2f} | Sig: {sig[i]:.2f} | Hist: {hist[i]:+.2f} {cross_str}")
