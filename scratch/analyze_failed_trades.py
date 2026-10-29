import os
import sys
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")

from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

ALL_DATES = [
    # Week 5 (Aug 31 - Sep 04)
    "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    # Week 6 (Sep 07 - Sep 11)
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    # Week 7 (Sep 14 - Sep 18)
    "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    # Week 8 (Sep 21 - Sep 25)
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
    # Week 9 (Sep 28 - Oct 01)
    "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01",
    # Week 10 (Oct 05 - Oct 09)
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
    # Week 11 (Oct 12 - Oct 13)
    "2026-10-12", "2026-10-13"
]

def analyze_failures():
    cfg = StrategyConfig.load_from_config("institutional_pullback")
    consultant = AIConsultant(mode="playbook")

    all_approved_trades = []
    failed_trade_details = []

    for d in ALL_DATES:
        eng = BacktestEngine(target_date=d)
        if not eng.spot_candles:
            continue
        raw_trades = eng.run_simulation(cfg)
        dte = eng.get_expiry_days()
        is_0dte = (dte <= 0.2)

        for i, t in enumerate(raw_trades, 1):
            idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
            dos = generate_market_dossier(
                target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
                direction=t.direction, symbol=t.symbol, strike=t.strike,
                option_entry_price=t.entry_price, trade_history=raw_trades[:i-1],
                days_to_expiry=dte, is_expiry_0dte=is_0dte
            )
            v = consultant.evaluate(dos)
            if v.is_approved:
                all_approved_trades.append(t)
                if t.pnl <= 0:
                    # Analyze post-exit market move in opposite direction
                    exit_idx = t.exit_bar if t.exit_bar is not None else idx + 15
                    exit_spot = eng.spot_candles[min(exit_idx, len(eng.spot_candles)-1)]["close"]
                    
                    # Track opposite direction potential over next 15m, 30m, 60m
                    future_bars = eng.spot_candles[exit_idx: min(exit_idx + 45, len(eng.spot_candles))]
                    opp_direction = "PE" if t.direction == "CE" else "CE"
                    
                    max_favorable_spot_move = 0.0
                    if opp_direction == "PE":
                        # Spot dropping is favorable for PE
                        min_future_spot = min([b["low"] for b in future_bars]) if future_bars else exit_spot
                        max_favorable_spot_move = exit_spot - min_future_spot
                    else:
                        # Spot rising is favorable for CE
                        max_future_spot = max([b["high"] for b in future_bars]) if future_bars else exit_spot
                        max_favorable_spot_move = max_future_spot - exit_spot

                    failed_trade_details.append({
                        "date": d,
                        "trade_id": t.trade_id,
                        "failed_direction": t.direction,
                        "symbol": t.symbol,
                        "entry_time": t.entry_time,
                        "exit_time": t.exit_time,
                        "loss_rs": t.pnl * 2, # 2 lots
                        "loss_pct": t.pnl_pct,
                        "exit_reason": t.exit_reason,
                        "exit_spot": exit_spot,
                        "opp_direction": opp_direction,
                        "opp_spot_expansion_pts": round(max_favorable_spot_move, 1),
                        "bars_available": len(future_bars)
                    })

    print("=" * 110)
    print(f" 🔍 FORENSIC AUDIT OF FAILED TRADES: Total Losses = {len(failed_trade_details)}")
    print("=" * 110)
    print(f"{'Date':<12} {'Dir':<4} {'Loss (2 Lots)':<15} {'Exit Reason':<24} {'Opposite Dir':<14} {'Opp Max Expansion (Spot)':<26}")
    print("-" * 110)

    massive_reversals = 0
    total_reversal_pts = 0.0

    for f in failed_trade_details:
        exp_str = f"+{f['opp_spot_expansion_pts']:.1f} pts"
        if f['opp_spot_expansion_pts'] >= 30.0:
            exp_str += " 🚀 [EXPLOSIVE REVERSAL]"
            massive_reversals += 1
        elif f['opp_spot_expansion_pts'] >= 15.0:
            exp_str += " ✅ [VIABLE FLIP]"
        else:
            exp_str += " ⚪ [CHOP / FLAT]"

        total_reversal_pts += f['opp_spot_expansion_pts']
        print(f"{f['date']:<12} {f['failed_direction']:<4} ₹{f['loss_rs']:>+11,.2f}   {f['exit_reason']:<24} {f['opp_direction']:<14} {exp_str:<26}")

    avg_reversal = total_reversal_pts / len(failed_trade_details) if failed_trade_details else 0
    pct_explosive = (massive_reversals / len(failed_trade_details) * 100) if failed_trade_details else 0

    print("=" * 110)
    print(f" SUMMARY OF FAILED TRADES REVERSAL BEHAVIOR:")
    print(f" • Total Failed Trades:            {len(failed_trade_details)}")
    print(f" • Average Opposite Spot Runway:   +{avg_reversal:.1f} points in next 30-45 minutes")
    print(f" • Explosive Reversals (>=30 pts): {massive_reversals} of {len(failed_trade_details)} ({pct_explosive:.1f}%)")
    print("=" * 110)

if __name__ == "__main__":
    analyze_failures()
