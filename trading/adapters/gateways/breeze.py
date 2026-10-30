"""Native Breeze REST gateway sharing Kite's serialized, fail-closed OMS."""

from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request

from entry_policy import EntryBlocked
from execution_safety import ReconciliationError, atomic_save
from market_clock import IST_TZ, MarketClock
from trading.adapters.gateways.base import BaseBrokerGateway
from trading.bootstrap import ensure_environment
from trading.domain.prices import round_tick

BREEZE_API_BASE_URL = "https://api.icicidirect.com/breezeapi/api/v1"
WORKSPACE = Path(__file__).resolve().parents[3]


def number(value):
    if isinstance(value, bool):
        raise ValueError("Boolean Breeze number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Non-finite Breeze number")
    return result


def quantity(value):
    result = number(value)
    if result < 0 or result != int(result):
        raise ValueError("Invalid Breeze quantity")
    return int(result)


def broker_time(value):
    """Breeze exchange timestamps are IST, including pre-open timestamps."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=IST_TZ)
        except ValueError:
            pass
    if not isinstance(value, str) or not re.match(r"\d{4}-\d{2}-\d{2}T", value):
        raise ValueError("Missing or invalid Breeze exchange timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=IST_TZ) if parsed.tzinfo is None else parsed.astimezone(IST_TZ)


def expiry_date(value):
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(str(value), fmt).date().isoformat()
        except ValueError:
            pass
    return date.fromisoformat(str(value).split("T")[0]).isoformat()


def option_contract(instrument_id):
    """Read exact metadata; never infer an expiry from a trading symbol."""
    match = re.fullmatch(r"INST-NIFTY-(\d{4}-\d{2}-\d{2})-(\d+)-(CE|PE)", str(instrument_id))
    if not match:
        raise ValueError("Breeze requires an exact INST-NIFTY-expiry-strike-CE/PE identity")
    expiry, strike, right = match.groups()
    if quantity(strike) <= 0:
        raise ValueError("Invalid option strike")
    return {
        "stock_code": "NIFTY",
        "exchange_code": "NFO",
        "product_type": "options",
        "expiry_date": expiry_date(expiry) + "T06:00:00.000Z",
        "strike_price": str(quantity(strike)),
        "right": "call" if right == "CE" else "put",
    }


class BreezeExecutionGateway(BaseBrokerGateway):
    _usage_lock = threading.RLock()

    def __init__(
        self,
        api_key=None,
        api_secret=None,
        api_session=None,
        account_id=None,
        *,
        journal_path=None,
        credentials_path=None,
        rate_limit_per_sec=1.5,
        burst_capacity=1,
    ):
        ensure_environment()
        super().__init__(
            broker_name="breeze",
            rate_limit_per_sec=min(rate_limit_per_sec, 1.5),
            burst_capacity=1,
            journal_path=journal_path,
        )
        self.api_key = api_key or os.getenv("BREEZE_API_KEY", "")
        self.api_secret = api_secret or os.getenv("BREEZE_API_SECRET") or os.getenv("BREEZE_SECRET_KEY") or ""
        self.api_session = (
            api_session or os.getenv("BREEZE_API_SESSION") or os.getenv("BREEZE_SESSION_TOKEN") or ""
        )
        self.account_id = account_id or os.getenv("BREEZE_ACCOUNT_ID", "")
        path = Path(credentials_path or WORKSPACE / "config/breeze_credentials.json").resolve()
        if not path.is_relative_to(WORKSPACE):
            raise ValueError("Breeze credentials must stay inside the workspace")
        if path.exists() and not all((self.api_key, self.api_secret, self.api_session, self.account_id)):
            data = json.loads(path.read_text(encoding="utf-8"))
            self.api_key = self.api_key or data.get("api_key", "")
            self.api_secret = self.api_secret or data.get("api_secret") or data.get("secret_key") or ""
            self.api_session = self.api_session or data.get("api_session") or data.get("session_token") or ""
            self.account_id = self.account_id or data.get("account_id") or data.get("user_id") or ""
        self.base_url = BREEZE_API_BASE_URL
        self._verified_account = self._verified_credentials = self._session_token = None
        self._verified_at = 0.0
        self._contracts: dict[str, str] = {}
        self._usage_path = self.journal.path.parent / "breeze_api_usage.json"
        self._had_usage_file = False

    def _credentials(self):
        return self.api_key, self.api_secret, self.api_session, self.account_id

    def _revoke(self):
        self._verified_account = self._session_token = self._verified_credentials = None
        self._live_authorized = False

    def is_connected(self):
        return bool(self._verified_account and self._verified_credentials == self._credentials())

    def get_account_id(self):
        return self._verified_account or ""

    def get_status(self):
        with self._lock:
            try:
                if self._verified_credentials != self._credentials():
                    self._revoke()
                if not all(self._credentials()):
                    raise ReconciliationError("Breeze key, secret, API session and account ID are required")
                if not self.is_connected() or time.monotonic() - self._verified_at >= 60:
                    profile = self._request(
                        "GET",
                        "/customerdetails",
                        {"SessionToken": self.api_session, "AppKey": self.api_key},
                        timeout=3,
                        session_exchange=True,
                    )
                    if not isinstance(profile, dict) or profile.get("error"):
                        raise ReconciliationError("Breeze customer verification failed")
                    account, token = profile.get("idirect_userid"), profile.get("session_token")
                    if account != self.account_id or not isinstance(token, str) or not token:
                        raise ReconciliationError("Breeze account/session mismatch")
                    self.journal.bind(account)
                    self._verified_account, self._session_token = account, token
                    self._verified_credentials = self._credentials()
                    self._verified_at = time.monotonic()
                return super().get_status()
            except Exception:
                self._revoke()
                return self._error("BREEZE_ACCOUNT_UNVERIFIED")

    def _ensure_verified(self):
        current = self.get_status()
        if current.get("error") or not current.get("connected"):
            raise ReconciliationError("Breeze account is unverified")

    def _reserve_request(self):
        """Persist each attempt; scheduler singleton covers separate processes."""
        with self._usage_lock:
            exists = self._usage_path.exists()
            if self._had_usage_file and not exists:
                raise ReconciliationError("Breeze request-budget file was removed")
            data = json.loads(self._usage_path.read_text(encoding="utf-8")) if exists else {}
            if not isinstance(data, dict):
                raise ReconciliationError("Invalid Breeze request-budget file")
            key = hashlib.sha256(self.api_key.encode()).hexdigest()
            record = data.get(key, {})
            today = MarketClock.today_ist_str()
            count = quantity(record["count"]) if record.get("date") == today else 0
            if count >= 5000:
                raise ReconciliationError("Breeze daily request budget exhausted")
            data[key] = {"date": today, "count": count + 1}
            atomic_save(self._usage_path, data)
            self._had_usage_file = True

    def _request(self, method, endpoint, data=None, *, timeout=10, session_exchange=False):
        mutation = method != "GET"
        if session_exchange and (method != "GET" or endpoint != "/customerdetails"):
            return self._error("INVALID_SESSION_EXCHANGE")
        if not session_exchange and not self.is_connected():
            self._revoke()
            return self._error("BREEZE_ACCOUNT_UNVERIFIED")
        if mutation and (self._mode != "LIVE" or not self._live_authorized or not self._owns_account_lease()):
            return self._error("NATIVE_LIVE_NOT_ARMED")
        deadline = time.monotonic() + timeout
        if self._read_deadline is not None:
            deadline = min(deadline, self._read_deadline)
        transmitted = False
        try:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not self.rate_limiter.acquire(timeout=remaining):
                return self._error("BROKER_REQUEST_BUDGET_EXHAUSTED")
            self._reserve_request()
            if mutation:
                blocked = self._before_transmit()
                if blocked:
                    return blocked
            if not session_exchange and (
                not self.is_connected()
                or (mutation and (not self._live_authorized or not self._owns_account_lease()))
            ):
                return self._error("BREEZE_ACCOUNT_UNVERIFIED")
            wire_data = data() if callable(data) else (data or {})
            payload = json.dumps(wire_data, separators=(",", ":"), allow_nan=False).encode("utf-8")
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if not session_exchange:
                timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                checksum = hashlib.sha256(timestamp.encode() + payload + self.api_secret.encode()).hexdigest()
                headers.update(
                    {
                        "X-Checksum": "token " + checksum,
                        "X-Timestamp": timestamp,
                        "X-AppKey": self.api_key,
                        "X-SessionToken": str(self._session_token),
                    }
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return self._error("BROKER_REQUEST_BUDGET_EXHAUSTED")
            request = urllib.request.Request(
                self.base_url + endpoint, data=payload, headers=headers, method=method
            )
            transmitted = True
            with urllib.request.urlopen(request, timeout=remaining) as response:
                result = json.loads(response.read(2_000_001).decode("utf-8"))
            if not isinstance(result, dict) or "Success" not in result or "Status" not in result:
                return self._error("INVALID_BREEZE_RESPONSE", unknown=mutation)
            code = int(result["Status"])
            if code in (401, 403):
                self._revoke()
            if code != 200 or result.get("Error"):
                return dict(
                    self._error(
                        "BREEZE_API_ERROR", unknown=mutation and (not 400 <= code < 500 or code == 408)
                    ),
                    status_code=code,
                )
            if result["Success"] is None:
                return self._error("INVALID_BREEZE_RESPONSE", unknown=mutation)
            if not mutation and time.monotonic() > deadline:
                return self._error("BROKER_REQUEST_BUDGET_EXHAUSTED")
            return result["Success"]
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401, 403):
                self._revoke()
            return dict(
                self._error(f"BREEZE_HTTP_{code}", unknown=mutation and (code >= 500 or code == 408)),
                status_code=code,
            )
        except EntryBlocked:
            raise
        except Exception:
            # Never print broker response bodies, headers, sessions or secrets.
            # Mutations use one attempt; lost acknowledgements reconcile by tag.
            return self._error("BREEZE_REQUEST_FAILED", unknown=mutation and transmitted)

    def register_contract(self, instrument_id, symbol):
        option_contract(instrument_id)
        if not symbol or str(symbol).startswith("INST-"):
            raise ValueError("Explicit trading symbol required for Breeze contract mapping")
        previous = self._contracts.get(str(instrument_id))
        if previous and previous != str(symbol):
            raise ValueError("Breeze contract mapping changed")
        if any(key != str(instrument_id) and value == str(symbol) for key, value in self._contracts.items()):
            raise ValueError("Breeze symbol maps to multiple contracts")
        self._contracts[str(instrument_id)] = str(symbol)

    def execution_symbol(self, instrument_id):
        symbol = self._contracts.get(str(instrument_id))
        if symbol is None:
            raise ValueError("Breeze contract has no verified mapping")
        return symbol

    def restore_recovery_state(self, state):
        if state.get("instrument_id") and state.get("symbol"):
            self.register_contract(state["instrument_id"], state["symbol"])
        return super().restore_recovery_state(state)

    def _contract_for_symbol(self, symbol):
        matches = {key for key, value in self._contracts.items() if value == symbol}
        matches.update(
            r["instrument_id"]
            for r in self.journal.records.values()
            if r.get("symbol") == symbol and r.get("instrument_id")
        )
        if len(matches) != 1:
            raise ReconciliationError("Missing or ambiguous Breeze contract mapping")
        return option_contract(matches.pop())

    def _raw_identity(self, raw):
        if str(raw["exchange_code"]).upper() != "NFO" or str(raw["product_type"]).lower() != "options":
            raise ReconciliationError("Unsupported Breeze account exposure requires reconciliation")
        if str(raw["stock_code"]).upper() != "NIFTY":
            raise ReconciliationError("Non-NIFTY exposure requires reconciliation")
        right = {"call": "CE", "put": "PE"}.get(str(raw["right"]).lower())
        if not right:
            raise ReconciliationError("Invalid Breeze option right")
        instrument = f"INST-NIFTY-{expiry_date(raw['expiry_date'])}-{quantity(raw['strike_price'])}-{right}"
        option_contract(instrument)
        symbols = {self._contracts[instrument]} if instrument in self._contracts else set()
        symbols.update(
            r["symbol"]
            for r in self.journal.records.values()
            if r.get("instrument_id") == instrument and r.get("symbol")
        )
        if len(symbols) > 1:
            raise ReconciliationError("Conflicting Breeze trading-symbol aliases")
        return instrument, next(iter(symbols), instrument.replace("INST-", "BREEZE-", 1))

    def _to_standard_order(self, raw):
        oid = str(raw["order_id"] or "")
        if not oid:
            raise ReconciliationError("Missing Breeze order ID")
        instrument, symbol = self._raw_identity(raw)
        item = self.journal.match(order_id=oid, tag=raw.get("user_remark"))
        action, order_type = str(raw["action"]).lower(), str(raw["order_type"]).lower()
        if action not in ("buy", "sell") or order_type not in ("limit", "stoploss"):
            raise ReconciliationError("Unsupported Breeze action/type")
        kind = "ENTRY" if action == "buy" else ("STOP" if order_type == "stoploss" else "EXIT")
        if item and action == "sell" and item.get("kind") == "STOP" and order_type == "limit":
            # A triggered conditional SELL may be reported as a regular limit.
            # Retain its durable parent/kind, and expose it as OPEN below.
            kind = "STOP"
        if item:
            if item.get("kind") != kind or item.get("symbol") != symbol:
                raise ReconciliationError("Breeze order differs from persisted intent")
            expected = item.get("instrument_id")
            if not expected and item.get("entry_order_id"):
                parent = self.journal.match(order_id=item["entry_order_id"])
                expected = parent.get("instrument_id") if parent else None
            if expected != instrument:
                raise ReconciliationError("Breeze contract differs from persisted intent")
        states = {
            "requested": "PENDING",
            "queued": "PENDING",
            "ordered": "OPEN",
            "freezed": "OPEN",
            "partially executed": "PARTIALLY_FILLED",
            "executed": "FILLED",
            "rejected": "REJECTED",
            "cancelled": "CANCELLED",
            "expired": "EXPIRED",
            "partially executed and cancelled": "CANCELLED",
            "partially executed and expired": "EXPIRED",
        }
        raw_state = str(raw["status"]).lower()
        if raw_state not in states:
            raise ReconciliationError("Unknown Breeze order status")
        qty, pending, cancelled = (
            quantity(raw["quantity"]),
            quantity(raw["pending_quantity"]),
            quantity(raw["cancelled_quantity"]),
        )
        expired = quantity(raw.get("expired_quantity") or 0)
        if qty == 0 or ("expired" in raw_state and "expired_quantity" not in raw):
            raise ReconciliationError("Breeze fill quantity is unverified")
        fill = qty - pending - cancelled - expired
        if raw_state == "rejected" and pending + cancelled + expired <= qty:
            fill = 0
        if not 0 <= fill <= qty or (raw_state == "executed" and fill != qty):
            raise ReconciliationError("Inconsistent Breeze fill quantities")
        if raw_state in ("requested", "queued", "ordered", "freezed", "rejected") and fill != 0:
            raise ReconciliationError("Unexpected fills for Breeze order state")
        normalized_state = states[raw_state]
        if (
            kind == "STOP"
            and order_type == "stoploss"
            and raw_state == "ordered"
            and number(raw["stoploss"]) > 0
        ):
            # Breeze reports an accepted outstanding conditional order as
            # Ordered + StopLoss, rather than Kite's TRIGGER PENDING. Partial
            # fills, queued requests and converted LIMIT orders never qualify.
            normalized_state = "TRIGGER_PENDING"
        timestamp = broker_time(raw["order_datetime"])
        if item and (item.get("order_id") != oid or item.get("phase") in ("PREPARED", "UNKNOWN")):
            self.journal.put(item["request_id"], order_id=oid, phase="ACKNOWLEDGED")
        ref = item.get("entry_order_id") if item else None
        return {
            "order_id": oid,
            "broker_order_id": oid,
            "request_id": item["request_id"] if item else raw.get("user_remark") or oid,
            "kind": kind,
            "status": normalized_state,
            "symbol": symbol,
            "instrument_id": instrument,
            "quantity": qty,
            "filled_quantity": fill,
            "pending_quantity": pending,
            "average_price": number(raw["average_price"]),
            "price": number(raw["price"]),
            "trigger_price": number(raw.get("stoploss") or 0),
            "entry_order_id": ref,
            "parent_order_id": ref,
            "mode": "LIVE",
            "account_id": self.get_account_id(),
            "engine_owned": item is not None,
            "product": "options",
            "exchange": "NFO",
            "variety": "regular",
            "created_at": timestamp.isoformat(),
        }

    def _fetch_broker_orders(self):
        self._ensure_verified()
        today = MarketClock.today_ist_str()
        result = self._request(
            "GET",
            "/order",
            {
                "exchange_code": "NFO",
                "from_date": today + "T00:00:00.000Z",
                "to_date": today + "T23:59:59.000Z",
            },
        )
        if not isinstance(result, list):
            raise ReconciliationError("Breeze orders unavailable")
        return [self._to_standard_order(raw) for raw in result]

    def _fetch_broker_positions(self):
        self._ensure_verified()
        result = self._request("GET", "/portfoliopositions")
        if not isinstance(result, list):
            raise ReconciliationError("Breeze positions unavailable")
        positions = []
        for raw in result:
            qty = quantity(raw["quantity"])
            if not qty:
                continue
            instrument, symbol = self._raw_identity(raw)
            action = str(raw["action"]).lower()
            if action not in ("buy", "sell"):
                raise ReconciliationError("Unverified Breeze position direction")
            positions.append(
                {
                    "symbol": symbol,
                    "instrument_id": instrument,
                    "quantity": qty if action == "buy" else -qty,
                    "average_price": number(raw["average_price"]),
                    "ltp": number(raw["ltp"]),
                    "last_bid": None,
                    "mode": "LIVE",
                    "account_id": self.get_account_id(),
                    "product": "options",
                    "exchange": "NFO",
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
                raise ReconciliationError("Unowned Breeze orders require explicit reconciliation")

    def _fetch_broker_funds(self):
        self._ensure_verified()
        result = self._request("GET", "/funds")
        if not isinstance(result, dict) or result.get("error"):
            raise ReconciliationError("Breeze funds unavailable")
        allocated, blocked = number(result["allocated_fno"]), number(result["block_by_trade_fno"])
        if allocated < 0 or blocked < 0:
            raise ReconciliationError("Invalid Breeze F&O funds")
        # Bank cash and other segment allocations cannot fund these orders.
        return {
            "available_margin": max(0.0, allocated - blocked),
            "cash": allocated,
            "used_margin": blocked,
            # Timestamp is the verified API response receipt, NOT broker P&L.
            "funds_asof": MarketClock.now_ist().isoformat(),
            "account_id": self.get_account_id(),
            "source": "breeze:funds:authenticated-receipt",
        }

    def get_contract_quote(self, instrument_id, *, timeout_sec=1.0):
        started = time.monotonic()
        try:
            with self._lock, self.read_budget(timeout_sec):
                self._ensure_verified()
                if str(instrument_id) in ("INST-NIFTY-INDEX", "NIFTY-INDEX", "NIFTY", "NIFTY 50"):
                    contract = {"stock_code": "NIFTY", "exchange_code": "NSE", "product_type": "cash"}
                else:
                    contract = self._contract_for_symbol(self.execution_symbol(instrument_id))
                result = self._request("GET", "/quotes", contract, timeout=timeout_sec)
                if not isinstance(result, list) or len(result) != 1:
                    raise ReconciliationError("Breeze quote unavailable or ambiguous")
                raw = result[0]
                if contract["exchange_code"] == "NFO":
                    actual, _ = self._raw_identity(raw)
                    if actual != str(instrument_id):
                        raise ReconciliationError("Breeze quote contract mismatch")
                elif str(raw["stock_code"]).upper() != "NIFTY" or str(raw["exchange_code"]).upper() != "NSE":
                    raise ReconciliationError("Breeze index quote mismatch")
                return {
                    "instrument_id": str(instrument_id),
                    "last_price": number(raw["ltp"]),
                    "best_bid": raw.get("best_bid_price"),
                    "best_ask": raw.get("best_offer_price"),
                    "best_bid_qty": raw.get("best_bid_quantity"),
                    "best_ask_qty": raw.get("best_offer_quantity"),
                    "timestamp": broker_time(raw["ltt"]).isoformat(),
                    "request_started_monotonic": started,
                    "received_monotonic": time.monotonic(),
                }
        except Exception:
            return self._error("BREEZE_QUOTE_UNAVAILABLE")

    def _order_data(self, symbol, qty, price, tag, action, trigger=None):
        contract = self._contract_for_symbol(symbol)
        product = contract.pop("product_type")
        if quantity(qty) <= 0 or number(price) <= 0 or (trigger is not None and number(trigger) <= 0):
            raise ValueError("Positive order quantity and prices required")
        return {
            **contract,
            "product": product,
            "action": action,
            "order_type": "stoploss" if trigger is not None else "limit",
            "quantity": str(qty),
            "price": f"{round_tick(price):.2f}",
            "validity": "day",
            "disclosed_quantity": "0",
            "stoploss": f"{round_tick(trigger):.2f}" if trigger is not None else "0",
            "user_remark": tag,
        }

    def _submit_buy_order(self, symbol, quantity, limit_price, tag):
        return self._request(
            "POST", "/order", lambda: self._order_data(symbol, quantity, limit_price, tag, "buy")
        )

    def _submit_stop_loss(self, symbol, quantity, trigger_price, limit_price, tag):
        return self._request(
            "POST",
            "/order",
            lambda: self._order_data(symbol, quantity, limit_price, tag, "sell", trigger_price),
        )

    def _submit_exit_order(self, symbol, quantity, limit_price, tag):
        return self._request(
            "POST",
            "/order",
            lambda: self._order_data(
                symbol,
                quantity,
                (self._order_payload.get() or {}).get("limit_price", limit_price),
                tag,
                "sell",
            ),
        )

    def _modify_data(self, order_id, trigger_price, limit_price):
        order = self.get_order(order_id)
        if order.get("error"):
            raise ReconciliationError("Breeze modification quantity is unverified")
        if number(limit_price) <= 0 or (trigger_price is not None and number(trigger_price) <= 0):
            raise ValueError("Positive modification prices required")
        return {
            "exchange_code": "NFO",
            "order_id": str(order_id),
            "order_type": "stoploss" if trigger_price is not None else "limit",
            "quantity": str(order["quantity"]),
            "price": f"{round_tick(limit_price):.2f}",
            "validity": "day",
            "disclosed_quantity": "0",
            "stoploss": f"{round_tick(trigger_price):.2f}" if trigger_price is not None else "0",
        }

    def _submit_modify_stop(self, order_id, trigger_price, limit_price):
        data = self._modify_data(order_id, trigger_price, limit_price)
        return self._request("PUT", "/order", data)

    def _submit_reprice_exit(self, order_id, limit_price):
        return self._request("PUT", "/order", self._modify_data(order_id, None, limit_price))

    def _submit_cancel_order(self, order_id):
        return self._request("DELETE", "/order", {"exchange_code": "NFO", "order_id": str(order_id)})

    def get_historical_candles(self, instrument_id, from_date, to_date, *, interval="1m"):
        """Read-only raw broker candles, with an explicit contract and range."""
        intervals = {"1m": "1minute", "5m": "5minute", "30m": "30minute", "1d": "1day"}
        try:
            with self._lock:
                self._ensure_verified()
                result = self._request(
                    "GET",
                    "/historicalcharts",
                    {
                        **(
                            {"stock_code": "NIFTY", "exchange_code": "NSE", "product_type": "cash"}
                            if instrument_id == "INST-NIFTY-INDEX"
                            else option_contract(instrument_id)
                        ),
                        "interval": intervals[interval],
                        "from_date": from_date,
                        "to_date": to_date,
                    },
                )
                if not isinstance(result, list):
                    raise ReconciliationError("Breeze history unavailable")
                return {"candles": result, "source": "breeze", "instrument_id": instrument_id}
        except Exception:
            return self._error("BREEZE_HISTORY_UNAVAILABLE")

    def get_option_chain(self, expiry, *, right):
        """Explicit expiry and right, as required by Breeze."""
        if right not in ("call", "put"):
            return self._error("INVALID_OPTION_RIGHT")
        try:
            with self._lock:
                self._ensure_verified()
                result = self._request(
                    "GET",
                    "/optionchain",
                    {
                        "stock_code": "NIFTY",
                        "exchange_code": "NFO",
                        "product_type": "options",
                        "expiry_date": expiry_date(expiry) + "T06:00:00.000Z",
                        "right": right,
                    },
                )
                if not isinstance(result, list):
                    raise ReconciliationError("Breeze option chain unavailable")
                return {"contracts": result, "source": "breeze", "expiry": expiry_date(expiry)}
        except Exception:
            return self._error("BREEZE_OPTION_CHAIN_UNAVAILABLE")
