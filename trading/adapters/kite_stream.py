"""KiteTicker lifecycle, bounded quote cache and gap-aware in-memory spot candles.

The SDK is imported only when explicitly starting a configured stream. Web mode
uses an existing web session; Connect mode requires an existing data entitlement.
"""

import copy
from datetime import datetime, timedelta
import importlib
import threading
import time
from urllib.parse import urlencode

from market_clock import IST_TZ, MarketClock
from trading.adapters.market_sources import MarketDataError
from trading.domain.market_data import completed_spot_bars, exchange_time, number


class TickStore:
    def __init__(self, *, monotonic=None):
        self.monotonic = monotonic or time.monotonic
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self.connected = False
        self.spot_token = None
        self._quotes = {}
        self._bars = {}
        self._seed = {}
        self._dirty = set()
        self._last_spot = None
        self._day = None
        self._seeded = False

    def _roll(self):
        day = MarketClock.today_ist_str()
        if day != self._day:
            self._quotes.clear()
            self._bars.clear()
            self._seed.clear()
            self._dirty.clear()
            self._last_spot = None
            self._seeded = False
            self._day = day

    def _gap(self, start, end):
        opening = end.replace(hour=9, minute=15, second=0, microsecond=0)
        closing = end.replace(hour=15, minute=30, second=0, microsecond=0)
        cursor = max(opening, start.replace(second=0, microsecond=0))
        while cursor <= end and cursor < closing:
            self._dirty.add(cursor)
            cursor += timedelta(minutes=1)

    def connection(self, connected):
        with self._lock:
            self._roll()
            now = MarketClock.now_ist()
            self._gap(self._last_spot or now, now)
            self.connected = connected
            self._quotes.clear()  # A reconnected socket must deliver new ticks.
            self._changed.notify_all()

    def put(self, tick):
        with self._lock:
            self._roll()
            if not self.connected:
                return
            token = int(number(tick["instrument_token"], minimum=1))
            stamp = exchange_time(tick["timestamp"])
            now = MarketClock.now_ist()
            if stamp.date() != now.date() or not -2 <= (now - stamp).total_seconds() < 20:
                self._quotes.pop(token, None)
                if token == self.spot_token:
                    self._gap(self._last_spot or now, now)
                return
            previous = self._quotes.get(token)
            if previous and stamp < exchange_time(previous["timestamp"]):
                return
            price = number(tick["last_price"], minimum=0.01)
            quote = copy.deepcopy(tick)
            quote.update(timestamp=stamp.isoformat(), _received=self.monotonic())
            self._quotes[token] = quote
            self._changed.notify_all()
            if token != self.spot_token:
                return
            if self._last_spot and (stamp - self._last_spot).total_seconds() >= 20:
                self._gap(self._last_spot, stamp)
            if self._last_spot and stamp < self._last_spot:
                return
            self._last_spot = stamp
            minute = stamp.replace(second=0, microsecond=0)
            if not "09:15" <= minute.strftime("%H:%M") < "15:30":
                return
            if minute not in self._bars:
                self._bars[minute] = dict(
                    start_time=minute.isoformat(), open=price, high=price, low=price, close=price, volume=0
                )
            else:
                bar = self._bars[minute]
                bar.update(high=max(bar["high"], price), low=min(bar["low"], price), close=price)

    def quote(self, token, *, max_age=20):
        with self._lock:
            self._roll()
            quote = self._quotes.get(token)
            if not self.connected or not quote:
                raise MarketDataError("Streaming quote is not ready")
            exchange_age = (MarketClock.now_ist() - exchange_time(quote["timestamp"])).total_seconds()
            received_age = self.monotonic() - quote["_received"]
            if not 0 <= exchange_age < max_age or not 0 <= received_age < max_age:
                raise MarketDataError("Streaming quote is stale")
            return copy.deepcopy({k: v for k, v in quote.items() if not k.startswith("_")})

    def invalidate(self, token):
        with self._lock:
            self._quotes.pop(token, None)
            if token == self.spot_token:
                now = MarketClock.now_ist()
                self._gap(self._last_spot or now, now)

    def wait_quotes(self, tokens, budget, *, max_age=20):
        with self._changed:
            while True:
                try:
                    result = {token: self.quote(token, max_age=max_age) for token in tokens}
                    budget.remaining()
                    return result
                except MarketDataError:
                    self._changed.wait(timeout=min(budget.remaining(), 1.0))

    def seed(self, rows):
        with self._lock:
            self._roll()
            for bar in completed_spot_bars(rows, MarketClock.now_ist()):
                start = exchange_time(bar["start_time"])
                self._seed[start] = bar
                self._dirty.discard(start)
            self._seeded = True

    def history(self):
        with self._lock:
            self._roll()
            if not self._seeded:
                raise MarketDataError("Streaming candle history needs backfill")
            now = MarketClock.now_ist()
            self.quote(self.spot_token)
            minute = now.replace(second=0, microsecond=0)
            bars = dict(self._seed)
            bars.update(
                {
                    start: bar
                    for start, bar in self._bars.items()
                    if start not in self._seed and start not in self._dirty
                }
            )
            opening = now.replace(hour=9, minute=15, second=0, microsecond=0)
            closing = now.replace(hour=15, minute=30, second=0, microsecond=0)
            cursor = opening
            while cursor < min(minute, closing):
                if cursor not in bars or cursor in self._dirty:
                    raise MarketDataError("Streaming candle gap needs backfill")
                cursor += timedelta(minutes=1)
            return copy.deepcopy([bar for start, bar in sorted(bars.items()) if start < minute])


