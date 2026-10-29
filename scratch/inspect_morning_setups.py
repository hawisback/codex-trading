#!/usr/bin/env python3
"""Inspect live setups created so far this morning without starting scheduler."""

import json
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime, timedelta
from trading.adapters.market_data import create_market_data
from trading.adapters.market_sources import ReadBudget
from trading.application.market_context import MarketContextService
from trading.strategies.macd_momentum import MacdMomentumStrategy, resample_1m_to_2m, calculate_macd
from ai_opportunity_radar import AIOpportunityRadar
from market_clock import MarketClock

provider = create_market_data("kite")
now = MarketClock.now_ist()
start = now.replace(hour=9, minute=15, second=0, microsecond=0)
b = ReadBudget(15)

try:
    svc = MarketContextService(provider, lambda: {"available_margin": 10663.1})
    ctx = svc.fetch()
    print("=" * 65)
    print(f"LIVE MARKET DIAGNOSTIC AT {now.strftime('%H:%M:%S')} IST")
    print("=" * 65)
    spot = ctx["spot"]
    vwap = ctx["session_vwap"]
    ema9 = ctx["ema_9"]
    ema20 = ctx["ema_20"]
    ema50 = ctx["ema_50"]
    rsi = ctx["rsi_14"]
    day_open = ctx.get("open") or candles_first_open if "open" in ctx else "N/A"
    
    candles_1m = ctx.get("candles_1m", [])
    open_p = candles_1m[0]["open"] if candles_1m else spot
    high_p = max(c["high"] for c in candles_1m) if candles_1m else spot
    low_p = min(c["low"] for c in candles_1m) if candles_1m else spot
    
    print(f"NIFTY Spot:     {spot:.2f}")
    print(f"Session Open:   {open_p:.2f}")
    print(f"Session High:   {high_p:.2f}")
    print(f"Session Low:    {low_p:.2f}")
    print(f"Net From Open:  {spot - open_p:+.2f} pts")
    print(f"Session VWAP:   {vwap:.2f} (Dist: {spot - vwap:+.2f} pts)")
    print(f"5m EMA 9:       {ema9:.2f} (Dist: {spot - ema9:+.2f} pts)")
    print(f"5m EMA 20:      {ema20:.2f}")
    print(f"5m EMA 50:      {ema50:.2f}")
    print(f"Spot RSI-14:    {rsi:.2f}")
    print(f"15m Box Spread: {ctx.get('box_spread_15m')} pts ({ctx.get('box_low_15m')} to {ctx.get('box_high_15m')})")
    print(f"Total 1m Bars:  {len(candles_1m)}")

    print("\n" + "-" * 65)
    print("HISTORICAL MINUTE-BY-MINUTE SIGNAL AUDIT (09:15 to NOW):")
    print("-" * 65)
    radar = AIOpportunityRadar()
    
    # Calculate RSI history across candles
    from trading.domain.indicators import simple_rsi
    closes = [c["close"] for c in candles_1m]
    rsi_history = []
    for i in range(len(closes)):
        if i < 14:
            rsi_history.append(50.0)
        else:
            rsi_history.append(simple_rsi(closes[:i+1], 14))

    found_radar_setups = []
    for i in range(10, len(candles_1m)):
        bar = candles_1m[i]
        bar_time = bar["start_time"][11:16]
        
        # Calculate sub-session VWAP up to this bar
        typicals = [(c["high"] + c["low"] + c["close"]) / 3.0 for c in candles_1m[:i+1]]
        sub_vwap = sum(typicals) / len(typicals)
        
        # 15m box up to this bar
        recent_15 = candles_1m[max(0, i-14): i+1]
        b_high = max(c["high"] for c in recent_15)
        b_low = min(c["low"] for c in recent_15)
        
        opp = radar.evaluate(
            bar_idx=i,
            bar=bar,
            all_bars=candles_1m[:i+1],
            spot_closes=closes[:i+1],
            session_vwap=sub_vwap,
            ema9=ema9,
            ema20=ema20,
            rsi=rsi_history[i],
            rsi_history=rsi_history[:i+1],
            day_open=open_p,
            box_high=b_high,
            box_low=b_low
        )
        if opp and opp.action != "STAND_ASIDE":
            found_radar_setups.append((bar_time, opp))
            print(f"  [{bar_time} IST] >>> {opp.action} ({opp.regime}) Conviction: {opp.conviction}%")
            print(f"             Thesis: {opp.thesis}")
            print(f"             Invalidation: {opp.invalidation_level}")
    
    if not found_radar_setups:
        print("  - No Strategy 4 Opportunity Radar setups triggered between 09:15 and now.")
        print(f"    (Min RSI reached today: {min(rsi_history):.1f} | Max Drop from Open: {low_p - open_p:.1f} pts).")

    print("\n" + "-" * 65)
    print("STRATEGY 5: 2-MINUTE MACD MOMENTUM AUDIT:")
    print("-" * 65)
    bars_2m = resample_1m_to_2m(candles_1m, as_of=now)
    print(f"Completed 2m Bars Today: {len(bars_2m)}")
    for idx, b in enumerate(bars_2m):
        t = b["start_time"][11:16]
        print(f"  Bar {idx+1:02d} [{t} IST]: O={b['open']:.2f}, H={b['high']:.2f}, L={b['low']:.2f}, C={b['close']:.2f}")
    
    with open("config/strategies.json") as f:
        strat_cfg = json.load(f)["strategies"]["macd_momentum"]
    macd_strat = MacdMomentumStrategy(strat_cfg)
    macd_res = macd_strat.evaluate(ctx)
    print(f"\nOfficial Strategy 5 Evaluation: {macd_res.signal}")
    for r in macd_res.reasons:
        print(f"  - {r}")

    # Microstructure MACD preview (if calculated on available 2m bars):
    if len(bars_2m) >= 6:
        closes = [b["close"] for b in bars_2m]
        # fast=3, slow=6, signal=3 for mini early look
        m_fast, s_slow, h_mini = calculate_macd(closes, 4, min(10, len(closes)-1), 3)
        print(f"\nEarly Microstructure MACD (on {len(bars_2m)} bars):")
        print(f"  - MACD Line: {m_fast[-1]:.2f} | Signal: {s_slow[-1]:.2f} | Hist: {h_mini[-1]:+.2f}")
        prev_diff = m_fast[-2] - s_slow[-2]
        curr_diff = m_fast[-1] - s_slow[-1]
        print(f"  - Momentum Trend: {'Bullish Divergence' if curr_diff > 0 else 'Bearish Pressure'}")

finally:
    provider.close()
