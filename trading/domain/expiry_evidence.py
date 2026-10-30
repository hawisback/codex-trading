"""Resolve NIFTY option expiries only from matching dated source evidence.

This domain service never downloads a calendar, constructs a broker symbol,
or guesses an expiry from weekday arithmetic. Adapters provide dated
exchange-session and broker-master snapshots with provenance.
"""

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Mapping

from market_clock import IST_TZ


class ExpiryEvidenceError(ValueError):
    pass


@dataclass(frozen=True)
class ListedOption:
    instrument_id: str
    symbol: str
    strike: int
    right: str
    expiry: date


@dataclass(frozen=True)
class ExpiryEvidence:
    exchange_source: str
    exchange_asof: date
    session_dates: frozenset[date]
    broker_source: str
    master_asof: date
    contracts: tuple[ListedOption, ...]

    @classmethod
    def from_records(
        cls,
        *,
        exchange_source: str,
        exchange_asof: date,
        sessions: Iterable[date],
        broker_source: str,
        master_asof: date,
        contracts: Iterable[Mapping],
    ):
        if not exchange_source or not broker_source:
            raise ExpiryEvidenceError("EXPIRY_SOURCE_MISSING")
        if not isinstance(exchange_asof, date) or not isinstance(master_asof, date):
            raise ExpiryEvidenceError("EXPIRY_ASOF_INVALID")
        valid_sessions = frozenset(sessions)
        if not valid_sessions or any(type(x) is not date for x in valid_sessions):
            raise ExpiryEvidenceError("EXCHANGE_SESSIONS_INVALID")
        listed: list[ListedOption] = []
        identities = set()
        for item in contracts:
            if not isinstance(item, Mapping):
                raise ExpiryEvidenceError("BROKER_CONTRACT_INVALID")
            instrument = item.get("instrument_id")
            symbol = item.get("symbol")
            strike = item.get("strike")
            right = item.get("right")
            expiry = item.get("expiry")
            if (
                not isinstance(instrument, str)
                or not instrument
                or not isinstance(symbol, str)
                or not symbol
                or type(strike) is not int
                or strike <= 0
                or right not in ("CE", "PE")
                or type(expiry) is not date
            ):
                raise ExpiryEvidenceError("BROKER_CONTRACT_INVALID")
            if instrument in identities or any(r.symbol == symbol for r in listed):
                raise ExpiryEvidenceError("BROKER_CONTRACT_AMBIGUOUS")
            identities.add(instrument)
            listed.append(ListedOption(instrument, symbol, strike, right, expiry))
        if not listed:
            raise ExpiryEvidenceError("BROKER_CONTRACT_MASTER_EMPTY")
        return cls(exchange_source, exchange_asof, valid_sessions, broker_source, master_asof, tuple(listed))


def listed_expiry_contracts(
    evidence: ExpiryEvidence,
    *,
    trade_date: date,
    quote_asof: datetime,
    max_source_lag_days: int = 0,
) -> tuple[ListedOption, ...]:
    """Reject any stale, conflicting or nontradable source evidence.

    max_source_lag_days defaults to zero: both snapshots must belong to the
    current trading session, not an old cached holiday list. The broker
    adapter still has to verify instrument price/quote and account identity.
    """
    if not isinstance(evidence, ExpiryEvidence) or type(trade_date) is not date:
        raise ExpiryEvidenceError("EXPIRY_EVIDENCE_INVALID")
    if not isinstance(quote_asof, datetime) or quote_asof.tzinfo is None:
        raise ExpiryEvidenceError("EXPIRY_CLOCK_INVALID")
    if quote_asof.astimezone(IST_TZ).date() != trade_date:
        raise ExpiryEvidenceError("EXPIRY_QUOTE_DATE_MISMATCH")
    if trade_date not in evidence.session_dates:
        raise ExpiryEvidenceError("NOT_AN_EXCHANGE_SESSION")
    if max_source_lag_days < 0 or any(
        (trade_date - observed).days < 0 or (trade_date - observed).days > max_source_lag_days
        for observed in (evidence.exchange_asof, evidence.master_asof)
    ):
        raise ExpiryEvidenceError("EXPIRY_SOURCE_STALE")
    result = tuple(
        item
        for item in evidence.contracts
        if item.expiry >= trade_date and item.expiry in evidence.session_dates
    )
    if not result:
        raise ExpiryEvidenceError("NO_VERIFIED_TRADABLE_EXPIRY")
    return result
