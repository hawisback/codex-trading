"""Read-only, typed trading-policy inspection.

This module is deliberately NOT wired into live configuration or order paths.
It reports code-observed policy precedence; it is not a replacement risk gate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
import re
from typing import Any, Mapping

from trading.domain.limits import (
    FEE_RESERVE,
    HARD_ENTRY_CUTOFF,
    HARD_SQUARE_OFF,
    LOT_SIZE,
    MAX_DAILY_ENTRIES,
    MAX_POSITION_QUANTITY,
)

_MISSING = object()
_TIME = re.compile(r"^(?:[01][0-9]|2[0-3]):[0-5][0-9]$")


@dataclass(frozen=True)
class PolicyObservation:
    """One source value, a known runtime rule, and limits on our confidence."""

    key: str
    configured: Any
    source: str
    runtime_rule: str
    runtime_source: str
    assessment: str


@dataclass(frozen=True)
class TradingPolicySnapshot:
    """Immutable inspection record; no broker/account access or live enforcement."""

    schema_version: int
    strategy_name: str
    strategy_source: str
    ai_mode: str
    ai_mode_source: str
    execution_broker: str
    execution_broker_source: str
    market_data_broker: str
    market_data_broker_source: str
    observations: tuple[PolicyObservation, ...]
    diagnostics: tuple[str, ...]
    inventory_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _freeze(value: Any) -> Any:
    """Detach nested JSON collections from the caller for immutable reports."""
    if isinstance(value, Mapping):
        return tuple((key, _freeze(item)) for key, item in sorted(value.items()))
    if isinstance(value, list):
        return tuple(_freeze(item) for item in value)
    return value


def _nested(config: Mapping[str, Any], path: str) -> tuple[Any, bool]:
    value: Any = config
    for part in path.split("."):
        if not isinstance(value, Mapping) or part not in value:
            return None, False
        value = value[part]
    return value, True


def _choose(
    cli_value: str | None,
    env_value: str | None,
    config_value: str | None,
    default: str,
    *,
    cli: str,
    env: str,
    file: str,
) -> tuple[str, str]:
    if cli_value:
        return cli_value, cli
    if env_value:
        return env_value, env
    if config_value:
        return config_value, file
    return default, "runtime default"


def _validate_scalar(key: str, value: Any, diagnostics: list[str]) -> None:
    if isinstance(value, bool):
        diagnostics.append(f"{key}: boolean is not a valid numeric quantity")
        return
    if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        diagnostics.append(f"{key}: expected a finite positive number")


def build_policy_snapshot(
    trading: Mapping[str, Any],
    strategies: Mapping[str, Any],
    *,
    strategy: str | None = None,
    ai_mode: str | None = None,
    execution_broker: str | None = None,
    market_data_broker: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> TradingPolicySnapshot:
    """Describe selected configuration and code-known guards without evaluating trades.

    The caller supplies already-parsed JSON; no files, imports of application
    services, environment mutation, or network operations occur here. Only a
    deliberate allowlist of nonsecret environment keys is considered.
    """
    env = {} if environ is None else environ
    diagnostics: list[str] = []
    ai_cfg = strategies.get("ai_consultation", {})
    profiles = strategies.get("strategies", {})
    if not isinstance(ai_cfg, Mapping):
        diagnostics.append("ai_consultation: expected object")
        ai_cfg = {}
    if not isinstance(profiles, Mapping):
        diagnostics.append("strategies: expected object")
        profiles = {}

    chosen_strategy, chosen_strategy_source = _choose(
        strategy,
        env.get("STRATEGY_MODE"),
        strategies.get("active_strategy"),
        "institutional_pullback",
        cli="--strategy",
        env="STRATEGY_MODE",
        file="config/strategies.json:active_strategy",
    )
    if chosen_strategy not in profiles:
        diagnostics.append(
            f"strategy {chosen_strategy!r} not found; runtime may fallback or reject based on request"
        )
    profile = profiles.get(chosen_strategy, {})
    if not isinstance(profile, Mapping):
        diagnostics.append("selected strategy profile: expected object")
        profile = {}
    compounding = profile.get("compounding", {})
    entry = profile.get("entry", {})
    if not isinstance(compounding, Mapping):
        diagnostics.append("selected compounding: expected object")
        compounding = {}
    if not isinstance(entry, Mapping):
        diagnostics.append("selected entry: expected object")
        entry = {}

    mode, mode_source = _choose(
        ai_mode,
        env.get("AI_CONSULTATION_MODE"),
        ai_cfg.get("default_mode"),
        "playbook",
        cli="--ai-mode",
        env="AI_CONSULTATION_MODE",
        file="config/strategies.json:ai_consultation.default_mode",
    )
    if mode not in ("rules", "playbook", "chat", "interactive"):
        diagnostics.append("ai_mode: unrecognized or disabled; actual scheduler may reject")
    broker, broker_source = _choose(
        execution_broker,
        env.get("EXECUTION_BROKER"),
        None,
        "proxy",
        cli="--broker",
        env="EXECUTION_BROKER",
        file="",
    )
    data_broker, data_source = _choose(
        market_data_broker,
        env.get("MARKET_DATA_BROKER"),
        None,
        "kite",
        cli="--market-data-broker",
        env="MARKET_DATA_BROKER",
        file="",
    )
    if broker not in ("proxy", "kite", "breeze"):
        diagnostics.append("execution_broker: invalid selection")
    if data_broker not in ("kite", "breeze"):
        diagnostics.append("market_data_broker: invalid selection")

    observations: list[PolicyObservation] = []

    def observe(key: str, *, rule: str, code: str, assessment: str) -> Any:
        value, exists = _nested(trading, key)
        observations.append(
            PolicyObservation(
                key=key,
                configured=_freeze(value),
                source=f"config/trading.json:{key}" if exists else "not configured",
                runtime_rule=rule,
                runtime_source=code,
                assessment=assessment,
            )
        )
        return value if exists else _MISSING

    cap = observe(
        "risk.max_order_quantity",
        rule="Strategy compounding max_order_quantity has truthy precedence; then trading risk cap, env MAX_ORDER_QUANTITY/default. Entry submission also limits to affordable quantity and MAX_POSITION_QUANTITY.",
        code="trading/domain/sizing.py; position_lifecycle.py:_submit_entry",
        assessment="Global value is NOT necessarily a universal hard ceiling.",
    )
    if cap is not _MISSING:
        _validate_scalar("risk.max_order_quantity", cap, diagnostics)
    strategy_cap = compounding.get("max_order_quantity")
    observations.append(
        PolicyObservation(
            "selected_strategy.compounding.max_order_quantity",
            _freeze(strategy_cap),
            f"config/strategies.json:strategies.{chosen_strategy}.compounding.max_order_quantity",
            f"Current strategy cap precedes trading risk cap; eventual global guard {MAX_POSITION_QUANTITY} contracts.",
            "trading/domain/sizing.py; position_lifecycle.py:_submit_entry",
            "This is a *potential upper bound*, not a promised order size.",
        )
    )
    if strategy_cap is not None:
        _validate_scalar("selected_strategy.compounding.max_order_quantity", strategy_cap, diagnostics)
    observations.append(
        PolicyObservation(
            "selected_strategy.entry.max_daily_entries",
            _freeze(entry.get("max_daily_entries")),
            f"config/strategies.json:strategies.{chosen_strategy}.entry.max_daily_entries",
            "Lifecycle entry gate uses this value, default 2; cycle workflow also checks a shared daily cap.",
            "position_lifecycle.py:_entry_limit_block; trading/application/workflows.py",
            "Per-strategy cap and shared cycle cap are both relevant.",
        )
    )
    if entry.get("max_daily_entries") is not None:
        _validate_scalar("selected_strategy.entry.max_daily_entries", entry["max_daily_entries"], diagnostics)
    observations.append(
        PolicyObservation(
            "selected_strategy.compounding.max_lots_cap",
            _freeze(compounding.get("max_lots_cap")),
            f"config/strategies.json:strategies.{chosen_strategy}.compounding.max_lots_cap",
            "Current sizing function uses the strategy compounding max_lots_cap.",
            "trading/domain/sizing.py:calculate_compounding_quantity",
            "Potential strategy preference, not guaranteed submitted lots.",
        )
    )
    if compounding.get("max_lots_cap") is not None:
        _validate_scalar(
            "selected_strategy.compounding.max_lots_cap", compounding["max_lots_cap"], diagnostics
        )
    observe(
        "risk.max_lots_per_trade",
        rule=f"Current sizing function uses strategy compounding.max_lots_cap, lot size {LOT_SIZE}; global lots setting is not referenced by that sizing calculation.",
        code="trading/domain/sizing.py:calculate_compounding_quantity",
        assessment="Not proof this key is unenforced on every other path.",
    )
    for key, code, rule in (
        (
            "risk.max_trades_per_day",
            "trading/application/workflows.py; trading/domain/limits.py",
            f"CycleWorkflow uses MAX_DAILY_ENTRIES={MAX_DAILY_ENTRIES}; lifecycle also applies strategy entry.max_daily_entries.",
        ),
        (
            "risk.account_equity",
            "position_lifecycle.py:_submit_entry",
            "Submission budget reads verified broker available_margin and subtracts the fee reserve.",
        ),
        (
            "risk.max_concurrent_positions",
            "position_lifecycle.py",
            "One-position gate is enforced through reconciliation and existing exposure checks.",
        ),
    ):
        val = observe(
            key,
            rule=rule,
            code=code,
            assessment="Configured setting is not necessarily the operative limit for this workflow.",
        )
        if key != "risk.account_equity" and val is not _MISSING:
            _validate_scalar(key, val, diagnostics)
    observations.append(
        PolicyObservation(
            "runtime.fee_reserve",
            FEE_RESERVE,
            "trading/domain/limits.py:FEE_RESERVE",
            f"Safe cash = verified available margin minus {FEE_RESERVE}, constrained by lot size {LOT_SIZE}.",
            "trading/domain/sizing.py; position_lifecycle.py",
            "Observed runtime constant, not a change proposal.",
        )
    )

    entry_after = observe(
        "session.no_new_trade_after",
        rule=f"Submission checks HARD_ENTRY_CUTOFF={HARD_ENTRY_CUTOFF}; active LIVE guard takes min(configured cutoff, hard cutoff), plus MarketClock's 14:15 trap gate.",
        code="position_lifecycle.py:_submit_entry; market_clock.py:is_new_trade_allowed",
        assessment="JSON's later time does not relax the hard runtime cutoff.",
    )
    before = observe(
        "session.no_new_trade_before",
        rule="EntryWorkflow and live submission use the configured opening gate with a 09:20 fallback.",
        code="trading/application/entry.py; position_lifecycle.py",
        assessment="Session boundaries depend on selected mode and call path.",
    )
    force_exit = observe(
        "session.force_exit_time",
        rule=f"Position monitoring and scheduler use HARD_SQUARE_OFF={HARD_SQUARE_OFF}; actual fill cannot be guaranteed on broker outage.",
        code="position_lifecycle.py; nifty_trader_scheduler.py",
        assessment="The configured later time does not guarantee later exposure is allowed.",
    )
    for key, value in (
        ("session.no_new_trade_before", before),
        ("session.no_new_trade_after", entry_after),
        ("session.force_exit_time", force_exit),
    ):
        if value is not _MISSING and (not isinstance(value, str) or not _TIME.fullmatch(value)):
            diagnostics.append(f"{key}: expected HH:MM string")

    premium = observe(
        "option_selection.max_option_premium",
        rule="Selection reads configured cap (fallback 185 for candidate); EntryPolicy.from_config reads configured cap (fallback 70).",
        code="trading/application/selection.py; entry_policy.py:EntryPolicy.from_config",
        assessment="Different defaults are not active if valid config provides a cap.",
    )
    if premium is not _MISSING:
        _validate_scalar("option_selection.max_option_premium", premium, diagnostics)
    holidays = observe(
        "option_selection.exchange_holidays",
        rule="Calendar input is read by strategy/market-data code; contract master still resolves actual supported expiries.",
        code="nifty_trader_scheduler.py; trading/adapters/market_sources.py",
        assessment="Holiday source and expiry correctness require separate audit.",
    )
    if holidays is not _MISSING and (
        not isinstance(holidays, list)
        or any(not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) for day in holidays)
    ):
        diagnostics.append("option_selection.exchange_holidays: expected list of YYYY-MM-DD strings")
    for key in ("mode", "auto_trade_enabled", "system_armed", "kill_switch"):
        flag = observe(
            key,
            rule="These JSON fields are NOT proof that the native gateway is armed; native CLI requires --live, then verified account/mode authorization.",
            code="trading/application/scheduler.py; trading/adapters/gateways/base.py",
            assessment="Observed configured flag only; not a read of the broker's actual mode.",
        )
        if key == "mode" and flag is not _MISSING and flag not in ("LIVE", "PAPER"):
            diagnostics.append("mode: expected LIVE or PAPER string")
        elif key != "mode" and flag is not _MISSING and type(flag) is not bool:
            diagnostics.append(f"{key}: expected boolean")

    observation_data = [asdict(o) for o in observations]
    digest = hashlib.sha256(
        json.dumps(
            {
                "strategy": chosen_strategy,
                "ai_mode": mode,
                "execution_broker": broker,
                "market_data_broker": data_broker,
                "observations": observation_data,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return TradingPolicySnapshot(
        schema_version=1,
        strategy_name=chosen_strategy,
        strategy_source=chosen_strategy_source,
        ai_mode=mode,
        ai_mode_source=mode_source,
        execution_broker=broker,
        execution_broker_source=broker_source,
        market_data_broker=data_broker,
        market_data_broker_source=data_source,
        observations=tuple(observations),
        diagnostics=tuple(diagnostics),
        inventory_sha256=digest,
    )
