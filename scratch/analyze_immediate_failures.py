import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import json, os
from datetime import datetime, timedelta
from trading.domain.market_data import resample_two_minutes
from trading.strategies.macd_momentum import calculate_macd
import scratch.audit_macd_full_backtest as b

res = b.run_backtest_variant('Refined + Midday 5% Trail', enable_refinements=True, enable_midday_5pct=True, max_daily_trades=2)
trades = res['trades']

immediate_fails = [t for t in trades if not t['is_win'] and not t['is_midday'] and int(t['time'].split(':')[0]) < 12 and t['peak_gain_pct'] < 4.0]

print("=" * 120)
print(f"DEEP DIVE: 5 IMMEDIATE MORNING FAILURES (Peak < 4.0%)")
print("=" * 120)

for t in immediate_fails:
    dt_str = t['date']
    spot_bars, _ = b.load_session_data(dt_str)
    
    # parse time
    parts = t['time'].split(':')
    trade_m = (int(parts[0]) - 9) * 60 + (int(parts[1]) - 15)
    
    bars_so_far = spot_bars[:trade_m + 1]
    spot_p = spot_bars[trade_m]["close"]
    vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
    dist_vwap = spot_p - vwap
    
    # Opening 15m range (09:15 - 09:30 = first 15 bars)
    orh = max(x["high"] for x in spot_bars[:15])
    orl = min(x["low"] for x in spot_bars[:15])
    or_spread = orh - orl
    
    # 2m MACD metrics
    res_2m = resample_two_minutes(bars_so_far)
    closes_2m = [x["close"] for x in res_2m]
    macd, sig, hist = calculate_macd(closes_2m)
    
    # Check 5m EMA
    # Resample 5m
    closes_1m = [x["close"] for x in bars_so_far]
    
    print(f"Date: {dt_str} Time: {t['time']} | Dir: {t['direction']} {t['strike']}")
    print(f"  Spot: {spot_p:.1f} | VWAP: {vwap:.1f} (Dist: {dist_vwap:+.1f} pts)")
    print(f"  Opening 15m Range: High {orh:.1f} - Low {orl:.1f} (Spread: {or_spread:.1f} pts)")
    print(f"  Spot vs Opening Range: High - Spot = {orh - spot_p:+.1f} pts | Spot - Low = {spot_p - orl:+.1f} pts")
    print(f"  MACD Hist: {hist[-1]:.3f} | Signal: {sig[-1]:.3f} | Line: {macd[-1]:.3f}")
    
    # Check what happened in next 5-10 bars
    next_bars = spot_bars[trade_m+1: min(len(spot_bars), trade_m + 16)]
    spot_next_high = max(x["high"] for x in next_bars)
    spot_next_low = min(x["low"] for x in next_bars)
    print(f"  Next 15 mins Spot High/Low: {spot_next_high:.1f} / {spot_next_low:.1f} (Move: {spot_next_high - spot_p:+.1f} / {spot_next_low - spot_p:+.1f})")
    print("-" * 120)
