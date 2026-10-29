import os
import sys
import json
from dataclasses import replace

sys.path.insert(0, ".")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics

def main():
    target_date = "2026-10-14"
    engine = BacktestEngine(target_date=target_date)
    
    # Filter candles to afternoon only (from 12:30 IST = 07:00 UTC, which is bar ~195)
    # Let's inspect bar start times
    bar_1230_idx = 0
    for idx, c in enumerate(engine.spot_candles):
        st = c.get("start_time", "")
        if "T07:00:" in st or "07:00:00" in st:
            bar_1230_idx = idx
            break

    print("=" * 95)
    print(f" AFTERNOON-ONLY BACKTEST: FLAT BOOK AT 12:30 IST (BAR {bar_1230_idx})")
    print(f" Simulating purely the afternoon session (12:30 to 15:30 IST)")
    print("=" * 95)

    base_cfg = StrategyConfig.load_from_config("institutional_pullback")

    variants = [
        ("Base Strategy 3 (Pullback <= 4.0 pts)", base_cfg),
        ("Variant A: Pullback <= 8.0 pts", replace(base_cfg, pullback_ema_tolerance_pts=8.0)),
        ("Variant B: Pullback <= 12.0 pts", replace(base_cfg, pullback_ema_tolerance_pts=12.0)),
        ("Variant C: Breakout (require_pullback=False)", replace(base_cfg, require_pullback=False)),
        ("Variant D: Breakout + 15m Range Box Spread 28", replace(base_cfg, require_pullback=False, enable_range_box_filter=True, range_box_spread_min=28.0)),
    ]

    # Temporarily slice candles to afternoon only
    orig_candles = engine.spot_candles
    engine.spot_candles = orig_candles[bar_1230_idx:]

    print(f"{'Strategy Variant':<45} | {'Trades':<7} | {'Win%':<7} | {'Gross PnL':<12} | {'Net (1 Lot)':<14}")
    print("-" * 95)

    for label, cfg in variants:
        trades = engine.run_simulation(cfg)
        m = calculate_metrics(trades)
        t_count = len(trades)
        win_pct = f"{m['win_rate']:.1f}%" if t_count > 0 else "N/A"
        friction = t_count * 40.0
        net = m["net_pnl"] - friction
        print(f"{label:<45} | {t_count:<7} | {win_pct:<7} | Rs {m['net_pnl']:+9,.2f} | Rs {net:+11,.2f}")
        for t in trades:
            pnl = (t.exit_price - t.entry_price) * 65.0
            print(f"   -> Bar {t.entry_bar} ({t.entry_time}) | {t.direction} {t.strike} @ Rs {t.entry_price:.2f} -> Exit @ Rs {t.exit_price:.2f} ({t.exit_reason}) | PnL: Rs {pnl:+.2f} ({t.pnl_pct:+.1f}%)")

if __name__ == "__main__":
    main()
