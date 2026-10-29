#!/usr/bin/env python3
"""
NIFTY Options Backtesting Engine
Supports three distinct, named strategies controlled via config:
1. "legacy_scalper": Strategy 1 - Original scalper with 6-minute (360s) stopwatch exit & % stops.
2. "structural_runner": Strategy 2 - Current structural model with Range Box, VWAP/EMA20 stops, and 5m EMA9 trailing runner.
3. "institutional_pullback": Strategy 3 - Advanced structural model with true pullback-to-EMA9 confirmation, strict ITM selection, and V-reversal filters.
"""

import os
import sys
import json
import math
import sqlite3
import argparse
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
from ai_context_dossier import generate_market_dossier
from trading.domain.indicators import exponential_average, simple_rsi, select_strike
from trading.domain.trailing import runner_trigger


HISTORICAL_DB_PATH = r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db"


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bsm_price(spot: float, strike: float, days_to_expiry: float,
              r: float = 0.065, sigma: float = 0.135, is_call: bool = True) -> float:
    """Black-Scholes option pricing model calibrated for NIFTY weekly options."""
    T = max(0.0001, days_to_expiry / 365.0)
    if T <= 0.0002:
        return max(0.05, (spot - strike) if is_call else (strike - spot))
    d1 = (math.log(spot / strike) + (r + 0.5 * (sigma ** 2)) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if is_call:
        price = spot * norm_cdf(d1) - strike * math.exp(-r * T) * norm_cdf(d2)
    else:
        price = strike * math.exp(-r * T) * norm_cdf(-d2) - spot * norm_cdf(-d1)
    return max(0.05, round(price, 2))


@dataclass
class Trade:
    trade_id: int
    symbol: str
    direction: str  # "CE" or "PE"
    strike: int
    entry_bar: int
    entry_time: str
    entry_price: float
    quantity: int = 65
    exit_bar: Optional[int] = None
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    peak_price: float = 0.0
    peak_gain_pct: float = 0.0
    runner_active: bool = False

    def morning_trail_floor(self, cfg: "StrategyConfig") -> float:
        return max(
            self.entry_price * (1.0 + cfg.morning_micro_trail_floor_pct / 100.0),
            self.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0),
        )

    def close(self, exit_bar: int, exit_time: str, exit_price: float, reason: str):
        self.exit_bar = exit_bar
        self.exit_time = exit_time
        self.exit_price = round(exit_price, 2)
        self.exit_reason = reason
        self.pnl = round((self.exit_price - self.entry_price) * self.quantity, 2)
        self.pnl_pct = round(((self.exit_price - self.entry_price) / self.entry_price) * 100, 2)

    @property
    def hold_minutes(self) -> int:
        if self.exit_bar is not None:
            return self.exit_bar - self.entry_bar
        return 0


