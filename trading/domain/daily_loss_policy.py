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
    limit_amount: Decimal | None = None


def _decimal(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        result = Decimal(str(value))
    except (ValueError, InvalidOperation):
        return None
    return result if result.is_finite() else None


def daily_loss_decision(
    funds: Mapping, scope: Mapping, now: datetime, *, lots: int, loss_per_lot=3000
) -> DailyLossDecision:
    """Require authenticated matching account, current IST session, fresh P&L.

    Expected broker-reconciled keys: pnl_account_id, pnl_session_date,
    pnl_asof, realized_pnl_today, unrealized_pnl_today. The owner-approved
    cash cap is recalculated for the actual proposed entry lot count. It
    blocks new entries only; existing-position protection remains active.
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
    realized = _decimal(funds.get("realized_pnl_today"))
    unrealized = _decimal(funds.get("unrealized_pnl_today"))
    per_lot = _decimal(loss_per_lot)
    if realized is None or unrealized is None or per_lot is None:
        return deny("PNL_INVALID")
    if type(lots) is not int or not 1 <= lots <= 10 or per_lot <= 0:
        return deny("PNL_LIMIT_INVALID")
    limit = per_lot * lots
    if realized + unrealized <= -limit:
        return DailyLossDecision(False, "DAILY_LOSS_LIMIT", limit)
    return DailyLossDecision(True, "OK", limit)
