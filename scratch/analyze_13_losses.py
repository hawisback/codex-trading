import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

def run_forensic_loss_analysis():
    s3 = StrategyConfig.load_from_config("institutional_pullback")
    c = AIConsultant(mode="playbook")

    weeks = [
        ("Week 8", ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]),
        ("Week 9", ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]),
        ("Week 10", ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]),
    ]

    losing_trades = []
    winning_trades = []

    for w_name, days in weeks:
        for d in days:
            eng = BacktestEngine(d)
            raw = eng.run_simulation(s3)
            dte = eng.get_expiry_days()
            for i, t in enumerate(raw, 1):
                idx = [k for k, x in enumerate(eng.spot_candles) if t.entry_time in x["start_time"]][0]
                dos = generate_market_dossier(d, eng.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, (dte <= 0.2))
                v = c.evaluate(dos)
                if v.is_approved:
                    if t.pnl <= 0:
                        losing_trades.append((w_name, d, t, dos, v))
                    else:
                        winning_trades.append((w_name, d, t, dos, v))

    print("=" * 130)
    print(f" 🔎 DETAILED AUDIT OF THE 13 FAILED TRADES ACROSS WEEKS 8, 9, 10")
    print(f" Total Approved: {len(winning_trades) + len(losing_trades)} | Wins: {len(winning_trades)} | Losses: {len(losing_trades)}")
    print("=" * 130)

    header = f"{'#':<2} | {'Week':<7} | {'Date':<10} | {'Dir':<3} | {'Entry (IST)':<11} | {'Exit (IST)':<11} | {'Entry ₹':<7} | {'Exit ₹':<7} | {'PnL ₹ (1 Lot)':<13} | {'PnL %':<7} | {'Exit Reason'}"
    print(header)
    print("-" * 130)

    for idx, (w, d, t, dos, v) in enumerate(losing_trades, 1):
        print(f"{idx:<2} | {w:<7} | {d:<10} | {t.direction:<3} | {dos.time_ist:<11} | {t.exit_time:<11} | {t.entry_price:<7.2f} | {t.exit_price:<7.2f} | {t.pnl:<13.2f} | {t.pnl_pct:<7.1f}% | {t.exit_reason}")

    print("\n" + "=" * 130)
    print(" 🔬 TECHNICAL INDICATOR DOSSIER AT ENTRY FOR EACH LOSING TRADE")
    print("=" * 130)

    for idx, (w, d, t, dos, v) in enumerate(losing_trades, 1):
        print(f"\n--- LOSS #{idx}: {d} ({w}) {t.direction} @ {dos.time_ist} (Exit {t.exit_time} | PnL: ₹{t.pnl:.2f}, {t.pnl_pct:.1f}%) ---")
        print(f"  • Spot: {dos.spot_price:.2f} | Strike: {dos.strike} {t.direction} | Option Entry: ₹{dos.option_entry_price:.2f} | DTE: {dos.days_to_expiry:.2f} (0DTE={dos.is_expiry_0dte})")
        print(f"  • Session Phase: {dos.session_phase} | Mins From Open: {dos.minutes_from_open}m | Mins To Close: {dos.minutes_to_close}m")
        print(f"  • VWAP: {dos.session_vwap:.2f} | Dist to VWAP: {dos.vwap_distance_pts:+.2f} pts | 15m VWAP Slope: {dos.vwap_slope_15m:+.4f}")
        print(f"  • 5m Ribbon: EMA Spread = {dos.ema_spread_5m:+.2f} pts | Pullback Dist = {dos.pullback_distance_pts:.2f} pts | Ribbon Compression = {dos.ribbon_compression_hazard}")
        print(f"  • 1m RSI: {dos.rsi_1m:.1f} | 30m Range Box: Spread = {dos.box_range_30m:.1f} pts, Box Position = {dos.box_position_pct:.1f}%")
        print(f"  • Day Extreme: Dist to Extreme = {dos.distance_to_day_extreme:.1f} pts | Consecutive Prev Losses: {dos.consecutive_losses_today}")
        print(f"  • Realized PnL Today Prior: ₹{dos.realized_pnl_today:,.2f} | Exit Reason: {t.exit_reason}")

if __name__ == "__main__":
    run_forensic_loss_analysis()
