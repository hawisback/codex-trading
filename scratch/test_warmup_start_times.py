import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

import scratch.dissect_user_proposals as d

print("Testing Warmup with different Start Times (Rolling 2m)...")
# Time indices: 
# 15 = 09:30
# 20 = 09:35
# 25 = 09:40
# 30 = 09:45
# 35 = 09:50
# 40 = 09:55
# 45 = 10:00
# 54 = 10:09 (Current default without warmup)

times = [
    (15, "09:30 AM"),
    (20, "09:35 AM"),
    (25, "09:40 AM"),
    (30, "09:45 AM"),
    (35, "09:50 AM"),
    (40, "09:55 AM"),
    (45, "10:00 AM"),
    (50, "10:05 AM"),
    (54, "10:09 AM"),
]

for t_idx, t_name in times:
    res = d.simulate_strategy(rolling=True, warmup=True, start_min=t_idx, vwap_climax=50.0, min_15m_range=24.0)
    print(f"Start: {t_name:10} (min {t_idx:2d}) | {res['trades']:2d} Trades | {res['wins']:2d}W / {res['losses']:2d}L ({res['wr']:4.1f}%) | PF: {res['pf']:4.2f} | PnL: Rs {res['pnl']:+10.2f}")
