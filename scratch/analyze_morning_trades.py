import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import scratch.audit_macd_full_backtest as b
import json

res = b.run_backtest_variant('Refined + Midday 5% Trail', enable_refinements=True, enable_midday_5pct=True, max_daily_trades=2)
trades = res['trades']

morn_trades = [t for t in trades if not t['is_midday'] and int(t['time'].split(':')[0]) < 12]

print("=" * 120)
print(f"FORENSIC AUDIT OF ALL {len(morn_trades)} MORNING TRADES (09:15 - 11:30 IST)")
print("=" * 120)
print(f"{'#':<3} {'Date':<11} {'Time':<6} {'Dir':<4} {'Strike':<6} {'Entry':<7} {'Exit':<7} {'Peak%':<7} {'PnL (2L)':<10} {'Result':<6} {'Exit Reason':<20}")
print("-" * 120)

for idx, t in enumerate(morn_trades, 1):
    res_str = "WIN" if t['is_win'] else "LOSS"
    pnl_str = f"+Rs {t['pnl_2lots']:,.2f}" if t['pnl_2lots'] > 0 else f"-Rs {abs(t['pnl_2lots']):,.2f}"
    print(f"{idx:<3} {t['date']:<11} {t['time']:<6} {t['direction']:<4} {t['strike']:<6} {t['entry_p']:<7.2f} {t['exit_p']:<7.2f} {t['peak_gain_pct']:<7.1f} {pnl_str:<10} {res_str:<6} {t['exit_reason']:<20}")

print("=" * 120)

# Break down losses by time bucket
losses = [t for t in morn_trades if not t['is_win']]
print(f"\nTotal Morning Losses: {len(losses)} / {len(morn_trades)}")

print("\nLosses by Time Bucket:")
b1 = [t for t in losses if t['time'] < "10:00"]
b2 = [t for t in losses if "10:00" <= t['time'] < "10:45"]
b3 = [t for t in losses if t['time'] >= "10:45"]
print(f"  09:15 - 10:00: {len(b1)} losses")
print(f"  10:00 - 10:45: {len(b2)} losses")
print(f"  10:45 - 11:30: {len(b3)} losses")

print("\nLosses by Peak Gain:")
p_high = [t for t in losses if t['peak_gain_pct'] >= 8.0]
p_mid = [t for t in losses if 4.0 <= t['peak_gain_pct'] < 8.0]
p_low = [t for t in losses if t['peak_gain_pct'] < 4.0]
print(f"  Peak Gain >= +8.0%: {len(p_high)} trades (gave back substantial gains!)")
for t in p_high:
    print(f"    - {t['date']} {t['time']} {t['direction']} Peak: +{t['peak_gain_pct']}% -> PnL: Rs {t['pnl_2lots']} ({t['exit_reason']})")
print(f"  Peak Gain +4.0% to +8.0%: {len(p_mid)} trades")
for t in p_mid:
    print(f"    - {t['date']} {t['time']} {t['direction']} Peak: +{t['peak_gain_pct']}% -> PnL: Rs {t['pnl_2lots']} ({t['exit_reason']})")
print(f"  Peak Gain < +4.0%: {len(p_low)} trades (immediate fail / adverse from start)")
for t in p_low:
    print(f"    - {t['date']} {t['time']} {t['direction']} Peak: +{t['peak_gain_pct']}% -> PnL: Rs {t['pnl_2lots']} ({t['exit_reason']})")
