import json
import os
import sys

sys.path.insert(0, ".")
from trading.bootstrap import configure_console
configure_console()

from trading.domain.market_data import resample_two_minutes
from trading.strategies.macd_momentum import calculate_macd

# Load all 30 sessions data
DATES = [
    "2026-09-11", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
    "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-05",
    "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12",
    "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19",
    "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"
]

with open("logs/backtest_audit/trades_30_sessions.json", "r") as f:
    trades = json.load(f)

trade_map = {t["date"] + "_" + t["entry_time"]: t for t in trades}

# Let's inspect features of each crossover in the 30 sessions
crossover_features = []

for dt in DATES:
    spot_file = f"data/spot_candles_{dt.replace('-', '')}.json"
    if not os.path.exists(spot_file): continue
    with open(spot_file, "r") as fp: spot_bars = json.load(fp)
    res_2m = resample_two_minutes(spot_bars)
    closes = [b["close"] for b in res_2m]
    macd, sig, hist = calculate_macd(closes)
    
    for i in range(26, len(res_2m)):
        end_1m = res_2m[i]["minute_idx"]
        hh = end_1m // 60 + 9
        mm = end_1m % 60
        t_str = f"{hh:02d}:{mm:02d} IST"
        k = dt + "_" + t_str
        
        pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
        ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
        if not (pe_cross or ce_cross): continue
        
        dir_str = "PE" if pe_cross else "CE"
        
        # Calculate feature values at crossover
        b = res_2m[i]
        candle_body = b["close"] - b["open"]
        candle_aligned = (candle_body > 0) if dir_str == "CE" else (candle_body < 0)
        body_size = abs(candle_body)
        
        # Hist delta (impulse strength)
        hist_delta = abs(hist[i] - hist[i-1])
        
        # VWAP distance
        bars_so_far = spot_bars[:end_1m + 1]
        vwap = sum((x["high"] + x["low"] + x["close"])/3.0 for x in bars_so_far) / len(bars_so_far)
        vwap_dist = abs(b["close"] - vwap)
        
        # 15m range box spread
        box_15 = bars_so_far[max(0, end_1m - 14): end_1m + 1]
        box_spread = max(x["high"] for x in box_15) - min(x["low"] for x in box_15)
        
        # Is in midday (11:30 - 13:15)
        is_midday = (135 <= (end_1m) <= 240)
        
        # Match with trade result
        tr = trade_map.get(k)
        if tr:
            crossover_features.append({
                "date": dt,
                "time": t_str,
                "direction": dir_str,
                "candle_aligned": candle_aligned,
                "body_size": round(body_size, 2),
                "hist_delta": round(hist_delta, 2),
                "vwap_dist": round(vwap_dist, 1),
                "box_spread": round(box_spread, 1),
                "is_midday": is_midday,
                "is_win": tr["pnl_pts"] > 0,
                "pnl_pts": tr["pnl_pts"],
                "peak_gain": tr["peak_gain_pct"]
            })

print(f"Collected {len(crossover_features)} matched crossovers.")

# Feature 1: Candle Direction Alignment (Does the 2m trigger candle close in trade direction?)
aligned_wins = [c for c in crossover_features if c["candle_aligned"] and c["is_win"]]
aligned_losses = [c for c in crossover_features if c["candle_aligned"] and not c["is_win"]]
unaligned_wins = [c for c in crossover_features if not c["candle_aligned"] and c["is_win"]]
unaligned_losses = [c for c in crossover_features if not c["candle_aligned"] and not c["is_win"]]

print("\n--- Feature 1: 2m Candle Alignment (Green for CE, Red for PE) ---")
tot_al = len(aligned_wins) + len(aligned_losses)
wr_al = len(aligned_wins) / tot_al * 100 if tot_al else 0
print(f"Candle Aligned:   {len(aligned_wins)} Wins / {len(aligned_losses)} Losses (Tot: {tot_al}) -> Win Rate: {wr_al:.1f}%")

tot_unal = len(unaligned_wins) + len(unaligned_losses)
wr_unal = len(unaligned_wins) / tot_unal * 100 if tot_unal else 0
print(f"Candle Unaligned: {len(unaligned_wins)} Wins / {len(unaligned_losses)} Losses (Tot: {tot_unal}) -> Win Rate: {wr_unal:.1f}%")

# Feature 2: 15m Box Spread (Market Expansion vs Dead Compression)
print("\n--- Feature 2: 15m Box Range Spread ---")
for min_sp in [15.0, 20.0, 25.0, 30.0]:
    filt = [c for c in crossover_features if c["box_spread"] >= min_sp]
    w = len([c for c in filt if c["is_win"]])
    tot = len(filt)
    wr = w / tot * 100 if tot else 0
    pnl = sum(c["pnl_pts"] for c in filt) * 130
    print(f"Box Spread >= {min_sp:4.1f} pts: {tot:3d} trades | {w:2d} Wins (WR: {wr:4.1f}%) | Net PnL (2 lots): Rs {pnl:+10,.2f}")

# Feature 3: Midday Filter (Skipping flatline chop when box spread < 25 pts)
print("\n--- Feature 3: Midday Flatline Chop Filter ---")
mid_chop = [c for c in crossover_features if c["is_midday"] and c["box_spread"] < 25.0]
mc_w = len([c for c in mid_chop if c["is_win"]])
mc_l = len(mid_chop) - mc_w
print(f"Midday Flatline Chop (11:30-13:15 with Range < 25 pts): {mc_w} Wins / {mc_l} Losses ({len(mid_chop)} trades) -> Losses avoided if filtered: {mc_l}!")

# Feature 4: Candle Aligned + Box Spread >= 20 pts + Avoiding Midday Flatline Chop
smart_crossover = [c for c in crossover_features if c["candle_aligned"] and c["box_spread"] >= 20.0 and not (c["is_midday"] and c["box_spread"] < 25.0)]
sc_w = len([c for c in smart_crossover if c["is_win"]])
sc_l = len(smart_crossover) - sc_w
sc_tot = len(smart_crossover)
sc_wr = sc_w / sc_tot * 100 if sc_tot else 0
sc_pnl = sum(c["pnl_pts"] for c in smart_crossover) * 130 - sc_tot * 40.0
print(f"\n🏆 SMART MACD CROSSOVER (Candle Aligned + Non-Compressed Box + No Midday Chop):")
print(f"   Trades: {sc_tot} | Wins: {sc_w} | Losses: {sc_l} | Win Rate: {sc_wr:.1f}% | Net PnL (2 Lots): Rs {sc_pnl:+,.2f}")
