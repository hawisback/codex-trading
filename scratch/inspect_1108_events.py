import json

with open("logs/daily/2026-10-21/events.jsonl", "r", encoding="utf-8") as f:
    events = [json.loads(line) for line in f if line.strip()]

target_events = [e for e in events if "11:08:" in e.get("timestamp", "")]
print(f"Events at 11:08: {len(target_events)}")
for i, ev in enumerate(target_events):
    print(f"\n--- Event at {ev.get('timestamp')} [{ev.get('event')}] ---")
    for k, v in ev.items():
        if k not in ("schema_version", "run_id"):
            print(f"  {k}: {v}")
