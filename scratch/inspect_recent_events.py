import json

with open("logs/daily/2026-10-21/events.jsonl", "r", encoding="utf-8") as f:
    events = [json.loads(line) for line in f if line.strip()]

recent_events = [e for e in events if e.get("timestamp", "") >= "2026-10-21T10:45:00"]
print(f"Total events since 10:45 IST: {len(recent_events)}")
print("=" * 100)

for i, ev in enumerate(recent_events):
    ts = ev.get("timestamp")
    evt = ev.get("event")
    state = ev.get("state", {})
    details = {}
    if evt == "candidate":
        details = {
            "signal": ev.get("decision", {}).get("signal"),
            "strategy": ev.get("decision", {}).get("strategy"),
            "reasons": ev.get("decision", {}).get("reasons"),
            "setup": ev.get("decision", {}).get("setup_type"),
            "strike": ev.get("decision", {}).get("target_strike"),
            "price": ev.get("decision", {}).get("ltp"),
        }
    elif evt == "ai_consultation":
        details = {"target": ev.get("dossier", {}).get("instrument_id")}
    elif evt == "ai_verdict":
        details = {
            "action": ev.get("verdict", {}).get("action"),
            "approved": ev.get("verdict", {}).get("is_approved"),
            "reasoning": ev.get("verdict", {}).get("reasoning"),
            "trap": ev.get("verdict", {}).get("trap_detected"),
        }
    elif evt == "entry_result":
        details = ev.get("result", {})
    elif evt in ("position_state", "position_closed"):
        details = {
            "status": state.get("status"),
            "symbol": state.get("symbol"),
            "qty": state.get("quantity"),
            "protection": state.get("protection_confirmed"),
            "risk_exit": state.get("risk_exit_required"),
            "exit_reason": state.get("exit_reason"),
            "entries_len": len(state.get("entries", [])),
            "stops_len": len(state.get("stops", [])),
            "exits_len": len(state.get("exits", [])),
        }
    else:
        details = {k: v for k, v in ev.items() if k not in ("schema_version", "event_id", "timestamp", "run_id")}

    print(f"[{i:02d}] {ts[11:19]} | {evt:<22} | {details}")
