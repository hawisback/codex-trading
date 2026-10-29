import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import json
import scratch.audit_macd_full_backtest as b

res = b.run_backtest_variant('Base', enable_refinements=True, enable_midday_5pct=True, max_daily_trades=2)
trades = res['trades']

target_dates = [
    ("2026-09-15", "10:52", "PE"),
    ("2026-09-22", "10:08", "CE"),
    ("2026-09-25", "10:32", "PE"),
    ("2026-09-28", "10:26", "PE"),
    ("2026-10-01", "10:20", "PE")
]

print("=" * 110)
print("DEEP CANDLE REPLAY: 5 MORNING TRADES WITH +8% TO +19% PEAK GAINS THAT REVERSED")
print("=" * 110)

for dt_str, tr_time, tr_dir in target_dates:
    t = [x for x in trades if x['date'] == dt_str and x['time'] == tr_time][0]
    spot_bars, opt_candles = b.load_session_data(dt_str)
    
    parts = tr_time.split(':')
    trade_m = (int(parts[0]) - 9) * 60 + (int(parts[1]) - 15)
    entry_spot = spot_bars[trade_m]["close"]
    
    # Trace bar by bar for 30 minutes after entry
    print(f"\n--- {dt_str} {tr_time} | {tr_dir} {t['strike']} | Entry Price: {t['entry_p']:.2f} | Peak Gain: +{t['peak_gain_pct']:.1f}% ---")
    entry_p = t['entry_p']
    
    peak_so_far = entry_p
    for step in range(1, 31):
        idx = trade_m + step
        if idx >= len(spot_bars): break
        sb = spot_bars[idx]
        t_str = f"{(idx+15)//60+9:02d}:{(idx+15)%60:02d}"
        
        # Option price
        days_base = 1.0
        p_open, p_high, p_low, p_close = b.get_option_price(sb["close"], t['strike'], tr_dir, idx, days_base, opt_candles, spot_bars)
        if p_high > peak_so_far: peak_so_far = p_high
        gain_at_bar = ((p_close - entry_p) / entry_p) * 100.0
        peak_gain_at_bar = ((peak_so_far - entry_p) / entry_p) * 100.0
        
        if step in (1, 3, 5, 8, 10, 15, 20, 25):
            print(f"  + {step:2d}m ({t_str}): Spot {sb['close']:8.1f} | Opt Close {p_close:6.2f} ({gain_at_bar:+5.1f}%) | Opt Peak {peak_so_far:6.2f} (+{peak_gain_at_bar:4.1f}%)")
    print(f"  Final Exit: {t['exit_p']:.2f} ({t['exit_reason']}) | PnL: Rs {t['pnl_2lots']:+,.2f}")