@dataclass
class StrategyConfig:
    key: str = "institutional_pullback"
    name: str = "Strategy 3: Institutional Pullback & ITM"
    # Entry Rules
    require_pullback: bool = True
    pullback_ema_tolerance_pts: float = 4.0
    enable_range_box_filter: bool = True
    range_box_spread_min: float = 28.0
    value_proximity_pts: float = 24.0
    strike_selection: str = "STRICT_ITM"  # "STRICT_ITM" or "ATM_ROUNDED"
    prevent_v_reversal_counter_trades: bool = True
    max_daily_entries: int = 999
    min_spacing_bars: int = 10

    # Exit & Risk Rules
    initial_stop_pct: float = 30.0
    target_pct: float = 50.0
    profit_target_enabled: bool = True
    aggressive_trail_enabled: bool = False
    aggressive_trail_activation_pct: float = 50.0
    aggressive_trail_pullback_pct: float = 5.0
    max_hold_minutes: int = 360  # 6 for legacy_scalper

    # Structural Stops
    enable_structural_stops: bool = True
    vwap_stop_buffer: float = 15.0
    ema20_stop: bool = True

    # Dynamic Trailing Runner
    enable_runner_trailing: bool = True
    runner_activation_pct: float = 20.0
    ema9_trailing_buffer: float = 4.0
    peak_pullback_pct: float = 10.0
    lock_breakeven_on_runner: bool = True
    late_day_micro_trail_enabled: bool = False
    late_day_micro_trail_bar: int = 285
    late_day_micro_trail_activation_pct: float = 4.0
    late_day_micro_trail_floor_pct: float = 1.0
    morning_micro_trail_enabled: bool = False
    morning_micro_trail_start_bar: int = 0
    morning_micro_trail_end_bar: int = 30
    morning_micro_trail_activation_pct: float = 10.0
    morning_micro_trail_floor_pct: float = 1.0
    morning_micro_trail_first_trade_only: bool = True

    # Climax Spring & Structural Wick Stop
    enable_climax_spring: bool = False
    climax_open_dist_min: float = 75.0
    climax_vwap_dist_min: float = 40.0
    climax_rsi_extreme: float = 32.0
    climax_impulse_delta_min: float = 18.0
    climax_window_max_bar: int = 120
    enable_structural_wick_stop: bool = False


    @classmethod
    def load_from_config(cls, strategy_key: str, config_path: str = "config/strategies.json") -> "StrategyConfig":
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            strat = data.get("strategies", {}).get(strategy_key)
            if strat:
                entry = strat.get("entry", {})
                exit_c = strat.get("exit", {})
                return cls(
                    key=strategy_key,
                    name=strat.get("display_name", strategy_key),
                    require_pullback=entry.get("require_pullback", False),
                    pullback_ema_tolerance_pts=entry.get("pullback_ema_tolerance_pts", 4.0),
                    enable_range_box_filter=entry.get("require_range_box_filter", False),
                    range_box_spread_min=entry.get("range_box_spread_min", 28.0),
                    value_proximity_pts=entry.get("value_proximity_pts", 24.0),
                    strike_selection=entry.get("strike_selection", "ATM_ROUNDED"),
                    prevent_v_reversal_counter_trades=entry.get("prevent_v_reversal_counter_trades", False),
                    min_spacing_bars=entry.get("min_spacing_bars", 10),
                    max_daily_entries=entry.get("max_daily_entries", 999),
                    max_hold_minutes=exit_c.get("max_hold_seconds", 21600) // 60,
                    initial_stop_pct=exit_c.get("initial_stop_pct", 30.0),
                    target_pct=exit_c.get("target_pct", 50.0),
                    profit_target_enabled=exit_c.get("profit_target_enabled", True),
                    aggressive_trail_enabled=exit_c.get("aggressive_trail_enabled", False),
                    aggressive_trail_activation_pct=exit_c.get("aggressive_trail_activation_pct", 50.0),
                    aggressive_trail_pullback_pct=exit_c.get("aggressive_trail_pullback_pct", 5.0),
                    enable_structural_stops=exit_c.get("structural_stops_enabled", True),
                    vwap_stop_buffer=exit_c.get("vwap_stop_buffer", 15.0),
                    ema20_stop=exit_c.get("ema20_stop", True),
                    enable_runner_trailing=exit_c.get("runner_trailing_enabled", True),
                    runner_activation_pct=exit_c.get("runner_activation_pct", 15.0),
                    ema9_trailing_buffer=exit_c.get("ema9_trailing_buffer", 4.0),
                    peak_pullback_pct=exit_c.get("trail_pullback_pct", exit_c.get("peak_pullback_pct", 10.0)),
                    lock_breakeven_on_runner=exit_c.get("lock_breakeven_on_runner", True),
                    late_day_micro_trail_enabled=exit_c.get("late_day_micro_trail_enabled", False),
                    late_day_micro_trail_bar=285,
                    late_day_micro_trail_activation_pct=exit_c.get("late_day_micro_trail_activation_pct", 4.0),
                    late_day_micro_trail_floor_pct=exit_c.get("late_day_micro_trail_floor_pct", 1.0),
                    morning_micro_trail_enabled=exit_c.get("morning_micro_trail_enabled", False),
                    morning_micro_trail_start_bar=0,
                    morning_micro_trail_end_bar=30,
                    morning_micro_trail_activation_pct=exit_c.get("morning_micro_trail_activation_pct", 10.0),
                    morning_micro_trail_floor_pct=exit_c.get("morning_micro_trail_floor_pct", 1.0),
                    morning_micro_trail_first_trade_only=exit_c.get("morning_micro_trail_first_trade_only", True),
                    enable_climax_spring=entry.get("enable_climax_spring", False),
                    climax_open_dist_min=entry.get("climax_open_dist_min", 75.0),
                    climax_vwap_dist_min=entry.get("climax_vwap_dist_min", 40.0),
                    climax_rsi_extreme=entry.get("climax_rsi_extreme", 32.0),
                    climax_impulse_delta_min=entry.get("climax_impulse_delta_min", 18.0),
                    climax_window_max_bar=entry.get("climax_window_max_bar", 120),
                    enable_structural_wick_stop=exit_c.get("enable_structural_wick_stop", False)
                )

        # Built-in fallbacks if file missing
        if strategy_key == "legacy_scalper":
            return cls(
                key="legacy_scalper",
                name="Strategy 1: Legacy Scalper",
                require_pullback=False,
                enable_range_box_filter=False,
                strike_selection="ATM_ROUNDED",
                prevent_v_reversal_counter_trades=False,
                min_spacing_bars=1,
                max_hold_minutes=6,  # 6-minute stopwatch timer
                initial_stop_pct=6.0,
                target_pct=7.0,
                enable_structural_stops=False,
                enable_runner_trailing=False,
                lock_breakeven_on_runner=False
            )
        elif strategy_key == "structural_runner":
            return cls(
                key="structural_runner",
                name="Strategy 2: Structural Runner",
                require_pullback=False,
                enable_range_box_filter=True,
                range_box_spread_min=28.0,
                value_proximity_pts=24.0,
                strike_selection="ATM_ROUNDED",
                prevent_v_reversal_counter_trades=False,
                min_spacing_bars=10,
                max_hold_minutes=360,
                initial_stop_pct=30.0,
                target_pct=50.0,
                enable_structural_stops=True,
                vwap_stop_buffer=15.0,
                ema20_stop=True,
                enable_runner_trailing=True,
                runner_activation_pct=15.0,
                ema9_trailing_buffer=4.0,
                peak_pullback_pct=10.0,
                lock_breakeven_on_runner=True
            )
        elif strategy_key == "ai_opportunity_radar":
            return cls(
                key="ai_opportunity_radar",
                name="Strategy 4: AI Opportunity Radar & Dynamic Swings",
                require_pullback=True,
                pullback_ema_tolerance_pts=4.0,
                enable_range_box_filter=True,
                range_box_spread_min=28.0,
                value_proximity_pts=24.0,
                strike_selection="STRICT_ITM",
                prevent_v_reversal_counter_trades=False,
                min_spacing_bars=10,
                max_hold_minutes=360,
                initial_stop_pct=30.0,
                target_pct=50.0,
                profit_target_enabled=False,
                aggressive_trail_enabled=True,
                enable_structural_stops=False,
                enable_structural_wick_stop=True,
                enable_runner_trailing=True,
                runner_activation_pct=20.0,
                ema9_trailing_buffer=4.0,
                peak_pullback_pct=10.0,
                lock_breakeven_on_runner=True,
                late_day_micro_trail_enabled=True,
                late_day_micro_trail_bar=285,
                late_day_micro_trail_activation_pct=4.0,
                late_day_micro_trail_floor_pct=1.0,
                enable_climax_spring=True,
                climax_open_dist_min=75.0,
                climax_vwap_dist_min=40.0,
                climax_rsi_extreme=32.0,
                climax_impulse_delta_min=18.0,
                climax_window_max_bar=120
            )
        else:
            return cls(
                key="institutional_pullback",
                name="Strategy 3: Institutional Pullback & ITM",
                require_pullback=True,
                pullback_ema_tolerance_pts=4.0,
                enable_range_box_filter=True,
                range_box_spread_min=28.0,
                value_proximity_pts=24.0,
                strike_selection="STRICT_ITM",
                prevent_v_reversal_counter_trades=True,
                min_spacing_bars=10,
                max_hold_minutes=360,
                initial_stop_pct=30.0,
                target_pct=50.0,
                enable_structural_stops=True,
                vwap_stop_buffer=15.0,
                ema20_stop=True,
                enable_runner_trailing=True,
                runner_activation_pct=15.0,
                ema9_trailing_buffer=4.0,
                peak_pullback_pct=10.0,
                lock_breakeven_on_runner=True,
                late_day_micro_trail_enabled=True,
                late_day_micro_trail_bar=285,
                late_day_micro_trail_activation_pct=4.0,
                late_day_micro_trail_floor_pct=1.0
            )


