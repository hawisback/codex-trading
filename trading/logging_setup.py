"""One bounded background writer for runtime logs and observational audit events."""

import atexit
import copy
import logging
from pathlib import Path
import queue
import sys
import threading
import time
import uuid

from trading.adapters.daily_logs import DailyJournalHandler, DailyRuntimeHandler, ISTFormatter


class QueuedHandler(logging.Handler):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner

    def emit(self, record):
        self.owner.enqueue(record)


class LoggingSession:
    def __init__(self, directory, *, console=None, queue_size=8192):
        self.run_id = uuid.uuid4().hex
        self.queue: queue.Queue[logging.LogRecord] = queue.Queue(maxsize=queue_size)
        self.dropped = 0
        self.failures = 0
        self._last_warning = float("-inf")
        self._state_lock = threading.Lock()
        self._stop = threading.Event()
        self._closed = False
        self._previous_handlers = None
        self._previous_level = logging.NOTSET
        runtime = DailyRuntimeHandler(directory)
        formatter = ISTFormatter(
            "%(asctime)s [%(process)d] [%(levelname)s] [%(name)s] [run=%(run_id)s] %(message)s"
        )
        runtime.setFormatter(formatter)
        self.handlers = [runtime, DailyJournalHandler(directory)]
        if console is not None:
            stream = logging.StreamHandler(console)
            stream.setFormatter(formatter)
            self.handlers.append(stream)
        self.handler = QueuedHandler(self)
        self.worker = threading.Thread(target=self._run, name="daily-log-writer", daemon=True)
        self.worker.start()

    def _warn(self, message, *, force=False):
        now = time.monotonic()
        if force or now - self._last_warning >= 10:
            self._last_warning = now
            try:
                sys.stderr.write(
                    f"[LOGGING WARNING] {message}; dropped={self.dropped} failures={self.failures}\n"
                )
            except Exception:
                pass

    def enqueue(self, record):
        try:
            with self._state_lock:
                if self._closed:
                    return
                item = copy.copy(record)
                item.run_id = self.run_id
                self.queue.put_nowait(item)
        except queue.Full:
            self.dropped += 1
            self._warn("background queue full; record not persisted")
        except Exception as exc:
            self.failures += 1
            self._warn(str(exc))

    def _run(self):
        while not self._stop.is_set() or not self.queue.empty():
            try:
                record = self.queue.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                for handler in self.handlers:
                    try:
                        handler.handle(record)
                    except Exception as exc:
                        self.failures += 1
                        self._warn(f"{type(handler).__name__}: {exc}")
            finally:
                self.queue.task_done()
        for handler in self.handlers:
            try:
                handler.close()
            except Exception:
                pass

    def install(self):
        root = logging.getLogger()
        self._previous_handlers = root.handlers[:]
        self._previous_level = root.level
        root.handlers = [self.handler]
        root.setLevel(logging.INFO)
        atexit.register(self.close)
        return self

    def close(self, timeout=5):
        with self._state_lock:
            if not self._closed:
                self._closed = True
                if self._previous_handlers is not None:
                    root = logging.getLogger()
                    root.handlers = self._previous_handlers
                    root.setLevel(self._previous_level)
                self._stop.set()
        self.worker.join(timeout)
        if self.worker.is_alive():
            self._warn(f"shutdown drain incomplete; {self.queue.qsize()} records pending", force=True)
        atexit.unregister(self.close)
        return not self.worker.is_alive()


def configure_logging(directory: Path, *, console=None):
    return LoggingSession(directory, console=console).install()
