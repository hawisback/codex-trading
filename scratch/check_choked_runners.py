import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import json
import scratch.audit_macd_full_backtest as b

res_base = b.run_backtest_variant('Base', enable_refinements=True, enable_midday_5pct=True, max_daily_trades=2)
morn_wins_base = [t for t in res_base['trades'] if t['is_win'] and not t['is_midday'] and int(t['time'].split(':')[0]) < 12]

print("BASELINE 9 MORNING WINS:")
for t in morn_wins_base:
    print(f"{t['date']} {t['time']} | {t['direction']} {t['strike']} | Peak: +{t['peak_gain_pct']:.1f}% | PnL: Rs {t['pnl_2lots']:+8.2f}")

tot_base_win_pnl = sum(t['pnl_2lots'] for t in morn_wins_base)
print(f"Total PnL from Baseline Morning Wins: Rs {tot_base_win_pnl:+,.2f}")
