import json

with open("data/opt_20261027_22750_CE.json", "r") as fp:
    candles = json.load(fp)

print(f"Total 22750 CE candles: {len(candles)}")
# Inspect candles from 11:00 to 11:45
for c in candles:
    st = c.get("start_time", "")
    if "11:00" <= st[11:16] <= "11:45":
        print(f"{st[11:16]} | Open: {c['open']:<6.2f} | High: {c['high']:<6.2f} | Low: {c['low']:<6.2f} | Close: {c['close']:<6.2f}")
