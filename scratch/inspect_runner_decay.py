import json

with open("data/spot_candles_20261027.json", "r") as fp:
    spot_bars = json.load(fp)

with open("data/opt_20261027_22750_CE.json", "r") as fp:
    opt_candles = json.load(fp)

opt_by_time = {c.get("start_time", "")[11:16]: c for c in opt_candles}

print(f"{'Time':<6} | {'Spot':<9} | {'Opt Open':<9} | {'Opt High':<9} | {'Opt Low':<9} | {'Opt Close':<9} | {'Gain from 53.75'}")
print("-" * 85)

for b in spot_bars:
    t = b.get("start_time", "")[11:16]
    if "12:33" <= t <= "13:05":
        oc = opt_by_time.get(t, {})
        o_high = oc.get("high", 0.0)
        o_close = oc.get("close", 0.0)
        gain_peak = ((o_high - 53.75) / 53.75) * 100.0 if o_high else 0.0
        gain_close = ((o_close - 53.75) / 53.75) * 100.0 if o_close else 0.0
        print(f"{t:<6} | {b['close']:<9.1f} | {oc.get('open', 0):<9.2f} | {o_high:<9.2f} | {oc.get('low', 0):<9.2f} | {o_close:<9.2f} | Peak: +{gain_peak:<5.1f}% (Close: +{gain_close:<5.1f}%)")
