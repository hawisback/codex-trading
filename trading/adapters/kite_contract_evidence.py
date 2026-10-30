"""Read-only NIFTY contract evidence from Kite's master and NSE's freeze CSV.

Only current-session receipts are cached. No fallback lot size or exchange
quantity is manufactured when either authoritative source is unavailable.
"""

import csv
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import io
import json
import time
import urllib.request

from market_clock import MarketClock
from trading.domain.broker_contracts import BrokerContractError, _number
from trading.domain.expiry_evidence import ExpiryEvidence, ExpiryEvidenceError, listed_expiry_contracts

KITE_MASTER_URL = "https://api.kite.trade/instruments/NFO"
NSE_FREEZE_URL = "https://nsearchives.nseindia.com/content/fo/qtyfreeze.csv"
NSE_CALENDAR_URL = "https://www.nseindia.com/api/holiday-master?type=trading"


class KiteContractEvidence:
    def __init__(self, *, opener=None):
        self.opener = opener or urllib.request.urlopen
        self._master = None
        self._freeze = None
        self._calendar = None

    def _read(self, url, maximum):
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "*/*"})
        try:
            with self.opener(request, timeout=10) as response:
                data = response.read(maximum + 1)
            if not data or len(data) > maximum:
                raise ValueError("Invalid source size")
        except Exception:
            raise BrokerContractError("KITE_CONTRACT_SOURCE_UNAVAILABLE") from None
        return data, hashlib.sha256(data).hexdigest()

    def _download(self, url, maximum):
        data, digest = self._read(url, maximum)
        try:
            rows = list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
            rows = [{key.strip(): value.strip() for key, value in row.items()} for row in rows]
            if not rows:
                raise ValueError("Empty CSV")
        except Exception:
            raise BrokerContractError("KITE_CONTRACT_SOURCE_UNAVAILABLE") from None
        return rows, digest

    def _regular_sessions(self, started):
        """Conservative regular weekday sessions; no special-session trading.

        Holiday dates come from the current NSE FO calendar. Expiry dates are
        never generated from weekdays: only exact listed master expiries pass.
        A next-year contract requires that year's authoritative calendar.
        """
        today = started.date()
        if self._calendar is None or self._calendar[0] != today:
            data, digest = self._read(NSE_CALENDAR_URL, 1_000_000)
            try:
                rows = json.loads(data)["FO"]
                if not isinstance(rows, list) or not rows:
                    raise ValueError("No FO calendar")
                holidays = {datetime.strptime(row["tradingDate"], "%d-%b-%Y").date() for row in rows}
                if len(holidays) != len(rows) or any(day.year != today.year for day in holidays):
                    raise ValueError("Wrong calendar year or duplicate dates")
                # A truncated response containing only part of the year must
                # not silently describe all other dates as trading sessions.
                if min(holidays).month != 1 or max(holidays).month != 12:
                    raise ValueError("Incomplete annual calendar")
            except (KeyError, TypeError, ValueError, UnicodeError):
                raise BrokerContractError("NSE_CALENDAR_UNVERIFIED") from None
            first, last = date(today.year, 1, 1), date(today.year + 1, 1, 1)
            sessions = frozenset(
                first + timedelta(days=index)
                for index in range((last - first).days)
                if (first + timedelta(days=index)).weekday() < 5
                and first + timedelta(days=index) not in holidays
            )
            self._calendar = (today, sessions, digest, started.isoformat())
        return self._calendar[1]

    def for_entry(self, instrument_id, symbol, *, lot_size, tick_size):
        started = MarketClock.now_ist()
        today = started.date()
        if self._master is None or self._master[0] != today:
            rows, digest = self._download(KITE_MASTER_URL, 20_000_000)
            self._master = (today, rows, digest, started.isoformat())
        if self._freeze is None or self._freeze[0] != today or time.monotonic() - self._freeze[1] > 300:
            rows, digest = self._download(NSE_FREEZE_URL, 1_000_000)
            self._freeze = (today, time.monotonic(), rows, digest, started.isoformat())
        matches = [row for row in self._master[1] if row.get("tradingsymbol") == symbol]
        if len(matches) != 1:
            raise BrokerContractError("KITE_CONTRACT_IDENTITY_UNVERIFIED")
        row = matches[0]
        if (row.get("name"), row.get("exchange"), row.get("segment")) != ("NIFTY", "NFO", "NFO-OPT"):
            raise BrokerContractError("KITE_CONTRACT_UNSUPPORTED")
        try:
            expiry = date.fromisoformat(row["expiry"])
            strike = _number(row["strike"])
            actual_lot = _number(row["lot_size"])
            actual_tick = _number(row["tick_size"])
        except (KeyError, ValueError):
            raise BrokerContractError("KITE_CONTRACT_FIELDS_INVALID") from None
        if (
            expiry < today
            or row.get("instrument_type") not in ("CE", "PE")
            or strike <= 0
            or strike != int(strike)
        ):
            raise BrokerContractError("KITE_CONTRACT_EXPIRED_OR_INVALID")
        expected = f"INST-NIFTY-{expiry}-{int(strike)}-{row['instrument_type']}"
        if instrument_id not in (expected, symbol):
            raise BrokerContractError("KITE_CONTRACT_IDENTITY_MISMATCH")
        if actual_lot != lot_size or actual_tick != Decimal(str(tick_size)):
            raise BrokerContractError("KITE_CONTRACT_LOT_OR_TICK_CHANGED")
        sessions = self._regular_sessions(started)
        calendar = self._calendar
        if calendar is None:
            raise BrokerContractError("NSE_CALENDAR_UNVERIFIED")
        try:
            evidence = ExpiryEvidence.from_records(
                exchange_source=NSE_CALENDAR_URL,
                exchange_asof=today,
                sessions=sessions,
                broker_source=KITE_MASTER_URL,
                master_asof=self._master[0],
                contracts=[
                    dict(
                        instrument_id=expected,
                        symbol=symbol,
                        strike=int(strike),
                        right=row["instrument_type"],
                        expiry=expiry,
                    )
                ],
            )
            listed_expiry_contracts(evidence, trade_date=today, quote_asof=started)
        except ExpiryEvidenceError as exc:
            raise BrokerContractError(str(exc)) from exc
        freeze_rows = [row for row in self._freeze[2] if row.get("SYMBOL") == "NIFTY"]
        if len(freeze_rows) != 1:
            raise BrokerContractError("NSE_FREEZE_LIMIT_UNVERIFIED")
        limit = _number(freeze_rows[0].get("VOL_FRZ_QTY"))
        if limit <= 0 or limit != int(limit) or limit % actual_lot != 0:
            raise BrokerContractError("NSE_FREEZE_LIMIT_INVALID")
        if MarketClock.now_ist().date() != today:
            raise BrokerContractError("KITE_CONTRACT_SESSION_CHANGED")
        return {
            "max_single_order_quantity": int(limit),
            "expiry_sessions_remaining": sum(today < session <= expiry for session in sessions),
            "contract_evidence": {
                "instrument_id": instrument_id,
                "symbol": symbol,
                "expiry": expiry.isoformat(),
                "lot_size": int(actual_lot),
                "tick_size": str(actual_tick),
                "master_source": KITE_MASTER_URL,
                "master_sha256": self._master[2],
                "master_received_at": self._master[3],
                "freeze_source": NSE_FREEZE_URL,
                "freeze_sha256": self._freeze[3],
                "freeze_received_at": self._freeze[4],
                "calendar_source": NSE_CALENDAR_URL,
                "calendar_sha256": calendar[2],
                "calendar_received_at": calendar[3],
            },
        }
