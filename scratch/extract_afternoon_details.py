import sys
import re

try:
    sys.stdout.reconfigure(encoding="utf-8")
except:
    pass

events = []
with open("logs/trader.log", "r", encoding="utf-8", errors="ignore") as f:
    for line in f:
        if not ("2026-10-14 1" in line):
            continue
        line_s = line.strip()
        if "Decision: NEUTRAL" in line_s:
            continue
        
        # Check interesting keywords
        if any(k in line_s for k in [
            "Decision: BUY",
            "Triggering AI Consultation",
            "AI Consultation APPROVED",
            "AI Consultation VETOED",
            "Submitting AI Order",
            "Submitting BUY order",
            "QUANTITY_LIMIT_EXCEEDED",
            "Insufficient funds",
            "FILLED",
            "Placing Resting Stop",
            "Ratcheting",
            "ORDER FLOW BLOCKED",
            "CLIMAX",
            "PULLBACK BLOCKED",
            "ACTIVE POSITION",
            "Square-Off",
            "Cancelled"
        ]):
            events.append(line_s)

print(f"Total relevant event lines: {len(events)}")

# Print with deduplication of identical consecutive lines
last_line = ""
repeat_count = 0
for l in events:
    # simplify timestamp
    content = l[24:] # strip timestamp
    if content == last_line:
        repeat_count += 1
        continue
    else:
        if repeat_count > 1:
            print(f"    ... [repeated {repeat_count} times]")
        repeat_count = 1
        last_line = content
        print(l[:23] + " | " + content)

if repeat_count > 1:
    print(f"    ... [repeated {repeat_count} times]")
