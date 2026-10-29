import sys, os
sys.path.insert(0, os.path.abspath("."))
from execution_client import AIExecutionClient
client = AIExecutionClient()
orders = client.get_orders()
for i, o in enumerate(orders):
    k = o.get("kind")
    st = o.get("status")
    bid = str(o.get("broker_order_id"))
    oid = o.get("order_id")
    req = o.get("request_id")
    dt = str(o.get("created_at"))[:10]
    print(f"[{i:02d}] {dt} | {k:<5} | {st:<15} | broker_id={bid:<22} | order_id={oid} | req={req}")
