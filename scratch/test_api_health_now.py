import time
import os
import sys
sys.path.insert(0, os.path.abspath("."))
from execution_client import AIExecutionClient

client = AIExecutionClient()

print("=" * 80)
print(f"BROKER & PLATFORM API HEALTH AUDIT - {time.strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# 1. Status
t0 = time.perf_counter()
status = client.get_status()
t_status = (time.perf_counter() - t0) * 1000.0
print(f"[OK]   Execution Status    | Time: {t_status:>6.1f}ms | Mode: {status.get('mode')}, LiveAuth: {status.get('live_authorized')}")

# 2. Broker Sessions
t0 = time.perf_counter()
sessions = client.get_broker_sessions()
t_sess = (time.perf_counter() - t0) * 1000.0
kite_sess = sessions.get("sessions", {}).get("kite", {})
breeze_sess = sessions.get("sessions", {}).get("icici_breeze", {})
print(f"[OK]   Broker Sessions     | Time: {t_sess:>6.1f}ms | Kite: {kite_sess.get('status')} | Breeze: {breeze_sess.get('status')}")

# 3. Funds / Margin
t0 = time.perf_counter()
funds = client.get_funds()
t_funds = (time.perf_counter() - t0) * 1000.0
print(f"[OK]   Account Funds       | Time: {t_funds:>6.1f}ms | Available Margin: INR {funds.get('available_margin', 0):,.2f}")

# 4. Positions
t0 = time.perf_counter()
pos = client.get_positions()
t_pos = (time.perf_counter() - t0) * 1000.0
open_pos = [p for p in pos.get("positions", []) if p.get("quantity", 0) != 0]
print(f"[OK]   Broker Positions    | Time: {t_pos:>6.1f}ms | Open Positions: {len(open_pos)}")

# 5. Orders (the one that timed out earlier!)
t0 = time.perf_counter()
orders = client.get_orders()
t_orders = (time.perf_counter() - t0) * 1000.0
print(f"[OK]   Broker Orders       | Time: {t_orders:>6.1f}ms | Total Orders Today: {len(orders)}")

# 6. Live Snapshot / Feed
t0 = time.perf_counter()
snap = client.get_snapshot()
t_snap = (time.perf_counter() - t0) * 1000.0
print(f"[OK]   NIFTY Snapshot      | Time: {t_snap:>6.1f}ms | Spot: {snap.get('spot')} | Change: {snap.get('day_change'):+.2f}%")

print("=" * 80)
