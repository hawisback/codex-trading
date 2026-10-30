"""One strategy-neutral R01 stop/trailing decision path.

Pure policy orchestration. This module does not place, modify or cancel broker
orders. Only positions explicitly stamped with the R01 policy use it; other
open positions retain their original strategy behavior.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from typing import Any, Mapping

from trading.domain.unified_stop_policy import unified_floor

R01_STOP_VERSION = "r01-owner-20261029-v1"
_TICK = Decimal("0.05")


@dataclass(frozen=True)
class UnifiedStopAction:
    kind: str                  # EXIT, RATCHET, HOLD
    reason: str
    trigger: float | None = None
    phase: str = ""


def r01_unified_active(state: Mapping[str, Any], trading_cfg: Mapping[str, Any]) -> bool:
    # The flag governs NEW entries. Once an entry has been stamped, its
    # original stop authority remains active even if runtime config is
    # disabled mid-session; this prevents retroactive policy migration.
    return (isinstance(state, Mapping)
            and state.get("r01_policy_version") == R01_STOP_VERSION)


def _positive(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    return number if number.is_finite() and number > 0 else None


def _nonnegative(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (ValueError, TypeError, InvalidOperation):
        return None
    return number if number.is_finite() and number >= 0 else None


def ceil_protective_tick(price: Decimal) -> float:
    """Always round stop floors UP to the exchange tick; never round down."""
    return float((price / _TICK).to_integral_value(rounding=ROUND_CEILING) * _TICK)


def r01_stop_floor(state: Mapping[str, Any], now: datetime,
                   *, initial_loss_pct: Any = 25) -> tuple[float, str] | None:
    if not isinstance(now, datetime) or now.tzinfo is None:
        return None
    from market_clock import IST_TZ
    now = now.astimezone(IST_TZ)
    entry = _positive(state.get("entry_price"))
    if entry is None:
        return None
    # All recorded/desired protection acts as a lower bound on tightening.
    existing = [
        _nonnegative(state.get(key) or 0)
        for key in ("desired_stop_trigger", "current_stop_trigger", "ai_stop_price")
    ]
    balances = state.get("entry_balances", {})
    if not isinstance(balances, Mapping):
        return None
    for record in state.get("stops", []):
        if not isinstance(record, Mapping):
            return None
        reference = record.get("entry_order_id") or record.get("parent_order_id")
        if reference in balances and balances.get(reference, 0) > 0 and (
            str(record.get("status", "")).upper() not in (
                "FILLED", "COMPLETE", "CANCELLED", "CANCELED", "REJECTED", "EXPIRED"
            )
        ):
            existing.append(_nonnegative(record.get("trigger_price") or 0))
    if any(v is None for v in existing):
        return None
    prior = max(existing, default=Decimal(0))
    # Broker-verified historical peaks may be reused on a new, fresh quote,
    # but never tighten a stop using stale/unverified quote state.
    fresh = False
    stamp = state.get("bid_timestamp")
    if state.get("quote_verified") is True and isinstance(stamp, str):
        try:
            observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            age = (now - observed).total_seconds() if observed.tzinfo else -1
            fresh = 0 <= age <= 2.0
        except ValueError:
            pass
    peak = _positive(state.get("peak_bid")) if fresh else entry
    if peak is None:
        return None
    decision = unified_floor(
        entry, peak, prior, now.strftime("%H:%M"), initial_loss_pct=initial_loss_pct
    )
    return (ceil_protective_tick(decision.trigger_floor), decision.phase) if decision else None


def decide_unified_stop(state: Mapping[str, Any], now: datetime, *,
                        initial_loss_pct: Any = 25,
                        max_quote_age_sec: float = 2.0) -> UnifiedStopAction:
    """Select a requested action from trusted position/quote evidence.

    A breached floor produces an EXIT request, not a competing SELL: the
    caller's existing OMS exit coordinator reconciles/cancels stops first.
    Without a fresh executable bid, no price-dependent action is permitted.
    """
    if not isinstance(now, datetime) or now.tzinfo is None:
        return UnifiedStopAction("HOLD", "CLOCK_UNVERIFIED")
    from market_clock import IST_TZ
    now_ist = now.astimezone(IST_TZ)
    if now_ist.strftime("%H:%M") >= "15:15":
        return UnifiedStopAction("EXIT", "SESSION_HARD_SQUARE_OFF")

    if state.get("quote_verified") is not True:
        return UnifiedStopAction("HOLD", "UNVERIFIED_EXECUTABLE_BID")
    stamp = state.get("bid_timestamp")
    if not isinstance(stamp, str):
        return UnifiedStopAction("HOLD", "BID_TIMESTAMP_MISSING")
    try:
        observed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("Ambiguous timestamp")
        age = (now - observed).total_seconds()
        if not 0 <= age <= max_quote_age_sec:
            return UnifiedStopAction("HOLD", "BID_STALE")
    except (TypeError, ValueError):
        return UnifiedStopAction("HOLD", "BID_TIMESTAMP_INVALID")

    bid = _positive(state.get("last_bid"))
    proposal = r01_stop_floor(state, now_ist, initial_loss_pct=initial_loss_pct)
    if bid is None or proposal is None:
        return UnifiedStopAction("HOLD", "STOP_INPUT_INVALID")
    floor, phase = proposal
    if bid <= Decimal(str(floor)):
        return UnifiedStopAction(
            "EXIT", "UNIFIED_PROTECTIVE_FLOOR_BREACHED", floor, phase
        )
    return UnifiedStopAction("RATCHET", "UNIFIED_PROTECTIVE_FLOOR", floor, phase)
