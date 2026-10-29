"""R10 incident classifications are observations, never automatic broker commands."""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class IncidentSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True)
class TradingIncident:
    code: str
    severity: IncidentSeverity
    new_entries_blocked: bool
    operator_action: str
    position_state_unverified: bool


_ACTIONS = {
    "BROKER_ACCOUNT_UNVERIFIED": (IncidentSeverity.CRITICAL, "Verify authenticated broker account and revoke new-entry arming.", True),
    "ORDER_OUTCOME_UNKNOWN": (IncidentSeverity.CRITICAL, "Keep request ID; reconcile broker order/fills before any further mutation.", True),
    "POSITION_UNPROTECTED": (IncidentSeverity.CRITICAL, "Escalate immediately; reconcile protective stops and verified residual exposure.", True),
    "SQUAREOFF_UNVERIFIED": (IncidentSeverity.CRITICAL, "Treat as live exposure until broker confirms flat and resting orders resolved.", True),
    "JOURNAL_UNREADABLE": (IncidentSeverity.CRITICAL, "Preserve all files and block entries; restore only after broker reconciliation.", True),
    "MARKET_FEED_STALE": (IncidentSeverity.WARNING, "Block new entries until exact-contract quote freshness recovers.", False),
    "DAILY_LOSS_LIMIT": (IncidentSeverity.WARNING, "Stop new entries; keep protective exits and broker reconciliation active.", False),
    "EXPIRY_SOURCE_UNVERIFIED": (IncidentSeverity.WARNING, "Do not infer an expiry or contract; refresh verified source evidence.", False),
}


def classify_incident(code: str) -> TradingIncident:
    """Unknown incident types must not silently resolve to an OK state."""
    if not isinstance(code, str) or not code:
        code = "UNCLASSIFIED"
    severity, action, unknown_position = _ACTIONS.get(
        code,
        (IncidentSeverity.CRITICAL,
         "Unclassified trading fault; block entries and reconcile state with broker.",
         True),
    )
    return TradingIncident(code, severity, True, action, unknown_position)
