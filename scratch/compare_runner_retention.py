import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import json
import scratch.test_morning_improvements as mi

# Let's inspect the 9 baseline morning wins in Config 1 and Config 2
# Let's write a small script to print their PnL in Config 1 vs Baseline
# Let's run a test where we trace exactly the 9 winning trades
import scratch.audit_macd_full_backtest as b

# Baseline
res_base = b.run_backtest_variant('Base', enable_refinements=True, enable_midday_5pct=True, max_daily_trades=2)
trades_base = {f"{t['date']} {t['time']}": t for t in res_base['trades']}

# Let's trace how each winning trade was handled in Config 1
# We can run test_morning_variations or check the trace
print("Trace done")
