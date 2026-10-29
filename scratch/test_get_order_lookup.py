import sys, os
sys.path.insert(0, os.path.abspath("."))
from execution_client import AIExecutionClient
client = AIExecutionClient()

test_ids = [
    ("Today Entry", "65002ee636824dc99f1d6a9fd9c41935"),
    ("Today Stop 1", "1e82a54dbf49456dbf37fe3d483c4ee8"),
    ("Today Stop 2", "e3c4f374ea3f40918c90c9e91c1b556c"),
    ("Today Exit", "bf236e2d824642459eb9104df291970e"),
    ("Oct 19 Entry", "11ef1f934f1d4b2dbe36316adfbe5219"),
    ("No Broker ID", "a0213457b4b543f6a2020940556353d0"),
    ("Paper Order", "3e20e2458131418486353995678e8dc8"),
]

for label, oid in test_ids:
    try:
        res = client.get_order(oid)
        st = res.get("status")
        bid = res.get("broker_order_id")
        err = res.get("error")
        detail = res.get("detail")
        print(f"{label:<15} ({oid[:8]}...): status={st} broker_id={bid} error={err} detail={detail}")
    except Exception as e:
        print(f"{label:<15} ({oid[:8]}...): EXCEPTION {e}")
