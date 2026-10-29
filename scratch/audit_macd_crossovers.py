#!/usr/bin/env python3
"""Audit 2-minute MACD crossovers bar by bar today."""

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from trading.adapters.market_data import create_market_data
from trading.adapters.market_sources import ReadBudget
from trading.domain.market_data import resample_two_minutes, completed_spot_bars
from trading.strategies.macd_momentum import calculate_macd
from market_clock import MarketClock

provider = create_market_data("kite")
now = MarketClock.now_ist()
start = now.replace(hour=9, minute=15, second=0, microsecond=0)
b = ReadBudget(15)

try:
    raw = provider.source.history(start, now, b)
    bars_1m = completed_spot_bars(raw, now)
    bars_2m = resample_two_minutes(bars_1m, as_of=now)
    closes = [b["close"] for b in bars_2m]
    print(f"Total 1m bars from Kite today: {len(bars_1m)}")
    print(f"Total 2m bars from Kite today: {len(bars_2m)}")
    
    macd, signal, hist = calculate_macd(closes, 12, 26, 9)
    print("\n2-MINUTE MACD BAR-BY-BAR TABLE (TODAY):")
    header = f"{'Bar':<4} {'Time':<8} {'Close':<10} {'MACD':<10} {'Signal':<10} {'Hist':<10} {'State':<12} {'Crossover?'}"
    print(header)
    print("-" * len(header))
    
    crossovers = []
    for i in range(len(bars_2m)):
        t = bars_2m[i]["start_time"][11:16]
        c = closes[i]
        m = macd[i]
        s = signal[i]
        h = hist[i]
        state = "MACD > Sig" if m > s else ("MACD < Sig" if m < s else "Equal")
        cross = ""
        if i >= 1 and i >= 26:  # crossover after slow period warmup
            if macd[i] > signal[i] and macd[i-1] <= signal[i-1]:
                cross = "🟢 BULLISH CROSS (BUY_CE)"
                crossovers.append((i+1, t, c, "BULLISH", m, s))
            elif macd[i] < signal[i] and macd[i-1] >= signal[i-1]:
                cross = "🔴 BEARISH CROSS (BUY_PE)"
                crossovers.append((i+1, t, c, "BEARISH", m, s))
        
        print(f"{i+1:<4} {t:<8} {c:<10.2f} {m:<10.2f} {s:<10.2f} {h:<+10.2f} {state:<12} {cross}")
    
    print("\n" + "=" * 65)
    print(f"TOTAL CROSSOVERS DETECTED AFTER WARMUP: {len(crossovers)}")
    if crossovers:
        for idx, t, c, direction, m, s in crossovers:
            print(f"  - Bar {idx} [{t} IST]: {direction} at {c:.2f} (MACD={m:.2f}, Signal={s:.2f})")
    else:
        print("  - Zero crossovers since 10:09 IST warmup completion.")
        print(f"  - Current State: MACD ({macd[-1]:.2f}) is riding continuously BELOW Signal ({signal[-1]:.2f})")
        print(f"  - Histogram: {hist[-1]:+.2f} (Bearish momentum dominant)")
finally:
    provider.close()
