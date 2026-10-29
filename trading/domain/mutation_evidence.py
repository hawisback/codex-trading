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


def verified_partial_cancel_exposure(
    intent: Mapping[str, Any],
    target: Mapping[str, Any],
    orders: list[Mapping[str, Any]],
    positions: list[Mapping[str, Any]],
    *,
    account_id: str,
    original_request_id: str,
) -> dict[str, Any] | None:
    """Confirm a partially filled CANCEL *and* exact remaining exposure.

    Requires the entire verified order snapshot, no working orders, one
    account-scoped position or none, and strict intraday buy/sell accounting.
    The caller MUST bracket the position read with two identical broker order
    snapshots. This evidence never authorizes a new SELL, proves a stop is
    currently protecting a position, or substitutes for OMS final preflight.
    """
    if intent.get("mutation_action") != "CANCEL":
        return None
    if not isinstance(target, Mapping):
        return None
    # The normal zero-fill verifier handles cancelled unfilled orders. For
    # partials, validate the same immutable target identity explicitly.
    order_id = intent.get("target_order_id")
    qty, part = target.get("quantity"), target.get("filled_quantity")
    if (not isinstance(order_id, str) or not order_id
            or str(target.get("order_id")) != order_id
            or type(qty) is not int or type(part) is not int
            or not 0 < part < qty
            or type(intent.get("target_quantity")) is not int
            or intent["target_quantity"] != qty):
        return None
    if (target.get("status") != "CANCELLED"
            or target.get("account_id") != account_id
            or target.get("mode") != "LIVE"
            or target.get("engine_owned") is not True
            or target.get("kind") != intent.get("target_kind")
            or target.get("symbol") != intent.get("symbol")
            or target.get("request_id") != original_request_id
            or target.get("variety") != "regular"):
        raise ReconciliationError("Partial cancel target identity unverified")
    if not isinstance(orders, list) or not isinstance(positions, list):
        raise ReconciliationError("Partial cancellation needs both broker books")
    seen, buys, sells, active = set(), 0, 0, 0
    symbol = target["symbol"]
    for order in orders:
        if not isinstance(order, Mapping):
            raise ReconciliationError("Malformed order in partial cancel book")
        oid = order.get("order_id")
        if not isinstance(oid, str) or not oid or oid in seen:
            raise ReconciliationError("Duplicate or absent broker order ID")
        seen.add(oid)
        if order.get("account_id") != account_id or order.get("mode") != "LIVE":
            raise ReconciliationError("Foreign broker order in recovery book")
        kind, state = order.get("kind"), order.get("status")
        if kind not in ("ENTRY", "STOP", "EXIT") or state not in (
            "FILLED", "CANCELLED", "REJECTED", "EXPIRED",
            "TRIGGER_PENDING", "OPEN", "PENDING", "PARTIALLY_FILLED",
        ):
            raise ReconciliationError("Unknown broker order type/status during recovery")
        n, fill = order.get("quantity"), order.get("filled_quantity")
        if (type(n) is not int or type(fill) is not int or n <= 0
                or not 0 <= fill <= n):
            raise ReconciliationError("Unverified order fills during recovery")
        if state not in ("FILLED", "CANCELLED", "REJECTED", "EXPIRED"):
            active += 1
        # Refuse external executions or active external orders anywhere on
        # this one-account one-position trading deployment.
        if (fill or state not in ("FILLED", "CANCELLED", "REJECTED", "EXPIRED")) and (
            order.get("engine_owned") is not True
        ):
            raise ReconciliationError("Unowned orders require operator recovery")
        if order.get("symbol") != symbol:
            if fill or state not in ("FILLED", "CANCELLED", "REJECTED", "EXPIRED"):
                raise ReconciliationError("Second instrument requires operator recovery")
            continue
        if fill:
            if kind == "ENTRY":
                buys += fill
            else:
                # A SELL must be linked to an entry and be owned.
                if not (order.get("entry_order_id") or order.get("parent_order_id")):
                    raise ReconciliationError("Unallocated SELL fill during recovery")
                sells += fill
    if order_id not in seen or active:
        return None  # An outstanding order can change exposure after this read.
    # The target must be the *same* normalized record in the verified complete
    # book, not a stale caller-supplied copy with an identical order ID.
    book_target = next(o for o in orders if o.get("order_id") == order_id)
    for field in ("request_id", "kind", "symbol", "status", "quantity",
                  "filled_quantity", "entry_order_id", "parent_order_id"):
        if target.get(field) != book_target.get(field):
            return None
    residual = buys - sells
    if residual < 0:
        raise ReconciliationError("Over-sold broker fills during partial cancellation")
    nonzero = []
    for pos in positions:
        if not isinstance(pos, Mapping):
            raise ReconciliationError("Malformed broker position")
        if pos.get("account_id") != account_id or pos.get("mode") != "LIVE":
            raise ReconciliationError("Broker position account mismatch")
        q = pos.get("quantity")
        if type(q) is not int:
            raise ReconciliationError("Nonintegral broker position quantity")
        if q:
            nonzero.append(pos)
    if len(nonzero) > 1:
        raise ReconciliationError("Multiple broker positions require operator recovery")
    if nonzero and (nonzero[0].get("symbol") != symbol
                    or nonzero[0]["quantity"] < 0):
        raise ReconciliationError("Unexpected broker position during recovery")
    observed = nonzero[0]["quantity"] if nonzero else 0
    if observed != residual:
        return None  # The broker books disagree or fills have raced our reads.
    return {
        "effect": "PARTIAL_CANCELLED_POSITION_RECONCILED",
        "broker_order_id": order_id,
        "broker_status": "CANCELLED",
        "verified_quantity": qty,
        "verified_filled_quantity": part,
        "reconciled_remaining_exposure": residual,
        "broker_position_quantity": observed,
        "verified_order_count": len(seen),
        "replacement_or_exit_authorized": False,
    }


def stable_order_fingerprint(orders: list[Mapping[str, Any]]) -> tuple:
    """Strict identity/fill snapshot equality across a broker position read."""
    if not isinstance(orders, list):
        raise ReconciliationError("No complete broker order book")
    seen, entries = set(), []
    for order in orders:
        if not isinstance(order, Mapping):
            raise ReconciliationError("Malformed broker order snapshot")
        oid = order.get("order_id")
        if not isinstance(oid, str) or not oid or oid in seen:
            raise ReconciliationError("Ambiguous broker order snapshot")
        seen.add(oid)
        entries.append((oid, order.get("status"), order.get("quantity"),
                        order.get("filled_quantity"), order.get("symbol"),
                        order.get("kind"), order.get("account_id"),
                        order.get("mode"), order.get("price"), order.get("trigger_price")))
    return tuple(sorted(entries))
