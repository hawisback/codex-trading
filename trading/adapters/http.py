"""Standard-library JSON HTTP adapter preserving the existing retry semantics."""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable


class JsonHttpTransport:
    def __init__(self, *, opener=None, sleeper=None, monotonic=None, logger=None):
        self._opener = opener
        self._sleeper = sleeper
        self._monotonic = monotonic
        self.logger = logger if logger is not None else logging.getLogger("AIExecutionClient")

    def request(
        self,
        method: str,
        url: str,
        payload: dict | None = None,
        *,
        headers: dict[str, str],
        timeout: float,
        retry_reads: bool,
        deadline: Callable[[], float | None],
        log_path: str,
    ) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        attempts = 2 if method == "GET" and retry_reads else 1
        for attempt in range(attempts):
            request_timeout = timeout
            read_deadline = deadline() if method == "GET" else None
            if read_deadline:
                available = read_deadline - (self._monotonic or time.monotonic)()
                if available <= 0:
                    return {"error": True, "detail": "READ_BUDGET_EXHAUSTED"}
                request_timeout = min(timeout, available)
            try:
                with (self._opener or urllib.request.urlopen)(req, timeout=request_timeout) as resp:
                    body = resp.read().decode("utf-8")
                    return json.loads(body) if body else {"status": resp.status}
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8")
                try:
                    raw = json.loads(body)
                except ValueError:
                    raw = {}
                if not isinstance(raw, dict):
                    raw = {}
                self.logger.error("HTTP %s on %s %s: %s", exc.code, method, log_path, body)
                return {
                    "error": True,
                    "code": exc.code,
                    "detail": raw.get("detail", body),
                    "raw": raw,
                    "outcome_unknown": method != "GET" and (exc.code >= 500 or exc.code == 408),
                }
            except Exception as exc:
                reason = getattr(exc, "reason", exc)
                timed_out = isinstance(reason, TimeoutError)
                if timed_out and attempt + 1 < attempts:
                    (self._sleeper or time.sleep)(0.5)
                    continue
                self.logger.error("Network/response error on %s %s: %s", method, log_path, exc)
                return {"error": True, "detail": str(exc), "outcome_unknown": method != "GET"}
