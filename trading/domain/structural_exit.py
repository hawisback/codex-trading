"""Strategy-independent adverse spot invalidation using supplied structure.

The candle/spot confirmation hierarchy remains deferred. This pure predicate
implements the current immediate breach check, not a new technical level.
"""

from __future__ import annotations

import math
from typing import Any


def existing_structural_breach(spot: Any, level: Any, direction: str) -> bool:
    if direction not in ("CE", "PE") or isinstance(spot, bool) or isinstance(level, bool):
        return False
    try:
        last = float(spot)
        threshold = float(level)
    except (TypeError, ValueError, OverflowError):
        return False
    if not all(math.isfinite(v) and v > 0 for v in (last, threshold)):
        return False
    return last <= threshold if direction == "CE" else last >= threshold
