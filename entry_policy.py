"""Deterministic entry bounds and quote validation. No network or order side effects."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import math
import time

from market_clock import IST_TZ, MarketClock

TICK = Decimal("0.05")


class EntryBlocked(ValueError):
    pass


def number(value):
    if isinstance(value, bool):
        raise EntryBlocked("INVALID_ENTRY_NUMBER")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise EntryBlocked("INVALID_ENTRY_NUMBER") from exc
    if not math.isfinite(result):
        raise EntryBlocked("INVALID_ENTRY_NUMBER")
    return result


def tick_price(value, *, up=False):
    number(value)
    value = Decimal(str(value))
    return float((value / TICK).to_integral_value(rounding=ROUND_CEILING if up else ROUND_FLOOR) * TICK)


def timestamp(value):
    """Full dated exchange timestamps only; naive gateway/Kite timestamps are IST."""
    try:
        if isinstance(value, datetime):
            result = value
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            epoch = number(value)
            result = datetime.fromtimestamp(epoch / 1000 if epoch > 1e11 else epoch, tz=IST_TZ)
        elif isinstance(value, str) and len(value) >= 19:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        else:
            raise ValueError("Full timestamp required")
        return result.replace(tzinfo=IST_TZ) if result.tzinfo is None else result.astimezone(IST_TZ)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise EntryBlocked("INVALID_ENTRY_TIMESTAMP") from exc


@dataclass(frozen=True)
class EntryPolicy:
    buffer_pct: float = 5.0
    climax_buffer_pct: float = 3.0
    downside_pct: float = 8.0
    max_points: float = 4.0
    limit_ticks: int = 1
    quote_age: float = 1.0
    quote_timeout: float = 1.0
    approval_ttl: float = 5.0
    candidate_age: float = 15.0
    min_premium: float = 0.0
    max_premium: float = 70.0
    max_spread_pct: float = 3.0
    order_timeout: float = 10.0

    @classmethod
    def from_config(cls, config):
        execution = config.get("execution", {})
        selection = config.get("option_selection", {})
        risk = config.get("risk", {})
        policy = cls(
            buffer_pct=number(execution.get("entry_buffer_pct", 5)),
            climax_buffer_pct=number(execution.get("climax_entry_buffer_pct", 3)),
            downside_pct=number(execution.get("entry_downside_buffer_pct", 8)),
            max_points=number(execution.get("max_slippage_ceiling_pts", 4)),
            limit_ticks=number(execution.get("marketable_limit_ticks", 1)),
            quote_age=number(execution.get("max_entry_quote_age_seconds", 1)),
            quote_timeout=number(execution.get("entry_quote_timeout_sec", 1)),
            approval_ttl=number(execution.get("ai_approval_ttl_seconds", 5)),
            candidate_age=number(execution.get("max_entry_candidate_age_seconds", 15)),
            min_premium=number(selection.get("min_option_premium", 0)),
            max_premium=number(selection.get("max_option_premium", 70)),
            max_spread_pct=number(selection.get("max_bid_ask_spread_pct", 3)),
            order_timeout=number(risk.get("entry_order_timeout_sec", 10)))
        if (not 0 <= policy.climax_buffer_pct <= policy.buffer_pct <= 100 or
                not 0 <= policy.downside_pct < 100 or policy.max_points < 0 or
                policy.limit_ticks < 0 or policy.limit_ticks != int(policy.limit_ticks) or
                min(policy.quote_age, policy.quote_timeout, policy.approval_ttl,
                    policy.candidate_age, policy.order_timeout) <= 0 or
                policy.min_premium < 0 or
                policy.max_premium < policy.min_premium or policy.max_spread_pct <= 0):
            raise EntryBlocked("INVALID_ENTRY_POLICY")
        return policy

    def band(self, reference, setup_type):
        reference = number(reference)
        if reference <= 0:
            raise EntryBlocked("INVALID_ENTRY_REFERENCE")
        pct = self.climax_buffer_pct if setup_type == "CLIMAX_SPRING" else self.buffer_pct
        base = Decimal(str(reference))
        upper = tick_price(min(base * (1 + Decimal(str(pct)) / 100),
                               base + Decimal(str(self.max_points)), Decimal(str(self.max_premium))))
        lower = tick_price(max(base * (1 - Decimal(str(self.downside_pct)) / 100),
                               Decimal(str(self.min_premium))), up=True)
        if not lower <= reference <= upper:
            raise EntryBlocked("ENTRY_REFERENCE_OUTSIDE_POLICY")
        return lower, upper


def approve_band(dossier, policy):
    """Called inside the consultant only after an actual, successful evaluation."""
    reference = number(dossier.option_entry_price)
    setup = dossier.setup_type
    lower, upper = policy.band(reference, setup)
    now = MarketClock.now_ist()
    candidate = timestamp(dossier.candidate_timestamp or now)
    invalidation = None if dossier.invalidation_level is None else number(dossier.invalidation_level)
    if invalidation is not None and invalidation <= 0:
        raise EntryBlocked("INVALID_ENTRY_STRUCTURE")
    return dict(min_entry_price=lower, max_entry_price=upper, reference_entry_price=reference,
                entry_instrument_id=dossier.instrument_id or dossier.symbol,
                entry_setup_type=setup, entry_candidate_at=candidate.isoformat(),
                entry_invalidation_level=invalidation,
                entry_approved_at=now.isoformat(),
                entry_valid_until=(now + timedelta(seconds=policy.approval_ttl)).isoformat())


def validate_approval(decision, policy):
    verdict = decision.get("ai_verdict")
    if (not isinstance(verdict, dict) or verdict.get("is_approved") is not True or
            verdict.get("action") != "APPROVED" or verdict.get("trap_detected")):
        raise EntryBlocked("AI_APPROVAL_REQUIRED")
    if (verdict.get("entry_risk_policy") or decision.get("stop_loss_policy")) and (
            verdict.get("entry_risk_policy") != decision.get("stop_loss_policy")):
        raise EntryBlocked("AI_ENTRY_RISK_POLICY_MISMATCH")
    if (not decision.get("instrument_id") or verdict.get("entry_instrument_id") != decision["instrument_id"] or
            verdict.get("entry_setup_type") != decision.get("setup_type", "TREND_PULLBACK")):
        raise EntryBlocked("AI_ENTRY_IDENTITY_MISMATCH")
    reference = number(verdict.get("reference_entry_price"))
    if reference != number(decision.get("ltp")):
        raise EntryBlocked("AI_ENTRY_REFERENCE_MISMATCH")
    invalidation = verdict.get("entry_invalidation_level")
    if invalidation != decision.get("invalidation_level"):
        raise EntryBlocked("AI_ENTRY_INVALIDATION_MISMATCH")
    lower, upper = policy.band(reference, verdict["entry_setup_type"])
    lower = max(lower, number(verdict.get("min_entry_price")))
    upper = min(upper, number(verdict.get("max_entry_price")))
    lower, upper = tick_price(lower, up=True), tick_price(upper)
    if not 0 < lower <= reference <= upper:
        raise EntryBlocked("INVALID_AI_ENTRY_BAND")
    approved = timestamp(verdict.get("entry_approved_at"))
    candidate = timestamp(verdict.get("entry_candidate_at"))
    expiry = timestamp(verdict.get("entry_valid_until"))
    now = MarketClock.now_ist()
    if (candidate > approved or approved > now or now >= expiry or
            (now - approved).total_seconds() >= policy.approval_ttl or
            (now - candidate).total_seconds() >= policy.candidate_age or
            expiry > approved + timedelta(seconds=policy.approval_ttl)):
        raise EntryBlocked("AI_ENTRY_APPROVAL_EXPIRED")
    return lower, upper


def validate_quote_age(quote, instrument_id, policy):
    if not isinstance(quote, dict) or quote.get("error"):
        raise EntryBlocked("ENTRY_QUOTE_UNAVAILABLE")
    if quote.get("instrument_id") != instrument_id:
        raise EntryBlocked("ENTRY_QUOTE_IDENTITY_MISMATCH")
    if (quote.get("stale") is True or quote.get("is_stale") is True or quote.get("ready") is False or
            str(quote.get("status", "")).upper() in ("STALE", "UNAVAILABLE", "ERROR", "CLOSED")):
        raise EntryBlocked("ENTRY_QUOTE_UNAVAILABLE")
    exchange_age = (MarketClock.now_ist() - timestamp(quote.get("timestamp"))).total_seconds()
    elapsed = time.monotonic() - number(quote.get("request_started_monotonic"))
    if exchange_age < 0 or elapsed < 0 or max(exchange_age, elapsed) > policy.quote_age:
        raise EntryBlocked("ENTRY_QUOTE_STALE")


def validate_invalidation(decision, quote, policy):
    if decision.get("invalidation_level") is None:
        if decision.get("stop_loss_policy"):
            raise EntryBlocked("INVALID_ENTRY_STRUCTURE")
        return
    validate_quote_age(quote, "INST-NIFTY-INDEX", policy)
    spot = number(quote.get("last_price"))
    level = number(decision["invalidation_level"])
    direction = decision.get("signal") or ("BUY_CE" if str(decision.get("symbol", "")).endswith("CE") else
                                          "BUY_PE" if str(decision.get("symbol", "")).endswith("PE") else None)
    if spot <= 0 or level <= 0 or direction not in ("BUY_CE", "BUY_PE"):
        raise EntryBlocked("INVALID_ENTRY_STRUCTURE")
    if (direction == "BUY_CE" and spot <= level) or (direction == "BUY_PE" and spot >= level):
        raise EntryBlocked("ENTRY_STRUCTURE_INVALIDATED")
    if decision.get("stop_loss_policy"):
        buffer = number(decision["stop_loss_policy"].get("min_invalidation_buffer_pts"))
        if buffer <= 0 or ((spot - level) if direction == "BUY_CE" else (level - spot)) + 1e-9 < buffer:
            raise EntryBlocked("ENTRY_STRUCTURE_BUFFER_TOO_SMALL")


def validate_quote(quote, instrument_id, policy):
    validate_quote_age(quote, instrument_id, policy)
    bid, ask = number(quote.get("best_bid")), number(quote.get("best_ask"))
    bid_qty, ask_qty = number(quote.get("best_bid_qty")), number(quote.get("best_ask_qty"))
    if (not 0 < bid <= ask or min(bid_qty, ask_qty) <= 0 or
            bid_qty != int(bid_qty) or ask_qty != int(ask_qty) or
            tick_price(bid) != bid or tick_price(ask) != ask):
        raise EntryBlocked("INVALID_ENTRY_QUOTE_DEPTH")
    if (ask - bid) / bid * 100 > policy.max_spread_pct:
        raise EntryBlocked("ENTRY_SPREAD_TOO_WIDE")
    return bid, ask


def entry_limit(decision, quote, policy):
    lower, upper = validate_approval(decision, policy)
    _, ask = validate_quote(quote, decision["instrument_id"], policy)
    if ask > upper:
        raise EntryBlocked("AI_ENTRY_CEILING_EXCEEDED")
    if ask < lower:
        raise EntryBlocked("AI_ENTRY_FLOOR_BREACHED")
    buffered = Decimal(str(ask)) + TICK * int(policy.limit_ticks)
    return min(tick_price(buffered), upper)
