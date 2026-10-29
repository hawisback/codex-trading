import json

with open("scratch/all_raw_crossovers_simulated.json") as fp:
    crossovers = json.load(fp)

total = len(crossovers)
all_wins = [c for c in crossovers if c["is_win"]]
all_losses = [c for c in crossovers if not c["is_win"]]

print("=" * 100)
print(f"TOTAL POOL: {total} Crossovers | {len(all_wins)} Wins ({len(all_wins)/total*100:.1f}%) | {len(all_losses)} Losses")
print("=" * 100)

filters = [
    ("pass_hist", "Min Hist Threshold (>= 0.20)"),
    ("pass_candle", "2m Trigger Candle Color Confirmation"),
    ("pass_vwap_flow", "VWAP Flow Side (within 12 pts)"),
    ("pass_climax", "VWAP Climax Extension (< 50 pts)"),
    ("pass_or", "Opening Range High/Low Floor/Ceiling (< 8 pts)"),
    ("pass_midday", "Midday Dead Zone Range (< 24 pts)"),
    ("pass_cutoff", "14:15 Hard Entry Cutoff"),
    ("pass_strike_macd", "Option Strike 2m MACD Confluence")
]

print(f"{'Filter Name':<42} {'Blocked':<8} {'Wins Blocked':<14} {'Losses Blocked':<16} {'Win Rate of Blocked':<20} {'Character':<15}")
print("-" * 120)

for flag, name in filters:
    blocked = [c for c in crossovers if not c[flag]]
    b_wins = [c for c in blocked if c["is_win"]]
    b_losses = [c for c in blocked if not c["is_win"]]
    b_tot = len(blocked)
    b_wr = (len(b_wins) / b_tot * 100.0) if b_tot else 0.0
    pnl = sum(c["pnl_2lots"] for c in blocked)
    
    char = "POISON FILTER" if b_wr > 65.0 else ("EFFECTIVE" if b_wr < 45.0 else "MIXED")
    print(f"{name:<42} {b_tot:<8} {len(b_wins):<14} {len(b_losses):<16} {b_wr:<6.1f}% (Rs {pnl:+9.0f})   {char:<15}")

print("=" * 120)

# Also check trades blocked purely by the 2 trades/day cap and 10 bars spacing!
# If a trade passes ALL 8 filters above, how many exist?
survivors = [c for c in crossovers if all(c[flag] for flag, _ in filters)]
s_wins = [c for c in survivors if c["is_win"]]
s_losses = [c for c in survivors if not c["is_win"]]
s_pnl = sum(c["pnl_2lots"] for c in survivors)
print(f"\nTrades Passing ALL 8 Filters (Before Daily Cap & Cooldown):")
print(f"  Total Trades: {len(survivors)} ({len(survivors)/30:.1f} per day)")
print(f"  Wins / Losses: {len(s_wins)} Wins / {len(s_losses)} Losses ({len(s_wins)/len(survivors)*100:.1f}% Win Rate)")
print(f"  Total PnL (Fixed 2 Lots): Rs {s_pnl:+,.2f}")
