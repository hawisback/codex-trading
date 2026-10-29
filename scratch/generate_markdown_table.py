import json

with open("scratch/all_30_sessions_trades_enriched.json", "r", encoding="utf-8") as f:
    trades = json.load(f)

lines = []
lines.append("| # | Date | Dir | Strike | Entry (IST) | Entry ₹ | Exit (IST) | Exit ₹ | Hold | Return % | Net PnL (1L) | Net PnL (2L) | Exit Mechanism | Status |")
lines.append("|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---|:---:|")

for t in trades:
    # shorten exit reason for clean display
    raw_reason = t["exit_reason"]
    if "TRAILING_DYNAMIC_RATCHET" in raw_reason:
        reason = "Dynamic Ratchet Stop"
    elif "AI_LATE_DAY_MICRO_TRAIL" in raw_reason:
        reason = "Late-Day Micro-Trail"
    elif "PROFIT_TARGET" in raw_reason:
        reason = "Target Hit (+50%)"
    elif "INITIAL_STOP" in raw_reason:
        reason = "Initial Stop (-30%)"
    elif "EOD_SQUAREOFF" in raw_reason or "MARKET_CLOSE" in raw_reason:
        reason = "EOD Square-Off"
    elif "STRUCTURAL" in raw_reason:
        reason = "Structural Exit"
    else:
        reason = raw_reason.split("(")[0].strip()

    status_badge = "**WIN**" if t["is_win"] else "LOSS"
    pnl1_str = f"₹{t['pnl_1lot']:>+8,.2f}"
    pnl2_str = f"**₹{t['pnl_2lots']:>+9,.2f}**" if t["is_win"] else f"₹{t['pnl_2lots']:>+9,.2f}"
    ret_str = f"{t['pnl_pct']:>+6.1f}%"
    
    row = f"| {t['trade_num']} | {t['date']} | {t['direction']} | {t['strike']} | {t['entry_ist']} | ₹{t['entry_price']:.2f} | {t['exit_ist']} | ₹{t['exit_price']:.2f} | {t['hold_minutes']}m | {ret_str} | {pnl1_str} | {pnl2_str} | {reason} | {status_badge} |"
    lines.append(row)

with open("scratch/trades_table.md", "w", encoding="utf-8") as f:
    f.write("\n".join(lines))

print(f"Generated table with {len(trades)} rows in scratch/trades_table.md")
