"""Read-only broker ingestion using configured sessions; no local API server or order calls."""

from contextlib import contextmanager
import csv
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from market_clock import IST_TZ, MarketClock
from trading.adapters.gateways.breeze import BreezeExecutionGateway, expiry_date
from trading.adapters.gateways.rate_limiter import TokenBucketRateLimiter
from trading.domain.market_data import exchange_time, number

ROOT = Path(__file__).resolve().parents[2]
HEAVYWEIGHTS = ("HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "TCS")
SPOT = "NIFTY 50"
VIX = "INDIA VIX"
SECTORS = {"BANKNIFTY": "NIFTY BANK", "NIFTYIT": "NIFTY IT"}


class MarketDataError(RuntimeError):
    pass


class ReadBudget:
    def __init__(self, seconds):
        self.deadline = time.monotonic() + number(seconds, minimum=0.001)

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Market-data read budget exhausted")
        return remaining


def workspace_file(value):
    path = (ROOT / value).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("Market data files must stay inside the workspace")
    return path


class InstrumentMaster:
    """Daily public Zerodha NFO master supplies exact symbols for either data broker."""

    def __init__(self, path=None, *, opener=None):
        self.path = workspace_file(path) if path else None
        self.opener = opener or urllib.request.urlopen
        self._day = None
        self._rows = []

    def options(self, budget):
        today = MarketClock.today_ist_str()
        if self._day == today:
            return self._rows
        if self.path:
            # An explicit file is operator-managed; never silently fetch a replacement.
            if datetime.fromtimestamp(self.path.stat().st_mtime, IST_TZ).date().isoformat() != today:
                raise MarketDataError("Instrument master file is not from today's session")
            content = self.path.read_text(encoding="utf-8-sig")
        else:
            request = urllib.request.Request("https://api.kite.trade/instruments/NFO")
            try:
                with self.opener(request, timeout=budget.remaining()) as response:
                    content = response.read(20_000_001).decode("utf-8-sig")
            except Exception:
                raise MarketDataError("Instrument master download failed") from None
        rows = []
        for raw in csv.DictReader(io.StringIO(content)):
            if raw.get("name") != "NIFTY" or raw.get("segment") != "NFO-OPT" or raw.get("exchange") != "NFO":
                continue
            if raw.get("instrument_type") not in ("CE", "PE"):
                continue
            expiry = expiry_date(raw["expiry"])
            if expiry >= today:
                strike = number(raw["strike"], minimum=1)
                token = int(number(raw["instrument_token"], minimum=1))
                symbol = raw["tradingsymbol"]
                if not symbol or not symbol.startswith("NIFTY"):
                    raise MarketDataError("Invalid NIFTY trading symbol in instrument master")
                rows.append(
                    dict(
                        expiry=expiry, strike=strike, right=raw["instrument_type"], symbol=symbol, token=token
                    )
                )
        if not rows:
            raise MarketDataError("No active NIFTY options in instrument master")
        identities = [(r["expiry"], r["strike"], r["right"]) for r in rows]
        if len(set(identities)) != len(identities):
            raise MarketDataError("Ambiguous NIFTY instrument master")
        self._day, self._rows = today, rows
        return rows


class KiteSessionSource:
    """Read through an explicitly selected existing Kite web or Connect session."""

    broker_name = "kite"

    def __init__(
        self,
        enctoken=None,
        user_id=None,
        *,
        opener=None,
        stream=None,
        transport="web",
        api_key=None,
        access_token=None,
    ):
        if transport not in ("web", "connect"):
            raise ValueError("Kite REST transport must be web or connect")
        self.enctoken = enctoken or os.getenv("KITE_ENCTOKEN", "")
        self.user_id = user_id or os.getenv("KITE_ACCOUNT_ID", "")
        self.transport = transport
        self.api_key = api_key or os.getenv("KITE_API_KEY", "")
        self.access_token = access_token or os.getenv("KITE_ACCESS_TOKEN", "")
        self.opener = opener or urllib.request.urlopen
        self.quote_limiter = TokenBucketRateLimiter(1, 1)
        self.history_limiter = TokenBucketRateLimiter(3, 1)
        self._baselines = {}
        self._spot_token = None
        self.stream = stream
        self._quote_tokens = {}
        self._token_day = None

    def _raw_quotes(self, keys, budget, *, max_age=20):
        if self.stream is None:
            return self._get("/quote", {"i": keys}, budget)
        if self._token_day != MarketClock.today_ist_str():
            self._quote_tokens.clear()
            self._token_day = MarketClock.today_ist_str()
        unknown = [key for key in keys if key not in self._quote_tokens]
        if unknown:
            raw = self._get("/quote", {"i": unknown}, budget)
            for key in unknown:
                self._quote_tokens[key] = int(number(raw[key]["instrument_token"], minimum=1))
        self.stream.subscribe(
            [self._quote_tokens[key] for key in keys], spot_token=self._quote_tokens.get("NSE:" + SPOT)
        )
        self.stream.start()
        quotes = self.stream.store.wait_quotes(
            [self._quote_tokens[key] for key in keys], budget, max_age=max_age
        )
        return {key: quotes[self._quote_tokens[key]] for key in keys}

    def _register_options(self, contracts):
        if self.stream is not None:
            if self._token_day != MarketClock.today_ist_str():
                self._quote_tokens.clear()
                self._token_day = MarketClock.today_ist_str()
            self._quote_tokens.update({"NFO:" + c["symbol"]: c["token"] for c in contracts})
            self.stream.subscribe([c["token"] for c in contracts])
            self.stream.start()

    def _get(self, endpoint, params, budget):
        connect_stream = self.stream is not None and self.stream.transport == "connect"
        connect = self.transport == "connect" or connect_stream
        if connect:
            key = self.stream.api_key if connect_stream else self.api_key
            token = self.stream.access_token if connect_stream else self.access_token
            if not key or not token:
                raise MarketDataError("Kite Connect market-data credentials are missing")
            base = "https://api.kite.trade"
            authorization = f"token {key}:{token}"
        elif not self.enctoken or not self.user_id:
            raise MarketDataError(
                "KITE_ENCTOKEN and KITE_ACCOUNT_ID are required for direct Kite market data"
            )
        else:
            base = "https://kite.zerodha.com/oms"
            authorization = "enctoken " + self.enctoken
        limiter = self.quote_limiter if endpoint == "/quote" else self.history_limiter
        if not limiter.acquire(timeout=budget.remaining()):
            raise TimeoutError("Kite market-data pacing budget exhausted")
        url = base + endpoint + "?" + urllib.parse.urlencode(params, doseq=True)
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": authorization,
                "Accept": "application/json",
                "X-Kite-Version": "3",
            },
        )
        try:
            with self.opener(request, timeout=budget.remaining()) as response:
                result = json.loads(response.read(20_000_001).decode("utf-8"))
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise MarketDataError(
                f"Kite market-data HTTP {code}; check the configured session and data access"
            ) from None
        except Exception:
            raise MarketDataError("Kite market-data read failed") from None
        budget.remaining()
        if not isinstance(result, dict) or result.get("status") != "success" or "data" not in result:
            raise MarketDataError("Invalid Kite market-data response")
        return result["data"]

    def quotes(self, symbols, budget):
        keys = {symbol: "NSE:" + symbol for symbol in symbols}
        raw = self._raw_quotes(list(keys.values()), budget)
        result = {}
        for symbol, key in keys.items():
            q = raw[key]
            if symbol == SPOT:
                self._spot_token = int(number(q["instrument_token"], minimum=1))
            result[symbol] = dict(q["ohlc"], last_price=q["last_price"], timestamp=q["timestamp"])
        return result

    def _history(self, token, interval, start, end, budget):
        result = self._get(
            f"/instruments/historical/{token}/{interval}",
            {
                "from": start.strftime("%Y-%m-%d %H:%M:%S"),
                "to": end.strftime("%Y-%m-%d %H:%M:%S"),
                "oi": 1,
                "user_id": self.user_id,
            },
            budget,
        )
        if not isinstance(result, dict) or not isinstance(result.get("candles"), list):
            raise MarketDataError("Invalid Kite historical candles")
        return result["candles"]

    def history(self, start, end, budget):
        if self.stream is not None:
            self.quotes([SPOT], budget)
            try:
                return self.stream.store.history()
            except MarketDataError:
                rows = self._history(self._spot_token, "minute", start, end, budget)
                self.stream.store.seed(rows)
                return self.stream.store.history()
        if self._spot_token is None:
            self.quotes([SPOT], budget)
        return self._history(self._spot_token, "minute", start, end, budget)

    def warmup_history(self, start, end, budget):
        """Prior-session REST history even when the live stream has today's bars."""
        if self._spot_token is None:
            self.quotes([SPOT], budget)
        return self._history(self._spot_token, "minute", start, end, budget)

    def option_quotes(self, contracts, expiry, budget):
        self._register_options(contracts)
        today = MarketClock.today_ist_str()
        now = MarketClock.now_ist()
        for contract in contracts:
            symbol = contract["symbol"]
            key = (today, symbol)
            if key not in self._baselines:
                bars = self._history(
                    contract["token"],
                    "day",
                    now - timedelta(days=10),
                    now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(seconds=1),
                    budget,
                )
                prior = [bar for bar in bars if len(bar) >= 7 and exchange_time(bar[0]).date() < now.date()]
                if not prior:
                    raise MarketDataError("Previous-session option OI is unavailable")
                latest = max(prior, key=lambda bar: exchange_time(bar[0]))
                self._baselines[key] = number(latest[6], minimum=0)
        # Baseline warm-up can take several seconds. Fetch current quotes afterwards.
        raw = self._raw_quotes(["NFO:" + c["symbol"] for c in contracts], budget)
        result = {}
        for contract in contracts:
            symbol = contract["symbol"]
            quote = raw["NFO:" + symbol]
            oi = number(quote["oi"], minimum=0)
            depth = quote.get("depth") or {}
            buy, sell = depth.get("buy") or [], depth.get("sell") or []
            result[symbol] = dict(
                ltp=quote["last_price"],
                open_interest=oi,
                oi_change=oi - self._baselines[(today, symbol)],
                volume=quote["volume"],
                timestamp=quote["timestamp"],
                bid=buy[0].get("price") if buy else None,
                ask=sell[0].get("price") if sell else None,
            )
        return result

    def depth(self, contract, budget):
        self._register_options([contract])
        quote = self._raw_quotes(["NFO:" + contract["symbol"]], budget, max_age=1)[
            "NFO:" + contract["symbol"]
        ]
        return dict(quote, timestamp=quote["timestamp"])

    def close(self):
        if self.stream is not None:
            self.stream.close()


