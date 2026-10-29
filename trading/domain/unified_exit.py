"""POL06_V1: shared session trailing and confirmed NIFTY structural invalidation.

Pure decision math. Never places orders, approves entries or assumes fills.
Actual broker STOP, cancel/replace and exit coordination remain with the OMS.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any, Mapping

from market_clock import MarketClock
from trading.domain.prices import round_tick


POLICY_VERSION = "POL06_V1"


def valid_price(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        n = float(value)
        return n if math.isfinite(n) and n > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def shared_profit_floor(entry: float, peak_bid: float, hm: str) -> float | None:
    """Universal long-option floor, using peak *executable bid*, not LTP.

    Thresholds and percentages are proposed POL-06 v1 policy values.
    The OMS must apply max(existing confirmed/desired floor, proposed floor).
    """
    entry, peak = valid_price(entry), valid_price(peak_bid)
    if entry is None or peak is None or peak < entry or not "09:15" <= hm < "15:15":
        return None
    gain = (peak / entry - 1.0) * 100
    floors: list[float] = []
    if gain >= 40:
        floors.append(entry * 1.30)
    elif gain >= 30:
        floors.append(entry * 1.20)
    elif gain >= 20:
        floors.append(entry * 1.10)
    # +50% and beyond: maintain the progressive locked floor, and
    # follow the executable peak by 3.5% irrespective of time of day.
    if gain >= 50:
        floors.append(peak * .965)
    if hm < "11:30":
        if gain >= 5:
            floors.append(entry * .92)
        if gain >= 10:
            floors.append(entry * 1.01)
        if gain >= 15:
            floors.extend([entry * 1.10, peak * .92])
    elif hm < "13:15":
        if gain >= 5:
            floors.extend([entry * 1.03, peak * .965])
    else:
        if gain >= 15:
            floors.extend([entry * 1.10, peak * .965])
        if hm >= "14:00" and gain >= 4:
            floors.append(entry * 1.01)
    return round_tick(max(floors)) if floors else None


def _completed_candle(candle: Any, now: datetime) -> tuple[datetime, float] | None:
    if not isinstance(candle, Mapping):
        return None
    stamp = MarketClock.parse_to_ist(candle.get("start_time") or candle.get("date"))
    if stamp is None or not timedelta(minutes=1) <= now - stamp <= timedelta(minutes=3):
        return None
    close = valid_price(candle.get("close"))
    low = valid_price(candle.get("low"))
    high = valid_price(candle.get("high"))
    if close is None or low is None or high is None or not low <= close <= high:
        return None
    return stamp, close


def _one_min_atr(candles: Any, now: datetime) -> float | None:
    if not isinstance(candles, list) or len(candles) < 15:
        return None
    tail = candles[-15:]
    times = []
    ranges = []
    previous_close = None
    for candle in tail:
        if not isinstance(candle, Mapping):
            return None
        stamp = MarketClock.parse_to_ist(candle.get("start_time") or candle.get("date"))
        high, low = valid_price(candle.get("high")), valid_price(candle.get("low"))
        close = valid_price(candle.get("close"))
        if stamp is None or high is None or low is None or close is None or not low <= close <= high:
            return None
        if times and stamp - times[-1] != timedelta(minutes=1):
            return None
        if previous_close is not None:
            ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        previous_close = close
        times.append(stamp)
    if not timedelta(minutes=1) <= now - times[-1] <= timedelta(minutes=3):
        return None
    return sum(ranges) / len(ranges) if len(ranges) == 14 else None


def structural_decision(
    state: Mapping[str, Any], ctx: Mapping[str, Any], now: datetime
) -> tuple[str | None, dict[str, Any] | None]:
    """One completed 1m close OR 2 distinct provider-timestamped decisive quotes.

    Returns (exit reason, new persisted confirmation state). A missing source
    timestamp may confirm a completed candle but MUST NOT count as a fresh tick.
    No companion consultation is required to cut risk.
    """
    level = valid_price(state.get("invalidation_level"))
    side = state.get("option_right")
    if side not in ("CE", "PE") or level is None:
        return None, None
    candles = ctx.get("candles_1m")
    if isinstance(candles, list) and candles:
        complete = _completed_candle(candles[-1], now)
        if complete is not None:
            _, closing = complete
            if (closing <= level if side == "CE" else closing >= level):
                return "Confirmed completed 1m candle closed beyond frozen structural invalidation", None
    spot = valid_price(ctx.get("spot"))
    atr = _one_min_atr(candles, now)
    if spot is None or atr is None:
        return None, None
    distance = max(5.0, 0.5 * atr)
    decisive = spot <= level - distance if side == "CE" else spot >= level + distance
    if not decisive:
        return None, {}  # clear a prior confirmation when price recovers
    stamp = MarketClock.parse_to_ist(ctx.get("spot_observed_at"))
    if stamp is None or not timedelta(0) <= now - stamp <= timedelta(seconds=10):
        return None, None
    previous = state.get("structural_breach_confirmation") or {}
    prior_stamp = MarketClock.parse_to_ist(previous.get("at")) if isinstance(previous, Mapping) else None
    count = (int(previous.get("count", 0)) + 1) if (
        prior_stamp is not None
        and prior_stamp < stamp
        and stamp - prior_stamp <= timedelta(seconds=30)
        and int(previous.get("count", 0)) >= 1
    ) else 1
    if count >= 2:
        return f"Two fresh decisive spot breaches beyond structural level by at least {distance:.1f} points", None
    return None, {"at": stamp.isoformat(), "count": count}
