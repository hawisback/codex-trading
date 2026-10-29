"""Existing nearest-tick rounding for broker orders (distinct from hard band floors)."""


def round_tick(price: float) -> float:
    return round(round(price / 0.05) * 0.05, 2)
