"""Shared runner price calculation; exchange state belongs to the OMS."""

from typing import Any, Mapping

from trading.domain.prices import round_tick
from trading.domain.market_data import number


def validate_session_trailing(config: Mapping[str, Any]) -> None:
    """Reject malformed session risk settings before scheduler startup."""

    def setting(key, default, *, minimum=None):
        value = config.get(key, default)
        if not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be numeric")
        return number(value, minimum=minimum)

    windows = []
    for prefix, flag, start, end in (
        ("morning_progressive_trail", "morning_progressive_trail_enabled", "09:15", "11:30"),
        ("midday_micro_trail", "midday_micro_trail_enabled", "11:30", "13:15"),
    ):
        enabled = config.get(flag, False)
        if not isinstance(enabled, bool):
            raise ValueError(f"{flag} must be a boolean")
        if not enabled:
            continue
        times = [config.get(prefix + "_start", start), config.get(prefix + "_end", end)]
        for value in times:
            if (
                not isinstance(value, str)
                or len(value) != 5
                or value[2] != ":"
                or not value[:2].isdigit()
                or not value[3:].isdigit()
                or int(value[:2]) > 23
                or int(value[3:]) > 59
            ):
                raise ValueError(f"Invalid {prefix} time")
        if not "09:15" <= times[0] < times[1] <= "15:15":
            raise ValueError(f"Invalid {prefix} window")
        windows.append(times)
    if len(windows) == 2 and windows[0][1] > windows[1][0]:
        raise ValueError("Session trailing windows must not overlap")
    if config.get("morning_progressive_trail_enabled", False):
        acts = [
            setting(k, d, minimum=0.01)
            for k, d in (
                ("morning_soft_sl_activation_pct", 8),
                ("morning_be_activation_pct", 12),
                ("morning_runner_activation_pct", 18),
            )
        ]
        floors = [
            setting(k, d)
            for k, d in (
                ("morning_soft_sl_floor_pct", -8),
                ("morning_be_floor_pct", 1),
                ("morning_runner_floor_pct", 10),
            )
        ]
        pullback = setting("morning_runner_pullback_pct", 8, minimum=0.01)
        if not (
            acts[0] < acts[1] < acts[2]
            and -100 < floors[0] <= floors[1] <= floors[2]
            and all(f < a for f, a in zip(floors, acts))
            and pullback < 100
        ):
            raise ValueError("Invalid morning progressive trailing stages")
    if config.get("midday_micro_trail_enabled", False):
        activation = setting("midday_micro_trail_activation_pct", 5, minimum=0.01)
        floor = setting("midday_micro_trail_floor_pct", 1.5, minimum=0)
        pullback = setting("midday_micro_trail_pullback_pct", 2.5, minimum=0.01)
        if not floor < activation or pullback >= 100:
            raise ValueError("Invalid midday micro trailing settings")


def session_trigger(entry: float, peak: float, config: Mapping[str, Any], now_time: str):
    """Return (active window, optional stop, label); windows are [start, end)."""
    gain = (peak / entry - 1) * 100 if entry > 0 else 0
    if config.get("morning_progressive_trail_enabled", False) and config.get(
        "morning_progressive_trail_start", "09:15"
    ) <= now_time < config.get("morning_progressive_trail_end", "11:30"):
        label = "MORNING PROGRESSIVE TRAIL"
        if gain + 1e-9 < config.get("morning_soft_sl_activation_pct", 8):
            return True, None, label
        floor = entry * (1 + config.get("morning_soft_sl_floor_pct", -8) / 100)
        if gain + 1e-9 >= config.get("morning_be_activation_pct", 12):
            floor = max(floor, entry * (1 + config.get("morning_be_floor_pct", 1) / 100))
        if gain + 1e-9 >= config.get("morning_runner_activation_pct", 18):
            floor = max(
                floor,
                entry * (1 + config.get("morning_runner_floor_pct", 10) / 100),
                peak * (1 - config.get("morning_runner_pullback_pct", 8) / 100),
            )
            # Keep stronger high-profit tiers and aggressive runner protection.
            if config.get("runner_trailing_enabled", True):
                morning_config = dict(config, trail_pullback_pct=config.get("morning_runner_pullback_pct", 8))
                floor = max(floor, runner_trigger(entry, peak, morning_config))
        return True, round_tick(floor), label
    if config.get("midday_micro_trail_enabled", False) and config.get(
        "midday_micro_trail_start", "11:30"
    ) <= now_time < config.get("midday_micro_trail_end", "13:15"):
        label = "MIDDAY MICRO-TRAIL"
        if gain + 1e-9 < config.get("midday_micro_trail_activation_pct", 5):
            return True, None, label
        floor = max(
            entry * (1 + config.get("midday_micro_trail_floor_pct", 1.5) / 100),
            peak * (1 - config.get("midday_micro_trail_pullback_pct", 2.5) / 100),
        )
        if config.get("runner_trailing_enabled", True) and gain + 1e-9 >= config.get(
            "runner_activation_pct", 15
        ):
            floor = max(floor, runner_trigger(entry, peak, config))
        return True, round_tick(floor), label
    return False, None, ""


def runner_trigger(entry: float, peak: float, config: Mapping[str, Any]) -> float:
    gain = (peak / entry - 1) * 100
    floor_pct = 0.0
    for tier in sorted(
        config.get(
            "progressive_floor_tiers",
            [
                {"gain_pct": 20, "floor_pct": 10},
                {"gain_pct": 30, "floor_pct": 20},
                {"gain_pct": 40, "floor_pct": 30},
            ],
        ),
        key=lambda tier: tier["gain_pct"],
        reverse=True,
    ):
        if gain + 1e-9 >= tier["gain_pct"]:
            floor_pct = tier["floor_pct"]
            break
    pullback = config.get("trail_pullback_pct", config.get("peak_pullback_pct", 10.0))
    if config.get("aggressive_trail_enabled", False) and gain + 1e-9 >= config.get(
        "aggressive_trail_activation_pct", 50.0
    ):
        pullback = config.get("aggressive_trail_pullback_pct", 5.0)
    return round_tick(max(entry * (1 + floor_pct / 100), peak * (1 - pullback / 100)))
