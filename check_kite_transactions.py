"""
Zerodha Kite Transactions & Orderbook Inspector
Directly queries Zerodha Kite Connect API using active authenticated broker credentials.
"""

import sys
import os
from pathlib import Path

# Force UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Read credentials from the environment first, then the ignored repo-local .env.
# Keep this utility independent of other local checkouts and never commit broker tokens.
api_key = os.getenv("KITE_API_KEY")
access_token = os.getenv("KITE_ACCESS_TOKEN")
env_path = Path(".env")
if env_path.is_file() and (not api_key or not access_token):
    with env_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("KITE_API_KEY=") and not api_key:
                api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("KITE_ACCESS_TOKEN=") and not access_token:
                access_token = line.split("=", 1)[1].strip().strip('"').strip("'")

if not api_key or not access_token:
    print("❌ Could not find active KITE_API_KEY and KITE_ACCESS_TOKEN.")
    sys.exit(1)

try:
    from kiteconnect import KiteConnect
except ImportError:
    print("❌ kiteconnect library not found. Install it in this project's Python environment.")
    sys.exit(1)

kite = KiteConnect(api_key=api_key)
kite.set_access_token(access_token)

print("=" * 80)
print("  ZERODHA KITE OFFICIAL TRADEBOOK & ORDERBOOK (TODAY)")
print("=" * 80)

try:
    trades = kite.trades()
    print(f"\n📊 [EXECUTED TRADES TODAY] Total: {len(trades)}")
    print("-" * 80)
    for t in trades:
        trade_id = t.get("trade_id")
        order_id = t.get("order_id")
        sym = t.get("tradingsymbol")
        side = t.get("transaction_type")
        qty = t.get("quantity")
        price = t.get("average_price") or t.get("price")
        fill_time = t.get("fill_timestamp") or t.get("order_timestamp")
        print(f"  • Trade #{trade_id} | Order #{order_id} | {sym:20} | {side:4} {qty:3} @ Rs.{price:.2f} | Time: {fill_time}")

    orders = kite.orders()
    print(f"\n📋 [COMPLETE ORDERBOOK TODAY] Total: {len(orders)}")
    print("-" * 80)
    for o in orders:
        order_id = o.get("order_id")
        sym = o.get("tradingsymbol")
        status = o.get("status")
        side = o.get("transaction_type")
        qty = o.get("quantity")
        filled = o.get("filled_quantity")
        avg = o.get("average_price") or 0.0
        limit_p = o.get("price") or 0.0
        trig_p = o.get("trigger_price") or 0.0
        order_time = o.get("order_timestamp")
        tag = o.get("tag") or ""
        msg = o.get("status_message") or ""
        
        status_icon = "✅" if status == "COMPLETE" else ("❌" if status == "REJECTED" else ("🚫" if status == "CANCELLED" else "⏳"))
        tag_str = f" [Tag: {tag}]" if tag else ""
        print(f"  {status_icon} Order #{order_id} | {sym:20} | {side:4} {qty:3} (Fill: {filled:3}) | Status: {status:9} | Avg: Rs.{avg:.2f} (Limit: {limit_p}, Trig: {trig_p}){tag_str} | {order_time}")
        if msg:
            print(f"     ↳ Reason: {msg}")

    print("=" * 80)

except Exception as e:
    print(f"❌ Error fetching from Kite API: {e}")
