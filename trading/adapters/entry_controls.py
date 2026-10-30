"""Read operator entry controls without changing active position policy."""

import json
from pathlib import Path

from trading.domain.pretrade_evidence import entry_control_block


def read_entry_control_block(path):
    """Fresh read for each entry check; invalid/unavailable config fails closed."""
    try:
        return entry_control_block(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError, UnicodeError):
        return "ENTRY_CONTROLS_UNAVAILABLE"
