import json

with open('scratch/production_backtest_30_sessions_results.json') as f:
    d = json.load(f)

trades = d['trades']
print("=" * 120)
print(f"ALL {len(trades)} PRODUCTION TRADES (STRATEGY 5 - CURRENT CODEBASE)")
print("=" * 120)
print(f"{'#':<3} {'Date':<11} {'Entry':<6} {'Exit':<6} {'Seg':<9} {'Dir':<4} {'Strike':<6} {'EntryP':<7} {'ExitP':<7} {'Peak%':<6} {'PnL (2L)':<10} {'Equity':<10} {'Result':<5} {'Exit Reason':<28}")
print("-" * 120)

for idx, t in enumerate(trades, 1):
    res_str = "WIN" if t['is_win'] else "LOSS"
    pnl_str = f"+Rs {t['pnl_2lots']:,.2f}" if t['pnl_2lots'] > 0 else f"-Rs {abs(t['pnl_2lots']):,.2f}"
    eq_str = f"Rs {t['equity_after']:,.2f}"
    print(f"{idx:<3} {t['date']:<11} {t['entry_time']:<6} {t['exit_time']:<6} {t['segment']:<9} {t['direction']:<4} {t['strike']:<6} {t['entry_price']:<7.2f} {t['exit_price']:<7.2f} {t['peak_gain_pct']:<6.1f} {pnl_str:<10} {eq_str:<10} {res_str:<5} {t['exit_reason']:<28}")

print("=" * 120)
