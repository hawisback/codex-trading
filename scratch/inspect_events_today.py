import json

with open("logs/daily/2026-10-21/events.jsonl", "r", encoding="utf-8") as f:
    events = [json.loads(line) for line in f if line.strip()]

print(f"Total events today: {len(events)}")
print("=" * 100)
for i, ev in enumerate(events):
    ts = ev.get("timestamp")
    evt = ev.get("event")
    state = ev.get("state", {})
    details = {}
    if evt == "candidate":
        details = {
            "signal": ev.get("decision", {}).get("signal"),
            "strategy": ev.get("decision", {}).get("strategy"),
            "reasons": ev.get("decision", {}).get("reasons"),
        }
    elif evt == "ai_consultation":
        details = {"dossier_target": ev.get("dossier", {}).get("instrument_id")}
    elif evt == "ai_verdict":
        details = {
            "action": ev.get("verdict", {}).get("action"),
            "is_approved": ev.get("verdict", {}).get("is_approved"),
            "reasoning": ev.get("verdict", {}).get("reasoning"),
            "trap": ev.get("verdict", {}).get("trap_detected"),
        }
    elif evt in ("entry_result", "order_submitted"):
        details = ev.get("result") or ev.get("order") or {}
    elif evt == "position_state":
        details = {
            "status": state.get("status"),
            "symbol": state.get("symbol"),
            "quantity": state.get("quantity"),
            "protection_confirmed": state.get("protection_confirmed"),
            "risk_exit_required": state.get("risk_exit_required"),
            "entries": len(state.get("entries", [])),
            "stops": len(state.get("stops", [])),
            "exits": len(state.get("exits", [])),
        }
    elif evt == "position_closed":
        details = {
            "status": state.get("status"),
            "symbol": state.get("symbol"),
            "exit_reason": state.get("exit_reason"),
            "entry_price": state.get("entry_price"),
            "last_bid": state.get("last_bid"),
            "exits": state.get("exits"),
        }
    else:
        details = {k: v for k, v in ev.items() if k not in ("schema_version", "event_id", "timestamp", "run_id")}
        
    print(f"[{i:02d}] {ts} | {evt:<20} | {details}")
