import re

times = []
spots = []

with open("logs/trader-2026-10-23.log", encoding="utf-8") as f:
    for line in f:
        m = re.search(r"(\d{2}:\d{2}:\d{2}).*Spot:\s*([\d\.]+)", line)
        if m:
            t, s = m.groups()
            times.append(t)
            spots.append(float(s))

def trace_after(start_time, duration_mins=60):
    start_idx = None
    for i, t in enumerate(times):
        if t >= start_time:
            start_idx = i
            break
    if start_idx is None:
        return
    
    base_spot = spots[start_idx]
    window = spots[start_idx : start_idx + duration_mins]
    max_s = max(window)
    min_s = min(window)
    print(f"\nTrace after {start_time} (Entry Spot: {base_spot:.2f}):")
    print(f"  Max Spot: {max_s:.2f} ({max_s - base_spot:+.1f} pts) at {times[start_idx + window.index(max_s)]}")
    print(f"  Min Spot: {min_s:.2f} ({min_s - base_spot:+.1f} pts) at {times[start_idx + window.index(min_s)]}")
    for k in range(0, min(len(window), 45), 10):
        print(f"    +{k}m ({times[start_idx+k]}): {spots[start_idx+k]:.2f} ({spots[start_idx+k] - base_spot:+.1f} pts)")

# Trace candidate #1 at 10:22:04
trace_after("10:22:04", 45)

# Trace candidate #2 at 10:45:08 (BUY_PE)
trace_after("10:45:08", 45)

# Trace candidate #3 at 11:02:08
trace_after("11:02:08", 45)

# Trace bottom at 12:52:08
trace_after("12:52:08", 60)
