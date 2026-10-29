"""Names for persisted position phases; unknown legacy strings stay unmodified."""

from enum import Enum
from typing import Any, Mapping


class PositionStatus(str, Enum):
    ENTRY_PENDING = "ENTRY_PENDING"
    OPEN = "OPEN"
    EXIT_PENDING = "EXIT_PENDING"
    EXIT_UNKNOWN = "EXIT_UNKNOWN"

    def __str__(self) -> str:
        return self.value


def is_exiting(position: Mapping[str, Any]) -> bool:
    return position.get("status") in (PositionStatus.EXIT_PENDING.value, PositionStatus.EXIT_UNKNOWN.value)
