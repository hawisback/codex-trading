"""Cross-workspace *local-host* single-writer lease for a verified broker account.

The lease guards the live scheduler lifetime, not individual journal writes. It
does not replace broker reconciliation, durable intents, or an account-wide
distributed coordinator across different hosts/OS users.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

from execution_safety import SchedulerLock


def account_lock_path(
    broker: str, account_id: str, *, directory: str | Path | None = None
) -> Path:
    """Return a stable, non-identifying lock path for the local OS user.

    All cooperating live schedulers must use the same path root. An explicit
    TRADING_ACCOUNT_LOCK_DIR supports shared installations; different hosts or
    uncoordinated directories cannot exclude each other.
    """
    if not isinstance(broker, str) or broker.lower() not in {"kite", "breeze", "proxy"}:
        raise ValueError("Unsupported execution broker for account ownership")
    if not isinstance(account_id, str) or not account_id.strip():
        raise ValueError("Verified nonempty broker account ID required")
    if directory is not None:
        root = Path(directory)
    elif os.environ.get("TRADING_ACCOUNT_LOCK_DIR"):
        root = Path(os.environ["TRADING_ACCOUNT_LOCK_DIR"])
    else:
        root = Path.home() / ".codex-trading" / "account-locks"
    key = f"{broker.lower()}:{account_id.strip()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return (root.expanduser().resolve() / f"account-{digest}.lock")


class AccountExecutionLease:
    """Hold one OS advisory lock until the entire live scheduler has stopped."""

    def __init__(
        self, broker: str, account_id: str, *, directory: str | Path | None = None
    ) -> None:
        self.path = account_lock_path(broker, account_id, directory=directory)
        self._guard = SchedulerLock(self.path)
        self._held = False

    def __enter__(self) -> "AccountExecutionLease":
        if self._held:
            raise RuntimeError("Account execution lease is already held")
        try:
            self._guard.__enter__()
        except (RuntimeError, OSError) as exc:
            raise RuntimeError(
                "Account execution already owned or ownership lock unavailable; "
                "LIVE scheduler cannot start"
            ) from exc
        self._held = True
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self._held:
            try:
                self._guard.__exit__(exc_type, exc, traceback)
            finally:
                self._held = False

    @property
    def held(self) -> bool:
        return self._held
