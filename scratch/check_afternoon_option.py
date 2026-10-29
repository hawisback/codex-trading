import json

with open("data/opt_20261027_22750_CE.json", "r") as fp:
    candles = json.load(fp)

print("12:30 to 13:15 candles:")
for c in candles:
    st = c.get("start_time", "")
    if "12:30" <= st[11:16] <= "13:15":
        print(f"{st[11:16]} | Open: {c['open']:<6.2f} | High: {c['high']:<6.2f} | Low: {c['low']:<6.2f} | Close: {c['close']:<6.2f}")
