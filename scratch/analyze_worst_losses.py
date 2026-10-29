import os
import sys

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from backtest_engine import BacktestEngine, StrategyConfig

dates_w1_3 = [
    ("2026-08-31", "Mon Aug 31"),
    ("2026-09-01", "Tue Sep 01 (0DTE)"),
    ("2026-09-02", "Wed Sep 02"),
    ("2026-09-03", "Thu Sep 03"),
    ("2026-09-04", "Fri Sep 04"),
    ("2026-09-07", "Mon Sep 07"),
    ("2026-09-08", "Tue Sep 08 (0DTE)"),
    ("2026-09-09", "Wed Sep 09"),
    ("2026-09-10", "Thu Sep 10"),
    ("2026-09-11", "Fri Sep 11"),
    ("2026-09-15", "Tue Sep 15 (0DTE)"),
    ("2026-09-16", "Wed Sep 16"),
    ("2026-09-17", "Thu Sep 17"),
    ("2026-09-18", "Fri Sep 18"),
]

s3 = StrategyConfig.load_from_config("institutional_pullback")

losses = []
for d, label in dates_w1_3:
    eng = BacktestEngine(d)
    if not eng.spot_candles:
        continue
    trades = eng.run_simulation(s3)
    for t in trades:
        if t.pnl < -500:
            losses.append((d, label, t, eng))

# Sort by loss descending (worst losses first)
losses.sort(key=lambda x: x[2].pnl)

print("=" * 120)
print(f"TOP {min(15, len(losses))} WORST LOSSES IN WEEKS 1-3:")
print("=" * 120)

for d, label, t, eng in losses[:15]:
    idx = t.entry_bar
    c = eng.spot_candles[idx]
    
    # Intraday context up to entry bar
    prior_bars = eng.spot_candles[:idx+1]
    dh = max(b["high"] for b in prior_bars)
    dl = min(b["low"] for b in prior_bars)
    drange = dh - dl
    
    # Distance to day high / low
    dist_high = dh - c["close"]
    dist_low = c["close"] - dl
    pos_in_range_pct = (c["close"] - dl) / drange * 100 if drange > 0 else 50.0
    
    # Spot typicals for VWAP
    typs = [(b["high"] + b["low"] + b["close"])/3.0 for b in prior_bars]
    vwap = sum(typs) / len(typs)
    vwap_dist = c["close"] - vwap
    
    # 5m EMA9 and EMA20
    closes = [b["close"] for b in prior_bars]
    bars_5m = [closes[i] for i in range(4, len(closes), 5)] or [c["close"]]
    ema9 = eng.calculate_ema(bars_5m, 9)
    ema20 = eng.calculate_ema(bars_5m, 20)
    rsi = eng.calculate_rsi(closes, 14)
    
    # Check what spot did after entry (next 30 bars)
    subsequent = eng.spot_candles[idx: min(idx+45, len(eng.spot_candles))]
    sub_min = min(b["low"] for b in subsequent)
    sub_max = max(b["high"] for b in subsequent)
    sub_move = subsequent[-1]["close"] - c["close"]
    
    print(f"\n{label} | {t.direction} @ {t.entry_time[:5]} | PnL: Rs {t.pnl:>8.2f} ({t.pnl_pct:>5.1f}%) | Exit: {t.exit_reason}")
    print(f"  Spot @ Entry: {c['close']:.1f} | Day High: {dh:.1f} (-{dist_high:.1f} pts) | Day Low: {dl:.1f} (+{dist_low:.1f} pts) | Range Pos: {pos_in_range_pct:.1f}%")
    print(f"  VWAP: {vwap:.1f} (Dist: {vwap_dist:+.1f} pts) | 5m EMA9: {ema9:.1f} | EMA20: {ema20:.1f} | RSI: {rsi:.1f}")
    print(f"  Subsequent 45m Spot Move: {sub_move:+.1f} pts (Min: {sub_min:.1f}, Max: {sub_max:.1f})")
