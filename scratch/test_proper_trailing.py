import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()

import json

entry_price = 53.75

with open("data/opt_20261027_22750_CE.json", "r") as fp:
    candles = json.load(fp)

def test_trailing(aggressive_pullback_pct=10.0):
    peak = entry_price
    current_stop = entry_price * 0.70
    exit_price = None
    exit_time = None
    exit_reason = None
    
    for c in candles:
        t = c.get("start_time", "")[11:16]
        if t < "12:33" or t > "13:15":
            continue
            
        opt_open = c["open"]
        opt_high = c["high"]
        opt_low = c["low"]
        opt_close = c["close"]
        
        if opt_low <= current_stop:
            exit_price = min(current_stop, opt_open)
            exit_time = t
            exit_reason = f"STOP HIT (Floor Rs {current_stop:.2f})"
            break
            
        if opt_high > peak:
            peak = opt_high
            
        gain_pct = ((peak - entry_price) / entry_price) * 100.0
        
        if gain_pct >= 40.0:
            current_stop = max(current_stop, entry_price * 1.30)
        elif gain_pct >= 30.0:
            current_stop = max(current_stop, entry_price * 1.20)
        elif gain_pct >= 20.0:
            current_stop = max(current_stop, entry_price * 1.10)
            
        if gain_pct >= 50.0:
            trail_level = peak * (1.0 - aggressive_pullback_pct / 100.0)
            current_stop = max(current_stop, trail_level)

    gain_realized = ((exit_price - entry_price) / entry_price) * 100.0
    print(f"Aggressive Pullback: {aggressive_pullback_pct:<4.1f}% | Exit Time: {exit_time} | Exit Price: Rs {exit_price:<6.2f} | Realized PnL: +{gain_realized:<5.1f}% | Reason: {exit_reason}")

print("Testing Dynamic Ratchet Trailing on 12:33 Trade (Entry: Rs 53.75, Peak: Rs 109.30):")
print("-" * 100)
test_trailing(aggressive_pullback_pct=5.0)
test_trailing(aggressive_pullback_pct=7.5)
test_trailing(aggressive_pullback_pct=10.0)
test_trailing(aggressive_pullback_pct=15.0)
