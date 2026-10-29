import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

with open("data/today_actual_candles_20261015.json", "r", encoding="utf-8") as f:
    data = json.load(f)

spot = data["NIFTY 50"]
ce_22900 = data["NIFTY26O1922900CE"]

# Group spot into 5m bars
bars_5m = []
for i in range(0, len(spot), 5):
    chunk = spot[i:i+5]
    if chunk:
        bars_5m.append({
            "time": chunk[0]["date"][:16],
            "open": chunk[0]["open"],
            "high": max(c["high"] for c in chunk),
            "low": min(c["low"] for c in chunk),
            "close": chunk[-1]["close"]
        })

# Compute 5m EMA9 and 20
k9 = 2.0 / 10.0
k20 = 2.0 / 21.0
ema9 = bars_5m[0]["close"]
ema20 = bars_5m[0]["close"]
for b in bars_5m:
    ema9 = b["close"] * k9 + ema9 * (1.0 - k9)
    ema20 = b["close"] * k20 + ema20 * (1.0 - k20)
    b["ema9"] = ema9
    b["ema20"] = ema20

entry_price = 144.90
target_50pct = entry_price * 1.50 # 217.35

print("=" * 80)
print("DEEP DIVE: TRAILING STOP LOSS MODELS ON TRADE #1 (22900 CE @ 144.90)")
print("=" * 80)

# Model 1: Original Strategy 2 Structural Runner (Pure 5m EMA9 trailing stop with 4pt buffer, no option ratchet)
print("\n--- MODEL 1: PURE STRUCTURAL RUNNER (5m EMA9 Trailing, 4.0 pt buffer, 50% Target) ---")
peak_price = entry_price
for i, c in enumerate(ce_22900):
    t_str = c["date"][:16]
    if t_str < "2026-10-15T11:10":
        continue
    
    # Matching spot 5m bar
    b5 = [b for b in bars_5m if b["time"] <= t_str][-1]
    spot_c = [s for s in spot if s["date"][:16] == t_str][0]["close"]
    
    if c["high"] > peak_price:
        peak_price = c["high"]
    
    peak_gain = ((peak_price - entry_price) / entry_price) * 100.0

    # 1. Target Hit
    if c["high"] >= target_50pct:
        pnl = (target_50pct - entry_price) * 65
        print(f"✅ TARGET HIT (+50.0%) at {c['date'][:19]}!")
        print(f"   Option High:  ₹{c['high']:.2f} >= Target ₹{target_50pct:.2f}")
        print(f"   Exit Price:   ₹{target_50pct:.2f}")
        print(f"   P&L per Lot:  ₹{pnl:+,.2f} (+50.0% / +₹4,709.25)")
        break

    # 2. 5m EMA9 Trail Check (Active if peak gain >= 15%)
    if peak_gain >= 15.0:
        if spot_c < (b5["ema9"] - 4.0):
            pnl = (c["close"] - entry_price) * 65
            print(f"🛑 5m EMA9 BREAK at {c['date'][:19]}: Spot {spot_c:.2f} < EMA9 ({b5['ema9']:.2f} - 4.0)")
            print(f"   Exit Price:  ₹{c['close']:.2f} ({((c['close']-entry_price)/entry_price)*100:+.1f}%)")
            print(f"   P&L per Lot: ₹{pnl:+,.2f}")
            break

# Model 2: Strategy 3 with Option-Price Continuous Ratchet (10% Pullback from Peak)
print("\n--- MODEL 2: DYNAMIC CONTINUOUS OPTION RATCHET (10% from Peak, +10%/+20%/+30% floors) ---")
peak_price = entry_price
for i, c in enumerate(ce_22900):
    t_str = c["date"][:16]
    if t_str < "2026-10-15T11:10":
        continue
    
    if c["high"] > peak_price:
        peak_price = c["high"]
    
    peak_gain = ((peak_price - entry_price) / entry_price) * 100.0

    if peak_gain >= 20.0:
        floor_pct = 10.0
        if peak_gain >= 40.0:
            floor_pct = 30.0
        elif peak_gain >= 30.0:
            floor_pct = 20.0
        floor_price = entry_price * (1.0 + floor_pct / 100.0)
        trail_stop = max(floor_price, peak_price * 0.90)

        # Trigger on option low
        if c["low"] <= trail_stop:
            pnl = (trail_stop - entry_price) * 65
            print(f"🛑 OPTION RATCHET HIT at {c['date'][:19]}!")
            print(f"   Peak Reached: ₹{peak_price:.2f} (+{peak_gain:.1f}%)")
            print(f"   Trail Stop:   ₹{trail_stop:.2f} (Floor: ₹{floor_price:.2f})")
            print(f"   Exit Price:   ₹{trail_stop:.2f} ({((trail_stop-entry_price)/entry_price)*100:+.1f}%)")
            print(f"   P&L per Lot:  ₹{pnl:+,.2f}")
            break

# Model 3: Breakeven / Fixed Stepped Floor Only (No 10% pullback, only lock +10% floor at +20%)
print("\n--- MODEL 3: STEPPED FLOOR ONLY (+10% floor @ +20%, +20% floor @ +30%, +30% floor @ +40%) ---")
peak_price = entry_price
for i, c in enumerate(ce_22900):
    t_str = c["date"][:16]
    if t_str < "2026-10-15T11:10":
        continue
    
    if c["high"] > peak_price:
        peak_price = c["high"]
    
    peak_gain = ((peak_price - entry_price) / entry_price) * 100.0

    # Target
    if c["high"] >= target_50pct:
        pnl = (target_50pct - entry_price) * 65
        print(f"✅ TARGET HIT (+50.0%) at {c['date'][:19]}!")
        print(f"   Exit Price:   ₹{target_50pct:.2f}")
        print(f"   P&L per Lot:  ₹{pnl:+,.2f}")
        break

    if peak_gain >= 20.0:
        floor_pct = 10.0
        if peak_gain >= 40.0:
            floor_pct = 30.0
        elif peak_gain >= 30.0:
            floor_pct = 20.0
        floor_price = entry_price * (1.0 + floor_pct / 100.0)

        # Trigger if option drops below floor
        if c["low"] <= floor_price:
            pnl = (floor_price - entry_price) * 65
            print(f"🛑 STEPPED FLOOR HIT at {c['date'][:19]}!")
            print(f"   Floor Price:  ₹{floor_price:.2f} (+{floor_pct:.0f}%)")
            print(f"   Exit Price:   ₹{floor_price:.2f}")
            print(f"   P&L per Lot:  ₹{pnl:+,.2f}")
            break
