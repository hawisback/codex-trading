"""Typed internal views. Public decisions, quotes and saved positions remain JSON dictionaries."""

from dataclasses import dataclass
from typing import Any, Protocol, TypedDict


@dataclass(frozen=True)
class CandidateSignal:
    signal: str
    reasons: list[str]
    setup_type: str = "NONE"
    invalidation_level: float | None = None


class SignalStrategy(Protocol):
    def evaluate(self, ctx: dict[str, Any], intel: dict[str, Any] | None = None) -> CandidateSignal: ...


class Decision(TypedDict, total=False):
    signal: str
    strategy: str
    setup_type: str
    instrument_id: str | None
    symbol: str | None
    ltp: float | None
    quantity: int
    order_qty: int
    bull_score: int
    bear_score: int
    invalidation_level: float | None
    target_strike: int | None
    candidate_timestamp: str
    reasons: list[str]
    ai_verdict: dict[str, Any]


class ContractQuote(TypedDict, total=False):
    instrument_id: str
    best_bid: float
    best_ask: float
    best_bid_qty: int
    best_ask_qty: int
    timestamp: str
    request_started_monotonic: float
    error: bool