class BreezeMarketSource:
    broker_name = "breeze"
    STOCK_CODES = {
        SPOT: "NIFTY",
        VIX: "INDVIX",
        "NIFTY BANK": "CNXBAN",
        "NIFTY IT": "CNXIT",
        "HDFCBANK": "HDFBAN",
        "RELIANCE": "RELIND",
        "ICICIBANK": "ICIBAN",
        "INFY": "INFTEC",
        "TCS": "TCS",
    }

    def __init__(self, gateway=None, *, stock_codes=None):
        self.gateway = gateway if gateway is not None else BreezeExecutionGateway()
        self.stock_codes = dict(self.STOCK_CODES, **(stock_codes or {}))

    @contextmanager
    def _read(self, budget):
        with self.gateway._lock, self.gateway.read_budget(budget.remaining()):
            self.gateway._ensure_verified()
            yield
        budget.remaining()

    def quotes(self, symbols, budget):
        result = {}
        with self._read(budget):
            for symbol in symbols:
                code = self.stock_codes[symbol]
                rows = self.gateway._request(
                    "GET",
                    "/quotes",
                    {
                        "stock_code": code,
                        "exchange_code": "NSE",
                        "product_type": "cash",
                        "expiry_date": "",
                        "right": "others",
                        "strike_price": "0",
                    },
                    timeout=budget.remaining(),
                )
                if not isinstance(rows, list) or len(rows) != 1:
                    raise MarketDataError("Breeze cash quote unavailable")
                q = rows[0]
                if str(q["stock_code"]).upper() != code or str(q["exchange_code"]).upper() != "NSE":
                    raise MarketDataError("Breeze cash quote identity mismatch")
                result[symbol] = dict(
                    last_price=q["ltp"],
                    open=q["open"],
                    high=q["high"],
                    low=q["low"],
                    close=q["previous_close"],
                    timestamp=q["ltt"],
                )
        return result

    def history(self, start, end, budget):
        with self._read(budget):
            result = self.gateway.get_historical_candles(
                "INST-NIFTY-INDEX", start.isoformat(), end.isoformat(), interval="1m"
            )
        if result.get("error") or not isinstance(result.get("candles"), list):
            raise MarketDataError("Breeze NIFTY spot history unavailable")
        rows = result["candles"]
        for row in rows:
            if (
                str(row.get("stock_code", "NIFTY")).upper() != "NIFTY"
                or str(row.get("exchange_code", "NSE")).upper() != "NSE"
            ):
                raise MarketDataError("Breeze history is not NIFTY spot")
        return rows

    def option_quotes(self, contracts, expiry, budget):
        wanted = {(c["strike"], c["right"]): c for c in contracts}
        result = {}
        with self._read(budget):
            for right, side in (("call", "CE"), ("put", "PE")):
                chain = self.gateway.get_option_chain(expiry, right=right)
                if chain.get("error") or not isinstance(chain.get("contracts"), list):
                    raise MarketDataError("Breeze option chain unavailable")
                for row in chain["contracts"]:
                    if (
                        str(row["stock_code"]).upper() != "NIFTY"
                        or str(row["exchange_code"]).upper() != "NFO"
                        or expiry_date(row["expiry_date"]) != expiry
                        or str(row["right"]).lower() != right
                    ):
                        raise MarketDataError("Breeze option chain identity mismatch")
                    key = (number(row["strike_price"]), side)
                    if key not in wanted:
                        continue
                    symbol = wanted[key]["symbol"]
                    if symbol in result:
                        raise MarketDataError("Duplicate Breeze option contract")
                    result[symbol] = dict(
                        ltp=row["ltp"],
                        open_interest=row["open_interest"],
                        oi_change=row["chnge_oi"],
                        volume=row["total_quantity_traded"],
                        timestamp=row["ltt"],
                        bid=row.get("best_bid_price"),
                        ask=row.get("best_offer_price"),
                    )
        return result

    def depth(self, contract, budget):
        from trading.adapters.gateways.breeze import option_contract

        identity = f"INST-NIFTY-{contract['expiry']}-{int(contract['strike'])}-{contract['right']}"
        with self._read(budget):
            rows = self.gateway._request(
                "GET", "/quotes", option_contract(identity), timeout=budget.remaining()
            )
        if not isinstance(rows, list) or len(rows) != 1:
            raise MarketDataError("Breeze option depth unavailable")
        raw = rows[0]
        actual, _ = self.gateway._raw_identity(raw)
        if actual != identity:
            raise MarketDataError("Breeze depth contract identity mismatch")
        return dict(
            timestamp=raw["ltt"],
            last_price=raw["ltp"],
            depth=dict(
                buy=[dict(price=raw["best_bid_price"], quantity=raw["best_bid_quantity"])],
                sell=[dict(price=raw["best_offer_price"], quantity=raw["best_offer_quantity"])],
            ),
        )

    def close(self):
        pass
