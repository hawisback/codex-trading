import json
import sys
sys.stdout.reconfigure(encoding="utf-8")

with open("scratch/all_30_sessions_trades_enriched.json", "r", encoding="utf-8") as f:
    trades = json.load(f)

print("=" * 80)
print("MULTI-TRADE SESSIONS & HOW RE-ENTRY ALREADY WORKS")
print("=" * 80)

for day in ["2026-09-01", "2026-09-15", "2026-09-22", "2026-10-06"]:
    day_t = [t for t in trades if t["date"] == day]
    print(f"\n--- {day} ({len(day_t)} trades) ---")
    for t in day_t:
        reason = t["exit_reason"].split("(")[0].strip()
        print(f"Trade #{t['trade_num']:>2} | {t['entry_ist']} to {t['exit_ist']} | {t['direction']} {t['strike']} | In: ₹{t['entry_price']:>6.2f} -> Out: ₹{t['exit_price']:>6.2f} ({t['pnl_pct']:>+5.1f}%) | {reason}")
