"""Validate read-only broker evidence without inventing missing fields.

This is a structural R04 anti-corruption contract. Existing Kite, Breeze
and proxy adapters still require separate integration and conformance checks.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from market_clock import IST_TZ


class BrokerContractError(ValueError):
    pass


def _number(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise BrokerContractError("BROKER_NUMBER_INVALID")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BrokerContractError("BROKER_NUMBER_INVALID") from exc
    if not result.is_finite():
        raise BrokerContractError("BROKER_NUMBER_INVALID")
    return result


def _fresh_timestamp(value: Any, now: datetime, max_age_sec: int) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise BrokerContractError("BROKER_CLOCK_UNVERIFIED")
    if not isinstance(value, str):
        raise BrokerContractError("BROKER_TIMESTAMP_MISSING")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BrokerContractError("BROKER_TIMESTAMP_INVALID") from exc
    if stamp.tzinfo is None:
        raise BrokerContractError("BROKER_TIMESTAMP_AMBIGUOUS")
    delta = (now - stamp).total_seconds()
    if delta < 0 or delta > max_age_sec:
        raise BrokerContractError("BROKER_SNAPSHOT_STALE")
    return stamp.astimezone(IST_TZ)


@dataclass(frozen=True)
class BrokerFundsView:
    account_id: str
    asof: datetime
    available_margin: Decimal
    max_single_order_quantity: int
    source: str

    @classmethod
    def validated(cls, payload: Mapping[str, Any], *, account_id: str, now: datetime, max_age_sec: int = 60):
        if not isinstance(payload, Mapping) or payload.get("error"):
            raise BrokerContractError("BROKER_FUNDS_UNAVAILABLE")
        if not isinstance(account_id, str) or not account_id:
            raise BrokerContractError("BROKER_ACCOUNT_UNVERIFIED")
        if payload.get("account_id") != account_id:
            raise BrokerContractError("BROKER_ACCOUNT_MISMATCH")
        stamp = _fresh_timestamp(payload.get("funds_asof"), now, max_age_sec)
        margin = _number(payload.get("available_margin"))
        if margin < 0:
            raise BrokerContractError("BROKER_MARGIN_INVALID")
        limit = payload.get("max_single_order_quantity")
        if type(limit) is not int or limit <= 0:
            raise BrokerContractError("BROKER_QUANTITY_LIMIT_UNVERIFIED")
        source = payload.get("source")
        if not isinstance(source, str) or not source:
            raise BrokerContractError("BROKER_SOURCE_UNVERIFIED")
        return cls(account_id, stamp, margin, limit, source)


@dataclass(frozen=True)
class BrokerOrderView:
    order_id: str
    account_id: str
    symbol: str
    status: str
    quantity: int
    filled_quantity: int
    remaining_quantity: int

    @classmethod
    def validated(cls, payload: Mapping[str, Any], *, account_id: str):
        if not isinstance(payload, Mapping) or payload.get("error"):
            raise BrokerContractError("BROKER_ORDER_UNAVAILABLE")
        if not account_id or payload.get("account_id") != account_id:
            raise BrokerContractError("BROKER_ACCOUNT_MISMATCH")
        order_id, symbol = payload.get("order_id"), payload.get("symbol")
        if not isinstance(order_id, str) or not order_id or not isinstance(symbol, str) or not symbol:
            raise BrokerContractError("BROKER_ORDER_IDENTITY_UNVERIFIED")
        status = payload.get("status")
        allowed_statuses = (
            "PENDING",
            "OPEN",
            "PARTIALLY_FILLED",
            "TRIGGER_PENDING",
            "FILLED",
            "CANCELLED",
            "REJECTED",
            "EXPIRED",
            "UNKNOWN",
        )
        if status not in allowed_statuses:
            raise BrokerContractError("BROKER_ORDER_STATUS_UNKNOWN")
        q, f, remaining = (
            payload.get("quantity"),
            payload.get("filled_quantity"),
            payload.get("pending_quantity"),
        )
        if type(q) is not int or type(f) is not int or type(remaining) is not int:
            raise BrokerContractError("BROKER_FILL_UNVERIFIED")
        if q <= 0 or not 0 <= f <= q or not 0 <= remaining <= q:
            raise BrokerContractError("BROKER_QUANTITY_INVALID")
        if status == "FILLED" and (f != q or remaining):
            raise BrokerContractError("BROKER_FILL_INCONSISTENT")
        if status in ("OPEN", "PENDING", "PARTIALLY_FILLED", "UNKNOWN") and remaining + f > q:
            raise BrokerContractError("BROKER_QUANTITY_INCONSISTENT")
        return cls(order_id, account_id, symbol, status, q, f, remaining)
