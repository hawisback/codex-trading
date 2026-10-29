"""Validate and freeze observed technical context for post-fill stop decisions."""

import math
from collections.abc import Mapping
from decimal import Decimal
from entry_policy import tick_price


def positive_price(value):
    if isinstance(value, bool):
        raise ValueError("A boolean is not a stop context price")
    price = float(value)
    if not math.isfinite(price) or price <= 0:
        raise ValueError("Stop context prices must be finite and positive")
    return price


def configured_stop_policy(strategy):
    """Explicit policy only: other strategy profiles retain their existing behavior."""
    cfg = strategy.get("exit", {})
    post_fill = cfg.get("post_fill_stop_loss")
    if post_fill is None:
        return {}
    if not isinstance(post_fill, Mapping):
        raise ValueError("post_fill_stop_loss must contain explicit percentage bounds")
    try:
        policy = {
            "min_loss_pct": post_fill["min_loss_pct"],
            "max_loss_pct": post_fill["max_loss_pct"],
            "min_invalidation_buffer_pts": strategy.get("entry", {}).get("min_invalidation_buffer_pts", 15),
            "initial_stop_pct": cfg["initial_stop_pct"],
        }
    except (KeyError, TypeError) as exc:
        raise ValueError("Incomplete post-fill stop policy") from exc
    return validate_stop_policy(policy)


def validate_stop_policy(policy):
    if not policy:
        return {}
    if not isinstance(policy, Mapping):
        raise ValueError("Invalid frozen stop policy")
    try:
        result = {key: positive_price(policy[key]) for key in (
            "min_loss_pct", "max_loss_pct", "min_invalidation_buffer_pts", "initial_stop_pct")}
    except (KeyError, TypeError) as exc:
        raise ValueError("Incomplete frozen stop policy") from exc
    if not 0 < result["min_loss_pct"] <= result["max_loss_pct"] <= result["initial_stop_pct"] < 100:
        raise ValueError("Post-fill stop losses must fit inside the initial stop percentage")
    return result


def stop_price_band(fill_price, policy):
    """Round inward so every exchange tick remains inside the configured loss band."""
    policy = validate_stop_policy(policy)
    fill = Decimal(str(positive_price(fill_price)))
    lower = tick_price(fill * (1 - Decimal(str(policy["max_loss_pct"])) / 100), up=True)
    upper = tick_price(fill * (1 - Decimal(str(policy["min_loss_pct"])) / 100))
    if not 0 < lower <= upper:
        raise ValueError("Post-fill stop band contains no valid exchange tick")
    return lower, upper


def structural_stop_limit(spot, direction, policy, previous=None):
    """Freeze the entry buffer; never loosen a pre-existing structural stop."""
    policy = validate_stop_policy(policy)
    anchor = positive_price(spot)
    buffer = policy["min_invalidation_buffer_pts"]
    if direction == "CE":
        limit = positive_price(anchor - buffer)
        return max(limit, positive_price(previous)) if previous is not None else limit
    if direction == "PE":
        limit = anchor + buffer
        return min(limit, positive_price(previous)) if previous is not None else limit
    raise ValueError("Unknown option direction")


def validate_stop_response(dossier, stop_price, invalidation=None, *, current_floor=0):
    """Check frozen policy before any position mutation or broker ratchet."""
    policy = validate_stop_policy(dossier.get("risk_policy", {}))
    if not policy:
        return
    lower, upper = stop_price_band(dossier["fill_price"], policy)
    floor = max(float(current_floor or 0), positive_price(dossier["active_stop_price"]))
    if not lower - 1e-9 <= positive_price(stop_price) <= max(upper, floor) + 1e-9:
        raise ValueError(f"Post-fill stop must be within {lower:.2f}..{upper:.2f}; existing tighter floors are preserved")
    if invalidation is not None:
        limit = structural_stop_limit(dossier["current_spot"], dossier["direction"], policy,
                                      dossier.get("entry_invalidation_level"))
        level = positive_price(invalidation)
        if ((dossier["direction"] == "CE" and level > limit + 1e-9)
                or (dossier["direction"] == "PE" and level < limit - 1e-9)):
            raise ValueError("Spot invalidation is inside the frozen minimum entry buffer")


def stop_loss_context(ctx):
    """Return a detached snapshot, or None rather than inventing missing structure."""
    try:
        candles = ctx.get("candles_1m") or []
        candle = candles[-1] if candles else {}
        snapshot = {key: positive_price(ctx.get(key)) for key in ("spot", "session_vwap", "ema_9", "ema_20")}
        for part in ("open", "high", "low", "close"):
            key = "candle_" + part
            snapshot[key] = positive_price(ctx.get(key) or candle.get(part))
        if not (
            snapshot["candle_low"]
            <= min(snapshot["candle_open"], snapshot["candle_close"])
            <= max(snapshot["candle_open"], snapshot["candle_close"])
            <= snapshot["candle_high"]
        ):
            return None
        snapshot["swing_low"] = positive_price(
            ctx.get("swing_low") or ctx.get("box_low_15m") or snapshot["candle_low"]
        )
        snapshot["swing_high"] = positive_price(
            ctx.get("swing_high") or ctx.get("box_high_15m") or snapshot["candle_high"]
        )
        snapshot["observed_at"] = ctx.get("observed_at", "")
        snapshot["candle_time"] = ctx.get("candle_time") or candle.get("start_time") or candle.get("date", "")
        return snapshot
    except (TypeError, ValueError, AttributeError, IndexError, KeyError):
        return None
