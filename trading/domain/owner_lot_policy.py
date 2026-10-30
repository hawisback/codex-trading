"""Owner-approved capital milestones shared by R01 preview and submission.

Pure arithmetic cannot authorize an order. Broker evidence, consultation and
the existing OMS remain responsible for validation and execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from trading.domain.limits import FEE_RESERVE, MAX_POSITION_QUANTITY

# Minimum capital milestones, per revised owner direction on 2026-10-30.
# Positive funds below 40k permit up to two lots, subject to affordability.
_OWNER_LOT_MILESTONES = (
    (Decimal("40000"), 4),
    (Decimal("60000"), 6),
    (Decimal("80000"), 8),
    (Decimal("100000"), 10),
)
_OWNER_MAX_LOTS = 10
_CAPITAL_BASES = frozenset(("available_margin", "account_equity"))


@dataclass(frozen=True)
class OwnerLotCeilingPreview:
    """Arithmetic ceilings; the caller must enforce broker, risk and OMS checks."""

    capital_basis: str
    ladder_lots: int
    affordable_lots: int
    broker_single_order_lots: int
    hard_position_lots: int
    ceiling_lots: int
    ceiling_contracts: int
    blocked_reason: str | None


def _money(value: Any) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return amount if amount.is_finite() else None


def owner_ladder_max_lots(bracket_capital: Any) -> int:
    """Return the approved tier ceiling, or zero for unknown/invalid funds.

    A positive tier NEVER guarantees affordability or trade eligibility.
    """
    capital = _money(bracket_capital)
    if capital is None or capital <= 0:
        return 0
    for minimum_capital, maximum_lots in reversed(_OWNER_LOT_MILESTONES):
        if capital >= minimum_capital:
            return min(maximum_lots, _OWNER_MAX_LOTS)
    return 2


def preview_owner_lot_ceiling(
    *,
    capital_basis: str,
    bracket_capital: Any,
    available_margin: Any,
    executable_option_ask: Any,
    lot_size: int,
    broker_single_order_quantity_limit: int,
    fee_reserve: Any = FEE_RESERVE,
) -> OwnerLotCeilingPreview:
    """Calculate only a potential upper bound using externally supplied figures.

    All funds and the executable option ask MUST have been independently verified
    against the intended broker account, quote age and contract by the caller.
    This function cannot perform that verification. A real order must additionally
    pass risk, loss, existing-position, freshness, market-time, and AI veto gates.

    capital_basis is explicit. R01 submission uses authenticated available
    margin and independently verifies the account and contract evidence.
    """

    def blocked(reason: str) -> OwnerLotCeilingPreview:
        return OwnerLotCeilingPreview(
            capital_basis=str(capital_basis),
            ladder_lots=0,
            affordable_lots=0,
            broker_single_order_lots=0,
            hard_position_lots=0,
            ceiling_lots=0,
            ceiling_contracts=0,
            blocked_reason=reason,
        )

    if capital_basis not in _CAPITAL_BASES:
        return blocked("UNDECIDED_OR_INVALID_CAPITAL_BASIS")
    if type(lot_size) is not int or lot_size <= 0:
        return blocked("INVALID_CONTRACT_LOT_SIZE")
    if type(broker_single_order_quantity_limit) is not int or broker_single_order_quantity_limit <= 0:
        return blocked("BROKER_ORDER_QUANTITY_LIMIT_UNVERIFIED")

    capital = _money(bracket_capital)
    funds = _money(available_margin)
    ask = _money(executable_option_ask)
    reserve = _money(fee_reserve)
    if capital is None or funds is None or capital <= 0 or funds <= 0:
        return blocked("BROKER_FUNDS_UNAVAILABLE_OR_INVALID")
    if ask is None or ask <= 0:
        return blocked("EXECUTABLE_OPTION_ASK_UNAVAILABLE_OR_INVALID")
    if reserve is None or reserve < 0:
        return blocked("INVALID_FEE_RESERVE")
    if capital_basis == "available_margin" and capital != funds:
        return blocked("CAPITAL_AND_AVAILABLE_MARGIN_DISAGREE")

    ladder_lots = owner_ladder_max_lots(capital)
    broker_lots = broker_single_order_quantity_limit // lot_size
    hard_lots = MAX_POSITION_QUANTITY // lot_size
    try:
        safe_funds = max(Decimal(0), funds - reserve)
        option_cost_per_lot = ask * lot_size
        affordable_lots = int(min(Decimal(_OWNER_MAX_LOTS), safe_funds // option_cost_per_lot))
    except (ArithmeticError, ValueError, OverflowError):
        return blocked("SIZING_ARITHMETIC_UNAVAILABLE")
    ceiling_lots = min(ladder_lots, affordable_lots, broker_lots, hard_lots)
    reason = None
    if ceiling_lots == 0:
        reason = "NO_AFFORDABLE_WHOLE_LOT_OR_BROKER_LIMIT"

    return OwnerLotCeilingPreview(
        capital_basis=capital_basis,
        ladder_lots=ladder_lots,
        affordable_lots=affordable_lots,
        broker_single_order_lots=broker_lots,
        hard_position_lots=hard_lots,
        ceiling_lots=ceiling_lots,
        ceiling_contracts=ceiling_lots * lot_size,
        blocked_reason=reason,
    )
