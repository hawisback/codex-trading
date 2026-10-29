"""Shared deterministic calculations with explicit legacy warm-up semantics."""

import math


def select_strike(spot: float, direction: str, mode: str = "STRICT_ITM") -> int:
    if mode == "STRICT_ITM":
        if direction == "CE":
            return int(spot // 50) * 50
        return int(math.ceil(spot / 50.0)) * 50
    return int(round(spot / 50.0) * 50)


def exponential_average(prices: list[float], period: int, *, last_during_warmup: bool = False) -> float:
    if last_during_warmup and len(prices) < period:
        return prices[-1] if prices else 0.0
    if not prices:
        return 0.0
    factor = 2.0 / (period + 1)
    average = prices[0]
    for price in prices[1:]:
        average = price * factor + average * (1 - factor)
    return average


def simple_rsi(prices: list[float], period: int = 14) -> float:
    if len(prices) <= period:
        return 50.0
    gains, losses = [], []
    for index in range(1, len(prices)):
        delta = prices[index] - prices[index - 1]
        gains.append(max(0.0, delta))
        losses.append(max(0.0, -delta))
    average_gain = sum(gains[-period:]) / period
    average_loss = sum(losses[-period:]) / period
    if average_loss == 0.0:
        return 100.0
    strength = average_gain / average_loss
    return 100.0 - (100.0 / (1.0 + strength))