class KiteTickStream:
    def __init__(
        self,
        *,
        transport="web",
        enctoken="",
        user_id="",
        api_key="",
        access_token="",
        ticker_factory=None,
        store=None,
    ):
        if transport not in ("web", "connect"):
            raise ValueError("Kite stream transport must be web or connect")
        self.transport = transport
        self.enctoken, self.user_id = enctoken, user_id
        self.api_key, self.access_token = api_key, access_token
        self.factory = ticker_factory
        self.store = store if store is not None else TickStore()
        self._lock = threading.RLock()
        self._tokens = set()
        self._ticker = None
        self._closed = False

    def _dispatch(self, action):
        ticker = self._ticker
        if ticker is None:
            return
        reactor = getattr(getattr(ticker, "factory", None), "reactor", None)
        if reactor is None and self.factory is None:
            reactor = importlib.import_module("twisted.internet.reactor")
        if reactor is not None:
            reactor.callFromThread(action)
        else:
            # Injected test drivers may execute commands synchronously.
            action()

    def start(self):
        with self._lock:
            if self._closed:
                raise MarketDataError("Kite stream is closed")
            if self._ticker is not None:
                return
            if self.transport == "web" and not (self.enctoken and self.user_id):
                raise MarketDataError("Kite web streaming requires enctoken and account ID")
            if self.transport == "connect" and not (self.api_key and self.access_token):
                raise MarketDataError("Kite Connect streaming credentials are missing")
            try:
                factory = self.factory or importlib.import_module("kiteconnect").KiteTicker
            except ImportError:
                raise MarketDataError("Install requirements-streaming.txt to use Kite streaming") from None
            ticker = factory(
                self.api_key if self.transport == "connect" else "kitefront",
                self.access_token if self.transport == "connect" else "",
                reconnect=True,
                reconnect_max_delay=5,
                connect_timeout=5,
            )
            if self.transport == "web":
                # Existing web-session transport; never silently switch to paid Connect.
                ticker.socket_url = "wss://ws.zerodha.com/?" + urlencode(
                    dict(
                        api_key="kitefront",
                        user_id=self.user_id,
                        enctoken=self.enctoken,
                        uid=str(int(time.time() * 1000)),
                        user_agent="kite3-web",
                        version="3.0.0",
                    )
                )
            ticker.on_ticks = self._on_ticks
            ticker.on_connect = self._on_connect
            ticker.on_close = self._on_disconnect
            ticker.on_error = self._on_disconnect
            ticker.on_reconnect = self._on_disconnect
            ticker.on_noreconnect = self._on_disconnect
            self._ticker = ticker
            try:
                ticker.connect(threaded=True)
            except Exception:
                self.store.connection(False)
                self._ticker = None
                raise MarketDataError("Kite stream connection failed") from None

    def subscribe(self, tokens, *, spot_token=None):
        with self._lock:
            new = set(int(t) for t in tokens) - self._tokens
            if len(self._tokens | new) > 3000:
                raise MarketDataError("Kite streaming subscription limit exceeded")
            self._tokens.update(new)
            if spot_token is not None:
                self.store.spot_token = int(spot_token)
            if new and self.store.connected:
                self._dispatch(lambda: self._subscribe(new))

    def _subscribe(self, tokens):
        if self._ticker is not None and not self._closed:
            self._ticker.subscribe(sorted(tokens))
            self._ticker.set_mode(self._ticker.MODE_FULL, sorted(tokens))

    def _on_connect(self, ticker, response):
        with self._lock:
            if self._closed:
                return
            self.store.connection(True)
            self._subscribe(self._tokens)

    def _on_disconnect(self, *args):
        self.store.connection(False)

    def _on_ticks(self, ticker, ticks):
        for raw in ticks:
            try:
                stamp = raw.get("exchange_timestamp")
                if not isinstance(stamp, datetime):
                    self.store.invalidate(raw.get("instrument_token"))
                    continue  # LTP/quote packets without exchange time are never executable.
                # KiteTicker constructs naive timestamps in the execution host's timezone.
                stamp = datetime.fromtimestamp(stamp.timestamp(), IST_TZ)
                tick = dict(raw, timestamp=stamp.isoformat())
                if "volume_traded" in raw:
                    tick["volume"] = raw["volume_traded"]
                self.store.put(tick)
            except (KeyError, ValueError, TypeError, OverflowError):
                self.store.invalidate(raw.get("instrument_token"))

    def close(self):
        with self._lock:
            self._closed = True
            self.store.connection(False)
            if self._ticker is not None:
                self._dispatch(self._ticker.close)
