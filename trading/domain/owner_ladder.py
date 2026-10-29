"""Owner-approved capital bands for a future opt-in sizing policy.

This is a pure calculation. It does not obtain/verify broker funds or quotes,
authorize a trade, override AI consultation, or write an order. The calling
entry path must supply authenticated fresh broker available_margin and a
freshly validated executable option limit price. Currently not enabled in
config/strategies.json.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from trading.domain.limits import FEE_RESERVE, LOT_SIZE, MAX_POSITION_QUANTITY


OWNER_LADDER_MODE = "owner_capital_ladder_v1"
OWNER_MAX_LOTS = 10


@dataclass(frozen=True)
class OwnerLadderDecision:
    tier_lots: int
    affordable_lots: int
    allowed_lots: int
    quantity: int


def _positive_finite(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _nonnegative_decision() -> OwnerLadderDecision:
    return OwnerLadderDecision(tier_lots=0, affordable_lots=0, allowed_lots=0, quantity=0)


def owner_ladder_decision(
    available_margin: float,
    option_limit_price: float,
    *,
    max_lots_cap: int = OWNER_MAX_LOTS,
    max_order_quantity: int = MAX_POSITION_QUANTITY,
) -> OwnerLadderDecision:
    """Calculate, never promise, a permitted quantity in whole NIFTY lots.

    Bands use the same verified available-margin field already consumed by the
    current entry workflow. This *provisional* bracket basis requires explicit
    review before the owner_ladder mode is enabled in production.

    Boundaries are inclusive on the lower-capital bands: 20k => 2; >20k
    through 40k => 4; >40k through 60k => 6; >60k through 80k => 8;
    >80k => 10. This is a ceiling, NOT a minimum order size.
    """
    if not (_positive_finite(available_margin) and _positive_finite(option_limit_price)):
        return _nonnegative_decision()
    if (type(max_lots_cap) is not int or type(max_order_quantity) is not int
            or max_lots_cap <= 0 or max_order_quantity < LOT_SIZE):
        return _nonnegative_decision()

    if available_margin <= 20_000:
        tier = 2
    elif available_margin <= 40_000:
        tier = 4
    elif available_margin <= 60_000:
        tier = 6
    elif available_margin <= 80_000:
        tier = 8
    else:
        tier = OWNER_MAX_LOTS

    per_lot = option_limit_price * LOT_SIZE
    if not math.isfinite(per_lot) or per_lot <= 0:
        return _nonnegative_decision()
    usable_margin = max(0.0, available_margin - FEE_RESERVE)
    affordable = int(usable_margin // per_lot)
    ceiling = min(
        tier, OWNER_MAX_LOTS, max_lots_cap,
        max_order_quantity // LOT_SIZE,
        MAX_POSITION_QUANTITY // LOT_SIZE,
    )
    approved = min(affordable, ceiling)
    return OwnerLadderDecision(
        tier_lots=tier,
        affordable_lots=affordable,
        allowed_lots=approved,
        quantity=approved * LOT_SIZE,
    )
