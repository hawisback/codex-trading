"""Durable native-gateway correlation metadata; contains no API credentials."""

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from execution_safety import ReconciliationError, SchedulerLock, atomic_save

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

    def _reload(self):
        try:
            stamp = (self.path.stat().st_mtime_ns, self.path.stat().st_size) if self.path.exists() else None
        except OSError as exc:
            raise ReconciliationError("Unreadable gateway recovery journal") from exc
        if stamp is None and self._had_file:
            raise ReconciliationError("Gateway recovery journal was removed")
        if stamp == self._stamp:
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
        # The RLock only protects threads in one process. Every write must
        # hold the same filesystem lock across gateway processes, reload the
        # latest durable state, and then atomically replace it. The OS frees
        # the lease after crashes; the journal itself is never deleted.
        lease = self.path.with_name(self.path.name + ".writer.lock")
        with SchedulerLock(lease), self._lock:
            self._reload()
            return self._put(request_id, **updates)

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
