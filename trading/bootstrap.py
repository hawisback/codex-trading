"""Explicit process setup. Importing this module does not read files or change streams."""

import os
from pathlib import Path
import sys
import threading

_environment_lock = threading.RLock()
_loaded_environment_paths: set[Path] = set()


def load_environment_file(filepath=".env"):
    """Retain the original dotenv parsing and process-environment precedence."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as stream:
            for line in stream:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def ensure_environment(filepath=".env"):
    path = Path(filepath).absolute()
    with _environment_lock:
        if path not in _loaded_environment_paths:
            load_environment_file(filepath)
            force_ipv4()
            _loaded_environment_paths.add(path)


def configure_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8")
        except Exception:
            pass


def force_ipv4():
    """Ensure all outbound network requests use IPv4 (AF_INET) to match broker static IP whitelists."""
    import socket

    if getattr(socket, "_ipv4_forced", False):
        return
    orig_getaddrinfo = socket.getaddrinfo

    def getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
        return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

    socket.getaddrinfo = getaddrinfo_ipv4_only
    setattr(socket, "_ipv4_forced", True)
