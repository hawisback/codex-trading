"""Broker-independent completed spot bars and deterministic five-minute metrics."""

from datetime import datetime, timedelta
import math
from typing import Any

from market_clock import IST_TZ
from trading.domain.indicators import simple_rsi


def number(value, *, minimum=None):
    if isinstance(value, bool):
        raise ValueError("Boolean market number")
    result = float(value)
    if not math.isfinite(result) or (minimum is not None and result < minimum):
        raise ValueError("Invalid market number")
    return result


def exchange_time(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            parsed = datetime.strptime(str(value), "%d-%b-%Y %H:%M:%S")
    return parsed.replace(tzinfo=IST_TZ) if parsed.tzinfo is None else parsed.astimezone(IST_TZ)


def completed_spot_bars(rows, now):
    """Accept native Kite arrays or Breeze dictionaries; reject ambiguous duplicates."""
    bars: dict[datetime, dict[str, Any]] = {}
    for raw in rows:
        if isinstance(raw, (list, tuple)):
            raw = dict(zip(("start_time", "open", "high", "low", "close", "volume", "oi"), raw))
        start = exchange_time(raw.get("start_time") or raw.get("datetime") or raw.get("date"))
        opening = start.replace(hour=9, minute=15, second=0, microsecond=0)
        closing = start.replace(hour=15, minute=30, second=0, microsecond=0)
        if start < opening or start >= closing or start + timedelta(minutes=1) > now:
            continue
        if start.second or start.microsecond:
            raise ValueError("Unaligned spot candle")
        bar = {k: number(raw[k], minimum=0.01) for k in ("open", "high", "low", "close")}
        if bar["low"] > min(bar["open"], bar["close"]) or bar["high"] < max(bar["open"], bar["close"]):
            raise ValueError("Invalid spot candle range")
        bar.update(start_time=start.isoformat(), volume=number(raw.get("volume", 0), minimum=0))
        if start in bars and bars[start] != bar:
            raise ValueError("Conflicting spot candles")
        bars[start] = bar
    return [bars[start] for start in sorted(bars)]


def resample_five_minutes(bars):
    groups: dict[datetime, list[dict[str, Any]]] = {}
    for bar in bars:
        start = exchange_time(bar["start_time"])
        bucket = start.replace(minute=start.minute - start.minute % 5)
        groups.setdefault(bucket, []).append(bar)
    result = []
    for start, group in sorted(groups.items()):
        expected = [start + timedelta(minutes=i) for i in range(5)]
        if [exchange_time(b["start_time"]) for b in group] != expected:
            continue
        result.append(
            dict(
                start_time=start.isoformat(),
                open=group[0]["open"],
                high=max(b["high"] for b in group),
                low=min(b["low"] for b in group),
                close=group[-1]["close"],
                volume=sum(b["volume"] for b in group),
            )
        )
    return result


def resample_two_minutes(bars, *, as_of=None):
    """Complete, contiguous pairs anchored at 09:15 IST; never join gaps/sessions.

    Historical callers may omit as_of when all input one-minute bars are closed.
    Live callers must supply their observation time to exclude forming candles.
    """
    result = []
    previous = None
    for index, bar in enumerate(bars):
        start = exchange_time(bar.get("start_time") or bar.get("date"))
        if start.second or start.microsecond or (previous is not None and start <= previous):
            raise ValueError("Unaligned, duplicate or unordered one-minute candles")
        if previous is not None and start != previous + timedelta(minutes=1):
            raise ValueError("Gap in one-minute candle history")
        previous = start
        opening = start.replace(hour=9, minute=15, second=0, microsecond=0)
        offset = int((start - opening).total_seconds() // 60)
        if not 0 <= offset < 375 or offset % 2 or index + 1 >= len(bars):
            continue
        following = bars[index + 1]
        next_start = exchange_time(following.get("start_time") or following.get("date"))
        if next_start != start + timedelta(minutes=1):
            raise ValueError("Gap inside a two-minute candle")
        if as_of is not None and start + timedelta(minutes=2) > as_of:
            continue
        result.append(dict(
            start_time=start.isoformat(), open=bar["open"],
            high=max(bar["high"], following["high"]), low=min(bar["low"], following["low"]),
            close=following["close"], volume=bar.get("volume", 0) + following.get("volume", 0),
            minute_idx=index + 1,
        ))
    return result


def resample_rolling_two_minutes(bars, *, as_of=None):
    """Completed overlapping pairs, one observation per minute, within sessions.

    An overnight gap starts a new session; an intraday gap is an error. Never
    manufacture an overnight candle or use a forming/future minute.
    """
    result = []
    previous = None
    for index, raw in enumerate(bars):
        start = exchange_time(raw.get("start_time") or raw.get("date"))
        opening = start.replace(hour=9, minute=15, second=0, microsecond=0)
        if start.second or start.microsecond or not opening <= start < opening + timedelta(minutes=375):
            raise ValueError("Unaligned or out-of-session rolling minute")
        bar = {k: number(raw[k], minimum=.01) for k in ("open", "high", "low", "close")}
        if bar["low"] > min(bar["open"], bar["close"]) or bar["high"] < max(bar["open"], bar["close"]):
            raise ValueError("Invalid rolling minute range")
        bar["volume"] = number(raw.get("volume", 0), minimum=0)
        if previous is not None:
            old_start, old = previous
            if start <= old_start:
                raise ValueError("Duplicate or unordered rolling minutes")
            if start.date() == old_start.date():
                if start != old_start + timedelta(minutes=1):
                    raise ValueError("Gap in rolling minute history")
                if as_of is None or start + timedelta(minutes=1) <= as_of:
                    result.append(dict(start_time=old_start.isoformat(), end_time=start.isoformat(),
                        minute_idx=index, open=old["open"], high=max(old["high"], bar["high"]),
                        low=min(old["low"], bar["low"]), close=bar["close"],
                        volume=old["volume"] + bar["volume"]))
        previous = start, bar
    return result


def prior_session_warmup(bars, now, *, holidays=()):
    """Exactly the previous trading session's 14:30..15:29 Spot minutes.

    Use the configured exchange calendar. Missing history for that session
    cannot silently select an older session with a different market regime.
    """
    now = exchange_time(now)
    previous = now.date() - timedelta(days=1)
    while previous.weekday() >= 5 or previous.isoformat() in holidays:
        previous -= timedelta(days=1)
    end = now.replace(year=previous.year, month=previous.month, day=previous.day,
                      hour=15, minute=30, second=0, microsecond=0)
    expected = [end - timedelta(minutes=i) for i in range(60, 0, -1)]
    selected = [dict(b) for b in bars if expected[0] <= exchange_time(b["start_time"]) < end]
    if [exchange_time(b["start_time"]) for b in selected] != expected:
        raise ValueError("Previous trading session warmup requires 60 contiguous closing minutes")
    resample_rolling_two_minutes(selected, as_of=now)  # Validate every price and timestamp.
    return selected


def macd_observation_bars(today, *, prior=(), as_of=None, rolling=False):
    """Warm up indicator state across sessions without merging overnight OHLC."""
    sampler = resample_rolling_two_minutes if rolling else resample_two_minutes
    warmup = sampler(prior, as_of=as_of) if prior else []
    return warmup + sampler(today, as_of=as_of)


def ema_series(values, period):
    result = [values[0]]
    factor = 2 / (period + 1)
    for value in values[1:]:
        result.append(value * factor + result[-1] * (1 - factor))
    return result


def technical_metrics(bars):
    if len(bars) < 50:
        raise ValueError("At least 50 completed five-minute spot candles are required")
    closes = [b["close"] for b in bars]
    macd = [fast - slow for fast, slow in zip(ema_series(closes, 12), ema_series(closes, 26))]
    signal = ema_series(macd, 9)
    histogram = [line - sig for line, sig in zip(macd, signal)]
    return dict(
        ema_9=round(ema_series(closes, 9)[-1], 2),
        ema_20=round(ema_series(closes, 20)[-1], 2),
        ema_50=round(ema_series(closes, 50)[-1], 2),
        rsi_14=round(simple_rsi(closes, 14), 2),
        macd=round(macd[-1], 4),
        macd_histogram=round(histogram[-1], 4),
        macd_histogram_expanding_positive=histogram[-1] > 0 and histogram[-1] > histogram[-2],
        macd_histogram_expanding_negative=histogram[-1] < 0 and histogram[-1] < histogram[-2],
    )


def two_minute_macd_metrics(bars, *, periods=(12, 26, 9), rolling=False):
    """MACD(12,26,9) context from at least 27 completed two-minute bars."""
    fast, slow, signal_period = periods
    if len(bars) < slow + 1:
        raise ValueError(f"At least {slow + 1} completed two-minute candles are required for MACD")
    closes = [number(bar["close"], minimum=.01) for bar in bars]
    macd = [f - s for f, s in zip(ema_series(closes, fast), ema_series(closes, slow))]
    signal = ema_series(macd, signal_period)
    histogram = [line - sig for line, sig in zip(macd, signal)]
    current, previous = histogram[-1], histogram[-2]
    if current > 0 and previous <= 0:
        momentum = "Bullish Crossover"
    elif current < 0 and previous >= 0:
        momentum = "Bearish Crossover"
    elif current > 0 and current > previous:
        momentum = "Bullish Expansion"
    elif current > 0:
        momentum = "Bullish Contraction"
    elif current < 0:
        momentum = "Bearish"
    else:
        momentum = "Neutral"
    start = exchange_time(bars[-1]["start_time"])
    return dict(macd=macd[-1], signal=signal[-1], histogram=current,
                previous_histogram=previous, expanding_positive=current > 0 and current > previous,
                momentum_status=momentum, interval="rolling_2m" if rolling else "2m", periods=list(periods),
                candle_start=start.isoformat(), candle_closed_at=(start + timedelta(minutes=2)).isoformat())


def causal_hybrid_context(rows, now, *, expiry, prior_rows=()):
    """Replay live 50-bar EMA inputs using only candles closed by now.

    OHLC history does not reconstruct executable depth or macro intelligence.
    Missing warmup and session gaps are explicit rather than filled with Spot.
    """
    now = exchange_time(now)
    bars = completed_spot_bars([*prior_rows, *rows], now)
    today = [b for b in bars if exchange_time(b["start_time"]).date() == now.date()]
    opening = now.replace(hour=9, minute=15, second=0, microsecond=0)
    minute = now.replace(second=0, microsecond=0)
    expected = [opening + timedelta(minutes=i)
                for i in range(max(0, int((minute - opening).total_seconds() // 60)))]
    if not today or [exchange_time(b["start_time"]) for b in today] != expected:
        raise ValueError("Incomplete replay session candles")
    five_minute = resample_five_minutes(bars)[-50:]
    metrics = technical_metrics(five_minute)
    typicals = [(b["high"] + b["low"] + b["close"]) / 3 for b in today]
    return dict(spot=today[-1]["close"], candles_1m=today, expiry=expiry,
                ema_9=metrics["ema_9"], ema_20=metrics["ema_20"], ema_50=metrics["ema_50"],
                session_vwap=sum(typicals) / len(typicals), observed_at=now.isoformat(),
                candle_time=today[-1]["start_time"], ema_observed_through=five_minute[-1]["start_time"],
                day_high=max(b["high"] for b in today), day_low=min(b["low"] for b in today),
                day_change=0, order_flow={})
