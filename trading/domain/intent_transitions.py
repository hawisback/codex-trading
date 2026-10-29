"""Pure OMS intent-state vocabulary; no network, persistence or order submission.

The gateway journal remains the durable source. These records are deliberately
not wired into trading until transition and crash parity can be established.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping


class IntentPhase(str, Enum):
    PREPARED = "PREPARED"
    SENT = "SENT"
    UNKNOWN = "UNKNOWN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    RECONCILED = "RECONCILED"


class InvalidIntentTransition(ValueError):
    pass


_ALLOWED = {
    IntentPhase.PREPARED: frozenset((IntentPhase.SENT, IntentPhase.UNKNOWN, IntentPhase.REJECTED)),
    IntentPhase.SENT: frozenset((IntentPhase.UNKNOWN, IntentPhase.ACKNOWLEDGED, IntentPhase.REJECTED)),
    IntentPhase.UNKNOWN: frozenset((IntentPhase.ACKNOWLEDGED, IntentPhase.REJECTED)),
    IntentPhase.ACKNOWLEDGED: frozenset((IntentPhase.RECONCILED, IntentPhase.UNKNOWN)),
    IntentPhase.REJECTED: frozenset((IntentPhase.RECONCILED,)),
    IntentPhase.RECONCILED: frozenset(),
}


@dataclass(frozen=True)
class OrderIntentView:
    """Explicitly scoped snapshot, not an authority to send broker mutations."""

    request_id: str
    account_id: str
    mode: str
    symbol: str
    kind: str
    phase: IntentPhase
    broker_order_id: str | None = None

    @classmethod
    def from_mapping(cls, record: Mapping, *, account_id: str, mode: str):
        if not isinstance(record, Mapping):
            raise InvalidIntentTransition("INTENT_RECORD_INVALID")
        try:
            view = cls(
                request_id=record["request_id"],
                account_id=account_id,
                mode=mode,
                symbol=record["symbol"],
                kind=record["kind"],
                phase=IntentPhase(record["phase"]),
                broker_order_id=record.get("order_id"),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise InvalidIntentTransition("INTENT_RECORD_INVALID") from exc
        if (not all(isinstance(v, str) and v.strip() for v in
                    (view.request_id, view.account_id, view.symbol))
                or view.mode not in ("LIVE", "PAPER")
                or view.kind not in ("ENTRY", "STOP", "EXIT")
                or (view.broker_order_id is not None and
                    (not isinstance(view.broker_order_id, str) or not view.broker_order_id))):
            raise InvalidIntentTransition("INTENT_IDENTITY_INVALID")
        return view


def transition(intent: OrderIntentView, phase: IntentPhase, *,
               verified_broker_order_id: str | None = None) -> OrderIntentView:
    """Return a new view or reject unsafe/ambiguous transition.

    UNKNOWN is unresolved, not an instruction to resubmit. REJECTED requires
    authoritative negative broker evidence; transition() cannot create it.
    """
    if not isinstance(intent, OrderIntentView) or not isinstance(phase, IntentPhase):
        raise InvalidIntentTransition("INTENT_PHASE_INVALID")
    if phase not in _ALLOWED[intent.phase]:
        raise InvalidIntentTransition("INTENT_ILLEGAL_TRANSITION")
    if verified_broker_order_id is not None:
        if not isinstance(verified_broker_order_id, str) or not verified_broker_order_id:
            raise InvalidIntentTransition("INTENT_BROKER_ID_INVALID")
        if intent.broker_order_id is not None and intent.broker_order_id != verified_broker_order_id:
            raise InvalidIntentTransition("INTENT_BROKER_ID_CHANGED")
    new_id = verified_broker_order_id or intent.broker_order_id
    if phase in (IntentPhase.ACKNOWLEDGED, IntentPhase.RECONCILED) and not new_id:
        raise InvalidIntentTransition("INTENT_BROKER_ACK_UNVERIFIED")
    return OrderIntentView(
        request_id=intent.request_id, account_id=intent.account_id,
        mode=intent.mode, symbol=intent.symbol, kind=intent.kind,
        phase=phase, broker_order_id=new_id,
    )
