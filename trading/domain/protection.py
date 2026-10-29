"""Pure OMS stop-floor calculations, with no broker mutation or strategy choice.

This is the structural start of POL-06. Until the owner approves common stop
percentages/time windows, existing stop values are supplied by the caller.
Do not remove the monotonic ratchet or confirmation checks in StopManager.
"""

from collections.abc import Mapping
from typing import Any

from trading.domain.prices import round_tick


def entry_reference(stop: Mapping[str, Any]) -> Any:
    """Use existing STOP-to-entry correlation, including legacy parent alias."""
    return stop.get("entry_order_id") or stop.get("parent_order_id")


def existing_stop_floor(state: Mapping[str, Any]) -> float:
    """Preserve the exact current stop floor behavior for open entry balances.

    A historical stop can retain a floor while its parent entry has a verified
    positive balance; that behavior remains unchanged pending policy review.
    """
    balances = state.get("entry_balances", {})
    return max(
        [float(s.get("trigger_price") or 0) for s in state["stops"]
         if balances.get(entry_reference(s), 0) > 0]
        + [float(state.get("desired_stop_trigger") or 0)]
    )


def initial_stop_trigger(entry_price: float, initial_loss_pct: float, floor: float) -> float:
    """Mechanical initial protection: same formula and tick rounding as before."""
    return round_tick(max(entry_price * (1 - initial_loss_pct / 100), floor))
