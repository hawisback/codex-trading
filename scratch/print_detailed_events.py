import json

with open("logs/daily/2026-10-21/events.jsonl", "r", encoding="utf-8") as f:
    events = [json.loads(line) for line in f if line.strip()]

for i in range(55, min(len(events), 66)):
    ev = events[i]
    print(f"\n=== Event {i} [{ev.get('event')}] at {ev.get('timestamp')} ===")
    for k, v in ev.items():
        if k not in ("schema_version", "run_id"):
            print(f"  {k}: {v}")
