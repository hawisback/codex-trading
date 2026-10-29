"""Durable native-gateway correlation metadata; contains no API credentials."""

import copy
import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from execution_safety import ReconciliationError, atomic_save

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

    def _reload(self):
        stamp = (self.path.stat().st_mtime_ns, self.path.stat().st_size) if self.path.exists() else None
        if stamp is None and self._had_file:
            raise ReconciliationError("Gateway recovery journal was removed")
        if stamp == self._stamp:
            return
        data = (
            json.loads(self.path.read_text(encoding="utf-8"))
            if self.path.exists()
            else {
                "schema_version": 1,
                "accounts": {},
            }
        )
        if (
            not isinstance(data, dict)
            or data.get("schema_version") != 1
            or not isinstance(data.get("accounts"), dict)
        ):
            raise ReconciliationError("Invalid gateway recovery journal")
        for records in data["accounts"].values():
            if not isinstance(records, dict) or any(
                not isinstance(item, dict) or item.get("request_id") != key or not item.get("tag")
                for key, item in records.items()
            ):
                raise ReconciliationError("Invalid gateway intent records")
        self.data, self._stamp, self._had_file = data, stamp, stamp is not None

    @property
    def records(self):
        if self.account is None:
            raise ReconciliationError("Gateway journal account is unverified")
        with self._lock:
            self._reload()
            return self.data["accounts"].get(f"{self.broker}:{self.account}", {})

    def put(self, request_id, **updates):
        with self._lock:
            return self._put(request_id, **updates)

    def _put(self, request_id, **updates):
        old = self.records.get(request_id, {})
        record = {**old, "request_id": request_id, "tag": broker_tag(request_id), **updates}
        for existing_id, existing in self.records.items():
            if existing_id != request_id and existing["tag"] == record["tag"]:
                raise ReconciliationError("Broker tag collision")
            if (
                existing_id != request_id
                and record.get("order_id")
                and existing.get("order_id") == record["order_id"]
            ):
                raise ReconciliationError("Broker order ID belongs to another intent")
        if record != old:
            data = copy.deepcopy(self.data)
            data["accounts"].setdefault(f"{self.broker}:{self.account}", {})[request_id] = record
            atomic_save(self.path, data)
            self.data = data
            self._stamp = (self.path.stat().st_mtime_ns, self.path.stat().st_size)
            self._had_file = True
        return record

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
