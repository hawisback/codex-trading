import json
import sys
import numpy as np
from datetime import datetime

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

with open("data/today_actual_candles_20261015.json", "r", encoding="utf-8") as f:
    data = json.load(f)

ce_22900 = data["NIFTY26O1922900CE"]
spot_candles = data["NIFTY 50"]

# Align candles by timestamp
candle_map = {}
for c in ce_22900:
    candle_map[c["date"][:16]] = {"opt": c}

for s in spot_candles:
    k = s["date"][:16]
    if k in candle_map:
        candle_map[k]["spot"] = s

aligned = []
for k in sorted(candle_map.keys()):
    if "opt" in candle_map[k] and "spot" in candle_map[k]:
        aligned.append({
            "time": k,
            "opt_open": candle_map[k]["opt"]["open"],
            "opt_high": candle_map[k]["opt"]["high"],
            "opt_low": candle_map[k]["opt"]["low"],
            "opt_close": candle_map[k]["opt"]["close"],
            "spot_open": candle_map[k]["spot"]["open"],
            "spot_high": candle_map[k]["spot"]["high"],
            "spot_low": candle_map[k]["spot"]["low"],
            "spot_close": candle_map[k]["spot"]["close"],
        })

# Compute 5m spot EMA9, EMA20, and VWAP iteratively
spot_closes = [b["spot_close"] for b in aligned]

# Calculate VWAP across session
cum_vol_price = 0.0
cum_vol = 0.0
vwaps = []
for b in aligned:
    # Typical price for spot
    tp = (b["spot_high"] + b["spot_low"] + b["spot_close"]) / 3.0
    # Spot volume is 0 in index, so we use cumulative simple average or standard session VWAP
    vwaps.append(tp)

def run_simulation(config_name, runner_activation_pct, trail_pullback_pct, tiers, enable_structural=True, target_pct=50.0):
    entry_price = 144.90
    entry_idx = None
    for i, b in enumerate(aligned):
        if "11:10" in b["time"]:
            entry_idx = i
            break

    peak_bid = entry_price
    initial_stop_price = entry_price * 0.70 # -30%
    target_price = entry_price * (1.0 + target_pct / 100.0)

    # 5m EMA tracking
    # Group into 5m bars to compute true 5m EMA9 and EMA20
    # For simulation, calculate 5m closes
    exit_info = None

    for i in range(entry_idx, len(aligned)):
        b = aligned[i]
        t_str = b["time"]
        opt_high = b["opt_high"]
        opt_low = b["opt_low"]
        opt_close = b["opt_close"]
        spot_close = b["spot_close"]

        # Update peak bid
        if opt_high > peak_bid:
            peak_bid = opt_high

        peak_gain_pct = ((peak_bid - entry_price) / entry_price) * 100.0
        current_gain_pct = ((opt_close - entry_price) / entry_price) * 100.0
        loss_from_entry = ((entry_price - opt_low) / entry_price) * 100.0

        # Check 1: Session Hard Square-off (15:20)
        if t_str[11:] >= "15:20":
            exit_info = {
                "reason": "SESSION_HARD_SQUARE_OFF (15:20 IST)",
                "exit_time": t_str,
                "exit_price": opt_close,
                "gain_pct": current_gain_pct,
                "peak_gain_pct": peak_gain_pct,
                "bar_idx": i
            }
            break

        # Check 2: Initial Stop Loss (-30%)
        if opt_low <= initial_stop_price:
            exit_info = {
                "reason": "INITIAL_STOP_LOSS (-30%)",
                "exit_time": t_str,
                "exit_price": initial_stop_price,
                "gain_pct": -30.0,
                "peak_gain_pct": peak_gain_pct,
                "bar_idx": i
            }
            break

        # Check 3: Target Hit (+50%)
        if opt_high >= target_price:
            exit_info = {
                "reason": f"PROFIT_TARGET_HIT (+{target_pct}%)",
                "exit_time": t_str,
                "exit_price": target_price,
                "gain_pct": target_pct,
                "peak_gain_pct": peak_gain_pct,
                "bar_idx": i
            }
            break

        # Check 4: Dynamic Trailing Ratchet
        if peak_gain_pct >= runner_activation_pct:
            floor_pct = 0.0
            for tier in sorted(tiers, key=lambda x: x["gain_pct"], reverse=True):
                if peak_gain_pct >= tier["gain_pct"]:
                    floor_pct = tier["floor_pct"]
                    break
            floor_price = entry_price * (1.0 + floor_pct / 100.0)
            trail_stop = max(floor_price, peak_bid * (1.0 - trail_pullback_pct / 100.0))

            if opt_low <= trail_stop:
                opt_open = b["opt_open"]
                realized_exit = min(opt_open, trail_stop) if opt_open < trail_stop else trail_stop
                exit_info = {
                    "reason": f"DYNAMIC_TRAILING_RATCHET (Peak {peak_bid:.2f} [+ {peak_gain_pct:.1f}%], Stop {trail_stop:.2f})",
                    "exit_time": t_str,
                    "exit_price": round(trail_stop, 2),
                    "gain_pct": round(((trail_stop - entry_price) / entry_price) * 100.0, 2),
                    "peak_gain_pct": peak_gain_pct,
                    "bar_idx": i
                }
                break

    return exit_info

