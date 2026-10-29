#!/usr/bin/env python3
"""
Institutional Market Clock & Session Time Service for NIFTY 50 Options
======================================================================
Guarantees strict, reliable Indian Standard Time (IST / Asia/Kolkata / UTC+05:30)
awareness across the trading engine regardless of the underlying host OS or cloud timezone.

Capabilities:
1. Explicit Timezone Anchoring: Always operates in UTC+05:30 (Asia/Kolkata).
2. Session Phase Classification:
   - WEEKEND_HALT (Saturday & Sunday)
   - OVERNIGHT_CLOSED (15:30 to 09:00 IST)
   - PRE_MARKET (09:00 to 09:15 IST)
   - OPENING_BUFFER (09:15 to 09:20 IST)
   - MORNING_EXPANSION (09:20 to 11:30 IST)
   - MIDDAY_DEAD_ZONE (11:30 to 13:15 IST - Trap 1 Chop Zone)
   - AFTERNOON_EXPANSION (13:15 to 14:15 IST)
   - LATE_DAY_SQUAREOFF (14:15 to 15:15 IST - Trap 5 Lockout)
   - MANDATORY_EXIT (15:15 to 15:30 IST - EOD Squareoff)
3. True Session Minute Calculation (0 to 375):
   - Replaces fragile array-length proxies (bar_idx).
4. Universal Timestamp Parser:
   - Robustly parses UTC, IST, ISO-8601, and unix timestamps.
5. Trading Permitted Evaluator:
   - Enforces config/trading.json session windows (no_new_trade_before / after).
6. Next Market Open Countdown & Sleep Calculator:
   - Accurately sleeps across overnight hours and weekends to Monday 09:15:00 IST.
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta, time
from typing import Optional, Tuple, Dict, Any, Set
from zoneinfo import ZoneInfo
from contextlib import contextmanager
from contextvars import ContextVar


try:
    IST_TZ = ZoneInfo("Asia/Kolkata")
except Exception:
    IST_TZ = timezone(timedelta(hours=5, minutes=30))

# Market Hours Constants (Indian Standard Time)
MARKET_PRE_OPEN_TIME = time(9, 0, 0)
MARKET_OPEN_TIME = time(9, 15, 0)
MARKET_OPEN_BUFFER_TIME = time(9, 20, 0)
CLIMAX_SPRING_END_TIME = time(11, 15, 0)
MIDDAY_START_TIME = time(11, 30, 0)
MIDDAY_END_TIME = time(13, 15, 0)
MICRO_TRAIL_START_TIME = time(14, 0, 0)
LATE_DAY_LOCKOUT_TIME = time(14, 15, 0)
NO_NEW_TRADE_END_TIME = time(14, 45, 0)
MANDATORY_SQUAREOFF_TIME = time(15, 15, 0)
HARD_SQUAREOFF_TIME = time(15, 20, 0)
MARKET_CLOSE_TIME = time(15, 30, 0)

TOTAL_SESSION_MINUTES = 375  # 09:15 to 15:30 = 6 hours 15 mins = 375 mins
_replay_instant: ContextVar[Optional[datetime]] = ContextVar("market_replay_instant", default=None)


class MarketClock:
    """
    Central Time Authority for NIFTY algorithmic trading.
    Provides uniform, timezone-safe queries for live engine and historical replays.
    """

    @staticmethod
    def now_ist() -> datetime:
        """Return the current datetime strictly localized to Indian Standard Time (IST)."""
        instant = _replay_instant.get()
        return instant if instant is not None else datetime.now(IST_TZ)

    @staticmethod
    @contextmanager
    def at(instant):
        """Scope an explicit replay clock to this context; live callers retain wall time."""
        if isinstance(instant, str) and (len(instant) < 19 or instant[4:5] != "-"):
            raise ValueError("Replay requires a full dated timestamp")
        parsed = MarketClock.parse_to_ist(instant)
        if parsed is None:
            raise ValueError("Invalid replay timestamp")
        token = _replay_instant.set(parsed)
        try:
            yield parsed
        finally:
            _replay_instant.reset(token)

    @staticmethod
    def now_ist_str(format_str: str = "%Y-%m-%d %H:%M:%S IST") -> str:
        """Return formatted IST timestamp string."""
        return MarketClock.now_ist().strftime(format_str)

    @staticmethod
    def today_ist_str() -> str:
        """Return current date in YYYY-MM-DD in IST."""
        return MarketClock.now_ist().strftime("%Y-%m-%d")

    @staticmethod
    def get_exchange_holidays() -> Set[str]:
        """Load configured exchange holidays from config/trading.json."""
        try:
            cfg_p = Path("config/trading.json")
            if cfg_p.exists():
                with open(cfg_p, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                return set(cfg.get("option_selection", {}).get("exchange_holidays", []))
        except Exception:
            pass
        return set()

    @staticmethod
    def parse_to_ist(val: Any) -> Optional[datetime]:
        """
        Robustly parse diverse timestamp formats into an IST-aware datetime object.
        Supports:
        - ISO string with UTC 'Z' or offset ('+00:00', '+05:30')
        - ISO string without timezone ('2026-10-16T09:15:00' or '2026-10-16 09:15:00')
        - Simple time string ('09:15:00', '03:45:00')
        - Unix epoch timestamp (int or float)
        - Already datetime object
        """
        if val is None:
            return None

        if isinstance(val, datetime):
            if val.tzinfo is None:
                # If naive, check if it's likely UTC (< 08:00 hour) or IST
                if val.hour < 8:
                    val = val.replace(tzinfo=timezone.utc)
                    return val.astimezone(IST_TZ)
                return val.replace(tzinfo=IST_TZ)
            return val.astimezone(IST_TZ)

        if isinstance(val, (int, float)):
            # Handle millisecond vs second unix timestamp
            sec = val / 1000.0 if val > 1e11 else float(val)
            return datetime.fromtimestamp(sec, tz=timezone.utc).astimezone(IST_TZ)

        if isinstance(val, str):
            s = val.strip()
            # 1. ISO string with T
            if "T" in s:
                try:
                    dt = datetime.fromisoformat(s)
                    if dt.tzinfo is None:
                        # Infer: if hour < 8, it's UTC market hours (03:45 to 10:00 UTC)
                        if dt.hour < 8:
                            dt = dt.replace(tzinfo=timezone.utc)
                            return dt.astimezone(IST_TZ)
                        return dt.replace(tzinfo=IST_TZ)
                    return dt.astimezone(IST_TZ)
                except Exception:
                    pass

            # 2. Date + Time with space 'YYYY-MM-DD HH:MM:SS'
            if len(s) >= 19 and s[4] == "-" and s[7] == "-" and s[10] == " ":
                try:
                    dt = datetime.fromisoformat(s[:19])
                    if dt.hour < 8:
                        dt = dt.replace(tzinfo=timezone.utc)
                        return dt.astimezone(IST_TZ)
                    return dt.replace(tzinfo=IST_TZ)
                except Exception:
                    pass

            # 3. Time only 'HH:MM:SS' or 'HH:MM'
            parts = s.split(":")
            if len(parts) >= 2:
                try:
                    h, m = int(parts[0]), int(parts[1])
                    sec = int(parts[2].split(".")[0]) if len(parts) > 2 else 0
                    today = MarketClock.now_ist()
                    if h < 8:  # UTC hour -> convert to IST (+5h 30m)
                        total_mins = (h * 60 + m + 330) % 1440
                        h, m = total_mins // 60, total_mins % 60
                    return today.replace(hour=h, minute=m, second=sec, microsecond=0)
                except Exception:
                    pass

        return None

    @staticmethod
    def get_session_minutes(dt: Optional[datetime] = None) -> Tuple[int, int]:
        """
        Calculate minutes from session open (09:15 IST) and minutes to close (15:30 IST).
        Returns:
            (minutes_from_open, minutes_to_close)
            e.g. at 09:15 IST: (0, 375)
            e.g. at 11:30 IST: (135, 240)
            e.g. at 14:15 IST: (300, 75)
            e.g. at 15:30 IST: (375, 0)
        """
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        h, m = now.hour, now.minute

        mins_from_open = (h - 9) * 60 + (m - 15)
        mins_to_close = (15 - h) * 60 + (30 - m)
        return mins_from_open, mins_to_close

    @staticmethod
    def get_session_phase(dt: Optional[datetime] = None) -> str:
        """
        Categorize market phase according to institutional rules.
        """
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()

        # Check weekend
        if now.weekday() in (5, 6):  # Saturday or Sunday
            return "WEEKEND_HALT"

        # Check exchange holiday
        if now.strftime("%Y-%m-%d") in MarketClock.get_exchange_holidays():
            return "EXCHANGE_HOLIDAY"

        t = now.time()

        if t < MARKET_PRE_OPEN_TIME:
            return "OVERNIGHT_CLOSED"
        elif t < MARKET_OPEN_TIME:
            return "PRE_MARKET (09:00 - 09:15)"
        elif t < MARKET_OPEN_BUFFER_TIME:
            return "OPENING_DRIVE (09:15 - 10:15 | Opening Buffer)"
        elif t < time(10, 15, 0):
            return "OPENING_DRIVE (09:15 - 10:15)"
        elif t < MIDDAY_START_TIME:
            return "MORNING_TREND (10:15 - 11:30)"
        elif t < MIDDAY_END_TIME:
            return "MIDDAY_DEAD_ZONE (11:30 - 13:15)"
        elif t < LATE_DAY_LOCKOUT_TIME:
            return "AFTERNOON_EXPANSION (13:15 - 14:15)"
        elif t < MANDATORY_SQUAREOFF_TIME:
            return "LATE_DAY_SQUAREOFF (14:15 - 15:15 | Trap 5 Lockout)"
        elif t < MARKET_CLOSE_TIME:
            return "MANDATORY_EXIT (15:15 - 15:30)"
        else:
            return "POST_MARKET_CLOSED (15:30+)"

    @staticmethod
    def is_market_open(dt: Optional[datetime] = None) -> bool:
        """True strictly during regular market trading hours (09:15:00 to 15:30:00 IST on weekdays)."""
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        if now.weekday() in (5, 6):
            return False
        if now.strftime("%Y-%m-%d") in MarketClock.get_exchange_holidays():
            return False
        return MARKET_OPEN_TIME <= now.time() < MARKET_CLOSE_TIME

    @staticmethod
    def is_climax_spring_window(dt: Optional[datetime] = None) -> bool:
        """True during the opening 2-hour capitulation turn window (09:15 to 11:15 IST / min 0 to 120)."""
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        if now.weekday() in (5, 6):
            return False
        return MARKET_OPEN_TIME <= now.time() <= CLIMAX_SPRING_END_TIME

    @staticmethod
    def is_late_day_micro_trail_active(dt: Optional[datetime] = None) -> bool:
        """True post-14:00 IST when late-day runners must lock in +1% profit floor against EOD theta decay."""
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        return now.time() >= MICRO_TRAIL_START_TIME

    @staticmethod
    def is_mandatory_squareoff_time(dt: Optional[datetime] = None) -> bool:
        """True post-15:15 IST when all intraday MIS positions must be flattened."""
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        return now.time() >= MANDATORY_SQUAREOFF_TIME

    @staticmethod
    def is_hard_cutoff_time(dt: Optional[datetime] = None) -> bool:
        """True post-15:20 IST for hard terminal cancellation."""
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        return now.time() >= HARD_SQUAREOFF_TIME

    @staticmethod
    def is_new_trade_allowed(
        dt: Optional[datetime] = None,
        no_new_trade_before: str = "09:20",
        no_new_trade_after: str = "14:45"
    ) -> Tuple[bool, str]:
        """
        Verifies if initiating a new candidate trade is permitted by market hours and config.
        Returns:
            (is_allowed: bool, reason: str)
        """
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()

        if now.weekday() in (5, 6):
            return False, f"Market CLOSED: Weekend ({now.strftime('%A')}). Zero orders permitted."

        if now.strftime("%Y-%m-%d") in MarketClock.get_exchange_holidays():
            return False, f"Market CLOSED: Exchange Holiday ({now.strftime('%Y-%m-%d')}). Zero orders permitted."

        t = now.time()

        if t < MARKET_OPEN_TIME:
            return False, f"Market PRE-OPEN ({now.strftime('%H:%M:%S')} IST < 09:15:00). Zero orders permitted."

        if t >= MARKET_CLOSE_TIME:
            return False, f"Market CLOSED ({now.strftime('%H:%M:%S')} IST >= 15:30:00). Trading session concluded."

        # Parse config limits
        try:
            b_h, b_m = map(int, no_new_trade_before.split(":"))
            before_t = time(b_h, b_m, 0)
        except Exception:
            before_t = MARKET_OPEN_BUFFER_TIME

        try:
            a_h, a_m = map(int, no_new_trade_after.split(":"))
            after_t = time(a_h, a_m, 0)
        except Exception:
            after_t = NO_NEW_TRADE_END_TIME

        if t < before_t:
            return False, f"OPENING VOLATILITY BUFFER: Current time {now.strftime('%H:%M:%S')} IST < {no_new_trade_before} entry threshold."

        if t >= after_t:
            return False, f"LATE-DAY LOCKOUT: Current time {now.strftime('%H:%M:%S')} IST >= {no_new_trade_after} cutoff. Avoid EOD theta decay."

        if t >= LATE_DAY_LOCKOUT_TIME:
            # Trap 5 late-day degradation zone
            return False, f"TRAP 5 LOCKOUT: Current time {now.strftime('%H:%M:%S')} IST >= 14:15. Institutional block rebalancing in effect."

        return True, "Trading window open."

    @staticmethod
    def get_seconds_until_next_open(dt: Optional[datetime] = None) -> float:
        """
        Calculate total seconds until the next trading session opens (09:15:00 IST).
        Handles:
        - Weekday evenings (sleeps until tomorrow 09:15 IST, skipping holidays)
        - Friday evenings (sleeps across weekend to Monday 09:15 IST)
        - Saturday / Sunday / Exchange Holidays (sleeps until next open working day 09:15 IST)
        - Weekday mornings before 09:15 IST (sleeps until 09:15 today)
        """
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        today_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
        today_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
        holidays = MarketClock.get_exchange_holidays()

        weekday = now.weekday()

        if weekday in (5, 6) or now.strftime("%Y-%m-%d") in holidays:
            next_open = today_open + timedelta(days=1)
            while next_open.weekday() in (5, 6) or next_open.strftime("%Y-%m-%d") in holidays:
                next_open += timedelta(days=1)
        elif now >= today_close:
            # Post market close on weekday
            next_open = today_open + timedelta(days=1)
            while next_open.weekday() in (5, 6) or next_open.strftime("%Y-%m-%d") in holidays:
                next_open += timedelta(days=1)
        elif now < today_open:
            next_open = today_open
        else:
            # Market is currently open!
            return 0.0

        return max(0.0, (next_open - now).total_seconds())

    @staticmethod
    def get_next_open_datetime(dt: Optional[datetime] = None) -> datetime:
        """Return the datetime of the next market open in IST."""
        sec = MarketClock.get_seconds_until_next_open(dt)
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        return now + timedelta(seconds=sec)

    @staticmethod
    def get_market_clock_hud(dt: Optional[datetime] = None) -> str:
        """
        Render a concise, high-visibility Market Clock HUD string for log outputs.
        Example:
        '[IST 11:21:05] | Phase: MIDDAY_DEAD_ZONE | Min: 126/375 | 249m to close | Trading: NO (Chop Zone)'
        """
        now = MarketClock.parse_to_ist(dt) or MarketClock.now_ist()
        phase = MarketClock.get_session_phase(now)
        mins_open, mins_close = MarketClock.get_session_minutes(now)
        allowed, reason = MarketClock.is_new_trade_allowed(now)
        trade_status = "ALLOWED" if allowed else "LOCKED"

        if MarketClock.is_market_open(now):
            return (
                f"[MARKET CLOCK] IST {now.strftime('%H:%M:%S')} | Phase: {phase} | "
                f"Session: Min {max(0, mins_open)}/375 ({mins_close}m to close) | New Trades: {trade_status}"
            )
        else:
            sec_to_open = MarketClock.get_seconds_until_next_open(now)
            hrs = sec_to_open / 3600.0
            return (
                f"[MARKET CLOCK] IST {now.strftime('%H:%M:%S')} | Market CLOSED ({phase}) | "
                f"Next Open: in {hrs:.1f}h ({MarketClock.get_next_open_datetime(now).strftime('%A %Y-%m-%d 09:15')} IST)"
            )


if __name__ == "__main__":
    from trading.bootstrap import configure_console
    configure_console()
    print("=" * 70)
    print("  INSTITUTIONAL MARKET CLOCK DIAGNOSTIC")
    print("=" * 70)
    now = MarketClock.now_ist()
    print(f"Current Local IST Time:     {MarketClock.now_ist_str()}")
    print(f"Session Phase:              {MarketClock.get_session_phase()}")
    mins_from_open, mins_to_close = MarketClock.get_session_minutes()
    print(f"Session Progress:           Min {mins_from_open} of 375 ({mins_to_close} mins to close)")
    print(f"Is Market Open Now:         {MarketClock.is_market_open()}")
    allowed, reason = MarketClock.is_new_trade_allowed()
    print(f"New Trades Allowed:         {allowed} ({reason})")
    sec_to_open = MarketClock.get_seconds_until_next_open()
    print(f"Time Until Next Open:       {sec_to_open:.0f}s ({sec_to_open/3600:.1f} hours)")
    print(f"Next Open Target:           {MarketClock.get_next_open_datetime().strftime('%Y-%m-%d %H:%M:%S %A IST')}")
    print("\n[HUD DISPLAY]:")
    print(MarketClock.get_market_clock_hud())
    print("=" * 70)
