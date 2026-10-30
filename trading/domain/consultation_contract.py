"""R07 read-only consultation envelope identity and freshness checker.

This is NOT a substitute for the real, mandatory AIConsultant.evaluate call
and is not connected to the broker submission path.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


@dataclass(frozen=True)
class ConsultationRecord:
    verdict_id: str
    request_id: str
    instrument_id: str
    account_id: str
    action: str
    trap_detected: bool
    valid_from: datetime
    valid_until: datetime
    min_price: object
    max_price: object


def consultation_matches(
    record: ConsultationRecord,
    *,
    request_id: str,
    instrument_id: str,
    account_id: str,
    proposed_price: object,
    observed_at: datetime,
    consumed_verdict_ids: frozenset[str],
) -> bool:
    """Return false on any ambiguity; no mutation or persistence occurs."""
    if (
        not isinstance(record, ConsultationRecord)
        or record.action != "APPROVED"
        or record.trap_detected is not False
        or not all(
            isinstance(s, str) and s
            for s in (record.verdict_id, record.request_id, record.instrument_id, record.account_id)
        )
        or record.verdict_id in consumed_verdict_ids
        or (record.request_id, record.instrument_id, record.account_id)
        != (request_id, instrument_id, account_id)
    ):
        return False
    if (
        not isinstance(observed_at, datetime)
        or observed_at.tzinfo is None
        or not isinstance(record.valid_from, datetime)
        or record.valid_from.tzinfo is None
        or not isinstance(record.valid_until, datetime)
        or record.valid_until.tzinfo is None
    ):
        return False
    clock = observed_at.astimezone(timezone.utc)
    if not (
        record.valid_from.astimezone(timezone.utc) <= clock < record.valid_until.astimezone(timezone.utc)
    ):
        return False
    try:
        price, minimum, maximum = (
            Decimal(str(proposed_price)),
            Decimal(str(record.min_price)),
            Decimal(str(record.max_price)),
        )
    except (TypeError, ValueError, InvalidOperation):
        return False
    return all(x.is_finite() for x in (price, minimum, maximum)) and 0 < minimum <= price <= maximum
