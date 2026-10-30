"""Reconcile authenticated Kite intraday positions against today's trade book.

Carry positions are deliberately unsupported: their lifetime cost-basis P&L
cannot safely be treated as today's account loss. Closed rows must be retained.
This module performs no I/O and grants no trading authority.
"""

from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from market_clock import IST_TZ, MarketClock
from trading.domain.broker_contracts import BrokerContractError, _number


def _identity(row):
    if not isinstance(row, Mapping):
        raise BrokerContractError("KITE_PNL_ROW_INVALID")
    key = tuple(row.get(name) for name in ("exchange", "tradingsymbol", "product"))
    if any(not isinstance(value, str) or not value for value in key):
        raise BrokerContractError("KITE_PNL_IDENTITY_INVALID")
    return key


def _quantity(value, *, signed=False):
    result = _number(value)
    if result != result.to_integral_value() or (not signed and result < 0):
        raise BrokerContractError("KITE_PNL_QUANTITY_INVALID")
    return int(result)


def kite_daily_pnl(positions, trades, *, account_id: str, observed_at: datetime):
    """Require complete matching net/day quantities, values and unique daily fills.

    The caller must authenticate both reads to this account, enforce a bounded
    receipt window and reject credentials/session changes. Monetary values are
    broker-reported gross P&L, before any subsequently posted broker charges.
    """
    if not account_id or not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise BrokerContractError("KITE_PNL_ACCOUNT_OR_CLOCK_UNVERIFIED")
    if (
        not isinstance(positions, Mapping)
        or positions.get("error")
        or any(positions.get(flag) for flag in ("truncated", "has_more", "next_cursor"))
        or not isinstance(positions.get("net"), list)
        or not isinstance(positions.get("day"), list)
        or not isinstance(trades, list)
    ):
        raise BrokerContractError("KITE_PNL_BOOK_UNAVAILABLE")
    today = observed_at.astimezone(IST_TZ).date()
    books = []
    for name in ("net", "day"):
        book = {}
        for row in positions[name]:
            key = _identity(row)
            if key in book:
                raise BrokerContractError("KITE_PNL_DUPLICATE_POSITION")
            if _quantity(row.get("overnight_quantity"), signed=True) != 0:
                raise BrokerContractError("KITE_PNL_CARRY_POSITION_UNSUPPORTED")
            buy = _quantity(row.get("day_buy_quantity"))
            sell = _quantity(row.get("day_sell_quantity"))
            if _quantity(row.get("quantity"), signed=True) != buy - sell:
                raise BrokerContractError("KITE_PNL_QUANTITY_MISMATCH")
            values = tuple(_number(row.get(f"day_{side}_value")) for side in ("buy", "sell"))
            if any(value < 0 for value in values):
                raise BrokerContractError("KITE_PNL_VALUE_INVALID")
            realized, unrealized, total = (
                _number(row.get(field)) for field in ("realised", "unrealised", "pnl")
            )
            if abs(realized + unrealized - total) > Decimal("0.02"):
                raise BrokerContractError("KITE_PNL_TOTAL_MISMATCH")
            book[key] = (buy, sell, *values, realized, unrealized)
        books.append(book)
    net, day = books
    if net.keys() != day.keys() or any(net[key][:4] != day[key][:4] for key in net):
        raise BrokerContractError("KITE_PNL_POSITION_BOOK_MISMATCH")

    fills: dict[tuple, list[Decimal]] = defaultdict(lambda: [Decimal(0) for _ in range(4)])
    identities = set()
    for trade in trades:
        key = _identity(trade)
        trade_id, order_id = trade.get("trade_id"), trade.get("order_id")
        if not isinstance(trade_id, str) or not trade_id or not isinstance(order_id, str) or not order_id:
            raise BrokerContractError("KITE_PNL_FILL_IDENTITY_INVALID")
        identity = (key[0], trade_id, order_id)
        if identity in identities:
            raise BrokerContractError("KITE_PNL_DUPLICATE_FILL")
        identities.add(identity)
        stamp = MarketClock.parse_to_ist(trade.get("fill_timestamp"))
        if stamp is None or stamp.date() != today or stamp > observed_at.astimezone(IST_TZ):
            raise BrokerContractError("KITE_PNL_FILL_SESSION_INVALID")
        side = trade.get("transaction_type")
        if side not in ("BUY", "SELL"):
            raise BrokerContractError("KITE_PNL_FILL_SIDE_INVALID")
        quantity, price = _quantity(trade.get("quantity")), _number(trade.get("average_price"))
        if quantity <= 0 or price <= 0:
            raise BrokerContractError("KITE_PNL_FILL_INVALID")
        index = 0 if side == "BUY" else 1
        fills[key][index] += quantity
        fills[key][index + 2] += quantity * price
    if fills.keys() != net.keys():
        raise BrokerContractError("KITE_PNL_TRADE_BOOK_MISMATCH")
    for key, fill_totals in fills.items():
        if tuple(fill_totals[:2]) != net[key][:2] or any(
            abs(fill_totals[index] - net[key][index]) > Decimal("0.02") for index in (2, 3)
        ):
            raise BrokerContractError("KITE_PNL_TRADE_BOOK_MISMATCH")
    return {
        "pnl_account_id": account_id,
        "pnl_session_date": today.isoformat(),
        "pnl_asof": observed_at.isoformat(),
        "pnl_source": "kite:portfolio/positions+trades:authenticated-receipts",
        "realized_pnl_today": str(sum((row[4] for row in net.values()), Decimal(0))),
        "unrealized_pnl_today": str(sum((row[5] for row in net.values()), Decimal(0))),
    }
