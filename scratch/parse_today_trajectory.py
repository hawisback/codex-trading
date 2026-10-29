import re

times = []
spots = []
vwaps = []
changes = []

with open("logs/trader-2026-10-23.log", encoding="utf-8") as f:
    for line in f:
        m = re.search(r"(\d{2}:\d{2}:\d{2}).*Spot:\s*([\d\.]+)\s*\(Change:\s*([\+\-\d\.]+)%\).*VWAP:\s*([\d\.]+)", line)
        if m:
            t, s, c, v = m.groups()
            times.append(t)
            spots.append(float(s))
            changes.append(float(c))
            vwaps.append(float(v))

print(f"Total cycles extracted: {len(times)}")
print(f"Day High: {max(spots):.2f} at {times[spots.index(max(spots))]}")
print(f"Day Low:  {min(spots):.2f} at {times[spots.index(min(spots))]}")
print(f"Day Open: {spots[0]:.2f} at {times[0]}")
print(f"Day Close:{spots[-1]:.2f} at {times[-1]}")
print(f"Total Drop: {max(spots) - min(spots):.2f} pts!")

# Sample every 30 minutes
print("\nSession Milestones:")
for i in range(0, len(times), 30):
    print(f"  {times[i]} | Spot: {spots[i]:>8.2f} | VWAP: {vwaps[i]:>8.2f} | Diff: {spots[i] - vwaps[i]:>+6.1f} pts | Change: {changes[i]:>+6.2f}%")
