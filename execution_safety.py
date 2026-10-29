"""Local OMS safety primitives. No broker calls or strategy decisions at import time."""

import json
import os
import tempfile
import threading
import time
from pathlib import Path


class ReconciliationError(RuntimeError):
    pass


def status(order):
    value = str(order.get("status", "UNKNOWN")).upper().replace(" ", "_")
    return {"COMPLETE": "FILLED", "CANCELED": "CANCELLED"}.get(value, value)


TERMINAL = {"FILLED", "CANCELLED", "REJECTED", "EXPIRED"}


def rows(response, key):
    """A failed, malformed or truncated read is never an empty broker book."""
    if isinstance(response, list):
        result = response
    elif isinstance(response, dict) and not response.get("error") and isinstance(response.get(key), list):
        if response.get("has_more") or response.get("next_cursor") or response.get("truncated"):
            raise ReconciliationError(f"Incomplete {key} response")
        result = response[key]
    else:
        raise ReconciliationError(f"Unverified {key} response")
    if any(not isinstance(item, dict) for item in result):
        raise ReconciliationError(f"Malformed {key} record")
    if key == "orders" and len(result) >= 200:
        raise ReconciliationError("Journal limit reached; complete order reconciliation required")
    return result


def symbol_of(record):
    return record.get("symbol") or record.get("stock_code") or record.get("tradingsymbol")


def filled(order):
    if order.get("filled_quantity") is not None:
        return int(order["filled_quantity"])
    return int(order.get("quantity") or 0) if status(order) == "FILLED" else 0


def remaining(order):
    if status(order) in TERMINAL:
        return 0
    return int(order.get("pending_quantity") if order.get("pending_quantity") is not None
               else max(0, int(order.get("quantity") or 0) - filled(order)))


def same_scope(record, scope, known=False):
    """Known persisted references support legacy records lacking scope fields."""
    for field in ("mode", "account_id", "product", "exchange"):
        expected, actual = scope.get(field), record.get(field)
        if expected and actual and str(expected).upper() != str(actual).upper():
            return False
    return known or (bool(scope.get("mode")) and record.get("mode") == scope["mode"])


def atomic_save(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(5):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class SchedulerLock:
    """OS-owned lock: crash releases ownership; a leftover file is harmless."""

    _mutex = threading.RLock()
    _held = set()

    def __init__(self, path):
        self.path = Path(path).resolve()
        self.stream = None

    @classmethod
    def is_held(cls, path):
        with cls._mutex:
            return Path(path).resolve() in cls._held

    def __enter__(self):
        with self._mutex:
            if self.path in self._held:
                raise RuntimeError("Another scheduler instance already holds the lock")
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.stream = self.path.open("a+b")
            try:
                self.stream.seek(0, os.SEEK_END)
                if not self.stream.tell():
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                self.stream.close()
                self.stream = None
                raise RuntimeError("Another scheduler instance already holds the lock") from exc
            self._held.add(self.path)
        return self

    def __exit__(self, *exc):
        with self._mutex:
            if self.stream:
                self.stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
                self.stream.close()
                self.stream = None
                self._held.discard(self.path)
