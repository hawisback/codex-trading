"""Pure, broker-observation-based position balance calculations for OMS.

Network reads, cancellation, journal writes and verification ownership remain in
PositionLifecycle. This module must not assume unknown orders are flat.
"""

from collections.abc import Mapping
from typing import Any

from execution_safety import ReconciliationError, filled


def reconciled_entry_balances(state: Mapping[str, Any]) -> dict[str, int]:
    """Reconcile filled entry quantity minus filled STOP/EXIT quantity per entry ID.

    Preserves PositionLifecycle._entry_balances semantics for the current v2
    schema and legacy parent_order_id aliases. Missing allocation identity for
    an executed SELL, or a negative residual, is a reconciliation failure.
    """
    balances = {e["order_id"]: filled(e) for e in state["entries"] if e.get("order_id")}
    for order in state["stops"] + state["exits"]:
        qty = filled(order)
        ref = order.get("entry_order_id") or order.get("parent_order_id")
        if qty and ref not in balances:
            raise ReconciliationError("Cannot allocate SELL fills to entry references")
        if ref in balances:
            balances[ref] -= qty
    if any(q < 0 for q in balances.values()):
        raise ReconciliationError("SELL fills exceed tracked entry quantity")
    return balances
