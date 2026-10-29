import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import scratch.audit_macd_full_backtest as b

res = b.run_backtest_variant('Refined + Midday', enable_refinements=True, enable_midday_5pct=True, max_daily_trades=2)
trades = res['trades']

print("\n--- ALL MORNING TRADES (09:15 - 11:30) ---")
morn_trades = [t for t in trades if not t['is_midday'] and int(t['time'].split(':')[0]) < 12]
for t in morn_trades:
    status = "WIN " if t['is_win'] else "LOSS"
    print(f"{t['date']} {t['time']} | {status} | {t['direction']} {t['strike']} | Entry: {t['entry_p']:6.2f} Exit: {t['exit_p']:6.2f} | Peak: +{t['peak_gain_pct']:4.1f}% | PnL: Rs {t['pnl_2lots']:+8.2f} | {t['exit_reason']}")
