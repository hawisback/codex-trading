"""Filesystem-backed position repository; migrations live in PositionStateCodec."""

import json
from pathlib import Path

from execution_safety import ReconciliationError, atomic_save
from trading.adapters.position_codec import PositionStateCodec


class JsonPositionStore:
    def __init__(self, path, *, writer=None):
        self.path = Path(path)
        self._writer = writer
        self._codec = PositionStateCodec()

    def exists(self) -> bool:
        return self.path.exists()

    def save(self, data: dict) -> None:
        self._codec.encode(data)
        (self._writer or atomic_save)(self.path, data)

    def load(self) -> dict:
        if not self.exists():
            return {}
        try:
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(state, dict) or not state:
                raise ValueError("Invalid position state")
        except (OSError, ValueError) as exc:
            raise ReconciliationError("Unreadable position state; entries blocked") from exc
        return self._codec.decode(state)

    def delete(self, *, missing_ok: bool = False) -> None:
        self.path.unlink(missing_ok=missing_ok)
