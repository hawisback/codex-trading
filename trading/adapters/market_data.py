"""The engine's six market-data capabilities, executed in this process."""

import copy
from datetime import timedelta
import math
import os
import threading
import time
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from market_clock import MarketClock
from trading.adapters.market_sources import (
    BreezeMarketSource,
    HEAVYWEIGHTS,
    InstrumentMaster,
    KiteSessionSource,
    MarketDataError,
    ReadBudget,
    SPOT,
    VIX,
    SECTORS,
)
from trading.bootstrap import ensure_environment
from trading.domain.market_data import (
    completed_spot_bars,
    exchange_time,
    number,
    resample_five_minutes,
    technical_metrics,
    two_minute_macd_metrics,
    prior_session_warmup,
    macd_observation_bars,
)


class BrokerMarketData:
    requires_complete_context = True

    def __init__(self, source, *, master=None, max_age_sec=20, timeout_sec=30):
        self.source = source
        self.master = master if master is not None else InstrumentMaster()
        self.max_age_sec = number(max_age_sec, minimum=0.01)
        if self.max_age_sec > 20:
            raise ValueError("Market-data freshness cannot exceed 20 seconds")
        self.timeout_sec = number(timeout_sec, minimum=0.01)
        self._lock = threading.RLock()
        self._history_minute = None
        self._history = []
        self._warmup_key = None
        self._warmup = []

    def _budget(self, timeout):
        return ReadBudget(self.timeout_sec if timeout is None else timeout)

    def _fresh(self, timestamp):
        stamp = exchange_time(timestamp)
        age = (MarketClock.now_ist() - stamp).total_seconds()
        if age < -2 or age >= self.max_age_sec:
            raise MarketDataError("Market quote timestamp is stale or in the future")
        if stamp.date() != MarketClock.now_ist().date():
            raise MarketDataError("Market quote is from another session")
        return stamp, max(0.0, age)

    def _snapshot(self, budget, quotes=None):
        quote = (quotes if quotes is not None else self.source.quotes([SPOT], budget))[SPOT]
        stamp, age = self._fresh(quote["timestamp"])
        underlying = {
            k: number(quote[k], minimum=0.01) for k in ("last_price", "open", "high", "low", "close")
        }
        if underlying["high"] < underlying["low"]:
            raise MarketDataError("Invalid spot day range")
        underlying.update(
            symbol=SPOT, change_pct=round((underlying["last_price"] / underlying["close"] - 1) * 100, 4)
        )
        return {"underlying": underlying}, stamp, age

    def get_data_quality(self, *, timeout=None):
        with self._lock:
            try:
                _, stamp, age = self._snapshot(self._budget(timeout))
                return dict(
                    quote_ready=True,
                    market_feed=dict(status="LIVE", latency_sec=age, last_tick_time=stamp.isoformat()),
                )
            except Exception:
                return dict(
                    quote_ready=False,
                    market_feed=dict(status="UNAVAILABLE", latency_sec=999.0, last_tick_time=None),
                )

    def get_snapshot(self, *, timeout=None, scope="full"):
        if scope not in ("full", "vix", "spot"):
            raise ValueError("Snapshot scope must be full, vix or spot")
        with self._lock:
            budget = self._budget(timeout)
            if scope != "full":
                result = self._snapshot(budget)[0]
                if scope == "vix":
                    try:
                        result["vix"] = self._index_quote(VIX, self.source.quotes([VIX], budget)[VIX])
                    except Exception:
                        pass  # Exposure management retains spot when VIX is unavailable.
                return result
            quotes = self.source.quotes([SPOT, VIX, *SECTORS.values()], budget)
            result = self._snapshot(budget, quotes)[0]
            result["vix"] = self._index_quote(VIX, quotes[VIX])
            result["sectors"] = {
                key: self._index_quote(symbol, quotes[symbol]) for key, symbol in SECTORS.items()
            }
            budget.remaining()
            return result

    def _index_quote(self, symbol, quote):
        stamp, _ = self._fresh(quote["timestamp"])
        price, close = number(quote["last_price"], minimum=0.01), number(quote["close"], minimum=0.01)
        return dict(
            symbol=symbol,
            last_price=price,
            change_pct=round((price / close - 1) * 100, 4),
            timestamp=stamp.isoformat(),
        )

    def get_vix(self, *, timeout=None):
        with self._lock:
            return self._index_quote(VIX, self.source.quotes([VIX], self._budget(timeout))[VIX])

    def get_sectors(self, *, timeout=None):
        with self._lock:
            quotes = self.source.quotes(list(SECTORS.values()), self._budget(timeout))
            return {key: self._index_quote(symbol, quotes[symbol]) for key, symbol in SECTORS.items()}

    def _resolve_contract(self, instrument_id, budget):
        contracts = self.master.options(budget)
        matches = [
            c
            for c in contracts
            if instrument_id
            in (
                c["symbol"],
                f"NFO:{c['symbol']}",
                f"INST-NIFTY-{c['expiry']}-{int(c['strike'])}-{c['right']}",
            )
        ]
        if len(matches) != 1:
            raise MarketDataError("Option identity is unavailable or ambiguous in instrument master")
        return matches[0]

    def get_contract_quote(self, instrument_id, *, timeout_sec=3.0):
        """Native executable top-of-book plus any available broker depth levels."""
        started = time.monotonic()
        try:
            with self._lock:
                budget = self._budget(timeout_sec)
                if instrument_id in ("INST-NIFTY-INDEX", SPOT, "NSE:NIFTY 50"):
                    snapshot, stamp, _ = self._snapshot(budget)
                    return dict(
                        instrument_id=instrument_id,
                        last_price=snapshot["underlying"]["last_price"],
                        timestamp=stamp.isoformat(),
                        status="LIVE",
                        request_started_monotonic=started,
                        received_monotonic=time.monotonic(),
                    )
                contract = self._resolve_contract(str(instrument_id), budget)
                raw = self.source.depth(contract, budget)
                stamp, age = self._fresh(raw["timestamp"])
                if age >= 3.0 or stamp > MarketClock.now_ist():
                    raise MarketDataError("Executable option depth is at least three seconds old")
                depth = raw["depth"]
                sides: dict[str, list[dict[str, Any]]] = {}
                for side in ("buy", "sell"):
                    levels = depth[side]
                    if not isinstance(levels, list) or not levels:
                        raise MarketDataError("Option depth has no executable liquidity")
                    sides[side] = []
                    for level in levels[:5]:
                        price = number(level["price"], minimum=0)
                        qty = number(level["quantity"], minimum=0)
                        if qty != int(qty):
                            raise MarketDataError("Invalid option depth quantity")
                        sides[side].append(dict(price=price, quantity=int(qty)))
                bid, ask = sides["buy"][0], sides["sell"][0]
                if (
                    bid["price"] <= 0
                    or ask["price"] < bid["price"]
                    or min(bid["quantity"], ask["quantity"]) <= 0
                ):
                    raise MarketDataError("Invalid or crossed option book")
                if any(
                    abs(price / 0.05 - round(price / 0.05)) > 1e-7 for price in (bid["price"], ask["price"])
                ):
                    raise MarketDataError("Option book price is off tick")
                budget.remaining()
                return dict(
                    instrument_id=instrument_id,
                    symbol=contract["symbol"],
                    best_bid=bid["price"],
                    best_ask=ask["price"],
                    best_bid_qty=bid["quantity"],
                    best_ask_qty=ask["quantity"],
                    depth=sides,
                    timestamp=stamp.isoformat(),
                    status="LIVE",
                    request_started_monotonic=started,
                    received_monotonic=time.monotonic(),
                )
        except Exception:
            return dict(
                error=True,
                detail="OPTION_DEPTH_UNAVAILABLE",
                instrument_id=instrument_id,
                status="UNAVAILABLE",
            )

    def get_entry_quotes(self, instrument_id, *, include_index=False, timeout_sec=3.0):
        budget = self._budget(timeout_sec)
        quote = self.get_contract_quote(instrument_id, timeout_sec=budget.remaining())
        spot = None
        if include_index and not quote.get("error"):
            try:
                spot = self.get_contract_quote("INST-NIFTY-INDEX", timeout_sec=budget.remaining())
            except TimeoutError:
                spot = {"error": True, "detail": "MARKET_DATA_READ_BUDGET_EXHAUSTED"}
        return {"quote": quote, "spot_quote": spot}

    def close(self):
        close = getattr(self.source, "close", None)
        if close is not None:
            close()

    def _bars(self, budget):
        now = MarketClock.now_ist()
        minute = now.replace(second=0, microsecond=0)
        if minute != self._history_minute:
            rows = self.source.history(
                now.replace(hour=9, minute=15, second=0, microsecond=0) - timedelta(days=10), now, budget
            )
            bars = completed_spot_bars(rows, now)
            opening = now.replace(hour=9, minute=15, second=0, microsecond=0)
            closing = now.replace(hour=15, minute=30, second=0, microsecond=0)
            end = min(minute, closing)
            today = [b for b in bars if exchange_time(b["start_time"]).date() == now.date()]
            count = max(0, int((end - opening).total_seconds() // 60))
            expected = [opening + timedelta(minutes=i) for i in range(count)]
            if not today or [exchange_time(b["start_time"]) for b in today] != expected:
                raise MarketDataError("NIFTY spot session candles are stale, incomplete, or contain gaps")
            self._history, self._history_minute = bars, minute
        return self._history

    def get_candles(self, interval="1m", limit=375, *, timeout=None):
        if interval not in ("1m", "5m") or isinstance(limit, bool) or not 1 <= int(limit) <= 375:
            raise ValueError("Candles require interval 1m/5m and limit 1..375")
        with self._lock:
            bars = self._bars(self._budget(timeout))
            if interval == "1m":
                today = MarketClock.today_ist_str()
                bars = [b for b in bars if b["start_time"].startswith(today)]
            else:
                bars = resample_five_minutes(bars)
            return {"candles": copy.deepcopy(bars[-int(limit) :])}

    def get_technicals(self, interval="5m", limit=50, *, timeout=None):
        if interval != "5m" or not 50 <= int(limit) <= 375:
            raise ValueError("Technicals require interval 5m and limit 50..375")
        candles = self.get_candles("5m", limit, timeout=timeout)["candles"]
        return {"metrics": technical_metrics(candles)}

    def get_prior_session_warmup(self, *, holidays=(), timeout=None):
        """Read-only premarket/session cache, independent of today's feed health."""
        with self._lock:
            now = MarketClock.now_ist()
            key = (now.date(), tuple(sorted(holidays)))
            if key != self._warmup_key:
                opening = now.replace(hour=9, minute=15, second=0, microsecond=0)
                history = getattr(self.source, "warmup_history", self.source.history)
                rows = history(opening - timedelta(days=14), opening, self._budget(timeout))
                bars = completed_spot_bars(rows, opening)
                self._warmup = prior_session_warmup(bars, now, holidays=holidays)
                self._warmup_key = key
            return copy.deepcopy(self._warmup)

    def get_strike_macd(
        self,
        instrument_id,
        *,
        as_of=None,
        timeout=None,
        use_rolling_2m=False,
        warmup_enabled=False,
        holidays=(),
        periods=(12, 26, 9),
    ):
        """Read the exact option token's session candles; never substitute Spot.

        Kite native history is currently supported. Unsupported sources and
        incomplete/stale history raise so the dossier can report unavailable data.
        as_of freezes the observation at the same completed candle as Spot.
        """
        with self._lock:
            now = MarketClock.now_ist()
            cutoff = exchange_time(as_of) if as_of is not None else now
            if cutoff > now or cutoff.date() != now.date():
                raise MarketDataError("Invalid option MACD observation time")
            history = getattr(self.source, "_history", None)
            if history is None:
                raise MarketDataError("Option minute history is unsupported by this market-data source")
            budget = self._budget(timeout)
            contract = self._resolve_contract(str(instrument_id), budget)
            opening = cutoff.replace(hour=9, minute=15, second=0, microsecond=0)
            rows = history(
                contract["token"],
                "minute",
                opening - timedelta(days=14) if warmup_enabled else opening,
                cutoff,
                budget,
            )
            completed = completed_spot_bars(rows, cutoff)
            minutes = [bar for bar in completed if exchange_time(bar["start_time"]).date() == cutoff.date()]
            expected_minutes = [
                opening + timedelta(minutes=i) for i in range(int((cutoff - opening).total_seconds() // 60))
            ]
            if [exchange_time(bar["start_time"]) for bar in minutes] != expected_minutes:
                raise MarketDataError("Selected option current-session minute history is incomplete")
            prior = prior_session_warmup(completed, cutoff, holidays=holidays) if warmup_enabled else []
            bars = macd_observation_bars(minutes, prior=prior, as_of=cutoff, rolling=use_rolling_2m)
            cadence = 60 if use_rolling_2m else 120
            expected_close = opening + timedelta(
                seconds=cadence * int((cutoff - opening).total_seconds() // cadence)
            )
            if (
                not bars
                or exchange_time(bars[-1]["start_time"]) + timedelta(minutes=2) != expected_close
                or now - expected_close >= timedelta(minutes=3)
            ):
                raise MarketDataError("Option two-minute candles are stale or incomplete")
            metrics = two_minute_macd_metrics(bars, periods=periods, rolling=use_rolling_2m)
            budget.remaining()
            return dict(
                metrics,
                instrument_id=str(instrument_id),
                symbol=contract["symbol"],
                strike=contract["strike"],
                right=contract["right"],
                expiry=contract["expiry"],
            )

    def get_options(self, strike_window=10, expiry=None, *, timeout=None):
        window = int(strike_window)
        if isinstance(strike_window, bool) or not 0 <= window <= 30:
            raise ValueError("Strike window must be between 0 and 30")
        with self._lock:
            budget = self._budget(timeout)
            spot = self._snapshot(budget)[0]["underlying"]["last_price"]
            atm = int(math.floor(spot / 50 + 0.5)) * 50
            instruments = self.master.options(budget)
            expiries = sorted({c["expiry"] for c in instruments})
            expiry = expiry or expiries[0]
            if expiry not in expiries:
                raise MarketDataError("Requested NIFTY expiry is not in the current instrument master")
            strikes = [atm + i * 50 for i in range(-window, window + 1)]
            contracts = [c for c in instruments if c["expiry"] == expiry and c["strike"] in strikes]
            if len(contracts) != len(strikes) * 2:
                raise MarketDataError("Requested option strike window is incomplete")
            quotes = self.source.option_quotes(contracts, expiry, budget)
            result: dict[int, dict[str, Any]] = {strike: {"strike": strike} for strike in strikes}
            totals = {side: {"oi": 0.0, "volume": 0.0} for side in ("CE", "PE")}
            for contract in contracts:
                quote = quotes[contract["symbol"]]
                self._fresh(quote["timestamp"])
                leg = dict(
                    instrument_id=f"INST-NIFTY-{expiry}-{int(contract['strike'])}-{contract['right']}",
                    symbol=contract["symbol"],
                    ltp=number(quote["ltp"], minimum=0.01),
                    open_interest=number(quote["open_interest"], minimum=0),
                    oi_change=number(quote["oi_change"]),
                    volume=number(quote["volume"], minimum=0),
                    timestamp=exchange_time(quote["timestamp"]).isoformat(),
                )
                for field in ("bid", "ask"):
                    if quote.get(field) is not None:
                        leg[field] = number(quote[field], minimum=0)
                result[contract["strike"]]["call" if contract["right"] == "CE" else "put"] = leg
                totals[contract["right"]]["oi"] += leg["open_interest"]
                totals[contract["right"]]["volume"] += leg["volume"]
            # Recheck after all baseline/history reads; a slow chain must not appear current.
            for quote in quotes.values():
                self._fresh(quote["timestamp"])
            budget.remaining()
            calls, puts = totals["CE"], totals["PE"]
            return dict(
                atm_strike=atm,
                expiry=expiry,
                summary=dict(
                    pcr_oi=puts["oi"] / calls["oi"] if calls["oi"] else None,
                    pcr_volume=puts["volume"] / calls["volume"] if calls["volume"] else None,
                ),
                strikes=[result[strike] for strike in strikes],
            )

    def get_heavyweights(self, *, timeout=None):
        with self._lock:
            quotes = self.source.quotes(HEAVYWEIGHTS, self._budget(timeout))
            stocks = []
            for symbol in HEAVYWEIGHTS:
                quote = quotes[symbol]
                self._fresh(quote["timestamp"])
                price, close = number(quote["last_price"], minimum=0.01), number(quote["close"], minimum=0.01)
                stocks.append(
                    dict(symbol=symbol, last_price=price, change_pct=round((price / close - 1) * 100, 4))
                )
            return {"stocks": stocks}

    def __call__(self, path, timeout=None):
        """Compatibility for MarketReader: dispatch Python calls, never HTTP endpoints."""
        parsed = urlsplit(path)
        if parsed.scheme or parsed.netloc:
            raise ValueError("MarketReader accepts capability names, not URLs")
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        methods = {
            "/data-quality": self.get_data_quality,
            "/nifty/snapshot": self.get_snapshot,
            "/nifty/candles": self.get_candles,
            "/nifty/technicals": self.get_technicals,
            "/nifty/options": self.get_options,
            "/heavyweights": self.get_heavyweights,
            "/vix": self.get_vix,
            "/sectors": self.get_sectors,
        }
        if parsed.path.startswith("/market/quote/"):
            return self.get_contract_quote(
                unquote(parsed.path[len("/market/quote/") :]),
                timeout_sec=self.timeout_sec if timeout is None else timeout,
            )
        if parsed.path not in methods:
            raise ValueError("Unsupported local market-data capability")
        return methods[parsed.path](**query, timeout=timeout)


def create_market_data(broker=None, *, gateway=None, **kwargs):
    ensure_environment()
    selected = (broker or os.getenv("MARKET_DATA_BROKER", "kite")).lower().strip()
    source: KiteSessionSource | BreezeMarketSource
    if selected == "kite":
        transport = os.getenv("MARKET_DATA_STREAMING", "off").lower().strip()
        if transport not in ("off", "web", "connect"):
            raise ValueError("MARKET_DATA_STREAMING must be off, web or connect")
        rest_transport = (
            os.getenv("MARKET_DATA_TRANSPORT", "connect" if transport == "connect" else "web").lower().strip()
        )
        if transport != "off" and rest_transport != transport:
            raise ValueError("Kite REST and streaming transports must match")
        source = KiteSessionSource(transport=rest_transport)
        if transport != "off":
            from trading.adapters.kite_stream import KiteTickStream

            source.stream = KiteTickStream(
                transport=transport,
                enctoken=source.enctoken,
                user_id=source.user_id,
                api_key=os.getenv("KITE_API_KEY", ""),
                access_token=os.getenv("KITE_ACCESS_TOKEN", ""),
            )
    elif selected == "breeze":
        source = BreezeMarketSource(gateway if getattr(gateway, "broker_name", None) == "breeze" else None)
    else:
        raise ValueError("MARKET_DATA_BROKER must be kite or breeze")
    master = InstrumentMaster(os.getenv("MARKET_INSTRUMENTS_FILE") or None)
    return BrokerMarketData(
        source, master=master, timeout_sec=float(os.getenv("MARKET_DATA_TIMEOUT_SEC", "30")), **kwargs
    )
