"""JSON position repository, including the existing schema-v2 compatibility view."""

import json
from pathlib import Path

from execution_safety import ReconciliationError, TERMINAL, atomic_save, status


class JsonPositionStore:
    def __init__(self, path, *, writer=None):
        self.path = Path(path)
        self._writer = writer

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, data: dict) -> None:
        data["schema_version"] = 2
        data["entry_order_ids"] = [e["order_id"] for e in data.get("entries", []) if e.get("order_id")]
        data["stop_order_ids"] = [
            s["order_id"] for s in data.get("stops", []) if s.get("order_id") and status(s) not in TERMINAL
        ]
        data["entry_order_id"] = next(iter(data["entry_order_ids"]), None)
        data["trade_id"] = data["entry_order_id"] or "RECONCILIATION-PENDING"
        data["stop_order_id"] = next(iter(data["stop_order_ids"]), None)
        (self._writer or atomic_save)(self.path, data)

    def load(self) -> dict:
        if not self.exists():
            return {}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not state:
                raise ValueError("Invalid position state")
        except (OSError, ValueError) as exc:
            raise ReconciliationError("Unreadable position state; entries blocked") from exc
        state.setdefault("entries", [])
        state.setdefault("stops", [])
        state.setdefault("exits", [])
        entry_id = state.get("entry_order_id")
        if entry_id and not str(entry_id).startswith("ACTIVE-POS-") and not state["entries"]:
            state["entries"].append(
                {
                    "order_id": entry_id,
                    "status": "UNKNOWN",
                    "kind": "ENTRY",
                    "quantity": state.get("quantity", 0),
                }
            )
        for stop_id in state.get("stop_order_ids", []) or [state.get("stop_order_id")]:
            if stop_id and not any(s.get("order_id") == stop_id for s in state["stops"]):
                state["stops"].append(
                    {
                        "order_id": stop_id,
                        "entry_order_id": entry_id,
                        "kind": "STOP",
                        "trigger_price": state.get("current_stop_trigger", 0),
                        "status": "UNKNOWN",
                    }
                )
        return state

    def delete(self, *, missing_ok: bool = False) -> None:
        self.path.unlink(missing_ok=missing_ok)
