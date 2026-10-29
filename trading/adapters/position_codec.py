"""Schema-v2 position-state compatibility, independent of filesystem I/O.

The live OMS owns reconciliation and exposure decisions. This codec only manages
persisted field aliases and rejects malformed record containers; it never treats
invalid persisted state as an empty position.
"""

from execution_safety import ReconciliationError, TERMINAL, status


class PositionStateCodec:
    """Translate between persisted JSON dictionaries and legacy OMS views.

    Encoding deliberately updates the supplied dictionary in place: existing
    callers of ``JsonPositionStore.save`` rely on the aliases being populated.
    Decoding only hydrates in memory; the original JSON file is not rewritten.
    """

    SCHEMA_VERSION = 2
    COLLECTIONS = ("entries", "stops", "exits")

    @classmethod
    def encode(cls, state: dict) -> dict:
        state["schema_version"] = cls.SCHEMA_VERSION
        state["entry_order_ids"] = [e["order_id"] for e in state.get("entries", []) if e.get("order_id")]
        state["stop_order_ids"] = [
            s["order_id"]
            for s in state.get("stops", [])
            if s.get("order_id") and status(s) not in TERMINAL
        ]
        state["entry_order_id"] = next(iter(state["entry_order_ids"]), None)
        state["trade_id"] = state["entry_order_id"] or "RECONCILIATION-PENDING"
        state["stop_order_id"] = next(iter(state["stop_order_ids"]), None)
        return state

    @classmethod
    def decode(cls, state: dict) -> dict:
        # Validate all collections *before* adding legacy aliases, so a failed
        # recovery never partially normalizes an invalid document.
        for field in cls.COLLECTIONS:
            records = state.get(field, [])
            if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
                raise ReconciliationError(f"Malformed position {field}; entries blocked")

        stop_order_ids = state.get("stop_order_ids")
        if stop_order_ids is not None and (
            not isinstance(stop_order_ids, list)
            or any(
                not (
                    (isinstance(order_id, str) and bool(order_id))
                    or (type(order_id) is int and order_id > 0)
                )
                for order_id in stop_order_ids
            )
        ):
            raise ReconciliationError("Malformed stop_order_ids; entries blocked")

        for field in cls.COLLECTIONS:
            state.setdefault(field, [])
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
