import json
import os
import sys

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

import scratch.dissect_user_proposals as d

res = d.simulate_strategy(rolling=True, warmup=True, start_min=15, vwap_climax=50.0, min_15m_range=24.0)

early_trades = [t for t in res["trade_list"] if t["entry_time"] < "10:00"]
print(f"Total Early Trades (< 10:00 AM): {len(early_trades)}")
for t in early_trades:
    status = "WIN " if t["is_win"] else "LOSS"
    print(f"{t['date']} {t['entry_time']} -> {t['exit_time']} | {status} | {t['direction']} {t['strike']} | Peak: +{t['peak_gain_pct']:4.1f}% | PnL: Rs {t['pnl_2lots']:+8.2f} | {t['exit_reason']}")
