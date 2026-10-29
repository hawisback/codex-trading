"""Pure R01 daily loss guard. No broker calls or order permissions."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Mapping

from market_clock import IST_TZ


@dataclass(frozen=True)
class DailyLossDecision:
    allowed: bool
    reason: str


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        return None
    return result if result.is_finite() else None


def daily_loss_decision(funds: Mapping, scope: Mapping, now: datetime,
                        limit_pct=1.5) -> DailyLossDecision:
    """Require authenticated matching account, current IST session, fresh P&L.

    Expected broker-reconciled keys: pnl_account_id, pnl_session_date,
    pnl_asof, start_of_day_equity, realized_pnl_today, unrealized_pnl_today.
    Missing data or a loss at the threshold forbids new entries.
    """
    deny = lambda code: DailyLossDecision(False, code)
    if not isinstance(funds, Mapping) or not isinstance(scope, Mapping):
        return deny("PNL_MISSING")
    if scope.get("mode") != "LIVE" or not scope.get("account_id"):
        return deny("ACCOUNT_UNVERIFIED")
    if funds.get("pnl_account_id") != scope["account_id"]:
        return deny("ACCOUNT_MISMATCH")
    if not isinstance(now, datetime) or now.tzinfo is None:
        return deny("CLOCK_UNVERIFIED")
    today = now.astimezone(IST_TZ)
    if funds.get("pnl_session_date") != today.date().isoformat():
        return deny("PNL_SESSION_UNVERIFIED")
    try:
        stamp = datetime.fromisoformat(funds["pnl_asof"].replace("Z", "+00:00"))
        age = (today - stamp.astimezone(IST_TZ)).total_seconds()
    except (KeyError, AttributeError, ValueError, TypeError):
        return deny("PNL_TIMESTAMP_UNVERIFIED")
    if stamp.tzinfo is None or not 0 <= age <= 60:
        return deny("PNL_STALE")
    start = _decimal(funds.get("start_of_day_equity"))
    realized = _decimal(funds.get("realized_pnl_today"))
    unrealized = _decimal(funds.get("unrealized_pnl_today"))
    limit = _decimal(limit_pct)
    if any(v is None for v in (start, realized, unrealized, limit)):
        return deny("PNL_INVALID")
    if start <= 0 or limit <= 0 or limit > 100:
        return deny("PNL_LIMIT_INVALID")
    if realized + unrealized <= -(start * limit / 100):
        return deny("DAILY_LOSS_LIMIT")
    return DailyLossDecision(True, "OK")
