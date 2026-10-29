"""Conservative broker-fill daily P&L and planned loss budget for LIVE options.

The only accepted observed P&L comes from complete, account-matched broker
order fills. Missing histories, foreign fills, ambiguous executions, open
positions, bad prices or missing dates deny *new entry*, not protective exits.
Estimated fee cushion is NOT a certified actual brokerage/tax statement.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any, Mapping, Sequence

from execution_safety import ReconciliationError
from trading.domain.limits import LOT_SIZE


def money(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ReconciliationError("Missing or nonnumeric broker fill price")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, OverflowError) as exc:
        raise ReconciliationError("Invalid broker fill price") from exc
    if not amount.is_finite():
        raise ReconciliationError("Non-finite broker fill price")
    return amount


def checked_limit(config: Mapping[str, Any], key: str, expected: int) -> Decimal:
    risk = config.get("risk")
    if not isinstance(risk, Mapping):
        raise ReconciliationError("Missing daily risk policy")
    amount = risk.get(key)
    if isinstance(amount, bool) or not isinstance(amount, (int, float, Decimal)):
        raise ReconciliationError("Missing daily risk limit")
    number = money(amount)
    if number != expected:
        raise ReconciliationError("Daily risk policy differs from owner-approved ceiling")
    return number


def broker_filled_day_pnl(
    orders: Sequence[Mapping[str, Any]],
    today: str,
    scope: Mapping[str, Any],
    *,
    fee_cushion_per_entry: Decimal,
) -> tuple[Decimal, int]:
    """Account-wide closed-session cash P&L from today's complete broker fills.

    Must be called only after OMS has verified *no* open positions/uncertain
    orders, and after a complete broker get_orders() read. This is a flat-book
    intraday calculation, so net filled BUY and SELL contracts must match for
    every instrument. We do not infer fills from order status or from LTP.
    """
    try:
        date.fromisoformat(today)
    except (TypeError, ValueError) as exc:
        raise ReconciliationError("Invalid exchange session day") from exc
    if not isinstance(orders, (list, tuple)):
        raise ReconciliationError("Unverified daily broker order book")
    if scope.get("mode") not in ("LIVE", "PAPER") or not scope.get("account_id"):
        raise ReconciliationError("Unverified account for daily risk")
    if fee_cushion_per_entry < 0:
        raise ReconciliationError("Invalid estimated fee reserve")
    net = Decimal("0")
    entries = 0
    quantities: dict[str, int] = {}
    seen_ids: set[str] = set()
    for order in orders:
        if not isinstance(order, Mapping):
            raise ReconciliationError("Malformed broker order in daily risk")
        created = order.get("created_at")
        if not isinstance(created, str) or len(created) < 10:
            raise ReconciliationError("Broker fill date is unverified")
        if created[:10] != today:
            continue
        if order.get("mode") != scope["mode"] or order.get("account_id") != scope["account_id"]:
            raise ReconciliationError("Other account/mode in daily broker book")
        oid = order.get("order_id")
        if not isinstance(oid, str) or not oid or oid in seen_ids:
            raise ReconciliationError("Duplicate or absent broker order ID")
        seen_ids.add(oid)
        filled = order.get("filled_quantity")
        if isinstance(filled, bool) or not isinstance(filled, int) or filled < 0:
            raise ReconciliationError("Broker filled quantity invalid")
        if not filled:
            continue
        # Untracked fills can affect account-wide equity. Do not silently
        # report zero P&L or permit BUY while they are unaccounted for.
        if order.get("engine_owned") is not True:
            raise ReconciliationError("Untracked broker fills require daily P&L reconciliation")
        kind = order.get("kind")
        symbol = order.get("instrument_id") or order.get("symbol")
        if kind not in ("ENTRY", "STOP", "EXIT") or not isinstance(symbol, str) or not symbol:
            raise ReconciliationError("Unidentified broker fill in daily risk")
        price = money(order.get("average_price"))
        if price <= 0:
            raise ReconciliationError("Broker average fill price invalid")
        if filled % LOT_SIZE:
            # A partial fill can be smaller than a lot on some APIs. Preserve
            # true contracts and never infer quantity; no divisibility gate.
            pass
        delta = filled if kind == "ENTRY" else -filled
        quantities[symbol] = quantities.get(symbol, 0) + delta
        net -= Decimal(delta) * price
        if kind == "ENTRY":
            entries += 1
            net -= fee_cushion_per_entry
    if any(balance != 0 for balance in quantities.values()):
        raise ReconciliationError("Daily broker fills do not represent verified flat exposure")
    return net, entries


def entry_risk_quantity(
    *,
    candidate_qty: int,
    option_limit_price: Any,
    observed_net_pnl: Decimal,
    config: Mapping[str, Any],
    fee_cushion: Decimal = Decimal("150"),
) -> int:
    """Whole-lot cap using a conservative 20% option stop planning assumption.

    Realized losses can exceed these budgets due to stop gaps, brokerage or
    liquidity. This calculation never increases the original lot ladder.
    """
    daily = checked_limit(config, "max_daily_loss_rupees", 5000)
    per_trade = checked_limit(config, "max_planned_loss_per_trade_rupees", 2000)
    if not isinstance(candidate_qty, int) or candidate_qty <= 0:
        return 0
    price = money(option_limit_price)
    if price <= 0:
        return 0
    pnl = money(observed_net_pnl)
    if pnl <= -daily:
        return 0
    # Do not reinvest today's profits to enlarge the permitted loss budget.
    remaining = daily + min(Decimal("0"), pnl)
    usable = min(per_trade, remaining) - fee_cushion
    if usable <= 0:
        return 0
    # Worst planned initial premium loss is 20%; this is not a fill guarantee.
    contract_loss = price * Decimal("0.20")
    lots = int((usable / (contract_loss * LOT_SIZE)).to_integral_value(rounding=ROUND_FLOOR))
    return min(candidate_qty // LOT_SIZE, max(0, lots)) * LOT_SIZE
