import json

log_path = "logs/daily/2026-10-23/events.jsonl"
events = []
with open(log_path, encoding="utf-8") as f:
    for line in f:
        try:
            events.append(json.loads(line))
        except Exception:
            pass

print(f"Total events logged today: {len(events)}")

candidates = [e for e in events if e.get("event") == "candidate"]
verdicts = [e for e in events if e.get("event") == "ai_verdict"]

print(f"Candidates submitted to AI: {len(candidates)}")
print(f"AI Verdicts issued: {len(verdicts)}")

approved = [v for v in verdicts if v.get("payload", {}).get("is_approved") or v.get("is_approved")]
vetoed = [v for v in verdicts if not (v.get("payload", {}).get("is_approved") or v.get("is_approved"))]

print(f"Approved: {len(approved)}")
print(f"Vetoed: {len(vetoed)}")

# Group vetoes by trap
traps = {}
for v in vetoed:
    p = v.get("payload") or v
    t = p.get("trap_detected", "Unknown")
    traps[t] = traps.get(t, 0) + 1

print("\nTraps triggered today:")
for t, count in traps.items():
    print(f"  • {t}: {count} candidate(s) blocked")