class BacktestEngine:
    def __init__(self, target_date: str = "2026-10-05", *, data_source=None):
        self.data_source = data_source
        self.target_date = target_date
        self.spot_candles: List[dict] = []
        self.options_data: Dict[str, List[dict]] = {}
        self.is_synthetic_options = False
        self.load_data()

    def load_data(self):
        source = getattr(self, "data_source", None)
        if source is not None:
            day = source.load_day(self.target_date)
            self.spot_candles = day.spot_candles
            self.options_data = day.options_data
            self.is_synthetic_options = day.is_synthetic_options
            return
        local_spot_file = f"data/spot_candles_{self.target_date.replace('-', '')}.json"
        if os.path.exists(local_spot_file):
            with open(local_spot_file, "r", encoding="utf-8") as f:
                self.spot_candles = json.load(f)
        else:
            conn = sqlite3.connect(HISTORICAL_DB_PATH)
            conn.row_factory = sqlite3.Row
            query = """
                SELECT start_time, open, high, low, close, volume 
                FROM historical_candles 
                WHERE instrument_id = 'INST-NIFTY-INDEX' AND interval = '1m'
                  AND start_time >= ? AND start_time <= ?
                  AND start_time LIKE '%+00:00'
                ORDER BY start_time ASC
            """
            start_utc = f"{self.target_date}T03:45:00+00:00"
            end_utc = f"{self.target_date}T10:00:00+00:00"
            rows = [dict(r) for r in conn.execute(query, (start_utc, end_utc)).fetchall()]

            # If native 1-minute candles are incomplete (< 100 bars), synthesize from complete 5m candles
            if len(rows) < 100:
                query_5m = """
                    SELECT start_time, open, high, low, close, volume 
                    FROM historical_candles 
                    WHERE instrument_id = 'INST-NIFTY-INDEX' AND interval = '5m'
                      AND start_time >= ? AND start_time <= ?
                      AND start_time LIKE '%+00:00'
                    ORDER BY start_time ASC
                """
                end_5m_utc = f"{self.target_date}T09:59:59+00:00"
                rows_5m = conn.execute(query_5m, (start_utc, end_5m_utc)).fetchall()
                if rows_5m:
                    synthesized = []
                    for r in rows_5m:
                        raw_time, o, h, l, c, v = r["start_time"], r["open"], r["high"], r["low"], r["close"], r["volume"]
                        t0 = datetime.fromisoformat(raw_time)
                        sub_v = int(v / 5) if v else 0
                        if c >= o:
                            sub_bars = [
                                (o, max(o, l), l, l),
                                (l, (o + h)/2, l, (o + h)/2),
                                ((o + h)/2, h, (o + h)/2, h),
                                (h, h, (h + c)/2, (h + c)/2),
                                ((h + c)/2, max((h + c)/2, c), min((h + c)/2, c), c)
                            ]
                        else:
                            sub_bars = [
                                (o, h, min(o, h), h),
                                (h, h, (o + l)/2, (o + l)/2),
                                ((o + l)/2, (o + l)/2, l, l),
                                (l, (l + c)/2, l, (l + c)/2),
                                ((l + c)/2, max((l + c)/2, c), min((l + c)/2, c), c)
                            ]
                        for i, (so, sh, sl, sc) in enumerate(sub_bars):
                            sub_time = (t0 + timedelta(minutes=i)).isoformat()
                            synthesized.append({
                                "start_time": sub_time,
                                "open": round(so, 2),
                                "high": round(sh, 2),
                                "low": round(sl, 2),
                                "close": round(sc, 2),
                                "volume": sub_v
                            })
                    rows = synthesized

            conn.close()
            os.makedirs("data", exist_ok=True)
            with open(local_spot_file, "w", encoding="utf-8") as f:
                json.dump(rows, f, indent=2)
            self.spot_candles = rows

        local_opt_file = f"data/option_candles_{self.target_date.replace('-', '')}.json"
        if self.target_date == "2026-10-09" and os.path.exists("option_candles_today.json"):
            with open("option_candles_today.json", "r", encoding="utf-8") as f:
                self.options_data = json.load(f)
            self.is_synthetic_options = False
        elif os.path.exists(local_opt_file):
            with open(local_opt_file, "r", encoding="utf-8") as f:
                self.options_data = json.load(f)
            self.is_synthetic_options = False
        else:
            self.is_synthetic_options = True

    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        return exponential_average(prices, period, last_during_warmup=True)

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> float:
        return simple_rsi(prices, period)

    def get_expiry_days(self) -> float:
        target_d = datetime.strptime(self.target_date, "%Y-%m-%d").date()
        # NIFTY weekly options expire on Tuesdays (weekday 1)
        if target_d.weekday() <= 1:
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
        else:
            expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
        delta_days = (expiry_d - target_d).days
        return max(0.1, float(delta_days))

    def select_contract(self, spot: float, direction: str, mode: str = "STRICT_ITM") -> Tuple[str, int]:
        strike = select_strike(spot, direction, mode)
        return f"NIFTY_{self.target_date}_{strike}_{direction}", strike

    def get_option_bar(self, sym: str, strike: int, direction: str, bar_idx: int,
                       spot_bar: dict) -> Tuple[float, float, float]:
        if not self.is_synthetic_options and sym in self.options_data:
            c = self.options_data[sym][bar_idx]
            return c["high"], c["low"], c["close"]

        days_base = self.get_expiry_days()
        days_remaining = days_base - (bar_idx / 375.0) * 0.25
        is_call = (direction == "CE")

        c_close = bsm_price(spot_bar["close"], strike, days_remaining, is_call=is_call)
        c_high = bsm_price(spot_bar["high"] if is_call else spot_bar["low"], strike, days_remaining, is_call=is_call)
        c_low = bsm_price(spot_bar["low"] if is_call else spot_bar["high"], strike, days_remaining, is_call=is_call)
        return max(c_close, c_high), min(c_close, c_low), c_close

    def run_simulation(self, cfg: StrategyConfig) -> List[Trade]:
        trades: List[Trade] = []
        current_trade: Optional[Trade] = None
        last_exit_bar = -999
        spot_closes: List[float] = []
        spot_typicals: List[float] = []

        for idx, bar in enumerate(self.spot_candles):
            close = bar["close"]
            high = bar["high"]
            low = bar["low"]
            spot_closes.append(close)
            spot_typicals.append((high + low + close) / 3.0)

            session_vwap = sum(spot_typicals) / len(spot_typicals)
            bars_5m = [spot_closes[i] for i in range(4, len(spot_closes), 5)] or [close]
            ema9 = self.calculate_ema(bars_5m, 9)
            ema20 = self.calculate_ema(bars_5m, 20)
            rsi = self.calculate_rsi(spot_closes, 14)

            recent_15m = self.spot_candles[max(0, idx - 14): idx + 1]
            box_high = max(c["high"] for c in recent_15m)
            box_low = min(c["low"] for c in recent_15m)
            box_spread = box_high - box_low

            raw_time = bar["start_time"]
            time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

            # Position Management
            if current_trade is not None:
                is_ce = (current_trade.direction == "CE")
                opt_high, opt_low, opt_close = self.get_option_bar(
                    current_trade.symbol, current_trade.strike, current_trade.direction, idx, bar
                )

                if opt_high > current_trade.peak_price:
                    current_trade.peak_price = opt_high
                    current_trade.peak_gain_pct = round(
                        ((opt_high - current_trade.entry_price) / current_trade.entry_price) * 100, 2
                    )

                hold_duration = idx - current_trade.entry_bar
                exit_reason = None
                exit_price = opt_close

                # A. Initial Stop
                if opt_low <= current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0):
                    exit_reason = "INITIAL_STOP"
                    exit_price = round(current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0), 2)
                # B. Profit Target Cap
                elif cfg.profit_target_enabled and opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                    exit_reason = "PROFIT_TARGET"
                    exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)
                # C. Max Hold Duration (e.g. 6 mins for Legacy Scalper!)
                elif hold_duration >= cfg.max_hold_minutes:
                    exit_reason = f"MAX_HOLD_TIME ({cfg.max_hold_minutes}m stopwatch)"
                    exit_price = opt_close
                # D. Active Incremental Runner Trailing Check (if peak gain >= runner_activation_pct)
                elif cfg.enable_runner_trailing and current_trade.peak_gain_pct >= cfg.runner_activation_pct:
                    current_trade.runner_active = True
                    floor_pct = 10.0
                    if current_trade.peak_gain_pct >= 40.0:
                        floor_pct = 30.0
                    elif current_trade.peak_gain_pct >= 30.0:
                        floor_pct = 20.0
                    floor_price = current_trade.entry_price * (1.0 + floor_pct / 100.0)
                    trail_stop = max(floor_price, current_trade.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0))
                    if cfg.aggressive_trail_enabled:
                        trail_stop = runner_trigger(current_trade.entry_price, current_trade.peak_price, {
                            "peak_pullback_pct": cfg.peak_pullback_pct,
                            "aggressive_trail_enabled": True,
                            "aggressive_trail_activation_pct": cfg.aggressive_trail_activation_pct,
                            "aggressive_trail_pullback_pct": cfg.aggressive_trail_pullback_pct,
                        })

                    if opt_close <= trail_stop:
                        exit_reason = f"TRAILING_DYNAMIC_RATCHET (Stop={trail_stop:.2f})"
                        exit_price = round(trail_stop, 2)
                    elif is_ce and close < (ema9 - cfg.ema9_trailing_buffer):
                        exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} < {ema9:.1f})"
                        exit_price = opt_close
                    elif not is_ce and close > (ema9 + cfg.ema9_trailing_buffer):
                        exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} > {ema9:.1f})"
                        exit_price = opt_close

                # D1b. Morning Micro-Trail (09:15-09:45 IST = bars 0-30, first trade, activation >= 10.0%)
                elif (
                    not exit_reason
                    and cfg.morning_micro_trail_enabled
                    and cfg.morning_micro_trail_start_bar <= current_trade.entry_bar <= cfg.morning_micro_trail_end_bar
                    and (not cfg.morning_micro_trail_first_trade_only or len(trades) == 0)
                    and current_trade.peak_gain_pct >= cfg.morning_micro_trail_activation_pct
                ):
                    morning_floor = current_trade.morning_trail_floor(cfg)
                    if opt_close <= morning_floor:
                        exit_reason = f"AI_MORNING_MICRO_TRAIL (Floor={morning_floor:.2f})"
                        exit_price = round(morning_floor, 2)

                # D2. Late-Day Micro-Trail (Protects +4% gains after 14:00 IST = bar 285+)
                elif cfg.late_day_micro_trail_enabled and idx >= cfg.late_day_micro_trail_bar and current_trade.peak_gain_pct >= cfg.late_day_micro_trail_activation_pct:
                    floor_price = current_trade.entry_price * (1.0 + cfg.late_day_micro_trail_floor_pct / 100.0)
                    if opt_close <= floor_price:
                        exit_reason = f"AI_LATE_DAY_MICRO_TRAIL (Floor={floor_price:.2f})"
                        exit_price = round(floor_price, 2)

                # E. Structural Stops if Trailing Not Yet Activated (< runner_activation_pct)
                elif cfg.enable_structural_stops:
                    if is_ce:
                        if close < (session_vwap - cfg.vwap_stop_buffer):
                            exit_reason = f"STRUCTURAL_VWAP_STOP ({close:.1f} < {session_vwap - cfg.vwap_stop_buffer:.1f})"
                            exit_price = opt_close
                        elif cfg.ema20_stop and (close < ema20) and (ema9 < ema20):
                            exit_reason = f"STRUCTURAL_EMA20_STOP ({close:.1f} < {ema20:.1f})"
                            exit_price = opt_close
                    else:
                        if close > (session_vwap + cfg.vwap_stop_buffer):
                            exit_reason = f"STRUCTURAL_VWAP_STOP ({close:.1f} > {session_vwap + cfg.vwap_stop_buffer:.1f})"
                            exit_price = opt_close
                        elif cfg.ema20_stop and (close > ema20) and (ema9 > ema20):
                            exit_reason = f"STRUCTURAL_EMA20_STOP ({close:.1f} > {ema20:.1f})"
                            exit_price = opt_close


                # E. EOD Square-Off
                if idx >= 360 and not exit_reason:
                    exit_reason = "EOD_SQUAREOFF"
                    exit_price = opt_close

                if exit_reason:
                    current_trade.close(idx, time_str, exit_price, exit_reason)
                    trades.append(current_trade)
                    current_trade = None
                    last_exit_bar = idx
                continue

            # Entry Evaluation
            if idx < 10 or idx > 330:
                continue
            if len(trades) >= cfg.max_daily_entries:
                continue
            if (idx - last_exit_bar) < cfg.min_spacing_bars:
                continue

            # Pullback condition
            if cfg.require_pullback:
                ce_pullback = (low <= ema9 + cfg.pullback_ema_tolerance_pts)
                pe_pullback = (high >= ema9 - cfg.pullback_ema_tolerance_pts)
            else:
                ce_pullback = True
                pe_pullback = True

            # Momentum / V-Reversal Sanity
            if cfg.prevent_v_reversal_counter_trades:
                pe_reversal_veto = (rsi > 50.0) or (close > ema9)
            else:
                pe_reversal_veto = False

            ce_signal = (close > ema9) and (ema9 > ema20) and (close > session_vwap) and ce_pullback
            pe_signal = (close < ema9) and (ema9 < ema20) and (close < session_vwap) and pe_pullback and not pe_reversal_veto

            direction = None
            if ce_signal:
                if cfg.enable_range_box_filter and box_spread < cfg.range_box_spread_min and close >= (box_high - 3.0):
                    ce_signal = False
                if (close - ema9) > cfg.value_proximity_pts or rsi > 78.0:
                    ce_signal = False
                if ce_signal:
                    direction = "CE"

            elif pe_signal:
                if cfg.enable_range_box_filter and box_spread < cfg.range_box_spread_min and close <= (box_low + 3.0):
                    pe_signal = False
                if (ema9 - close) > cfg.value_proximity_pts or rsi < 22.0:
                    pe_signal = False
                if pe_signal:
                    direction = "PE"

            if direction:
                sym, strike = self.select_contract(close, direction, mode=cfg.strike_selection)
                opt_h, opt_l, opt_entry = self.get_option_bar(sym, strike, direction, idx, bar)
                trade_id = len(trades) + 1
                current_trade = Trade(
                    trade_id=trade_id,
                    symbol=sym,
                    direction=direction,
                    strike=strike,
                    entry_bar=idx,
                    entry_time=time_str,
                    entry_price=opt_entry,
                    peak_price=opt_entry,
                    peak_gain_pct=0.0
                )

        if current_trade is not None:
            last_bar = self.spot_candles[-1]
            _, _, last_opt = self.get_option_bar(
                current_trade.symbol, current_trade.strike, current_trade.direction,
                len(self.spot_candles) - 1, last_bar
            )
            current_trade.close(len(self.spot_candles) - 1, last_bar["start_time"][11:19], last_opt, "EOD_SQUAREOFF")
            trades.append(current_trade)

        return trades


