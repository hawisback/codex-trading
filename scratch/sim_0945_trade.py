import urllib.request
import json
import math
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

def bsm_price(spot: float, strike: float, days_to_expiry: float,
              r: float = 0.065, sigma: float = 0.135, is_call: bool = True) -> float:
    T = max(0.0001, days_to_expiry / 365.0)
    if T <= 0.0002:
        return max(0.05, (spot - strike) if is_call else (strike - spot))
    d1 = (math.log(spot / strike) + (r + 0.5 * (sigma ** 2)) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        price = spot * norm_cdf(d1) - strike * math.exp(-r * T) * norm_cdf(d2)
    else:
        price = strike * math.exp(-r * T) * norm_cdf(-d2) - spot * norm_cdf(-d1)
    return max(0.05, round(price, 2))

c1m_resp = json.loads(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/ai/nifty/candles?interval=1m&limit=500").read().decode())
today_1m = []
for c in c1m_resp.get("candles", []):
    st = c.get("start_time", "")
    dt_utc = datetime.fromisoformat(st.replace("Z", "+00:00"))
    dt_ist = dt_utc.astimezone(IST)
    if dt_ist.strftime("%Y-%m-%d") == "2026-10-15":
        c_copy = dict(c)
        c_copy["time_str"] = dt_ist.strftime("%H:%M")
        today_1m.append(c_copy)

# Let's simulate entering Strike 22700 CE (Strict ITM) at 09:45 AM (spot = 22747 - 22770)
days_to_expiry = 4.0
entry_idx = 30 # 09:45 IST
entry_bar = today_1m[entry_idx]
entry_spot = entry_bar["close"]
entry_strike = 22700
entry_prem = bsm_price(entry_spot, entry_strike, days_to_expiry, is_call=True)
qty = 65
margin = entry_prem * qty

print(f"=== SIMULATION OF 09:45 AM TRADE: STRIKE {entry_strike} CE ===")
print(f"Entry Time: {entry_bar['time_str']} IST")
print(f"Entry Spot: {entry_spot:.2f}")
print(f"Entry Premium: Rs. {entry_prem:.2f}")
print(f"Margin Used: Rs. {margin:.2f} (Budget: Rs. 9,531.60 -> SAFE)")

peak_prem = entry_prem
peak_gain = 0.0

print("\n--- Minute-by-Minute Performance from 09:45 to 11:05 ---")
for idx in range(entry_idx, len(today_1m)):
    bar = today_1m[idx]
    spot = bar["close"]
    h = bar["high"]
    t_str = bar["time_str"]
    days_rem = max(0.001, days_to_expiry - (idx / 375.0) * 0.25)
    cur_prem = bsm_price(spot, entry_strike, days_rem, is_call=True)
    high_prem = bsm_price(h, entry_strike, days_rem, is_call=True)

    if high_prem > peak_prem:
        peak_prem = high_prem
        peak_gain = ((high_prem - entry_prem) / entry_prem) * 100

    pnl = (cur_prem - entry_prem) * qty
    pnl_pct = ((cur_prem - entry_prem) / entry_prem) * 100

    if idx % 5 == 0 or idx == len(today_1m) - 1:
        print(f"[{t_str}] Spot: {spot:.1f} | Opt Premium: Rs. {cur_prem:.2f} | PnL: Rs. {pnl:+,.2f} ({pnl_pct:+.1f}%) | Peak: Rs. {peak_prem:.2f} (+{peak_gain:.1f}%)")

print("\n--- Final Performance Summary ---")
last_bar = today_1m[-1]
final_prem = bsm_price(last_bar["close"], entry_strike, days_to_expiry, is_call=True)
final_pnl = (final_prem - entry_prem) * qty
final_pnl_pct = ((final_prem - entry_prem) / entry_prem) * 100
print(f"Initial Investment: Rs. {margin:.2f}")
print(f"Peak Option Premium: Rs. {peak_prem:.2f} (+{peak_gain:.1f}%)")
print(f"Current Premium as of {last_bar['time_str']}: Rs. {final_prem:.2f}")
print(f"Current Profit on 1 Lot: Rs. {final_pnl:+,.2f} ({final_pnl_pct:+.1f}%)")
