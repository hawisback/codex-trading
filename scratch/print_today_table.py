from trading.bootstrap import configure_console
configure_console()
import json

events = []
with open("logs/daily/2026-10-23/events.jsonl", encoding="utf-8") as f:
    for line in f:
        d = json.loads(line)
        if d.get("event") == "ai_verdict":
            events.append(d)

print(f"Total Candidates Evaluated Today: {len(events)}\n")
print(f"{'#':<3} | {'Time':<8} | {'Signal':<7} | {'Setup':<14} | {'Strike':<6} | {'LTP':<6} | {'Trap Intercepted':<42} | {'AI Forensic Reasoning'}")
print("-" * 145)

for i, e in enumerate(events, 1):
    dec = e.get("decision", {})
    v = e.get("verdict", {})
    ts = e.get("timestamp", "")[11:19]
    sig = dec.get("signal", "N/A")
    setup = dec.get("setup_type", "N/A")
    strike = str(dec.get("target_strike", "N/A"))
    ltp = float(dec.get("ltp") or 0.0)
    trap_name = v.get("trap_detected", "N/A")
    reason = v.get("reasoning", "")
    print(f"{i:<3} | {ts:<8} | {sig:<7} | {setup:<14} | {strike:<6} | {ltp:<6.1f} | {trap_name:<42} | {reason}")
