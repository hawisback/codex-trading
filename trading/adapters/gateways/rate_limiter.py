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

    def acquire(self, tokens: float = 1.0, timeout: float | None = 10.0) -> bool:
        """Block until the requested tokens are available, or until timeout.

        Returns:
            True if tokens were acquired, False if timeout occurred.
        """
        start_time = time.monotonic()
        if tokens <= 0 or tokens > self.capacity:
            raise ValueError("Token request must fit the bucket")
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self.last_update
                self.last_update = now
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

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
        with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.last_update = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False
