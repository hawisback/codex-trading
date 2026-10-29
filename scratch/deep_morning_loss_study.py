import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import json
import scratch.audit_macd_full_backtest as b

res_base = b.run_backtest_variant('Base', enable_refinements=True, enable_midday_5pct=True, max_daily_trades=2)
morn_losses = [t for t in res_base['trades'] if not t['is_win'] and not t['is_midday'] and int(t['time'].split(':')[0]) < 12]

print(f"{'Date':<11} {'Time':<6} {'Dir':<4} {'Strike':<6} {'Entry':<7} {'Exit':<7} {'Peak%':<6} {'PnL':<10} {'Reason':<20}")
print("-" * 90)
for t in morn_losses:
    print(f"{t['date']:<11} {t['time']:<6} {t['direction']:<4} {t['strike']:<6} {t['entry_p']:<7.2f} {t['exit_p']:<7.2f} {t['peak_gain_pct']:<6.1f} {t['pnl_2lots']:<10.2f} {t['exit_reason']:<20}")
