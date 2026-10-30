"""Typed configuration assembly retaining existing values, precedence and fallbacks."""

from dataclasses import dataclass
import json
import logging
import math
import os
from pathlib import Path
from typing import Any, Mapping
from ai_opportunity_radar import AIOpportunityRadar
from trading.domain.volatility import validate_vix_policy
from trading.domain.stop_loss import configured_stop_policy
from trading.strategies.macd_momentum import MacdMomentumStrategy
from trading.domain.trailing import validate_session_trailing

logger = logging.getLogger("NiftyAI")


def validate_trailing_configuration(strategy: Mapping[str, Any]) -> None:
    cfg = strategy.get("exit", {})
    validate_session_trailing(cfg)
    validate_vix_policy(cfg)
    configured_stop_policy(strategy)
    for key, default in (
        ("stop_confirmation_timeout_sec", 10),
        ("monitor_quote_max_age_sec", 2),
        ("monitor_quote_timeout_sec", 1.5),
        ("stop_min_improvement_points", 0.5),
    ):
        value = float(cfg.get(key, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"Invalid trailing setting: {key}")
    if cfg.get("aggressive_trail_enabled", False):
        normal = float(cfg.get("trail_pullback_pct", cfg.get("peak_pullback_pct", 10)))
        aggressive = float(cfg.get("aggressive_trail_pullback_pct", 5))
        activation = float(cfg.get("aggressive_trail_activation_pct", 50))
        if not (
            0 < aggressive <= normal < 100
            and math.isfinite(activation)
            and activation >= float(cfg.get("runner_activation_pct", 20))
        ):
            raise ValueError("Aggressive trailing must tighten the normal pullback after runner activation")


@dataclass(frozen=True)
class RuntimeConfiguration:
    strategy_name: str
    strategy: dict[str, Any]
    trading: dict[str, Any]
    ai_mode: str
    ai_timeout: int


def load_configuration(
    strategy_name: str | None = None,
    ai_mode: str | None = None,
    *,
    root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfiguration:
    root = Path(".") if root is None else Path(root)
    environ = os.environ if environ is None else environ
    cfg_file = root / "config/strategies.json"
    ai_cfg = {}
    if cfg_file.exists():
        with open(cfg_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        ai_cfg = data.get("ai_consultation", {})
        mode = (
            strategy_name
            or environ.get("STRATEGY_MODE")
            or data.get("active_strategy", "institutional_pullback")
        )
        if mode in data.get("strategies", {}):
            strategy_mode = mode
            strategy_cfg = data["strategies"][mode]
            logger.info(f"Loaded Strategy Profile: {strategy_cfg.get('display_name')} ({mode})")
        else:
            strategy_mode = "institutional_pullback"
            strategy_cfg = data.get("strategies", {}).get("institutional_pullback", {})
    else:
        strategy_mode = "institutional_pullback"
        strategy_cfg = {
            "display_name": "Strategy 3: Institutional Pullback & ITM",
            "entry": {
                "require_pullback": True,
                "pullback_ema_tolerance_pts": 4.0,
                "require_range_box_filter": True,
                "range_box_spread_min": 28.0,
                "value_proximity_pts": 24.0,
                "strike_selection": "STRICT_ITM",
                "prevent_v_reversal_counter_trades": True,
            },
            "exit": {
                "max_hold_seconds": 21600,
                "initial_stop_pct": 30.0,
                "target_pct": 50.0,
                "structural_stops_enabled": True,
                "vwap_stop_buffer": 15.0,
                "ema20_stop": True,
                "runner_trailing_enabled": True,
                "runner_activation_pct": 15.0,
                "ema9_trailing_buffer": 4.0,
                "peak_pullback_pct": 10.0,
                "lock_breakeven_on_runner": True,
                "late_day_micro_trail_enabled": True,
                "late_day_micro_trail_time": "14:00",
                "late_day_micro_trail_activation_pct": 4.0,
                "late_day_micro_trail_floor_pct": 1.0,
                "morning_micro_trail_enabled": True,
                "morning_micro_trail_start": "09:15",
                "morning_micro_trail_end": "09:45",
                "morning_micro_trail_activation_pct": 10.0,
                "morning_micro_trail_floor_pct": 1.0,
                "morning_micro_trail_first_trade_only": True,
            },
        }

    # Load trading config (for session parameters, risk thresholds, etc.)
    trading_cfg_file = root / "config/trading.json"
    if trading_cfg_file.exists():
        try:
            with open(trading_cfg_file, "r", encoding="utf-8") as f:
                trading_cfg = json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config/trading.json: {e}")
            trading_cfg = {}
    else:
        trading_cfg = {}

    selected_ai_mode = (
        ai_mode or environ.get("AI_CONSULTATION_MODE") or ai_cfg.get("default_mode", "playbook")
    )
    ai_timeout = int(ai_cfg.get("timeout_seconds", 45))
    if str(selected_ai_mode).lower() == "disabled":
        raise ValueError("AI consultation cannot be disabled for the scheduler")
    if (
        strategy_name or environ.get("STRATEGY_MODE")
    ) == "macd_momentum" and strategy_mode != "macd_momentum":
        raise ValueError("The requested macd_momentum profile is missing; refusing another strategy")
    validate_trailing_configuration(strategy_cfg)
    if strategy_mode == "macd_momentum":
        MacdMomentumStrategy(strategy_cfg)  # Validate entry settings before arming the scheduler.
    return RuntimeConfiguration(strategy_mode, strategy_cfg, trading_cfg, selected_ai_mode, ai_timeout)


def build_radar(strategy_cfg: dict[str, Any]) -> AIOpportunityRadar:
    entry_cfg = strategy_cfg.get("entry", {})
    return AIOpportunityRadar(
        enable_climax_spring=entry_cfg.get("enable_climax_spring", True),
        climax_open_dist_min=float(entry_cfg.get("climax_open_dist_min", 75.0)),
        climax_vwap_dist_min=float(entry_cfg.get("climax_vwap_dist_min", 40.0)),
        climax_rsi_extreme=float(entry_cfg.get("climax_rsi_extreme", 32.0)),
        climax_impulse_delta_min=float(entry_cfg.get("climax_impulse_delta_min", 18.0)),
        climax_window_max_bar=int(entry_cfg.get("climax_window_max_bar", 120)),
        pullback_ema_tolerance_pts=float(entry_cfg.get("pullback_ema_tolerance_pts", 4.0)),
        value_proximity_pts=float(entry_cfg.get("value_proximity_pts", 24.0)),
        range_box_spread_min=float(entry_cfg.get("range_box_spread_min", 28.0)),
    )
