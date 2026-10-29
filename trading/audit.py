"""Observational events only: never a source of execution or recovery state."""

import copy
from dataclasses import asdict, is_dataclass
import json
import logging
import sys
import uuid

from market_clock import MarketClock

logger = logging.getLogger("TradeAudit")


def _failure(name, exc):
    try:
        sys.stderr.write(f"[AUDIT FAILURE] {name}: {exc}\n")
    except Exception:
        pass


def event(name, owner=None, **details):
    """Snapshot mutable inputs before the background log writer sees them."""
    try:
        if not logger.isEnabledFor(logging.INFO):
            return
        payload = {
            "schema_version": 1,
            "event_id": uuid.uuid4().hex,
            "timestamp": MarketClock.now_ist().isoformat(),
            "event": name,
            "candidate_id": getattr(owner, "_audit_candidate_id", None),
            "strategy": getattr(owner, "strategy_mode", None),
            "scope": getattr(owner, "execution_scope", {}),
            **details,
        }
        logger.info("[AUDIT] %s", name, extra={"audit_event": copy.deepcopy(payload)})
    except Exception as exc:
        # Diagnostics must not raise into a stop/exit path, even during disk failure.
        _failure(name, exc)


def candidate(owner, decision, context, intelligence):
    try:
        owner._audit_candidate_id = uuid.uuid4().hex
        event("candidate", owner, decision=decision, market=context, intelligence=intelligence)
    except Exception as exc:
        _failure("candidate", exc)


def consultation(owner, dossier):
    try:
        event(
            "ai_consultation",
            owner,
            dossier=asdict(dossier) if (is_dataclass(dossier) and not isinstance(dossier, type)) else {},
        )
    except Exception as exc:
        _failure("ai_consultation", exc)


def position(owner, state, *, closed=False):
    """Emit meaningful order transitions, not every mark-to-market tick."""
    try:
        if not logger.isEnabledFor(logging.INFO):
            return
        signature = json.dumps(
            {
                key: state.get(key)
                for key in (
                    "symbol",
                    "scope",
                    "status",
                    "quantity",
                    "entries",
                    "stops",
                    "exits",
                    "protection_confirmed",
                    "desired_stop_trigger",
                    "exit_reason",
                    "risk_exit_required",
                )
            },
            sort_keys=True,
            default=str,
        )
        if closed or signature != getattr(owner, "_audit_position_signature", None):
            event("position_closed" if closed else "position_state", owner, state=state)
            owner._audit_position_signature = signature
    except Exception as exc:
        # Recovery persistence remains authoritative and keeps its existing failures.
        _failure("position", exc)
