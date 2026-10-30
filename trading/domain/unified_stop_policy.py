"""Shared strategy-independent R01 stop floor proposal.

Pure calculation only: no broker modifications, no change to OMS ownership.
An already-confirmed protective floor can never be loosened.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


@dataclass(frozen=True)
class StopFloorDecision:
    trigger_floor: Decimal
    phase: str


def _finite(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation, TypeError):
        return None
    return number if number.is_finite() else None


def unified_floor(
    entry_price: Any,
    highest_verified_bid: Any,
    existing_floor: Any,
    time_ist: str,
    *,
    initial_loss_pct: Any = 25,
) -> StopFloorDecision | None:
    """Compute R01 monotonic stop floor from the active MACD trailing schedule.

    This policy is independent of strategy name. An external caller must
    verify quote identity/freshness and let the existing OMS broker state
    machine own any subsequent order change.
    """
    price = _finite(entry_price)
    peak = _finite(highest_verified_bid)
    prior = _finite(existing_floor)
    loss = _finite(initial_loss_pct)
    if price is None or peak is None or prior is None or loss is None:
        return None
    if price <= 0 or peak <= 0 or prior < 0 or not 0 < loss < 100:
        return None
    if not isinstance(time_ist, str) or len(time_ist) != 5 or time_ist[2] != ":":
        return None
    try:
        h, m = int(time_ist[:2]), int(time_ist[3:])
    except ValueError:
        return None
    if not 0 <= h <= 23 or not 0 <= m <= 59:
        return None

    gain = (peak / price - 1) * 100
    floor = max(prior, price * (1 - loss / 100))
    phase = "INITIAL"
    for threshold, protected in ((15, 0), (20, 10), (30, 20), (40, 30)):
        if gain >= threshold:
            floor = max(floor, price * (1 + Decimal(protected) / 100))
            phase = "PROFIT_TIER"
    if "09:15" <= time_ist < "11:30":
        for threshold, protect in ((5, -8), (10, 1), (15, 10)):
            if gain >= threshold:
                floor = max(floor, price * (1 + Decimal(protect) / 100))
                phase = "MORNING"
    elif "11:30" <= time_ist < "13:15" and gain >= 5:
        floor = max(floor, price * Decimal("1.03"))
        phase = "MIDDAY"
    return StopFloorDecision(floor, phase)
