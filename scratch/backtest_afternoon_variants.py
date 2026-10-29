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
    
    print("=" * 95)
    print(f" EXPERIMENTAL BACKTEST: TODAY'S AFTERNOON OPTIMIZATION ({target_date})")
    print(f" Real 1-minute Option Candles: {not engine.is_synthetic_options} | Total Bars: {len(engine.spot_candles)}")
    print("=" * 95)

    base_cfg = StrategyConfig.load_from_config("institutional_pullback")

    variants = [
        ("Base Strategy 3 (Pullback <= 4.0 pts)", base_cfg),
        ("Variant A: Pullback <= 8.0 pts", replace(base_cfg, pullback_ema_tolerance_pts=8.0)),
        ("Variant B: Pullback <= 12.0 pts", replace(base_cfg, pullback_ema_tolerance_pts=12.0)),
        ("Variant C: Pullback <= 16.0 pts", replace(base_cfg, pullback_ema_tolerance_pts=16.0)),
        ("Variant D: Breakout (No Pullback Required)", replace(base_cfg, require_pullback=False)),
        ("Variant E: Breakout + 10m Spacing", replace(base_cfg, require_pullback=False, min_spacing_bars=10)),
        ("Variant F: 15m Range Box Breakout Only", replace(base_cfg, require_pullback=False, enable_range_box_filter=True, range_box_spread_min=28.0)),
    ]

    print(f"{'Strategy Variant':<42} | {'Trades':<7} | {'Win%':<7} | {'Gross PnL':<12} | {'Net (1 Lot)':<14} | {'Best Trade':<12}")
    print("-" * 95)

    for label, cfg in variants:
        trades = engine.run_simulation(cfg)
        m = calculate_metrics(trades)
        t_count = len(trades)
        win_pct = f"{m['win_rate']:.1f}%" if t_count > 0 else "N/A"
        friction = t_count * 40.0
        net = m["net_pnl"] - friction
        best_pnl = max((t.pnl for t in trades), default=0.0)
        print(f"{label:<42} | {t_count:<7} | {win_pct:<7} | Rs {m['net_pnl']:+9,.2f} | Rs {net:+11,.2f} | Rs {best_pnl:+9,.2f}")

    # Detailed trade breakdown for Variant D (Breakout / No Pullback)
    print("\n" + "=" * 95)
    print(" DETAILED TRADES FOR VARIANT D (NO PULLBACK REQUIRED / PURE MOMENTUM):")
    print("=" * 95)
    cfg_d = replace(base_cfg, require_pullback=False)
    trades_d = engine.run_simulation(cfg_d)
    for t in trades_d:
        pnl = (t.exit_price - t.entry_price) * 65.0
        print(f"  Bar {t.entry_bar:<3} ({t.entry_time[-14:-6]} IST) | {t.direction:<2} Strike {t.strike} @ Rs {t.entry_price:<6.2f} -> Exit @ Rs {t.exit_price:<6.2f} | PnL: Rs {pnl:+8.2f} ({t.pnl_pct:+5.1f}%) | Reason: {t.exit_reason}")

if __name__ == "__main__":
    main()
