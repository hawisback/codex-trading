"""
2-Minute MACD Momentum Strategy (Path A).
Proposes high-momentum candidates on 2m MACD crossovers for AI Companion / Gatekeeper evaluation.
Never places orders directly.
"""

from datetime import timedelta
from typing import List, Dict, Optional, Tuple
from trading.models import CandidateSignal
from market_clock import MarketClock
from trading.domain.market_data import (
    exchange_time, number, resample_two_minutes, resample_rolling_two_minutes,
    macd_observation_bars, prior_session_warmup,
)
from trading.domain.limits import HARD_ENTRY_CUTOFF


def resample_1m_to_2m(candles_1m: List[Dict], *, as_of=None) -> List[Dict]:
    """Shared completed-candle resampling for live and historical analysis."""
    return resample_two_minutes(candles_1m, as_of=as_of)


def resample_1m_to_rolling_2m(candles_1m: List[Dict], *, as_of=None) -> List[Dict]:
    return resample_rolling_two_minutes(candles_1m, as_of=as_of)


def calculate_ema(series: List[float], period: int) -> List[float]:
    """Computes Exponential Moving Average."""
    if not series:
        return []
    res = [series[0]]
    mult = 2.0 / (period + 1.0)
    for v in series[1:]:
        res.append(v * mult + res[-1] * (1.0 - mult))
    return res


