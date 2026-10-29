import json
import urllib.request
import re
from datetime import datetime

def main():
    print("=" * 70)
    print("FORENSIC AUDIT: OCTOBER 14, 2026 SESSION (FOCUS: AFTERNOON OPPORTUNITIES)")
    print("=" * 70)

    # 1. Fetch candles from API
    try:
        req = urllib.request.Request("http://localhost:8000/api/v1/ai/nifty/candles?interval=1m&limit=375")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            candles = data.get("candles", [])
    except Exception as e:
        print(f"Error fetching candles: {e}")
        candles = []

    print(f"Total 1m candles fetched: {len(candles)}")
    if candles:
        first = candles[0]
        last = candles[-1]
        print(f"Start: {first.get('start_time')} | Close: {first.get('close')}")
        print(f"End:   {last.get('start_time')} | Close: {last.get('close')}")

    # 2. Fetch orders
    try:
        req = urllib.request.Request("http://localhost:8000/api/v1/ai/execution/orders")
        with urllib.request.urlopen(req, timeout=10) as resp:
            orders_data = json.loads(resp.read().decode())
            orders = orders_data.get("orders", []) if isinstance(orders_data, dict) else orders_data
    except Exception as e:
        print(f"Error fetching orders: {e}")
        orders = []

    print(f"\nTotal Journal Orders: {len(orders)}")
    for i, o in enumerate(orders):
        print(f"[{i+1}] {o.get('order_id')} | {o.get('kind')} | {o.get('symbol')} | Qty: {o.get('quantity')} | Limit: {o.get('limit_price')} | Avg: {o.get('average_price')} | Status: {o.get('status')} | Message: {o.get('message')} | Created: {o.get('created_at')}")

    # 3. Analyze afternoon candles (12:00 to 15:30)
    print("\n" + "=" * 70)
    print("AFTERNOON PRICE ACTION (12:00 to 15:30 IST)")
    print("=" * 70)
    
    afternoon_candles = []
    for c in candles:
        st = c.get("start_time", "")
        # Time part
        time_part = st.split("T")[1][:5] if "T" in st else st[-8:-3]
        if time_part >= "12:00":
            afternoon_candles.append((time_part, c))

    if afternoon_candles:
        high_p = max(c["high"] for _, c in afternoon_candles)
        low_p = min(c["low"] for _, c in afternoon_candles)
        open_1200 = afternoon_candles[0][1]["open"]
        close_1530 = afternoon_candles[-1][1]["close"]
        print(f"12:00 Open: {open_1200} | 15:30 Close: {close_1530} | Drop: {close_1530 - open_1200:.2f} pts")
        print(f"Afternoon High: {high_p} | Afternoon Low: {low_p} | Total Range: {high_p - low_p:.2f} pts")
        
        # Breakdown into 15m intervals
        print("\n15-Minute Windows:")
        for w_start in ["12:00", "12:15", "12:30", "12:45", "13:00", "13:15", "13:30", "13:45", "14:00", "14:15", "14:30", "14:45", "15:00", "15:15"]:
            w_candles = [c for t, c in afternoon_candles if t >= w_start and t < f"{int(w_start[:2]) + (1 if int(w_start[3:])+15>=60 else 0):02d}:{(int(w_start[3:])+15)%60:02d}"]
            if w_candles:
                o = w_candles[0]["open"]
                h = max(c["high"] for c in w_candles)
                l = min(c["low"] for c in w_candles)
                cl = w_candles[-1]["close"]
                v = sum(c.get("volume", 0) for c in w_candles)
                print(f"  {w_start} - {w_candles[-1]['start_time'][-8:-3]}: Open={o:.2f}, High={h:.2f}, Low={l:.2f}, Close={cl:.2f} (Delta={cl-o:+.2f} pts)")

    # 4. Parse trader.log for afternoon evaluations and signals
    print("\n" + "=" * 70)
    print("PARSING TRADER.LOG FOR AFTERNOON SIGNALS & BLOCKS (12:00 - 15:30)")
    print("=" * 70)
    
    log_file = "logs/trader.log"
    blocks = []
    signals = []
    consultations = []
    
    with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if not ("2026-10-14 12:" in line or "2026-10-14 13:" in line or "2026-10-14 14:" in line or "2026-10-14 15:" in line):
                continue
            
            # Check for candidate signals or blocks
            if "Candidate Signal:" in line or "Signal Candidate" in line or "EVALUATING" in line or "PULLBACK" in line or "BLOCKED" in line or "Veto" in line or "APPROVED" in line or "REJECTED" in line or "SUBMITTING" in line or "FILLED" in line or "TRIGGER" in line:
                if any(k in line for k in ["Signal Candidate", "Consultation", "VETO", "VERDICT", "REJECT", "FILLED", "Submitting", "Decision", "BLOCKED:"]):
                    print(line.strip())

if __name__ == "__main__":
    main()
