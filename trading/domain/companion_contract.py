"""Bounded neural-companion requests and structured judgments; no I/O."""

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import math
from typing import Any


class CompanionError(ValueError):
    pass


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise CompanionError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    def constant(value):
        raise CompanionError("NONFINITE_JSON_NUMBER")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def _text(value, maximum=256):
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


@dataclass(frozen=True)
class PendingConsultation:
    kind: str
    request_id: str
    subject_id: str
    created_at: datetime
    deadline: datetime
    payload: dict[str, Any]

    @property
    def identity(self):
        return f"{self.kind}:{self.request_id}"


def pending_consultation(kind, payload, now):
    status = {"ENTRY": "AWAITING_VERDICT", "STOP": "AWAITING_STOP_LOSS"}.get(kind)
    if not isinstance(payload, dict) or status is None or payload.get("status") != status:
        raise CompanionError("NO_ACTIVE_CONSULTATION")
    subject = "candidate_id" if kind == "ENTRY" else "trade_id"
    if not _text(payload.get("request_id")) or not _text(payload.get(subject)):
        raise CompanionError("CONSULTATION_IDENTITY_MISSING")
    if not isinstance(payload.get("dossier"), dict) or not payload["dossier"]:
        raise CompanionError("DOSSIER_MISSING")
    timeout = payload.get("timeout_seconds")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < timeout <= 45
        or not math.isfinite(timeout)
    ):
        raise CompanionError("CONSULTATION_TIMEOUT_INVALID")
    try:
        created = datetime.fromisoformat(payload["created_at"])
    except (KeyError, TypeError, ValueError):
        raise CompanionError("CONSULTATION_TIMESTAMP_INVALID") from None
    if created.tzinfo is None or now.tzinfo is None:
        raise CompanionError("CONSULTATION_TIMEZONE_MISSING")
    deadline = created + timedelta(seconds=timeout)
    if not created <= now < deadline:
        raise CompanionError("CONSULTATION_EXPIRED_OR_FUTURE")
    expires = payload.get("expires_at_timestamp")
    if expires is not None and (
        type(expires) not in (int, float)
        or not math.isfinite(expires)
        or abs(expires - deadline.timestamp()) > 0.001
    ):
        raise CompanionError("CONSULTATION_DEADLINE_MISMATCH")
    if kind == "STOP" and any(
        payload["dossier"].get(key) != payload[key] for key in ("request_id", "trade_id")
    ):
        raise CompanionError("STOP_DOSSIER_IDENTITY_MISMATCH")
    return PendingConsultation(kind, payload["request_id"], payload[subject], created, deadline, payload)


def judgment_schema(kind):
    properties: dict[str, Any] = {
        "kind": {"type": "string", "enum": [kind]},
        "request_id": {"type": "string"},
        "reasoning": {"type": "string", "minLength": 1, "maxLength": 2000},
        "trailing": {"type": "string", "enum": ["standard", "runner_ema9", "tight_ema20"]},
    }
    if kind == "ENTRY":
        properties.update(
            candidate_id={"type": "string"},
            action={"type": "string", "enum": ["APPROVED", "VETOED"]},
            confidence={"type": "integer", "minimum": 0, "maximum": 100},
            trap={"type": ["string", "null"]},
        )
    elif kind == "STOP":
        properties.update(
            trade_id={"type": "string"},
            action={"type": "string", "enum": ["ADJUST", "HOLD"]},
            stop_price={"type": ["number", "null"]},
            spot_invalidation={"type": ["number", "null"]},
        )
    else:
        raise CompanionError("UNKNOWN_CONSULTATION_KIND")
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def validate_judgment(request, result):
    schema = judgment_schema(request.kind)
    if not isinstance(result, dict) or set(result) != set(schema["properties"]):
        raise CompanionError("JUDGMENT_SCHEMA_MISMATCH")
    subject = "candidate_id" if request.kind == "ENTRY" else "trade_id"
    if (
        result["kind"] != request.kind
        or result["request_id"] != request.request_id
        or result[subject] != request.subject_id
    ):
        raise CompanionError("JUDGMENT_IDENTITY_MISMATCH")
    if not _text(result["reasoning"], 2000) or result["trailing"] not in (
        "standard",
        "runner_ema9",
        "tight_ema20",
    ):
        raise CompanionError("JUDGMENT_FIELDS_INVALID")
    if request.kind == "ENTRY":
        if (
            result["action"] not in ("APPROVED", "VETOED")
            or type(result["confidence"]) is not int
            or not 0 <= result["confidence"] <= 100
        ):
            raise CompanionError("ENTRY_JUDGMENT_INVALID")
        if result["trap"] is not None and not _text(result["trap"], 500):
            raise CompanionError("TRAP_FIELD_INVALID")
        if result["trap"] is not None:
            result = {**result, "action": "VETOED"}
    else:
        if result["action"] not in ("ADJUST", "HOLD"):
            raise CompanionError("STOP_JUDGMENT_INVALID")
        for key in ("stop_price", "spot_invalidation"):
            value = result[key]
            if value is not None and (
                type(value) not in (int, float) or not math.isfinite(value) or value <= 0
            ):
                raise CompanionError("STOP_JUDGMENT_PRICE_INVALID")
        if result["action"] == "ADJUST" and result["stop_price"] is None:
            raise CompanionError("STOP_PRICE_MISSING")
        if result["action"] == "HOLD" and any(
            result[key] is not None for key in ("stop_price", "spot_invalidation")
        ):
            raise CompanionError("HOLD_MUST_NOT_CHANGE_PROTECTION")
    return result
