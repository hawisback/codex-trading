"""Pure, bounded redaction for observational telemetry only.

The durable OMS evidence is never modified by this formatter. No credential,
account identifier, API token or cookie is emitted from a named field.
"""

from collections.abc import Mapping
from typing import Any

_SENSITIVE = (
    "api_key", "access_token", "api_secret", "secret_key", "token",
    "password", "passwd", "authorization", "credential", "cookie",
    "account_id", "client_id", "user_id", "session_key",
)


def redact_for_audit(value: Any, *, depth: int = 0) -> Any:
    if depth > 14:
        return "[NESTED_REDACTED]"
    if isinstance(value, Mapping):
        result = {}
        for key, item in value.items():
            name = str(key)
            if any(s in name.lower() for s in _SENSITIVE):
                result[name] = "[REDACTED]"
            else:
                result[name] = redact_for_audit(item, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [redact_for_audit(item, depth=depth + 1) for item in value[:1000]]
    if isinstance(value, str) and len(value) > 2048:
        return value[:2048] + "[TRUNCATED]"
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return "[UNSERIALIZABLE]"
