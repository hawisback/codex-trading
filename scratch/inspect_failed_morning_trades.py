import json
import sys

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

import scratch.run_production_backtest_30_sessions as r
from trading.domain.market_data import exchange_time

dates_to_inspect = [
    ("2026-10-07", 26), # ~09:41
    ("2026-10-14", 23), # ~09:38
    ("2026-10-22", 16), # ~09:31
    ("2026-10-27", 36), # ~09:51
]

for dt, bar_idx in dates_to_inspect:
    spot_bars, _ = r.load_session_data(dt)
    if not spot_bars: continue
    
    # 09:15 - 09:30 opening range
    or_high = max(b["high"] for b in spot_bars[:15])
    or_low = min(b["low"] for b in spot_bars[:15])
    or_range = or_high - or_low
    
    sb = spot_bars[bar_idx]
    t_str = exchange_time(sb["start_time"]).strftime("%H:%M")
    spot_p = sb["close"]
    
    # VWAP
    vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in spot_bars[:bar_idx+1]) / (bar_idx + 1)
    
    # Position relative to OR
    in_or = (or_low <= spot_p <= or_high)
    dist_or_break = (spot_p - or_high) if spot_p > or_high else ((or_low - spot_p) if spot_p < or_low else 0)
    
    print(f"\n--- {dt} at {t_str} (Bar {bar_idx}) ---")
    print(f"  Spot: {spot_p:.1f} | VWAP: {vwap:.1f}")
    print(f"  Opening Range (09:15-09:30): Low {or_low:.1f} - High {or_high:.1f} (Span: {or_range:.1f} pts)")
    print(f"  Is Spot Inside OR?: {in_or} | Breakout distance: {dist_or_break:.1f} pts")
    # Next 5 bars price action
    subsequent = spot_bars[bar_idx+1:bar_idx+10]
    sub_closes = [round(b["close"], 1) for b in subsequent]
    print(f"  Subsequent closes: {sub_closes}")
