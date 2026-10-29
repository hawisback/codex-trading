"""R02 OS-level broker/account process ownership, not wired to LIVE yet.

The existing SchedulerLock is a cross-process lease primitive. An adapter
can adopt this for a *single exclusive OMS session* after verifying its
broker and account; it must hold it until disarmed/closed. This class
makes no broker calls and must not be used as proof of account identity.
"""

import hashlib
from pathlib import Path

from execution_safety import SchedulerLock


def lease_path(state_directory: Path, broker: str, verified_account: str) -> Path:
    if (not isinstance(broker, str) or not broker.strip()
            or not isinstance(verified_account, str) or not verified_account.strip()):
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

    def __enter__(self):
        if self._held:
            raise RuntimeError("OMS account lease is already held")
        self._lease.__enter__()
        self._held = True
        return self

    def __exit__(self, *exc):
        try:
            if self._held:
                return self._lease.__exit__(*exc)
        finally:
            self._held = False
