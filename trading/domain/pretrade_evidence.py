"""R06 immutable pre-trade evidence checking, never broker order authorization.

The caller MUST still run the actual AIConsultant.evaluate, OMS locks,
fresh broker read/preflight and account authorization. A passing result from
this *pure* checker is not permission to place a BUY.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def _positive(value):
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return number if number.is_finite() and number > 0 else None


@dataclass(frozen=True)
class PreTradeEvidence:
    account_verified: bool
    consultation_verified: bool
    contract_identity_verified: bool
    quote_fresh: bool
    session_allows_entry: bool
    broker_funds_verified: bool
    no_unresolved_exposure: bool
    broker_limit_verified: bool
    loss_gate_passed: bool
    kill_switch_engaged: bool
    requested_quantity: int
    lot_size: int
    maximum_quantity: int
    executable_option_price: object
    available_margin: object
    fee_reserve: object


@dataclass(frozen=True)
class RiskCheck:
    passed: bool
    reasons: tuple[str, ...]
    version: str = "r06-evidence-v1"


def check_entry_evidence(e: PreTradeEvidence) -> RiskCheck:
    if not isinstance(e, PreTradeEvidence):
        return RiskCheck(False, ("EVIDENCE_MISSING",))
    flags = (
        ("ACCOUNT_UNVERIFIED", e.account_verified),
        ("CONSULTATION_UNVERIFIED", e.consultation_verified),
        ("CONTRACT_UNVERIFIED", e.contract_identity_verified),
        ("QUOTE_STALE", e.quote_fresh),
        ("SESSION_CLOSED", e.session_allows_entry),
        ("FUNDS_UNVERIFIED", e.broker_funds_verified),
        ("EXPOSURE_UNRESOLVED", e.no_unresolved_exposure),
        ("BROKER_QUANTITY_UNVERIFIED", e.broker_limit_verified),
        ("DAILY_LOSS_GATE_BLOCKED", e.loss_gate_passed),
    )
    reasons = [code for code, valid in flags if valid is not True]
    if e.kill_switch_engaged is not False:
        reasons.append("KILL_SWITCH_ENGAGED_OR_UNVERIFIED")
    if (any(type(x) is not int for x in (e.requested_quantity, e.lot_size, e.maximum_quantity))
            or e.lot_size <= 0 or e.requested_quantity <= 0 or
            e.maximum_quantity <= 0 or e.requested_quantity % e.lot_size or
            e.requested_quantity > e.maximum_quantity):
        reasons.append("ORDER_QUANTITY_INVALID")
    ask, margin, reserve = (
        _positive(e.executable_option_price),
        _positive(e.available_margin),
        _positive(e.fee_reserve),
    )
    if ask is None or margin is None or reserve is None:
        reasons.append("PRICE_OR_FUNDS_INVALID")
    elif e.requested_quantity > 0 and ask * e.requested_quantity + reserve > margin:
        reasons.append("ORDER_NOT_AFFORDABLE")
    return RiskCheck(not reasons, tuple(reasons))
