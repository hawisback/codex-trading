"""Thread-safe Token Bucket Rate Limiter for Broker APIs.

Paces requests within this client; other clients can still consume broker quota.
"""

import time
import threading
import math


class TokenBucketRateLimiter:
    """Thread-safe token bucket rate limiter.

    Args:
        rate: Number of tokens added per second (e.g., 5.0 for 5 req/s).
        capacity: Maximum number of tokens that can accumulate (burst limit).
    """

    def __init__(self, rate: float = 5.0, capacity: float = 5.0):
        self.rate = float(rate)
        self.capacity = float(capacity)
        if (
            not math.isfinite(self.rate)
            or not math.isfinite(self.capacity)
            or self.rate <= 0
            or self.capacity < 1
        ):
            raise ValueError("Rate must be positive and capacity at least one")
        self.tokens = float(capacity)
        self.last_update = time.monotonic()
        self._lock = threading.Lock()

    def _validate_tokens(self, tokens: float) -> None:
        """Reject malformed requests before touching the shared bucket."""
        if (
            isinstance(tokens, bool)
            or not isinstance(tokens, (int, float))
            or not math.isfinite(tokens)
            or tokens <= 0
            or tokens > self.capacity
        ):
            raise ValueError("Token request must be finite, positive and fit the bucket")

    def _refill_locked(self) -> None:
        """Refill conservatively; callers must hold ``self._lock``."""
        now = time.monotonic()
        elapsed = max(0.0, now - self.last_update)
        self.last_update = max(self.last_update, now)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

    def acquire(self, tokens: float = 1.0, timeout: float | None = 10.0) -> bool:
        """Block until the requested tokens are available, or until timeout.

        Returns:
            True if tokens were acquired, False if timeout occurred.
        """
        self._validate_tokens(tokens)
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or timeout < 0
        ):
            raise ValueError("Timeout must be finite and non-negative")
        start_time = time.monotonic()
        while True:
            with self._lock:
                self._refill_locked()

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

                missing = tokens - self.tokens
                wait_time = missing / self.rate

            if timeout is not None:
                remaining_timeout = timeout - (time.monotonic() - start_time)
                if remaining_timeout <= 0:
                    return False
                sleep_sec = min(wait_time, remaining_timeout)
            else:
                sleep_sec = wait_time

            time.sleep(max(0.01, min(sleep_sec, 0.2)))

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Non-blocking attempt to acquire tokens.

        Returns:
            True if tokens were acquired, False otherwise.
        """
        self._validate_tokens(tokens)
        with self._lock:
            self._refill_locked()

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
