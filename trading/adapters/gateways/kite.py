"""Native Kite REST adapter. Mutations are single-attempt and explicitly armed."""

import json
import math
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request

from execution_safety import ReconciliationError
from entry_policy import EntryBlocked
from market_clock import MarketClock
from trading.adapters.gateways.base import BaseBrokerGateway
from trading.bootstrap import ensure_environment
from trading.domain.prices import round_tick

KITE_API_BASE_URL = "https://api.kite.trade"


def finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Non-finite broker number")
    return number


def integer(value):
    number = finite(value)
    if number != int(number) or number < 0:
        raise ValueError("Invalid broker quantity")
    return int(number)


class KiteExecutionGateway(BaseBrokerGateway):
    def __init__(
        self,
        api_key=None,
        access_token=None,
        account_id=None,
        *,
        product="NRML",
        exchange="NFO",
        rate_limit_per_sec=5.0,
        burst_capacity=5.0,
        journal_path=None,
        credentials_path=None,
    ):
        ensure_environment()
        super().__init__(
            broker_name="kite",
            rate_limit_per_sec=rate_limit_per_sec,
            burst_capacity=burst_capacity,
            journal_path=journal_path,
        )
        self.api_key = api_key or os.getenv("KITE_API_KEY") or os.getenv("ZERODHA_API_KEY", "")
        self.access_token = (
            access_token or os.getenv("KITE_ACCESS_TOKEN") or os.getenv("ZERODHA_ACCESS_TOKEN", "")
        )
        self.account_id = account_id or os.getenv("KITE_ACCOUNT_ID") or os.getenv("ZERODHA_USER_ID", "")
        if not self.api_key or not self.access_token:
            path = Path(credentials_path or "config/kite_credentials.json")
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                self.api_key = self.api_key or data.get("api_key", "")
                self.access_token = self.access_token or data.get("access_token", "")
                self.account_id = self.account_id or data.get("account_id", "")
        self.default_product, self.default_exchange = product, exchange
        self.base_url = KITE_API_BASE_URL
        self._verified_account = None
        self._verified_at = 0.0
        self._verified_credentials = None
        self._contracts: dict[str, str] = {}

    def register_contract(self, instrument_id, symbol):
        if not instrument_id or not symbol or str(symbol).startswith("INST-"):
            raise ValueError("Native trading symbol required")
        instrument_id, symbol = str(instrument_id), str(symbol)
        old = self._contracts.get(instrument_id)
        if old and old != symbol:
            raise ValueError("Contract identity mapping changed")
        self._contracts[instrument_id] = symbol

    def execution_symbol(self, instrument_id):
        symbol = self._contracts.get(str(instrument_id), str(instrument_id))
        if symbol.startswith("INST-"):
            raise ValueError("Internal instrument ID has no verified trading-symbol mapping")
        return symbol

    def restore_recovery_state(self, state):
        if state.get("instrument_id") and state.get("symbol"):
            self.register_contract(state["instrument_id"], state["symbol"])
        return super().restore_recovery_state(state)

    def is_connected(self):
        return bool(
            self._verified_account and self._verified_credentials == (self.api_key, self.access_token)
        )

    def get_account_id(self):
        return self._verified_account or ""

    def get_status(self):
        with self._lock:
            try:
                if not self.api_key or not self.access_token:
                    raise ReconciliationError("Kite credentials are missing")
                credentials = (self.api_key, self.access_token)
                if credentials != self._verified_credentials:
                    self._verified_account = None
                    self._live_authorized = False
                if not self.is_connected() or time.monotonic() - self._verified_at >= 60:
                    profile = self._request("GET", "/user/profile", timeout=3)
                    if not isinstance(profile, dict) or profile.get("error") or not profile.get("user_id"):
                        raise ReconciliationError("Kite profile verification failed")
                    account = str(profile["user_id"])
                    if (self.account_id and account != self.account_id) or (
                        self._verified_account and account != self._verified_account
                    ):
                        raise ReconciliationError("Kite account identity mismatch")
                    self.journal.bind(account)
                    self._verified_account = account
                    self._verified_credentials = credentials
                    self._verified_at = time.monotonic()
                return super().get_status()
            except Exception as exc:
                self._verified_account = None
                self._live_authorized = False
                return self._error(str(exc))

    def _ensure_verified(self):
        result = self.get_status()
        if result.get("error") or not result.get("connected"):
            raise ReconciliationError(result.get("detail", "Kite account unverified"))

    def _request(self, method, endpoint, params=None, data=None, timeout=10.0, max_retries=1):
        mutation = method != "GET"
        if mutation and (self._mode != "LIVE" or not self._live_authorized or not self.is_connected()):
            return self._error("NATIVE_LIVE_NOT_ARMED")
        url = self.base_url + endpoint
        if params:
            url += "?" + urllib.parse.urlencode(params, doseq=True)
        deadline = time.monotonic() + timeout
        if self._read_deadline is not None:
            deadline = min(deadline, self._read_deadline)
        attempts = 1 if mutation else min(max_retries + 1, 2)
        for attempt in range(attempts):
            try:
                limiter = self.quote_limiter if endpoint == "/quote" else self.rate_limiter
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not limiter.acquire(timeout=remaining):
                    return self._error("BROKER_REQUEST_BUDGET_EXHAUSTED")
                if mutation:
                    blocked = self._before_transmit()
                    if blocked:
                        return blocked
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return self._error("BROKER_REQUEST_BUDGET_EXHAUSTED")
                if mutation and (not self._live_authorized or not self.is_connected()):
                    return self._error("NATIVE_LIVE_NOT_ARMED")
                # Exit callbacks may refresh price after pacing. Build the wire
                # body only after that callback has durably saved its final limit.
                wire_data = data() if callable(data) else data
                payload = urllib.parse.urlencode(wire_data).encode() if wire_data is not None else None
                headers = {
                    "X-Kite-Version": "3",
                    "Authorization": f"token {self.api_key}:{self.access_token}",
                    "Accept": "application/json",
                }
                if payload is not None:
                    headers["Content-Type"] = "application/x-www-form-urlencoded"
                request = urllib.request.Request(url, data=payload, headers=headers, method=method)
                with urllib.request.urlopen(request, timeout=remaining) as response:
                    result = json.loads(response.read().decode("utf-8"))
                if not isinstance(result, dict) or result.get("status") != "success" or "data" not in result:
                    return self._error("INVALID_KITE_RESPONSE", unknown=mutation)
                if not mutation and time.monotonic() > deadline:
                    return self._error("BROKER_REQUEST_BUDGET_EXHAUSTED")
                return result["data"]
            except urllib.error.HTTPError as exc:
                code = exc.code
                detail = f"KITE_HTTP_{code}"
                try:
                    body = json.loads(exc.read(16384).decode("utf-8"))
                    if isinstance(body, dict) and isinstance(body.get("message"), str):
                        detail = body["message"]
                except (ValueError, OSError, AttributeError, TypeError):
                    pass
                finally:
                    exc.close()
                if code == 403:
                    self._verified_account = None
                    self._live_authorized = False
                if not mutation and code == 429 and attempt + 1 < attempts:
                    if deadline - time.monotonic() <= 0.5:
                        return self._error("RATE_LIMITED")
                    time.sleep(0.5)
                    continue
                return dict(self._error(detail, unknown=mutation and code >= 500), status_code=code)
            except (urllib.error.URLError, TimeoutError, OSError):
                if not mutation and attempt + 1 < attempts and deadline - time.monotonic() > 0.5:
                    time.sleep(0.5)
                    continue
                return self._error("KITE_NETWORK_ERROR", unknown=mutation)
            except EntryBlocked:
                raise
            except (ValueError, TypeError, KeyError):
                return self._error("INVALID_KITE_RESPONSE", unknown=mutation)
        return self._error("KITE_REQUEST_FAILED", unknown=mutation)

    def _to_standard_order(self, raw):
        oid = str(raw["order_id"])
        if not oid:
            raise ReconciliationError("Missing broker order ID")
        item = self.journal.match(tag=raw.get("tag"), order_id=oid)
        txn, order_type = raw.get("transaction_type"), raw.get("order_type")
        kind = (
            "ENTRY"
            if txn == "BUY"
            else "STOP"
            if txn == "SELL" and order_type in ("SL", "SL-M")
            else ("EXIT" if txn == "SELL" else "UNKNOWN")
        )
        # On Kite, a triggered SL/SL-M order is reported as LIMIT/MARKET in order history once filled.
        if item and item.get("kind") in ("STOP", "EXIT") and kind in ("STOP", "EXIT"):
            kind = item["kind"]
        if item and item.get("kind") != kind:
            raise ReconciliationError("Broker order differs from persisted intent kind")
        if item and item.get("symbol") and str(item["symbol"]).split(":")[-1] != raw.get("tradingsymbol"):
            raise ReconciliationError("Broker order differs from persisted intent symbol")
        if raw.get("account_id") and str(raw["account_id"]) != self.get_account_id():
            raise ReconciliationError("Broker order account mismatch")
        timestamp = MarketClock.parse_to_ist(raw.get("order_timestamp"))
        if timestamp is None or not raw.get("status") or not raw.get("tradingsymbol"):
            raise ReconciliationError("Incomplete broker order")
        state = str(raw["status"]).upper().replace(" ", "_")
        state = {"COMPLETE": "FILLED", "CANCELLED_AFTER_EXPIRE": "CANCELLED"}.get(state, state)
        quantity = integer(raw["quantity"])
        fill = integer(raw.get("filled_quantity", 0) if state == "REJECTED" else raw["filled_quantity"])
        if fill > quantity:
            raise ReconciliationError("Broker fills exceed order quantity")
        ref = item.get("entry_order_id") if item else None
        if item and (item.get("order_id") != oid or item.get("phase") in ("PREPARED", "UNKNOWN")):
            self.journal.put(item["request_id"], order_id=oid, phase="ACKNOWLEDGED")
        return {
            "order_id": oid,
            "broker_order_id": oid,
            "request_id": item["request_id"] if item else raw.get("tag") or oid,
            "kind": kind,
            "status": state,
            "symbol": raw["tradingsymbol"],
            "instrument_id": (item.get("instrument_id") or raw["tradingsymbol"])
            if item
            else raw["tradingsymbol"],
            "quantity": quantity,
            "filled_quantity": fill,
            "pending_quantity": max(0, quantity - fill),
            "average_price": finite(raw.get("average_price") or 0),
            "price": finite(raw.get("price") or 0),
            "trigger_price": raw.get("trigger_price"),
            "entry_order_id": ref,
            "parent_order_id": ref,
            "mode": "LIVE",
            "account_id": self.get_account_id(),
            "engine_owned": item is not None,
            "product": raw["product"],
            "exchange": raw["exchange"],
            "variety": raw.get("variety", "regular"),
            "created_at": timestamp.isoformat(),
        }

    def _fetch_broker_orders(self):
        self._ensure_verified()
        result = self._request("GET", "/orders")
        if not isinstance(result, list):
            raise ReconciliationError("Kite orders unavailable")
        return [self._to_standard_order(raw) for raw in result]

    def _fetch_broker_positions(self):
        self._ensure_verified()
        result = self._request("GET", "/portfolio/positions")
        if not isinstance(result, dict) or result.get("error") or not isinstance(result.get("net"), list):
            raise ReconciliationError("Kite positions unavailable")
        positions = []
        for raw in result["net"]:
            number = finite(raw["quantity"])
            if number != int(number):
                raise ReconciliationError("Non-integral position quantity")
            if number:
                aliases = {
                    r.get("instrument_id")
                    for r in self.journal.records.values()
                    if r.get("symbol", "").split(":")[-1] == raw["tradingsymbol"] and r.get("instrument_id")
                }
                if len(aliases) > 1:
                    raise ReconciliationError("Ambiguous internal contract identity")
                positions.append(
                    {
                        "symbol": raw["tradingsymbol"],
                        "instrument_id": next(iter(aliases), raw["tradingsymbol"]),
                        "quantity": int(number),
                        "average_price": finite(raw["average_price"]),
                        "last_bid": None,
                        "ltp": finite(raw["last_price"]),
                        "product": raw["product"],
                        "exchange": raw["exchange"],
                        "mode": "LIVE",
                        "account_id": self.get_account_id(),
                    }
                )
        return positions

    def validate_reconciliation(self, state, positions, orders):
        symbols = {p["symbol"] for p in positions}
        for order in orders:
            if not order.get("engine_owned") and (
                order["status"] not in ("FILLED", "CANCELLED", "REJECTED", "EXPIRED")
                or (order["filled_quantity"] and order["symbol"] in symbols)
            ):
                raise ReconciliationError("Unowned broker orders require explicit reconciliation")

    def _fetch_broker_funds(self):
        self._ensure_verified()
        result = self._request("GET", "/user/margins")
        if not isinstance(result, dict) or result.get("error") or not isinstance(result.get("equity"), dict):
            raise ReconciliationError("Kite margin unavailable")
        equity = result["equity"]
        available, utilised = equity["available"], equity["utilised"]
        # Preserve a verified zero live balance; never replace it with stale opening cash.
        balance = (
            available["live_balance"] if available.get("live_balance") is not None else available["cash"]
        )
        return {
            "available_margin": finite(balance),
            "cash": finite(available["cash"]),
            "used_margin": finite(utilised["debits"]),
            # Local receipt time of an authenticated direct broker read,
            # never misrepresented as an exchange-origin timestamp.
            "funds_asof": MarketClock.now_ist().isoformat(),
            "account_id": self.get_account_id(),
            "source": "kite:user/margins:authenticated-receipt",
        }

    def get_contract_quote(self, instrument_id, *, timeout_sec=1.0):
        return self._get_quotes([instrument_id], timeout_sec)[str(instrument_id)]

    def get_entry_quotes(self, instrument_id, *, include_index=False, timeout_sec=1.0):
        instruments = [instrument_id] + (["INST-NIFTY-INDEX"] if include_index else [])
        quotes = self._get_quotes(instruments, timeout_sec)
        return {"quote": quotes[str(instrument_id)], "spot_quote": quotes.get("INST-NIFTY-INDEX")}

    def _get_quotes(self, instruments, timeout_sec):
        started = time.monotonic()
        queries = {}
        try:
            for instrument in instruments:
                symbol = str(instrument)
                if symbol in ("INST-NIFTY-INDEX", "NIFTY-INDEX", "NIFTY", "NIFTY 50"):
                    queries[symbol] = "NSE:NIFTY 50"
                else:
                    native = self.execution_symbol(symbol)
                    queries[symbol] = native if ":" in native else f"{self.default_exchange}:{native}"
            with self.read_budget(timeout_sec):
                self._ensure_verified()
                result = self._request(
                    "GET", "/quote", params={"i": list(queries.values())}, timeout=timeout_sec, max_retries=0
                )
                if not isinstance(result, dict) or result.get("error"):
                    raise ReconciliationError("Quote unavailable")
                output = {}
                for symbol, query in queries.items():
                    quote = result[query]
                    if not isinstance(quote, dict):
                        raise ReconciliationError("Invalid quote")
                    depth = quote.get("depth") or {}
                    if not isinstance(depth, dict):
                        raise ReconciliationError("Invalid depth")
                    buy, sell = depth.get("buy") or [], depth.get("sell") or []
                    if not isinstance(buy, list) or not isinstance(sell, list):
                        raise ReconciliationError("Invalid depth")
                    bid, ask = buy[0] if buy else {}, sell[0] if sell else {}
                    if not isinstance(bid, dict) or not isinstance(ask, dict):
                        raise ReconciliationError("Invalid depth")
                    output[symbol] = {
                        "instrument_id": symbol,
                        "last_price": quote.get("last_price"),
                        "best_bid": bid.get("price"),
                        "best_ask": ask.get("price"),
                        "best_bid_qty": bid.get("quantity"),
                        "best_ask_qty": ask.get("quantity"),
                        "timestamp": quote.get("timestamp"),
                        "request_started_monotonic": started,
                        "received_monotonic": time.monotonic(),
                    }
                return output
        except (ValueError, TypeError, KeyError, ReconciliationError):
            return {str(symbol): self._error("QUOTE_UNAVAILABLE") for symbol in instruments}

    def _order_data(self, symbol, quantity, price, tag, transaction, *, trigger=None):
        context = self._entry_context.get()
        exchange, name = (
            symbol.split(":", 1)
            if ":" in symbol
            else (context.get("exchange", self.default_exchange), symbol)
        )
        data = {
            "exchange": exchange,
            "tradingsymbol": name,
            "transaction_type": transaction,
            "order_type": "SL" if trigger is not None else "LIMIT",
            "quantity": str(quantity),
            "price": f"{price:.2f}",
            "product": context.get("product", self.default_product),
            "validity": "DAY",
            "tag": tag,
        }
        if trigger is not None:
            data["trigger_price"] = f"{trigger:.2f}"
        return data

    def _submit_buy_order(self, symbol, quantity, limit_price, tag):
        return self._request(
            "POST", "/orders/regular", data=self._order_data(symbol, quantity, limit_price, tag, "BUY")
        )

    def _submit_stop_loss(self, symbol, quantity, trigger_price, limit_price, tag):
        return self._request(
            "POST",
            "/orders/regular",
            data=self._order_data(symbol, quantity, limit_price, tag, "SELL", trigger=trigger_price),
        )

    def _submit_exit_order(self, symbol, quantity, limit_price, tag):
        return self._request(
            "POST",
            "/orders/regular",
            data=lambda: self._order_data(
                symbol,
                quantity,
                (self._order_payload.get() or {}).get("limit_price", limit_price),
                tag,
                "SELL",
            ),
        )

    def _submit_modify_stop(self, order_id, trigger_price, limit_price):
        return self._request(
            "PUT",
            f"/orders/regular/{order_id}",
            data={"order_type": "SL", "trigger_price": f"{trigger_price:.2f}", "price": f"{limit_price:.2f}"},
        )

    def _submit_reprice_exit(self, order_id, limit_price):
        return self._request(
            "PUT",
            f"/orders/regular/{order_id}",
            data={"order_type": "LIMIT", "price": f"{round_tick(limit_price):.2f}"},
        )

    def _submit_cancel_order(self, order_id):
        return self._request("DELETE", f"/orders/regular/{order_id}")

    def get_historical_candles(
        self, instrument_id, from_date, to_date, *, interval="1m", instrument_token=None
    ):
        """Read-only native history, using an explicit broker instrument token.

        This optional method is not selected by the default market-data path.
        """
        intervals = {"1m": "minute", "5m": "5minute", "30m": "30minute", "1d": "day"}
        try:
            token = integer(instrument_token)
            if not token or interval not in intervals:
                raise ValueError("Explicit Kite instrument token and supported interval required")
            with self._lock:
                self._ensure_verified()
                result = self._request(
                    "GET",
                    f"/instruments/historical/{token}/{intervals[interval]}",
                    params={"from": from_date, "to": to_date, "oi": 1},
                )
                if (
                    not isinstance(result, dict)
                    or result.get("error")
                    or not isinstance(result.get("candles"), list)
                ):
                    raise ReconciliationError("Kite history unavailable")
                return {"candles": result["candles"], "source": "kite", "instrument_id": instrument_id}
        except (ValueError, TypeError, ReconciliationError):
            return self._error("KITE_HISTORY_UNAVAILABLE")