def calculate_metrics(trades: List[Trade]) -> dict:
    if not trades:
        return {
            "total_trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
            "gross_profit": 0.0, "gross_loss": 0.0, "net_pnl": 0.0,
            "profit_factor": 0.0, "avg_trade": 0.0, "avg_win": 0.0,
            "avg_loss": 0.0, "max_win": 0.0, "max_loss": 0.0,
            "max_drawdown": 0.0, "avg_hold_mins": 0.0
        }
    wins = [t for t in trades if (t.pnl or 0) > 0]
    losses = [t for t in trades if (t.pnl or 0) <= 0]
    gross_profit = sum(t.pnl for t in wins)
    gross_loss = abs(sum(t.pnl for t in losses))
    net_pnl = gross_profit - gross_loss
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)

    equity = 0.0
    peak_equity = 0.0
    max_dd = 0.0
    for t in trades:
        equity += (t.pnl or 0.0)
        peak_equity = max(peak_equity, equity)
        dd = peak_equity - equity
        max_dd = max(max_dd, dd)

    avg_hold = sum(t.hold_minutes for t in trades) / len(trades)

    return {
        "total_trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round((len(wins) / len(trades)) * 100, 1),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "net_pnl": round(net_pnl, 2),
        "profit_factor": profit_factor,
        "avg_trade": round(net_pnl / len(trades), 2),
        "avg_win": round(gross_profit / len(wins), 2) if wins else 0.0,
        "avg_loss": round(-gross_loss / len(losses), 2) if losses else 0.0,
        "max_win": max([t.pnl for t in wins]) if wins else 0.0,
        "max_loss": min([t.pnl for t in losses]) if losses else 0.0,
        "max_drawdown": round(max_dd, 2),
        "avg_hold_mins": round(avg_hold, 1)
    }