print("=" * 95)
print("TRADE #1 (NIFTY26O1922900CE @ 144.90) AUTOMATED LIFECYCLE SIMULATIONS")
print("=" * 95)

# Scenario 1: Actual Strategy 3 (Original: 20% activation, 10% pullback, progressive floors)
tiers_orig = [
    {"gain_pct": 20.0, "floor_pct": 10.0},
    {"gain_pct": 30.0, "floor_pct": 20.0},
    {"gain_pct": 40.0, "floor_pct": 30.0}
]
res_orig = run_simulation("Strategy 3 (Original - 20% Activation / 10% Pullback)", 20.0, 10.0, tiers_orig, target_pct=50.0)
pnl_orig = (res_orig['exit_price'] - 144.90) * 65
print(f"\n1. Original Strategy 3 (20% Activation, 10% Pullback, +50% Target):")
print(f"   Exit Time:   {res_orig['exit_time']}")
print(f"   Exit Price:  ₹{res_orig['exit_price']:.2f} ({res_orig['gain_pct']:+.1f}%)")
print(f"   Exit Reason: {res_orig['reason']}")
print(f"   Peak Reached:₹{144.90 * (1 + res_orig['peak_gain_pct']/100):.2f} (+{res_orig['peak_gain_pct']:.1f}%)")
print(f"   P&L:         ₹{pnl_orig:+,.2f}")

# Scenario 2: Strategy 3 with 5% Trailing Activation (The patch discussed during Trade 2)
tiers_5pct = [
    {"gain_pct": 5.0, "floor_pct": 2.0},
    {"gain_pct": 10.0, "floor_pct": 5.0},
    {"gain_pct": 20.0, "floor_pct": 10.0},
    {"gain_pct": 30.0, "floor_pct": 20.0},
    {"gain_pct": 40.0, "floor_pct": 30.0}
]
res_5pct = run_simulation("Strategy 3 (5% Activation / 5% Pullback)", 5.0, 5.0, tiers_5pct, target_pct=50.0)
pnl_5pct = (res_5pct['exit_price'] - 144.90) * 65
print(f"\n2. Strategy with 5% Activation & 5% Pullback:")
print(f"   Exit Time:   {res_5pct['exit_time']}")
print(f"   Exit Price:  ₹{res_5pct['exit_price']:.2f} ({res_5pct['gain_pct']:+.1f}%)")
print(f"   Exit Reason: {res_5pct['reason']}")
print(f"   Peak Reached:₹{144.90 * (1 + res_5pct['peak_gain_pct']/100):.2f} (+{res_5pct['peak_gain_pct']:.1f}%)")
print(f"   P&L:         ₹{pnl_5pct:+,.2f}")

# Scenario 3: Strategy 2 (Structural Runner: 15% Activation / 10% Pullback)
tiers_15pct = [
    {"gain_pct": 15.0, "floor_pct": 5.0},
    {"gain_pct": 20.0, "floor_pct": 10.0},
    {"gain_pct": 30.0, "floor_pct": 20.0},
    {"gain_pct": 40.0, "floor_pct": 30.0}
]
res_15pct = run_simulation("Strategy 2 (15% Activation / 10% Pullback)", 15.0, 10.0, tiers_15pct, target_pct=50.0)
pnl_15pct = (res_15pct['exit_price'] - 144.90) * 65
print(f"\n3. Strategy 2 (15% Activation, 10% Pullback):")
print(f"   Exit Time:   {res_15pct['exit_time']}")
print(f"   Exit Price:  ₹{res_15pct['exit_price']:.2f} ({res_15pct['gain_pct']:+.1f}%)")
print(f"   Exit Reason: {res_15pct['reason']}")
print(f"   Peak Reached:₹{144.90 * (1 + res_15pct['peak_gain_pct']/100):.2f} (+{res_15pct['peak_gain_pct']:.1f}%)")
print(f"   P&L:         ₹{pnl_15pct:+,.2f}")

# Scenario 4: User's Actual Manual Execution
pnl_user = (162.10 - 144.90) * 65
print(f"\n4. User Actual Manual Execution:")
print(f"   Exit Time:   ~11:28 - 11:31 IST")
print(f"   Exit Price:  ₹162.10 (+11.9% / +13.5% on fills)")
print(f"   Exit Reason: Manual Operator Exit on Kite App")
print(f"   P&L:         ₹{pnl_user:+,.2f} (Broker Settled: +₹1,267.50)")
