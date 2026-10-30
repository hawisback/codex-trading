"""OS-level broker/account ownership used by native LIVE gateways.

The existing SchedulerLock is a cross-process lease primitive. An adapter
can adopt this for a *single exclusive OMS session* after verifying its
broker and account; it retains the lease through disarming until process exit. This class
makes no broker calls and must not be used as proof of account identity.
"""

import hashlib
import os
from pathlib import Path

from execution_safety import SchedulerLock


def lease_path(state_directory: Path, broker: str, verified_account: str) -> Path:
    if (
        not isinstance(broker, str)
        or not broker.strip()
        or not isinstance(verified_account, str)
        or not verified_account.strip()
    ):
        raise ValueError("Verified broker and account are required for OMS lease")
    digest = hashlib.sha256(
        (broker.strip().lower() + ":" + verified_account.strip()).encode("utf-8")
    ).hexdigest()[:24]
    return Path(state_directory).resolve() / ("oms-account-" + digest + ".lock")


class AccountSessionLease:
    """Explicit lifecycle wrapper; no implicit activation on import/construction."""

    def __init__(self, state_directory: Path, *, broker: str, verified_account: str):
        self.path = lease_path(state_directory, broker, verified_account)
        self._lease = SchedulerLock(self.path)
        self._held = False
        self._owner_pid: int | None = None

    def owns_current_process(self):
        """A path held by another instance or an inherited child is not ownership."""
        return (
            self._held
            and self._owner_pid == os.getpid()
            and self._lease.stream is not None
            and not self._lease.stream.closed
            and SchedulerLock.is_held(self.path)
        )

    def __enter__(self):
        if self._held:
            raise RuntimeError("OMS account lease is already held")
        self._lease.__enter__()
        self._held = True
        self._owner_pid = os.getpid()
        return self

    def __exit__(self, *exc):
        if self._held and self._owner_pid != os.getpid():
            raise RuntimeError("Cannot release another process's OMS lease")
        try:
            if self._held:
                return self._lease.__exit__(*exc)
        finally:
            self._held = False
            self._owner_pid = None
