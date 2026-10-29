import os
import json
import sys
from kiteconnect import KiteConnect

# Force UTF-8 output encoding
sys.stdout.reconfigure(encoding='utf-8')

# Use injected credentials or the ignored .env in this repository. Never rely on
# credentials stored in another local checkout.
api_key = os.getenv("KITE_API_KEY")
access_token = os.getenv("KITE_ACCESS_TOKEN")
if not api_key or not access_token:
    env_path = ".env"
    if os.path.isfile(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("KITE_API_KEY=") and not api_key:
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                elif line.startswith("KITE_ACCESS_TOKEN=") and not access_token:
                    access_token = line.split("=", 1)[1].strip().strip('"').strip("'")

if api_key and access_token:
    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)

    try:
        print("\n=== ALL EXECUTED TRADES ON KITE TODAY (kite.trades()) ===")
        trades = kite.trades()
        print(f"Total executed trades: {len(trades)}")
        for t in trades:
            order_id = t.get("order_id")
            trade_id = t.get("trade_id")
            sym = t.get("tradingsymbol")
            tx_type = t.get("transaction_type")
            qty = t.get("quantity")
            price = t.get("average_price") or t.get("price")
            fill_time = t.get("fill_timestamp") or t.get("order_timestamp")
            print(f"Trade #{trade_id} | Order #{order_id} | {sym} | {tx_type} {qty} @ Rs.{price} | Time: {fill_time}")

        print("\n=== ALL ORDERS ON KITE TODAY (kite.orders()) ===")
        orders = kite.orders()
        print(f"Total orders: {len(orders)}")
        for o in orders:
            order_id = o.get("order_id")
            sym = o.get("tradingsymbol")
            status = o.get("status")
            tx_type = o.get("transaction_type")
            qty = o.get("quantity")
            filled_qty = o.get("filled_quantity")
            price = o.get("price")
            avg_price = o.get("average_price")
            trigger_price = o.get("trigger_price")
            order_time = o.get("order_timestamp")
            tag = o.get("tag") or ""
            status_msg = o.get("status_message") or ""
            print(f"Order #{order_id} | {sym} | {tx_type} {qty} (Filled: {filled_qty}) | Status: {status} | Avg: Rs.{avg_price} (Limit: Rs.{price}, Trig: Rs.{trigger_price}) | Tag: {tag} | Time: {order_time} | {status_msg}")

    except Exception as e:
        print("Kite API Error:", e)