def calculate_macd(closes: List[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9) -> Tuple[List[float], List[float], List[float]]:
    """Computes MACD line, signal line, and histogram."""
    if len(closes) < slow_period:
        zeros = [0.0] * len(closes)
        return zeros, zeros, zeros
    fast = calculate_ema(closes, fast_period)
    slow = calculate_ema(closes, slow_period)
    macd_line = [f - s for f, s in zip(fast, slow)]
    signal_line = calculate_ema(macd_line, signal_period)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist


class MacdMomentumStrategy:
    """
    Path A: completed 2m MACD crossovers with optional 5m EMA confirmation.
    The active profile leaves EMA proximity and trend alignment advisory.
    """
    fast_period: int
    slow_period: int
    signal_period: int
    require_ema_confirmation: bool
    require_ema20_trend_alignment: bool
    require_candle_alignment: bool
    require_vwap_alignment: bool
    opening_range_filter_enabled: bool
    use_rolling_2m: bool
    prior_session_warmup_enabled: bool
    early_orb_required: bool

    def __init__(self, strategy_cfg: Optional[Dict] = None):
        self.cfg = strategy_cfg or {}
        entry = self.cfg.get("entry", {})
        for key, default in (("macd_fast", 12), ("macd_slow", 26), ("macd_signal", 9)):
            alias = {"macd_fast": "fast_period", "macd_slow": "slow_period", "macd_signal": "signal_period"}[key]
            if key in entry and alias in entry and entry[key] != entry[alias]:
                raise ValueError(f"Conflicting {key} and {alias}")
            value = number(entry.get(key, entry.get(alias, default)), minimum=1)
            if value != int(value):
                raise ValueError(f"{key} must be an integer")
            setattr(self, {"macd_fast": "fast_period", "macd_slow": "slow_period", "macd_signal": "signal_period"}[key], int(value))
        if not self.fast_period < self.slow_period:
            raise ValueError("MACD fast period must be below the slow period")
        for key in ("require_ema_confirmation", "require_ema20_trend_alignment"):
            value = entry.get(key, False)
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            setattr(self, key, value)
        self.ema_proximity_pts = number(entry.get("ema_proximity_pts", 10), minimum=0)
        self.min_invalidation_buffer_pts = number(entry.get("min_invalidation_buffer_pts", 25), minimum=.01)
        self.min_hist_threshold = number(entry.get("min_hist_threshold", .20), minimum=0)
        self.continuation_max_observations = number(entry.get("continuation_max_observations", 8), minimum=1)
        if int(self.continuation_max_observations) != self.continuation_max_observations or isinstance(entry.get("continuation_max_observations", 8), bool):
            raise ValueError("Continuation observation window must be a positive integer")
        self.continuation_max_observations = int(self.continuation_max_observations)
        self.vwap_tolerance_pts = number(entry.get("vwap_tolerance_pts", 12), minimum=0)
        self.vwap_climax_pts = number(entry.get("vwap_climax_pts", 50), minimum=.01)
        self.opening_range_buffer_pts = number(entry.get("opening_range_buffer_pts", 8), minimum=0)
        for key in ("require_candle_alignment", "require_vwap_alignment", "opening_range_filter_enabled"):
            value = entry.get(key, True)
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            setattr(self, key, value)
        midday = entry.get("midday_dead_zone_filter", {})
        if not isinstance(midday, dict) or not isinstance(midday.get("enabled", True), bool):
            raise ValueError("Invalid midday filter configuration")
        self.midday_enabled = midday.get("enabled", True)
        self.midday_start = number(midday.get("start_minute", 135), minimum=0)
        self.midday_end = number(midday.get("end_minute", 240), minimum=0)
        if not 0 <= self.midday_start < self.midday_end <= 360:
            raise ValueError("Invalid midday filter window")
        self.midday_min_range = number(midday.get("min_15m_range_pts", 24), minimum=0)
        for key in ("use_rolling_2m", "prior_session_warmup_enabled", "early_orb_required"):
            value = entry.get(key, False)
            if not isinstance(value, bool):
                raise ValueError(f"{key} must be a boolean")
            setattr(self, key, value)
        self.entry_start_time = entry.get("entry_start_time", "09:30" if self.use_rolling_2m else "09:15")
        self.early_orb_cutoff_time = entry.get("early_orb_cutoff_time", "10:00")
        for value in (self.entry_start_time, self.early_orb_cutoff_time):
            if (not isinstance(value, str) or len(value) != 5 or value[2] != ":"
                    or not value[:2].isdigit() or not value[3:].isdigit()
                    or int(value[:2]) > 23 or int(value[3:]) > 59):
                raise ValueError("Invalid MACD entry window")
        if not "09:15" <= self.entry_start_time < HARD_ENTRY_CUTOFF:
            raise ValueError("Invalid MACD entry start")
        if self.early_orb_required and not "09:30" <= self.entry_start_time < self.early_orb_cutoff_time <= HARD_ENTRY_CUTOFF:
            raise ValueError("Early ORB requires a completed opening range and ordered window")
        for key, default in (("min_spacing_bars", 10), ("max_daily_entries", 2)):
            value = number(entry.get(key, default), minimum=1)
            if not isinstance(entry.get(key, default), (int, float)) or value != int(value):
                raise ValueError(f"{key} must be an integer")

    def evaluate(self, ctx: Dict, intel: Optional[Dict] = None) -> CandidateSignal:
        def neutral(reason):
            return CandidateSignal("NEUTRAL", [reason], "NONE")

        candles = ctx.get("candles_1m") or []
        minimum = 15 if self.prior_session_warmup_enabled else (
            self.slow_period + 2 if self.use_rolling_2m else 2 * (self.slow_period + 1))
        if len(candles) < minimum:
            return neutral("Insufficient completed one-minute candles for a two-minute MACD crossover.")
        now = MarketClock.now_ist()
        if now.strftime("%H:%M") < self.entry_start_time:
            return neutral(f"Waiting for {self.entry_start_time} IST entry activation.")
        if now.strftime("%H:%M") >= HARD_ENTRY_CUTOFF:
            return neutral("No new directional entries at or after 14:15 IST.")
        try:
            opening = now.replace(hour=9, minute=15, second=0, microsecond=0)
            # Opening-range and session filters require today's contiguous history.
            if exchange_time(candles[0]["start_time"]) != opening:
                return neutral("Complete current-session candles from 09:15 IST are required.")
            prior = []
            if self.prior_session_warmup_enabled:
                try:
                    prior = prior_session_warmup(ctx.get("prior_session_warmup_candles") or [], now,
                        holidays=ctx.get("exchange_holidays", ()))
                except (ValueError, TypeError, KeyError, OverflowError):
                    return neutral("Previous trading session warmup is missing or invalid; preserving cash.")
            bars = macd_observation_bars(candles, prior=prior, as_of=now, rolling=self.use_rolling_2m)
            if len(bars) < self.slow_period + 1:
                return neutral("Insufficient completed two-minute candles for MACD.")
            latest = bars[-1]
            if latest["minute_idx"] != len(candles) - 1:
                return neutral("Waiting for the current two-minute candle to close.")
            if now - exchange_time(latest["start_time"]) >= timedelta(minutes=3):
                return neutral("Latest completed two-minute candle is stale.")
            closes = [number(b["close"], minimum=.01) for b in bars]
        except (ValueError, TypeError, KeyError, OverflowError):
            return neutral("Invalid or incomplete timestamped candle history.")
        macd, signal, hist = calculate_macd(closes, self.fast_period, self.slow_period, self.signal_period)
        # A verified same-direction MACD state may continue for a bounded
        # number of *completed observations* after its most recent cross.
        # Never infer a swing from the MACD sign alone: an actual crossing
        # must exist inside this window, with no later opposite cross.
        last_cross = None
        for index in range(len(macd) - 1, max(0, len(macd) - 1 - self.continuation_max_observations), -1):
            bullish = macd[index] > signal[index] and macd[index - 1] <= signal[index - 1]
            bearish = macd[index] < signal[index] and macd[index - 1] >= signal[index - 1]
            if bullish or bearish:
                last_cross = ("CE" if bullish else "PE", len(macd) - 1 - index)
                break
        if last_cross is None:
            return neutral("No recent completed MACD crossover or valid swing continuation.")
        direction, cross_age = last_cross
        sign = 1 if direction == "CE" else -1
        if sign * hist[-1] < self.min_hist_threshold:
            return neutral("MACD swing lost directional histogram conviction.")
        ce_cross, pe_cross = direction == "CE", direction == "PE"
        setup_label = "crossover" if cross_age == 0 else f"continuation ({cross_age} observations after cross)"
        try:
            spot = number(ctx.get("spot"), minimum=.01)
            raw_vwap = ctx.get("session_vwap")
            try:
                session_vwap = number(raw_vwap, minimum=.01)
            except (TypeError, ValueError, OverflowError):
                session_vwap = None
            if self.require_vwap_alignment and session_vwap is None:
                return neutral("Required VWAP reading unavailable.")
            if self.require_candle_alignment:
                body = latest["close"] - number(latest["open"], minimum=.01)
                if (ce_cross and body < 0) or (pe_cross and body > 0):
                    return neutral(f"2m MACD {direction} crossover rejected: Trigger candle opposes crossover.")
            supporting = []
            if session_vwap is None:
                supporting.append("VWAP unavailable; alignment unconfirmed")
            else:
                distance = abs(spot - session_vwap)
                aligned = (ce_cross and spot >= session_vwap) or (pe_cross and spot <= session_vwap)
                supporting.append(f"VWAP {'aligned' if aligned else 'countertrend'}; distance={distance:.1f}pts")
                if self.require_vwap_alignment and (
                    (ce_cross and spot < session_vwap - self.vwap_tolerance_pts)
                    or (pe_cross and spot > session_vwap + self.vwap_tolerance_pts)
                ):
                    return neutral("MACD swing is fighting explicitly required VWAP alignment.")
                if distance >= self.vwap_climax_pts:
                    supporting.append(f"VWAP extension {distance:.1f}pts: AI review required")
            for name in ("ema_9", "ema_20"):
                try:
                    level = number(ctx.get(name), minimum=.01)
                    supporting.append(f"{name}: {'aligned' if (ce_cross and spot >= level) or (pe_cross and spot <= level) else 'countertrend'}")
                except (TypeError, ValueError, OverflowError):
                    supporting.append(f"{name}: unavailable")

            early_orb = self.early_orb_required and now.strftime("%H:%M") < self.early_orb_cutoff_time
            if self.opening_range_filter_enabled or early_orb:
                orh = max(number(b["high"], minimum=.01) for b in candles[:15])
                orl = min(number(b["low"], minimum=.01) for b in candles[:15])
                # Before 10:00 require a completed trigger close outside the OR;
                # testing inside resistance conflicts with the existing 8pt veto.
                if early_orb and ((ce_cross and min(spot, latest["close"]) <= orh)
                                  or (pe_cross and max(spot, latest["close"]) >= orl)):
                    return neutral(f"2m MACD {direction} rejected: Early ORB requires a confirmed opening-range breakout.")
                distance = orh - spot if ce_cross else spot - orl
                if self.opening_range_filter_enabled and 0 <= distance <= self.opening_range_buffer_pts:
                    return neutral(f"2m MACD {direction} cross rejected: Spot is within {self.opening_range_buffer_pts:.1f} pts of Opening Range {'High' if ce_cross else 'Low'}.")
            session_minute = (now - opening).total_seconds() / 60
            if self.midday_enabled and self.midday_start <= session_minute < self.midday_end:
                # Calculate from completed candles; never substitute a permissive default.
                recent_box = candles[-15:]
                spread = max(number(b["high"], minimum=.01) for b in recent_box) - min(
                    number(b["low"], minimum=.01) for b in recent_box
                )
                if spread < self.midday_min_range:
                    return neutral(f"2m MACD crossover stand aside: Midday flatline (15m Range {spread:.1f} pts < {self.midday_min_range:.1f} pts).")
            confirmation = []
            if self.require_ema_confirmation:
                ema9 = number(ctx.get("ema_9"), minimum=.01)
                distance = abs(spot - ema9)
                if distance > self.ema_proximity_pts:
                    return neutral(f"2m MACD {direction} cross rejected: Spot is extended {distance:.2f} pts from 5m EMA9.")
                confirmation.append(f"EMA9 distance {distance:.2f} pts <= {self.ema_proximity_pts:.2f}")
            if self.require_ema20_trend_alignment:
                ema20 = number(ctx.get("ema_20"), minimum=.01)
                if (ce_cross and spot < ema20) or (pe_cross and spot > ema20):
                    return neutral(f"2m MACD {direction} cross rejected: Spot is on the wrong side of 5m EMA20.")
                confirmation.append("EMA20 trend aligned")
            recent = candles[-5:]
            if ce_cross:
                raw = min(number(b["low"], minimum=.01) for b in recent) - 2
                invalidation = min(raw, spot - self.min_invalidation_buffer_pts)
            else:
                raw = max(number(b["high"], minimum=.01) for b in recent) + 2
                invalidation = max(raw, spot + self.min_invalidation_buffer_pts)
            number(invalidation, minimum=.01)
        except (ValueError, TypeError, KeyError, OverflowError):
            return neutral("Required Spot/VWAP/EMA or structural prices are missing, non-finite or invalid.")
        reason = (f"Completed 2m MACD {direction} {setup_label}: MACD={macd[-1]:.2f}, "
                  f"Signal={signal[-1]:.2f}, Histogram={hist[-1]:+.2f}, Spot={spot:.1f}; "
                  f"structure invalidation={invalidation:.1f}; " + "; ".join(supporting + confirmation)
                  + ". Candidate only; Chat Companion must independently approve.")
        return CandidateSignal("BUY_" + direction, [reason], "MACD_2M_MOMENTUM", invalidation)
