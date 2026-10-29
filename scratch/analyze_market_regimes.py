import os
import sys

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from backtest_engine import BacktestEngine

dates_w1_3 = [
    ("2026-08-31", "Mon Aug 31"),
    ("2026-09-01", "Tue Sep 01 (0DTE)"),
    ("2026-09-02", "Wed Sep 02"),
    ("2026-09-03", "Thu Sep 03"),
    ("2026-09-04", "Fri Sep 04"),
    ("2026-09-07", "Mon Sep 07"),
    ("2026-09-08", "Tue Sep 08 (0DTE)"),
    ("2026-09-09", "Wed Sep 09"),
    ("2026-09-10", "Thu Sep 10"),
    ("2026-09-11", "Fri Sep 11"),
    ("2026-09-15", "Tue Sep 15 (0DTE)"),
    ("2026-09-16", "Wed Sep 16"),
    ("2026-09-17", "Thu Sep 17"),
    ("2026-09-18", "Fri Sep 18"),
]

print("=" * 115)
print(f"{'Date':<18} | {'Open':<9} {'High':<9} {'Low':<9} {'Close':<9} | {'Range':<8} {'Move':<9} {'Efficiency':<11} {'VWAP Crosses':<13} {'Regime'}")
print("=" * 115)

for d, label in dates_w1_3:
    eng = BacktestEngine(d)
    if not eng.spot_candles:
        continue
    
    o = eng.spot_candles[0]["open"]
    c = eng.spot_candles[-1]["close"]
    h = max(bar["high"] for bar in eng.spot_candles)
    l = min(bar["low"] for bar in eng.spot_candles)
    rng = h - l
    move = c - o
    eff = abs(move) / rng if rng > 0 else 0.0
    
    # Calculate VWAP crosses
    typicals = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in eng.spot_candles]
    vwap_line = []
    for i in range(len(typicals)):
        vwap_line.append(sum(typicals[:i+1]) / (i + 1))
    
    crosses = 0
    for i in range(1, len(eng.spot_candles)):
        prev_diff = eng.spot_candles[i-1]["close"] - vwap_line[i-1]
        curr_diff = eng.spot_candles[i]["close"] - vwap_line[i]
        if (prev_diff * curr_diff) < 0:
            crosses += 1
            
    if eff < 0.25 or crosses >= 10:
        regime = "CHOP / ROTATION"
    elif eff >= 0.55 and crosses <= 4:
        regime = "STRONG TREND EXPANSION"
    else:
        regime = "MODERATE TREND"
        
    print(f"{label:<18} | {o:>8.1f}  {h:>8.1f}  {l:>8.1f}  {c:>8.1f} | {rng:>7.1f}  {move:>+8.1f}  {eff:>9.2f}   {crosses:>10}    {regime}")
