"""Durable native-gateway correlation metadata; contains no API credentials."""

import copy
import hashlib
import json
import math
import threading
from pathlib import Path
from typing import Any

from execution_safety import ReconciliationError, SchedulerLock, atomic_save
from trading.domain.intent_state import proposed_transition

WORKSPACE = Path(__file__).resolve().parents[3]


def broker_tag(request_id):
    return "NIFTYAI" + hashlib.sha256(request_id.encode()).hexdigest()[:13]


class GatewayJournal:
    _lock = threading.RLock()

    def __init__(self, path, broker):
        self.path = Path(path).resolve()
        if not self.path.is_relative_to(WORKSPACE):
            raise ValueError("Gateway journal must stay inside the workspace")
        self.broker = broker
        self.account = None
        self.data: dict[str, Any] = {"schema_version": 1, "accounts": {}}
        self._stamp = None
        self._had_file = False

    def bind(self, account):
        if not account:
            raise ReconciliationError("Verified broker account required")
        with self._lock:
            self._reload()
            self.account = account

    @staticmethod
    def _validate_document(data):
        """Reject ambiguous persisted intent identities before using the journal."""
        if (
            not isinstance(data, dict)
            or type(data.get("schema_version")) is not int
            or data["schema_version"] != 1
            or not isinstance(data.get("accounts"), dict)
        ):
            raise ReconciliationError("Invalid gateway recovery journal")
        for account, records in data["accounts"].items():
            if not isinstance(account, str) or not account or not isinstance(records, dict):
                raise ReconciliationError("Invalid gateway intent records")
            tags, order_ids = set(), set()
            for key, item in records.items():
                if (
                    not isinstance(key, str)
                    or not key
                    or not isinstance(item, dict)
                    or item.get("request_id") != key
                    or not isinstance(item.get("tag"), str)
                    or not item["tag"]
                ):
                    raise ReconciliationError("Invalid gateway intent records")
                tag = item["tag"]
                order_id = str(item["order_id"]) if item.get("order_id") else None
                if tag in tags or (order_id is not None and order_id in order_ids):
                    raise ReconciliationError("Ambiguous gateway intent correlation")
                tags.add(tag)
                if order_id is not None:
                    order_ids.add(order_id)

    def _reload(self, *, force=False):
        try:
            stamp = (self.path.stat().st_mtime_ns, self.path.stat().st_size) if self.path.exists() else None
        except OSError as exc:
            raise ReconciliationError("Unreadable gateway recovery journal") from exc
        if stamp is None and self._had_file:
            raise ReconciliationError("Gateway recovery journal was removed")
        if stamp == self._stamp and not force:
            return
        try:
            data = (
                json.loads(self.path.read_text(encoding="utf-8"))
                if stamp is not None
                else {"schema_version": 1, "accounts": {}}
            )
        except (OSError, UnicodeError, ValueError) as exc:
            raise ReconciliationError("Unreadable gateway recovery journal") from exc
        self._validate_document(data)
        self.data, self._stamp, self._had_file = data, stamp, stamp is not None

    @property
    def records(self):
        if self.account is None:
            raise ReconciliationError("Gateway journal account is unverified")
        with self._lock:
            self._reload()
            # Callers cannot mutate the in-memory recovery evidence by reference.
            return copy.deepcopy(self.data["accounts"].get(f"{self.broker}:{self.account}", {}))

    def put(self, request_id, **updates):
        # Serialize read/modify/write across independent gateway processes.
        # The thread mutex alone is insufficient for JSON journal writers.
        # This lock is strictly scoped to the journal transaction: it does
        # NOT grant concurrent processes authority to submit broker orders.
        with self._lock, SchedulerLock(self.path.with_name(self.path.name + ".writer.lock")):
            self._reload(force=True)  # Always re-read after acquiring OS ownership.
            return self._put(request_id, **updates)

    def prepare_mutation(self, request_id, *, target_order_id, action, target_kind, symbol,
                         target_quantity=None, expected_trigger_price=None, expected_limit_price=None):
        """Write a distinct CANCEL/MODIFY intent before the broker mutation.

        This is an account-scoped atomic check+insert. A mutation owns its
        own request/tag identity, while the existing original order retains
        the *only* `order_id` field. The target is stored separately so
        journal.match(order_id=...) stays unambiguous.
        """
        if (not isinstance(request_id, str) or not request_id
                or not isinstance(target_order_id, str) or not target_order_id
                or action not in ("CANCEL", "MODIFY_STOP", "REPRICE_EXIT")
                or target_kind not in ("ENTRY", "STOP", "EXIT")
                or not isinstance(symbol, str) or not symbol
                or (target_quantity is not None and
                    (type(target_quantity) is not int or target_quantity <= 0))
                or (action == "MODIFY_STOP" and target_kind != "STOP")
                or (action == "REPRICE_EXIT" and target_kind != "EXIT")):
            raise ReconciliationError("Invalid existing-order mutation identity")
        for field, value in (
            ("expected_trigger_price", expected_trigger_price),
            ("expected_limit_price", expected_limit_price),
        ):
            if value is not None and (
                type(value) not in (int, float)
                or not math.isfinite(value) or value <= 0
            ):
                raise ReconciliationError(f"Invalid {field} in mutation intent")
        with self._lock, SchedulerLock(self.path.with_name(self.path.name + ".writer.lock")):
            self._reload(force=True)
            if self.account is None:
                raise ReconciliationError("Gateway journal account is unverified")
            records = self.data["accounts"].get(f"{self.broker}:{self.account}", {})
            if request_id in records:
                raise ReconciliationError("Existing mutation request ID cannot be replayed")
            for record in records.values():
                if (record.get("kind") == "MUTATION"
                        and record.get("target_order_id") == target_order_id
                        and record.get("phase") not in ("REJECTED", "RECONCILED")):
                    raise ReconciliationError(
                        "Unresolved mutation on broker order; reconcile before retry"
                    )
            return self._put(
                request_id, kind="MUTATION", mutation_action=action,
                target_kind=target_kind, target_order_id=target_order_id,
                symbol=symbol, phase="PREPARED",
                target_quantity=target_quantity,
                expected_trigger_price=expected_trigger_price,
                expected_limit_price=expected_limit_price,
            )

    def transition(self, request_id, next_phase, *, broker_verified=False, **updates):
        """Atomically validate a phase advance against the *latest* journal state.

        For staged adoption: this method makes strict phase writes available
        without rewriting existing schema-v1 records or bypassing historical
        recovery adapters. The caller is responsible for establishing broker
        identity/account evidence before broker_verified=True.
        """
        with self._lock, SchedulerLock(self.path.with_name(self.path.name + ".writer.lock")):
            self._reload(force=True)
            if self.account is None:
                raise ReconciliationError("Gateway journal account is unverified")
            records = self.data["accounts"].get(f"{self.broker}:{self.account}", {})
            old = records.get(request_id)
            if old is None:
                raise ReconciliationError("Missing durable intent to transition")
            if "phase" in updates:
                raise ReconciliationError("Duplicate phase update")
            validated = proposed_transition(
                old.get("phase"), next_phase, broker_verified=broker_verified
            )
            return self._put(request_id, phase=validated.value, **updates)

    def _put(self, request_id, **updates):
        if not isinstance(request_id, str) or not request_id:
            raise ReconciliationError("Invalid broker request identity")
        expected_tag = broker_tag(request_id)
        if (
            updates.get("request_id", request_id) != request_id
            or updates.get("tag", expected_tag) != expected_tag
        ):
            raise ReconciliationError("Broker request identity is immutable")
        records = self.records
        old = records.get(request_id, {})
        if old and old.get("kind") == "MUTATION":
            for field in (
                "kind", "mutation_action", "target_kind",
                "target_order_id", "symbol", "target_quantity",
                "expected_trigger_price", "expected_limit_price",
            ):
                if field in updates and updates[field] != old.get(field):
                    raise ReconciliationError("Mutation intent identity/expected prices are immutable")
        record = {**old, **updates, "request_id": request_id, "tag": expected_tag}
        for existing_id, existing in records.items():
            if existing_id != request_id and existing["tag"] == record["tag"]:
                raise ReconciliationError("Broker tag collision")
            if (
                existing_id != request_id
                and record.get("order_id")
                and str(existing.get("order_id")) == str(record["order_id"])
            ):
                raise ReconciliationError("Broker order ID belongs to another intent")
        if record != old:
            data = copy.deepcopy(self.data)
            data["accounts"].setdefault(f"{self.broker}:{self.account}", {})[request_id] = record
            atomic_save(self.path, data)
            self.data = data
            self._stamp = (self.path.stat().st_mtime_ns, self.path.stat().st_size)
            self._had_file = True
        return copy.deepcopy(record)

    def match(self, *, tag=None, order_id=None):
        found = [
            r
            for r in self.records.values()
            if (
                (order_id and r.get("order_id") == str(order_id))
                or (tag and tag in (r["tag"], r["request_id"][:20]))
            )
        ]
        if len(found) > 1:
            raise ReconciliationError("Ambiguous broker order correlation")
        return found[0] if found else None
