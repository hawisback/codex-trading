"""Deterministic replay provenance. Hashes data, never sends broker orders.

Decision replay and profit simulation are separate evidence sets. Hashes
identify snapshots; they do not certify historical completeness or fills.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Sequence


class ReplayEvidenceError(ValueError):
    pass


def canonical_sha256(value: Any) -> str:
    try:
        payload = json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False, ensure_ascii=False
        ).encode("utf-8")
    except (ValueError, TypeError, OverflowError) as exc:
        raise ReplayEvidenceError("REPLAY_DATA_NONCANONICAL") from exc
    return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class ReplayManifest:
    source: str
    dataset_hash: str
    policy_hash: str
    calendar_hash: str
    fee_model_hash: str
    event_count: int
    first_timestamp: str
    last_timestamp: str
    mode: str = "DECISION_ONLY"

    @classmethod
    def from_events(
        cls, events: Sequence[dict], *, source: str, policy_hash: str, calendar_hash: str, fee_model_hash: str
    ):
        if not source or not all(
            isinstance(h, str) and len(h) == 64 and all(c in "0123456789abcdef" for c in h)
            for h in (policy_hash, calendar_hash, fee_model_hash)
        ):
            raise ReplayEvidenceError("REPLAY_PROVENANCE_INCOMPLETE")
        if not isinstance(events, (list, tuple)) or not events:
            raise ReplayEvidenceError("REPLAY_EVENTS_EMPTY")
        stamps = []
        for event in events:
            if not isinstance(event, dict) or not isinstance(event.get("timestamp"), str):
                raise ReplayEvidenceError("REPLAY_EVENT_TIMESTAMP_MISSING")
            try:
                stamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            except ValueError as exc:
                raise ReplayEvidenceError("REPLAY_EVENT_TIMESTAMP_INVALID") from exc
            if stamp.tzinfo is None:
                raise ReplayEvidenceError("REPLAY_EVENT_TIMESTAMP_AMBIGUOUS")
            stamps.append(stamp.astimezone(timezone.utc))
        if stamps != sorted(stamps):
            raise ReplayEvidenceError("REPLAY_EVENTS_OUT_OF_ORDER")
        return cls(
            source=source,
            dataset_hash=canonical_sha256(events),
            policy_hash=policy_hash,
            calendar_hash=calendar_hash,
            fee_model_hash=fee_model_hash,
            event_count=len(events),
            first_timestamp=stamps[0].isoformat(),
            last_timestamp=stamps[-1].isoformat(),
        )


def reject_lookahead(input_timestamp: str, decision_timestamp: str) -> None:
    """Reject a future-labelled market datum before replay evaluation."""
    try:
        data = datetime.fromisoformat(input_timestamp.replace("Z", "+00:00"))
        decision = datetime.fromisoformat(decision_timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ReplayEvidenceError("REPLAY_CLOCK_INVALID") from exc
    if data.tzinfo is None or decision.tzinfo is None:
        raise ReplayEvidenceError("REPLAY_CLOCK_AMBIGUOUS")
    if data.astimezone(timezone.utc) > decision.astimezone(timezone.utc):
        raise ReplayEvidenceError("REPLAY_LOOKAHEAD_DETECTED")