def print_scorecard(title: str, m: dict):
    print("\n" + "=" * 65)
    print(f" {title.upper()}")
    print("=" * 65)
    print(f"  Total Trades:       {m['total_trades']:<6} (Wins: {m['wins']}, Losses: {m['losses']})")
    print(f"  Win Rate:           {m['win_rate']:.1f}%")
    print(f"  Gross Net P&L:      ₹{m['net_pnl']:+,.2f}")
    print(f"  Est. Friction:      ₹{m['total_trades'] * 40:,.2f} (@ ₹40/trade)")
    print(f"  Real Net (Post-Fee):₹{m['net_pnl'] - m['total_trades'] * 40:+,.2f}")
    print(f"  Profit Factor:      {m['profit_factor']:.2f}")
    print(f"  Avg Win / Avg Loss: ₹{m['avg_win']:+,.2f} / ₹{m['avg_loss']:+,.2f}")
    print(f"  Max Win / Max Loss: ₹{m['max_win']:+,.2f} / ₹{m['max_loss']:+,.2f}")
    print(f"  Max Drawdown:       ₹{m['max_drawdown']:,.2f}")
    print(f"  Avg Hold Time:      {m['avg_hold_mins']:.1f} minutes")
    print("=" * 65)


def print_trades_table(trades: List[Trade]):
    print("\n" + "-" * 115)
    print(f"{'#':<3} {'Type':<4} {'Symbol':<28} {'Entry Time':<10} {'Entry':<8} {'Exit Time':<10} {'Exit':<8} {'Hold(m)':<8} {'P&L (₹)':<11} {'Return':<8} {'Exit Reason'}")
    print("-" * 115)
    for t in trades:
        pnl_str = f"₹{t.pnl:+,.2f}"
        ret_str = f"{t.pnl_pct:+.1f}%"
        print(f"{t.trade_id:<3} {t.direction:<4} {t.symbol:<28} {t.entry_time:<10} {t.entry_price:<8.2f} {t.exit_time:<10} {t.exit_price:<8.2f} {t.hold_minutes:<8} {pnl_str:<11} {ret_str:<8} {t.exit_reason}")
    print("-" * 115)


