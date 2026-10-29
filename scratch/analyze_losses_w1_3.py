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

losing_trades = []
winning_trades = []

for d, label in dates_w1_3:
    eng = BacktestEngine(d)
    if not eng.spot_candles:
        continue
    trades = eng.run_simulation(s3)
    for t in trades:
        e_bar = eng.spot_candles[t.entry_bar]
        x_bar = eng.spot_candles[t.exit_bar] if t.exit_bar < len(eng.spot_candles) else eng.spot_candles[-1]
        
        # Check opposite direction movement after exit
        # If CE lost, how much did spot drop after exit?
        # If PE lost, how much did spot rally after exit?
        exit_idx = t.exit_bar
        bars_after_exit = eng.spot_candles[exit_idx: min(exit_idx + 60, len(eng.spot_candles))]
        if bars_after_exit:
            min_after = min(b["low"] for b in bars_after_exit)
            max_after = max(b["high"] for b in bars_after_exit)
            if t.direction == "CE":
                opp_move = e_bar["close"] - min_after # dropped
            else:
                opp_move = max_after - e_bar["close"] # rallied
        else:
            opp_move = 0.0

        item = {
            "date": d,
            "label": label,
            "trade": t,
            "spot_entry": e_bar["close"],
            "spot_exit": x_bar["close"],
            "spot_move": x_bar["close"] - e_bar["close"],
            "opp_move": opp_move,
            "reason": t.exit_reason
        }
        if t.pnl <= 0:
            losing_trades.append(item)
        else:
            winning_trades.append(item)

print(f"Total Trades in W1-3: {len(winning_trades) + len(losing_trades)} (Wins: {len(winning_trades)}, Losses: {len(losing_trades)})")
print("\n" + "=" * 115)
print("ANALYSIS OF ALL LOSING TRADES IN WEEKS 1-3:")
print("=" * 115)
print(f"{'Date':<12} {'Dir':<4} {'Time':<6} {'EntrySpot':<10} {'ExitSpot':<10} {'SpotDiff':<10} {'OppMove(60m)':<14} {'Loss':<10} {'Exit Reason'}")
print("-" * 115)

strong_reversals = 0
shallow_chops = 0

for item in losing_trades:
    t = item["trade"]
    opp = item["opp_move"]
    if opp >= 25.0:
        strong_reversals += 1
        rev_tag = "STRONG REVERSAL"
    else:
        shallow_chops += 1
        rev_tag = "SHALLOW CHOP"
        
    print(f"{item['date']:<12} {t.direction:<4} {t.entry_time[:5]:<6} {item['spot_entry']:>9.1f} {item['spot_exit']:>9.1f} {item['spot_move']:>+9.1f} {opp:>+10.1f} pts  Rs {t.pnl:>8.2f}  {t.exit_reason[:30]} [{rev_tag}]")

print("-" * 115)
print(f"Summary of Losses: {strong_reversals} Strong Market Reversals (>= 25 pts adverse move) | {shallow_chops} Shallow Chop/Whipsaw Trades")
