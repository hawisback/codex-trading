#!/usr/bin/env python3
"""
AI Opportunity Radar for NIFTY 50 Options
=========================================
Monitors market state continuously and synthesizes institutional regimes:
1. Dynamic Trend Pullback Mode (Strategy 3 Core: continuation when institutional flow is aligned)
2. Climax Rubber-Band Spring Mode (Exhaustion reversal when rubber band is at extreme tension)
3. Stand-Aside Mode (Capital preservation during chop / flat VWAP dead zones)
"""

from dataclasses import dataclass
from typing import List, Dict, Optional, Any
from market_clock import MarketClock

@dataclass
class AIOpportunity:
    action: str                 # "BUY_CE", "BUY_PE", "STAND_ASIDE"
    regime: str                 # "TREND_PULLBACK", "CLIMAX_SPRING", "CHOP_STAND_ASIDE"
    conviction: int             # 0 to 100
    thesis: str
    invalidation_level: Optional[float] = None
    recommended_trailing: str = "dynamic_ratchet"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "regime": self.regime,
            "conviction": self.conviction,
            "thesis": self.thesis,
            "invalidation_level": self.invalidation_level,
            "recommended_trailing": self.recommended_trailing
        }

class AIOpportunityRadar:
    """
    Autonomous AI Opportunity Radar:
    Evaluates the continuous 6D market state on every bar to synthesize
    institutional regime and trade conviction.
    """
    def __init__(
        self,
        enable_climax_spring: bool = True,
        climax_open_dist_min: float = 75.0,
        climax_vwap_dist_min: float = 40.0,
        climax_rsi_extreme: float = 32.0,
        climax_impulse_delta_min: float = 18.0,
        climax_window_max_bar: int = 120,
        pullback_ema_tolerance_pts: float = 4.0,
        value_proximity_pts: float = 24.0,
        range_box_spread_min: float = 28.0
    ):
        self.enable_climax_spring = enable_climax_spring
        self.climax_open_dist_min = climax_open_dist_min
        self.climax_vwap_dist_min = climax_vwap_dist_min
        self.climax_rsi_extreme = climax_rsi_extreme
        self.climax_impulse_delta_min = climax_impulse_delta_min
        self.climax_window_max_bar = climax_window_max_bar
        self.pullback_ema_tolerance_pts = pullback_ema_tolerance_pts
        self.value_proximity_pts = value_proximity_pts
        self.range_box_spread_min = range_box_spread_min

    def evaluate(
        self,
        bar_idx: int,
        bar: dict,
        all_bars: List[dict],
        spot_closes: List[float],
        session_vwap: float,
        ema9: float,
        ema20: float,
        rsi: float,
        rsi_history: List[float],
        day_open: float,
        box_high: float,
        box_low: float,
        session_minute: Optional[int] = None
    ) -> AIOpportunity:
        close = bar["close"]
        open_p = bar["open"]

        # Resolve true session minute (0 to 375)
        if session_minute is not None:
            effective_min = session_minute
        else:
            bar_ts = bar.get("start_time") or bar.get("date")
            dt_ist = MarketClock.parse_to_ist(bar_ts) if bar_ts else None
            if dt_ist is not None:
                effective_min = MarketClock.get_session_minutes(dt_ist)[0]
            else:
                effective_min = bar_idx

        # 1. Temporal Session Phase (minute 300+ = post-14:15 IST)
        is_late_day = (effective_min > 300)
        if is_late_day:
            return AIOpportunity("STAND_ASIDE", "CHOP_STAND_ASIDE", 0, "Late-day degradation zone (post-14:15 IST)")

        # -------------------------------------------------------------
        # CANDIDATE REGIME A: CLIMAX SPRING (Mean-Reversion Squeeze)
        # -------------------------------------------------------------
        if self.enable_climax_spring and effective_min <= self.climax_window_max_bar:
            recent_low = min(c["low"] for c in all_bars[max(0, bar_idx - 2): bar_idx + 1])
            recent_high = max(c["high"] for c in all_bars[max(0, bar_idx - 2): bar_idx + 1])
            recent_min_rsi = min(rsi_history[max(0, bar_idx - 2): bar_idx + 1])
            recent_max_rsi = max(rsi_history[max(0, bar_idx - 2): bar_idx + 1])
            delta = close - open_p

            dist_open_ext = recent_low - day_open
            dist_vwap_ext = recent_low - session_vwap

            # Bullish Climax Spring (Oversold capitulation turn)
            if (dist_open_ext <= -self.climax_open_dist_min or dist_vwap_ext <= -self.climax_vwap_dist_min) and \
               recent_min_rsi <= self.climax_rsi_extreme and delta >= self.climax_impulse_delta_min:
                return AIOpportunity(
                    action="BUY_CE",
                    regime="CLIMAX_SPRING",
                    conviction=92,
                    thesis=f"Oversold capitulation flush to {recent_low:.1f}. Violent +{delta:.1f} pt spring candle confirms buyer absorption.",
                    invalidation_level=recent_low - 2.0,
                    recommended_trailing="structural_wick_and_ratchet"
                )

            # Bearish Climax Upthrust (Overbought climax turn)
            elif (recent_high - day_open >= self.climax_open_dist_min or recent_high - session_vwap >= self.climax_vwap_dist_min) and \
                 recent_max_rsi >= (100.0 - self.climax_rsi_extreme) and delta <= -self.climax_impulse_delta_min:
                return AIOpportunity(
                    action="BUY_PE",
                    regime="CLIMAX_SPRING",
                    conviction=90,
                    thesis=f"Overbought euphoric spike to {recent_high:.1f}. Violent {delta:.1f} pt rejection candle confirms seller absorption.",
                    invalidation_level=recent_high + 2.0,
                    recommended_trailing="structural_wick_and_ratchet"
                )

        # -------------------------------------------------------------
        # CANDIDATE REGIME B: DYNAMIC TREND PULLBACK (Strategy 3 Core)
        # -------------------------------------------------------------
        box_spread = box_high - box_low
        # Bullish Pullback
        ce_trend = (close > ema9) and (ema9 > ema20) and (close > session_vwap)
        ce_pullback = (bar["low"] <= ema9 + self.pullback_ema_tolerance_pts)
        ce_value = (close - ema9 <= self.value_proximity_pts) and (rsi < 78.0)
        ce_not_at_ceiling = not (box_spread < self.range_box_spread_min and close >= (box_high - 3.0))

        if ce_trend and ce_pullback and ce_value and ce_not_at_ceiling:
            return AIOpportunity(
                action="BUY_CE",
                regime="TREND_PULLBACK",
                conviction=88,
                thesis=f"Institutional bullish trend confirmed. Clean pullback to 5m EMA9 ({close:.1f} holding above {ema9:.1f}).",
                invalidation_level=None,
                recommended_trailing="dynamic_ratchet"
            )

        # Bearish Pullback
        pe_trend = (close < ema9) and (ema9 < ema20) and (close < session_vwap)
        pe_pullback = (bar["high"] >= ema9 - self.pullback_ema_tolerance_pts)
        pe_value = (ema9 - close <= self.value_proximity_pts) and (rsi > 22.0)
        pe_not_at_floor = not (box_spread < self.range_box_spread_min and close <= (box_low + 3.0))

        if pe_trend and pe_pullback and pe_value and pe_not_at_floor:
            return AIOpportunity(
                action="BUY_PE",
                regime="TREND_PULLBACK",
                conviction=88,
                thesis=f"Institutional bearish trend confirmed. Clean pullback to 5m EMA9 ({close:.1f} holding below {ema9:.1f}).",
                invalidation_level=None,
                recommended_trailing="dynamic_ratchet"
            )

        return AIOpportunity("STAND_ASIDE", "CHOP_STAND_ASIDE", 0, "No high-conviction institutional setup detected.")