def compare_all_strategies(dates: List[str], day_by_day: bool = True):
    strat_keys = ["legacy_scalper", "structural_runner", "institutional_pullback"]
    configs = [StrategyConfig.load_from_config(k) for k in strat_keys]

    date_label = f"{dates[0]} to {dates[-1]}" if len(dates) > 1 else dates[0]

    if day_by_day and len(dates) > 1:
        for d in dates:
            day_name = datetime.strptime(d, "%Y-%m-%d").strftime("%A")
            is_expiry = " (NIFTY Expiry)" if day_name == "Tuesday" else ""
            print("\n" + "-" * 110)
            print(f" DAY BREAKDOWN: {d} ({day_name}){is_expiry}")
            print("-" * 110)
            print(f"{'Strategy Name':<42} {'Trades':<8} {'Win%':<8} {'Gross P&L':<14} {'Friction':<12} {'Real Net':<14} {'PF'}")
            print("-" * 110)
            for cfg in configs:
                eng = BacktestEngine(target_date=d)
                t = eng.run_simulation(cfg)
                m = calculate_metrics(t)
                fee = m["total_trades"] * 40.0
                real_net = m["net_pnl"] - fee
                print(f"{cfg.name:<42} {m['total_trades']:<8} {m['win_rate']:<8.1f}% ₹{m['net_pnl']:<13,.2f} ₹{fee:<11,.2f} ₹{real_net:<13,.2f} {m['profit_factor']:.2f}")

    print("\n" + "=" * 110)
    print(f" 3-STRATEGY CONSOLIDATED COMPARISON MATRIX ({date_label})")
    print("=" * 110)
    print(f"{'Strategy Name':<42} {'Trades':<8} {'Win%':<8} {'Gross P&L':<14} {'Friction':<12} {'Real Net':<14} {'PF'}")
    print("-" * 110)

    for cfg in configs:
        all_trades = []
        for d in dates:
            eng = BacktestEngine(target_date=d)
            t = eng.run_simulation(cfg)
            all_trades.extend(t)

        m = calculate_metrics(all_trades)
        fee = m["total_trades"] * 40.0
        real_net = m["net_pnl"] - fee

        print(f"{cfg.name:<42} {m['total_trades']:<8} {m['win_rate']:<8.1f}% ₹{m['net_pnl']:<13,.2f} ₹{fee:<11,.2f} ₹{real_net:<13,.2f} {m['profit_factor']:.2f}")

    print("=" * 110 + "\n")


