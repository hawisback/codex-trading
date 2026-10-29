"""Account-wide broker-margin lot limits; independent of strategy selection."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any, Mapping

from trading.domain.limits import FEE_RESERVE, LOT_SIZE


def _amount(value: Any) -> Decimal:
    """Never allow missing, non-finite or boolean monetary inputs."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Expected numeric broker margin or option price")
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation, OverflowError) as exc:
        raise ValueError("Invalid broker amount or option price") from exc
    if not result.is_finite():
        raise ValueError("Non-finite broker amount or option price")
    return result


@dataclass(frozen=True)
class LotTier:
    inclusive_maximum: Decimal | None
    lots: int


@dataclass(frozen=True)
class BrokerMarginLotPolicy:
    tiers: tuple[LotTier, ...]
    maximum_lots: int
    maximum_quantity: int

    @classmethod
    def from_trading_config(cls, trading_cfg: Mapping[str, Any]) -> "BrokerMarginLotPolicy":
        risk = trading_cfg.get("risk")
        if not isinstance(risk, Mapping):
            raise ValueError("Missing risk configuration")
        raw = risk.get("available_margin_lot_tiers")
        if not isinstance(raw, list) or len(raw) != 5:
            raise ValueError("Missing or incomplete capital lot ladder")
        max_lots = risk.get("max_lots_per_trade")
        max_quantity = risk.get("max_order_quantity")
        if type(max_lots) is not int or max_lots != 10:
            raise ValueError("Owner-approved maximum is 10 lots")
        if type(max_quantity) is not int or max_quantity != 10 * LOT_SIZE:
            raise ValueError("Owner-approved quantity ceiling is 10 complete lots")
        expected = (
            (Decimal("20000"), 2),
            (Decimal("40000"), 4),
            (Decimal("60000"), 6),
            (Decimal("80000"), 8),
            (None, 10),
        )
        tiers: list[LotTier] = []
        for index, (bound, lots) in enumerate(expected):
            row = raw[index]
            if not isinstance(row, Mapping) or type(row.get("max_lots")) is not int:
                raise ValueError("Malformed capital lot tier")
            value = row.get("max_available_margin")
            converted = None if value is None else _amount(value)
            if converted != bound or row["max_lots"] != lots:
                raise ValueError("Capital ladder differs from approved policy")
            tiers.append(LotTier(bound, lots))
        return cls(tuple(tiers), max_lots, max_quantity)

    def max_lots_for_margin(self, broker_available_margin: Any) -> int:
        try:
            margin = _amount(broker_available_margin)
        except ValueError:
            return 0
        if margin <= 0:
            return 0
        for tier in self.tiers:
            if tier.inclusive_maximum is None or margin <= tier.inclusive_maximum:
                return min(tier.lots, self.maximum_lots, self.maximum_quantity // LOT_SIZE)
        return 0

    def quantity_for(self, broker_available_margin: Any, option_limit_price: Any) -> int:
        """Max affordable whole lots; zero on any unverified amount or invalid price.

        NIFTY spot can determine the strike; funding uses option limit premium,
        verified broker buying power and the existing fee reserve.
        """
        try:
            margin = _amount(broker_available_margin)
            option_price = _amount(option_limit_price)
        except ValueError:
            return 0
        if margin <= Decimal(str(FEE_RESERVE)) or option_price <= 0:
            return 0
        tier_lots = self.max_lots_for_margin(margin)
        if tier_lots <= 0:
            return 0
        available = margin - Decimal(str(FEE_RESERVE))
        per_lot = option_price * LOT_SIZE
        affordable = int((available / per_lot).to_integral_value(rounding=ROUND_FLOOR))
        return LOT_SIZE * min(tier_lots, max(0, affordable))
