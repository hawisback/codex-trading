"""Freeze real, validated option liquidity for the Antigravity consultation."""

from entry_policy import EntryBlocked, number, tick_price, validate_quote


def order_book_snapshot(quote, instrument_id, policy):
    bid, ask = validate_quote(quote, instrument_id, policy)
    raw = quote.get("depth")
    depth = raw if raw is not None else {
        "buy": [{"price": bid, "quantity": quote["best_bid_qty"]}],
        "sell": [{"price": ask, "quantity": quote["best_ask_qty"]}],
    }
    if not isinstance(depth, dict):
        raise EntryBlocked("INVALID_CONSULTATION_DEPTH")
    sides = {}
    for side in ("buy", "sell"):
        levels = depth.get(side)
        if not isinstance(levels, list) or not levels:
            raise EntryBlocked("CONSULTATION_DEPTH_UNAVAILABLE")
        cleaned: list[dict[str, float | int]] = []
        for level in levels[:5]:
            if not isinstance(level, dict):
                raise EntryBlocked("INVALID_CONSULTATION_DEPTH")
            price, qty = number(level.get("price")), number(level.get("quantity"))
            if price == 0 and qty == 0:
                continue  # Broker padding is not liquidity.
            if price <= 0 or qty <= 0 or qty != int(qty) or tick_price(price) != price:
                raise EntryBlocked("INVALID_CONSULTATION_DEPTH")
            if cleaned and ((side == "buy" and price >= cleaned[-1]["price"])
                            or (side == "sell" and price <= cleaned[-1]["price"])):
                raise EntryBlocked("UNORDERED_CONSULTATION_DEPTH")
            cleaned.append(dict(price=price, quantity=int(qty)))
        if not cleaned:
            raise EntryBlocked("CONSULTATION_DEPTH_UNAVAILABLE")
        expected_price = bid if side == "buy" else ask
        expected_qty = quote["best_bid_qty" if side == "buy" else "best_ask_qty"]
        if cleaned[0] != dict(price=expected_price, quantity=expected_qty):
            raise EntryBlocked("CONSULTATION_DEPTH_TOP_MISMATCH")
        sides[side] = cleaned
    buy_qty = sum(level["quantity"] for level in sides["buy"])
    sell_qty = sum(level["quantity"] for level in sides["sell"])
    return dict(
        instrument_id=instrument_id, timestamp=quote["timestamp"],
        source="BROKER_DEPTH" if raw is not None else "BROKER_TOP_OF_BOOK",
        best_bid=bid, best_ask=ask, spread=round(ask - bid, 4),
        bid_quantity=buy_qty, ask_quantity=sell_qty,
        quantity_imbalance=round((buy_qty - sell_qty) / (buy_qty + sell_qty), 6), depth=sides,
    )
