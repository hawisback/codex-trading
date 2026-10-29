"""Conservative evidence predicate for a persisted existing-order mutation.

This is not a broker request, acknowledgement, position-flat assertion, or
authorization to place orders. Only normalized, fresh broker orders with exact
identity and expected fields can clear an uncertain mutation. Missing evidence
leaves the journal unresolved.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from execution_safety import ReconciliationError


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() else None
    except (InvalidOperation, TypeError, ValueError):
        return None


def verified_mutation_evidence(
    intent: Mapping[str, Any],
    order: Mapping[str, Any],
    *,
    account_id: str,
    original_request_id: str,
) -> dict[str, Any] | None:
    """Return strict order-state evidence, or None if effect unproven.

    Account/request/order/symbol/scope mismatches are *errors*, never soft
    no-matches. A cancelled STOP does not establish a flat or protected long.
    """
    target = intent.get("target_order_id")
    if (not isinstance(target, str) or not target
            or str(order.get("order_id")) != target
            or not isinstance(account_id, str) or not account_id
            or order.get("account_id") != account_id
            or order.get("mode") != "LIVE"
            or order.get("engine_owned") is not True
            or order.get("request_id") != original_request_id
            or order.get("kind") != intent.get("target_kind")
            or order.get("symbol") != intent.get("symbol")
            or order.get("variety") != "regular"):
        raise ReconciliationError("Mutation broker order identity/scope mismatch")

    qty, fill = order.get("quantity"), order.get("filled_quantity")
    expected_qty = intent.get("target_quantity")
    if (type(qty) is not int or qty <= 0
            or type(fill) is not int or not 0 <= fill <= qty
            or (expected_qty is not None and
                (type(expected_qty) is not int or expected_qty != qty))):
        raise ReconciliationError("Mutation broker order quantity is unverified")
    # Partial execution makes target order state insufficient to prove that
    # a CANCEL/MODIFY did not create or remove additional exposure.
    if fill:
        return None

    phase = order.get("status")
    action = intent.get("mutation_action")
    if action == "CANCEL":
        if phase != "CANCELLED":
            return None
        return {"effect": "CANCELLED_ZERO_FILL", "broker_order_id": target,
                "broker_status": phase, "verified_quantity": qty,
                "verified_filled_quantity": 0}

    if action in ("MODIFY_STOP", "REPRICE_EXIT"):
        field = "expected_trigger_price" if action == "MODIFY_STOP" else "expected_limit_price"
        requested = _number(intent.get(field))
        if requested is None or requested <= 0:
            # Legacy unparameterized records are deliberately not auto-cleared.
            return None
        observed = _number(order.get("trigger_price" if action == "MODIFY_STOP" else "price"))
        if observed is None or observed != requested:
            return None
        if action == "MODIFY_STOP":
            limit = _number(intent.get("expected_limit_price"))
            actual_limit = _number(order.get("price"))
            if (intent.get("target_kind") != "STOP" or phase != "TRIGGER_PENDING"
                    or limit is None or limit <= 0 or limit != actual_limit):
                return None
            effect = "CONFIRMED_RESTING_STOP_PRICES"
        else:
            if intent.get("target_kind") != "EXIT" or phase != "OPEN":
                return None
            effect = "CONFIRMED_OPEN_EXIT_PRICE"
        return {"effect": effect, "broker_order_id": target,
                "broker_status": phase, "verified_quantity": qty,
                "verified_filled_quantity": 0}
    raise ReconciliationError("Unsupported recorded mutation action")
