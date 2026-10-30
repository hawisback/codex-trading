"""Persistent request worker; application code owns validation and publication.

No broker adapter is imported. Entry and stop jobs use separate bounded slots;
one slow entry model cannot prevent observation of an existing-position request.
"""

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from typing import Any

from ai_consultant import submit_entry_verdict, submit_stop_loss_verdict
from execution_safety import atomic_save
from market_clock import MarketClock
from trading.domain.audit_redaction import redact_for_audit
from trading.domain.companion_contract import (
    CompanionError,
    PendingConsultation,
    judgment_schema,
    pending_consultation,
    strict_json,
    validate_judgment,
)

FILES = {
    "STOP": ("pending_stop_loss.json", "ai_stop_verdict.json"),
    "ENTRY": ("pending_consultation.json", "ai_verdict.json"),
}


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(1_000_001)
    if len(data) > 1_000_000:
        raise CompanionError("CONSULTATION_FILE_OVERSIZED")
    return strict_json(data.decode("utf-8"))


@dataclass
class Job:
    request: PendingConsultation
    future: Future[str]
    cancel: threading.Event
    sources: dict
    started: float


class CompanionWorker:
    publication_reserve_sec = 2.0

    def __init__(self, root, backend, *, now=MarketClock.now_ist, monotonic=time.monotonic, event=None):
        self.root, self.backend = Path(root).resolve(), backend
        self.now, self.monotonic = now, monotonic
        self.event = event or (lambda **details: print(json.dumps(details), flush=True))
        self.logs = self.root / "logs"
        self.state_path = self.logs / "codex_companion_state.json"
        self.state: dict[str, Any] = (
            read_json(self.state_path) if self.state_path.exists() else {"schema_version": 1, "requests": {}}
        )
        if (
            not isinstance(self.state, dict)
            or type(self.state.get("schema_version")) is not int
            or self.state["schema_version"] != 1
            or not isinstance(self.state.get("requests"), dict)
        ):
            raise CompanionError("COMPANION_STATE_UNVERIFIED")
        self.jobs: dict[str, Job] = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="codex-judgment")

    def _record(self, request, status, **extra):
        records = self.state["requests"]
        records[request.identity] = {
            "status": status,
            "request_id": request.request_id,
            "subject_id": request.subject_id,
            "observed_at": self.now().isoformat(),
            **extra,
        }
        if len(records) > 2000:
            for identity in list(records)[:-2000]:
                del records[identity]
        atomic_save(self.state_path, self.state)
        self.event(kind=request.kind, request_id=request.request_id, status=status, **extra)

    def packet(self, request):
        sources, text = {}, {}
        for name, relative in (("charter", "AGENTS.md"), ("playbook", "config/rules_playbook.md")):
            path = self.root / relative
            data = path.read_bytes()
            sources[relative] = hashlib.sha256(data).hexdigest()
            text[name] = data.decode("utf-8-sig")
        payload = request.payload
        if not payload.get("evaluation_rubric"):
            raise CompanionError("EVALUATION_RUBRIC_MISSING")
        policy = (
            payload.get("authoritative_risk_policy")
            if request.kind == "ENTRY"
            else payload["dossier"].get("risk_policy")
        )
        if not isinstance(policy, dict) or not policy:
            raise CompanionError("AUTHORITATIVE_RISK_POLICY_MISSING")
        if request.kind == "ENTRY":
            initial = policy.get("initial_stop_pct")
            if (
                isinstance(initial, bool)
                or not isinstance(initial, (int, float))
                or not 0 < initial < 100
                or not math.isfinite(initial)
            ):
                raise CompanionError("AUTHORITATIVE_INITIAL_PROTECTION_INVALID")
        dossier = redact_for_audit(payload["dossier"])
        if request.kind == "ENTRY" and policy.get("source") == "R01_UNIFIED":
            # Legacy refinement metadata is kept by the engine for entry
            # invalidation checks, but is not a competing R01 stop authority.
            dossier["risk_policy"] = policy
        packet = {
            "kind": request.kind,
            "request_id": request.request_id,
            "candidate_id" if request.kind == "ENTRY" else "trade_id": request.subject_id,
            "created_at": request.created_at.isoformat(),
            "deadline": request.deadline.isoformat(),
            "application_observed_at": self.now().isoformat(),
            "dossier": dossier,
            "authoritative_risk_policy": policy,
            "evaluation_rubric": payload["evaluation_rubric"],
            "proposed_entry_band": payload.get("proposed_entry_band"),
            "source_sha256": sources,
            **text,
        }
        return packet, sources

    def _current(self, request):
        pending, verdict = (self.logs / name for name in FILES[request.kind])
        current = read_json(pending)
        pending_consultation(request.kind, current, self.now())
        if current != request.payload:
            raise CompanionError("CONSULTATION_REPLACED")
        if verdict.exists():
            response = read_json(verdict)
            if isinstance(response, dict) and response.get("request_id") == request.request_id:
                raise CompanionError("VERDICT_ALREADY_PUBLISHED")
        return pending, verdict

    def publish(self, request, raw, sources):
        result = validate_judgment(request, strict_json(raw))
        for relative, digest in sources.items():
            if hashlib.sha256((self.root / relative).read_bytes()).hexdigest() != digest:
                raise CompanionError("COMPANION_POLICY_CHANGED")
        pending, verdict = self._current(request)
        kwargs = dict(expected_pending=request.payload, pending_path=pending, verdict_path=verdict)
        if request.kind == "ENTRY":
            submit_entry_verdict(
                request.request_id,
                result["action"],
                result["reasoning"],
                result["trailing"],
                confidence=result["confidence"],
                trap=result["trap"],
                **kwargs,
            )
        elif result["action"] == "ADJUST":
            submit_stop_loss_verdict(
                request.request_id,
                result["stop_price"],
                result["spot_invalidation"],
                result["trailing"],
                result["reasoning"],
                **kwargs,
            )
        else:
            # No stop mutation: the existing application's bounded wait retains
            # baseline protection. A HOLD cannot invent a looser replacement.
            return "HOLD_PROTECTION_RETAINED"
        return "SUBMITTED"

    def tick(self):
        for kind, job in list(self.jobs.items()):
            if job.future.done():
                try:
                    status = self.publish(job.request, job.future.result(), job.sources)
                    self._record(job.request, status, elapsed_sec=round(self.monotonic() - job.started, 3))
                except Exception as exc:
                    code = str(exc) if isinstance(exc, CompanionError) else type(exc).__name__
                    self._record(job.request, "FAILED_NO_VERDICT", reason=code)
                finally:
                    del self.jobs[kind]
            else:
                try:
                    self._current(job.request)
                except Exception:
                    job.cancel.set()
        # Existing exposure gets its own slot and is considered first.
        for kind, names in FILES.items():
            if kind in self.jobs:
                continue
            try:
                request = pending_consultation(kind, read_json(self.logs / names[0]), self.now())
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                continue
            if request.identity in self.state["requests"]:
                continue
            try:
                self._current(request)
                packet, sources = self.packet(request)
                budget = (request.deadline - self.now()).total_seconds() - self.publication_reserve_sec
                if budget <= 0:
                    raise CompanionError("INSUFFICIENT_HANDOFF_TIME")
                self._record(request, "INVOKING")  # Durable claim before starting the model.
                cancel, started = threading.Event(), self.monotonic()
                future = self.pool.submit(
                    self.backend.generate, packet, judgment_schema(kind), started + budget, cancel
                )
                self.jobs[kind] = Job(request, future, cancel, sources, started)
            except Exception as exc:
                code = str(exc) if isinstance(exc, CompanionError) else type(exc).__name__
                self._record(request, "FAILED_NO_VERDICT", reason=code)

    def close(self):
        for job in self.jobs.values():
            job.cancel.set()
        self.pool.shutdown(wait=True, cancel_futures=True)
