"""Pure order intent phases for staged OMS recovery hardening.

This is an explicit contract, not a broker side-effect dispatcher. Existing
schema-v1 journal values remain compatible. Later staged work will apply
transitions at durable persistence boundaries after golden-trace review.
"""

from __future__ import annotations

from enum import Enum

from execution_safety import ReconciliationError


class IntentPhase(str, Enum):
    PREPARED = "PREPARED"       # Durable intent exists; transmit may not have started.
    SENT = "SENT"               # Optional future write-ahead send marker.
    UNKNOWN = "UNKNOWN"         # Outcome could have reached the exchange.
    ACKNOWLEDGED = "ACKNOWLEDGED" # Order ID accepted, not necessarily filled.
    REJECTED = "REJECTED"       # Definitive not-submitted/rejected outcome only.
    RECONCILED = "RECONCILED"   # Broker order/position evidence verified.


_TRANSITIONS: dict[IntentPhase | None, frozenset[IntentPhase]] = {
    None: frozenset({IntentPhase.PREPARED}),
    IntentPhase.PREPARED: frozenset({
        IntentPhase.SENT, IntentPhase.UNKNOWN,
        IntentPhase.ACKNOWLEDGED, IntentPhase.REJECTED,
    }),
    IntentPhase.SENT: frozenset({
        IntentPhase.UNKNOWN, IntentPhase.ACKNOWLEDGED, IntentPhase.REJECTED,
    }),
    IntentPhase.UNKNOWN: frozenset({
        IntentPhase.ACKNOWLEDGED, IntentPhase.REJECTED, IntentPhase.RECONCILED,
    }),
    IntentPhase.ACKNOWLEDGED: frozenset({
        IntentPhase.UNKNOWN, IntentPhase.RECONCILED,
    }),
    IntentPhase.REJECTED: frozenset(),
    IntentPhase.RECONCILED: frozenset(),
}


def needs_reconciliation(phase: str | None) -> bool:
    """Fail closed on unknown or omitted phases in a previously stored intent.

    An acknowledged order can still be live and must be checked by the
    regular OMS broker reconciliation. This particular predicate concerns
    unresolved *submission outcome*, not flatness or exit completion.
    """
    return phase not in {
        IntentPhase.ACKNOWLEDGED.value,
        IntentPhase.REJECTED.value,
        IntentPhase.RECONCILED.value,
    }


def proposed_transition(
    previous: str | None, next_phase: str, *, broker_verified: bool = False
) -> IntentPhase:
    """Validate a proposed phase update without touching a journal or broker.

    Moving an ambiguous outcome into a definitive state requires independent
    broker verification. Callers must also verify order identity/account scope
    and actual exposure. This helper does not establish those facts itself.

    This strict rule is not yet wired into schema-v1 journal writes.
    """
    try:
        before = IntentPhase(previous) if previous is not None else None
        after = IntentPhase(next_phase)
    except ValueError as exc:
        raise ReconciliationError("Unknown OMS intent phase") from exc
    if before == after:
        return after
    if after not in _TRANSITIONS[before]:
        raise ReconciliationError("Invalid OMS intent phase transition")
    if before == IntentPhase.UNKNOWN and after in {
        IntentPhase.ACKNOWLEDGED, IntentPhase.REJECTED, IntentPhase.RECONCILED,
    } and not broker_verified:
        raise ReconciliationError("Broker verification required for unknown submission")
    if before == IntentPhase.ACKNOWLEDGED and after == IntentPhase.RECONCILED and not broker_verified:
        raise ReconciliationError("Broker reconciliation evidence required")
    return after
