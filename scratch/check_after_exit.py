import sys
sys.path.insert(0, ".")
import urllib.request
import json
from execution_client import AIExecutionClient

client = AIExecutionClient()

funds = client.get_funds()
print("Broker Live Funds:", funds)

pos = client.get_positions()
print("Broker Open Positions:", pos)

orders = client.get_orders()
print(f"Total orders: {len(orders) if isinstance(orders, list) else 'dict'}")
if isinstance(orders, list):
    for o in orders[-5:]:
        print("Order:", o.get("order_id"), o.get("symbol"), o.get("kind"), o.get("status"), "Price:", o.get("price") or o.get("average_price"), "Time:", o.get("created_at"))
