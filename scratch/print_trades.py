import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from scratch.backtest_macd_rsi_volume_matrix import run_matrix_backtest

print("=" * 80)
print("=== 2m FUTURES REVERSAL (3 Trades / 100% Win) ===")
print("=" * 80)
res_rev = run_matrix_backtest(2, 'FUTURES', True)
for t in res_rev['trades']:
    hh = t['entry_idx'] // 60 + 9
    mm = t['entry_idx'] % 60
    print(f"{t['date']} | {hh:02d}:{mm:02d} IST | {t['direction']} {t['strike']} | Entry: {t['entry_price']} | Exit: {t['exit_price']} ({t['ret_pct']:+5.1f}%) | Peak: +{t['peak_gain_pct']}% | PnL: INR {t['pnl_inr']:+8.2f} | {t['exit_reason']}")

print("\n" + "=" * 80)
print("=== 2m OPTIONS TREND (5 Trades / +INR 9,313 PnL / 60% Win) ===")
print("=" * 80)
res_opt = run_matrix_backtest(2, 'OPTIONS', False)
for t in res_opt['trades']:
    hh = t['entry_idx'] // 60 + 9
    mm = t['entry_idx'] % 60
    print(f"{t['date']} | {hh:02d}:{mm:02d} IST | {t['direction']} {t['strike']} | Entry: {t['entry_price']} | Exit: {t['exit_price']} ({t['ret_pct']:+5.1f}%) | Peak: +{t['peak_gain_pct']}% | PnL: INR {t['pnl_inr']:+8.2f} | {t['exit_reason']}")

print("\n" + "=" * 80)
print("=== 2m FUTURES TREND (7 Trades / +INR 6,011 PnL) ===")
print("=" * 80)
res_fut_tr = run_matrix_backtest(2, 'FUTURES', False)
for t in res_fut_tr['trades']:
    hh = t['entry_idx'] // 60 + 9
    mm = t['entry_idx'] % 60
    print(f"{t['date']} | {hh:02d}:{mm:02d} IST | {t['direction']} {t['strike']} | Entry: {t['entry_price']} | Exit: {t['exit_price']} ({t['ret_pct']:+5.1f}%) | Peak: +{t['peak_gain_pct']}% | PnL: INR {t['pnl_inr']:+8.2f} | {t['exit_reason']}")