def main():
    parser = argparse.ArgumentParser(description="NIFTY Options 3-Strategy Backtesting Engine")
    parser.add_argument("--strategy", default=None, choices=["legacy_scalper", "structural_runner", "institutional_pullback", "ai_opportunity_radar"],
                        help="Select active strategy (default reads config/strategies.json)")
    parser.add_argument("--date", default=None, help="Target date YYYY-MM-DD")
    parser.add_argument("--start-date", default=None, help="Start date YYYY-MM-DD for multi-day range")
    parser.add_argument("--end-date", default=None, help="End date YYYY-MM-DD for multi-day range")
    parser.add_argument("--week", action="store_true", help="Run across all 5 days of last week")
    parser.add_argument("--compare-all", action="store_true", help="Compare all 3 strategies side-by-side")
    parser.add_argument("--dossier", action="store_true", help="Print AI Market State Dossier for each candidate trade")
    args = parser.parse_args()

    if args.start_date and args.end_date:
        conn = sqlite3.connect(HISTORICAL_DB_PATH)
        query = """
            SELECT DISTINCT substr(start_time, 1, 10) as dt
            FROM historical_candles
            WHERE instrument_id = 'INST-NIFTY-INDEX'
              AND start_time >= ? AND start_time <= ?
            ORDER BY dt ASC
        """
        rows = [r[0] for r in conn.execute(query, (f"{args.start_date}T00:00:00", f"{args.end_date}T23:59:59")).fetchall()]
        conn.close()
        dates = rows
    elif args.week:
        dates = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    else:
        dates = [args.date or "2026-10-09"]

    if not dates:
        print(f"No trading data found for the specified date range ({args.start_date} to {args.end_date}).")
        return

    if args.compare_all:
        compare_all_strategies(dates)
        return

    # Determine strategy to run
    strategy_key = args.strategy
    if not strategy_key:
        if os.path.exists("config/strategies.json"):
            with open("config/strategies.json", "r", encoding="utf-8") as f:
                strategy_key = json.load(f).get("active_strategy", "institutional_pullback")
        else:
            strategy_key = "institutional_pullback"

    cfg = StrategyConfig.load_from_config(strategy_key)

    all_trades = []
    for d in dates:
        eng = BacktestEngine(target_date=d)
        t = eng.run_simulation(cfg)
        all_trades.extend(t)
        if len(dates) == 1:
            print(f"\nDETAILED TRADES: {cfg.name} on {d}")
            print_trades_table(t)

        if args.dossier:
            print(f"\n========================================================================================")
            print(f" AI MARKET STATE DOSSIERS FOR: {d} ({len(t)} trades)")
            print(f"========================================================================================\n")
            for i, trade in enumerate(t, 1):
                idx = 0
                for k, c in enumerate(eng.spot_candles):
                    if trade.entry_time in c["start_time"]:
                        idx = k
                        break
                dossier = generate_market_dossier(
                    target_date=d,
                    candles=eng.spot_candles,
                    current_bar_idx=idx,
                    direction=trade.direction,
                    symbol=trade.symbol,
                    strike=trade.strike,
                    option_entry_price=trade.entry_price,
                    trade_history=t[:i-1],
                    days_to_expiry=eng.get_expiry_days(),
                    is_expiry_0dte=(eng.get_expiry_days() <= 0.2)
                )
                outcome_tag = "🏆 WINNER" if trade.pnl > 0 else "❌ FAILED"
                print(f"--- TRADE #{i}: {trade.direction} {trade.symbol} | Actual: {outcome_tag} (₹{trade.pnl:+,.2f}, {trade.pnl_pct:+.1f}%) ---")
                print(f"Hold: {trade.exit_bar - trade.entry_bar} mins | Exit: {trade.exit_reason}\n")
                print(dossier.to_markdown())
                print("-" * 88 + "\n")

    m = calculate_metrics(all_trades)
    title = f"{cfg.name} ({dates[0]} to {dates[-1]}" if len(dates) > 1 else f"{cfg.name} ({dates[0]})"
    print_scorecard(title, m)


if __name__ == "__main__":
    from trading.bootstrap import configure_console
    configure_console()
    main()
