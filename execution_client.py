#!/usr/bin/env python3
"""
AI Execution Client for PR #51 Platform API
Interacts with http://127.0.0.1:8000/api/v1/ai
Supports both PAPER and LIVE modes via X-AI-Execution-Key.
"""

import os
import time
import json
import uuid
import logging
import urllib.request
import urllib.error
from urllib.parse import quote
from contextlib import contextmanager
from typing import Dict, Any, Optional
from execution_safety import (ReconciliationError, TERMINAL, filled, rows, status, symbol_of, same_scope)
from trading.adapters.http import JsonHttpTransport
from trading.ports import JsonTransport
from trading.bootstrap import ensure_environment, load_environment_file
from trading.domain.prices import round_tick

logger = logging.getLogger("AIExecutionClient")

def load_env_file(filepath: str = ".env"):
    """Compatibility entry point; environment loading is an explicit operation."""
    return load_environment_file(filepath)

DEFAULT_API_KEY = ""  # Configure credentials through .env or the process environment.
DEFAULT_BASE_URL = "http://127.0.0.1:8000/api/v1/ai"


class AIExecutionClient:
    def __init__(self, base_url: Optional[str] = None, api_key: Optional[str] = None, *,
                 transport: Optional[JsonTransport] = None):
        ensure_environment()
        self.base_url = (base_url or os.getenv("TRADING_API_BASE_URL") or os.getenv("API_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key or os.getenv("TRADING_API_KEY") or os.getenv("AI_EXECUTION_API_KEY") or DEFAULT_API_KEY
        self.transport = transport if transport is not None else JsonHttpTransport(logger=logger)

    @contextmanager
    def read_budget(self, seconds):
        previous = getattr(self, "_read_deadline", None)
        deadline = time.monotonic() + seconds
        self._read_deadline = min(previous, deadline) if previous else deadline
        try:
            yield
        finally:
            self._read_deadline = previous

    def _get_headers(self, with_auth: bool = True) -> Dict[str, str]:
        headers = {
            "Accept": "application/json",

            "Content-Type": "application/json"
        }
        if with_auth and self.api_key:
            headers["X-AI-Execution-Key"] = self.api_key
        return headers

    def _request(self, method: str, path: str, payload: Optional[dict] = None,
                 with_auth: bool = True, timeout: float = 10, retry_reads: bool = True) -> dict:
        """Compatibility facade; transport owns I/O, not execution decisions."""
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}{path}"
        return self.transport.request(method, url, payload, headers=self._get_headers(with_auth),
            timeout=timeout, retry_reads=retry_reads,
            deadline=lambda: getattr(self, "_read_deadline", None), log_path=path)

    # -------------------------------------------------------------
    # 1. Status & Mode Management
    # -------------------------------------------------------------
    def get_status(self) -> dict:
        """GET /execution/status: Check mode, live authorization, and broker connection."""
        return self._request("GET", "/execution/status", with_auth=False)

    def set_mode(self, mode: str) -> dict:
        """POST /execution/mode: Switch between 'PAPER' and 'LIVE'."""
        if mode not in ["PAPER", "LIVE"]:
            raise ValueError("Mode must be either 'PAPER' or 'LIVE'")
        return self._request("POST", "/execution/mode", {"mode": mode}, with_auth=True)

    # -------------------------------------------------------------
    # 2. Market Data & Feeds
    # -------------------------------------------------------------
    def get_data_quality(self) -> dict:
        """GET /data-quality: Check feed condition, timestamps, and quote freshness."""
        return self._request("GET", "/data-quality", with_auth=False)

    def get_broker_sessions(self) -> dict:
        """GET /broker/sessions: Kite and Breeze connection states."""
        return self._request("GET", "/broker/sessions", with_auth=False)

    def get_snapshot(self) -> dict:
        """GET /nifty/snapshot: Current NIFTY snapshot, readiness, and blockers."""
        return self._request("GET", "/nifty/snapshot", with_auth=False)

    def get_options(self, strike_window: int = 5, expiry: Optional[str] = None) -> dict:
        """GET /nifty/options: ATM strikes, quotes, volume, and OI."""
        path = f"/nifty/options?strike_window={strike_window}"
        if expiry:
            path += f"&expiry={expiry}"
        return self._request("GET", path, with_auth=False)

    def get_contract_quote(self, instrument_id: str, *, timeout_sec: float = 1.0) -> dict:
        """Read the documented gateway quote, retaining depth and exchange timestamp.

        No LTP fallback or automatic retry: the entry caller validates freshness
        again immediately before submitting. This is a socket-operation timeout,
        not a guarantee about end-to-end network latency.
        """
        root = self.base_url[:-3] if self.base_url.endswith("/ai") else self.base_url
        started = time.monotonic()
        result = self._request("GET", f"{root}/market/quote/{quote(str(instrument_id), safe='')}",
                               with_auth=False, timeout=timeout_sec, retry_reads=False)
        if not isinstance(result, dict):
            return {"error": True, "detail": "INVALID_CONTRACT_QUOTE"}
        return dict(result, request_started_monotonic=started,
                    received_monotonic=time.monotonic())

    def get_options_technicals(self, instrument_ids: list, interval: str = "5m", limit: int = 200) -> dict:
        """GET /nifty/options/technicals: Calculate indicators for multiple option contracts using their own OHLCV candles."""
        if not instrument_ids:
            return {"contracts": []}
        import urllib.parse
        query_parts = [f"instrument_ids={urllib.parse.quote(str(tid))}" for tid in instrument_ids[:6]]
        query_str = "&".join(query_parts) + f"&interval={interval}&limit={limit}"
        return self._request("GET", f"/nifty/options/technicals?{query_str}", with_auth=False)

    # -------------------------------------------------------------
    # 3. Order Placement & Status Reconciliation
    # -------------------------------------------------------------
    def place_buy_order(self, instrument_id: str, quantity: int, limit_price: float,
                        request_id: Optional[str] = None, before_submit=None) -> dict:
        """POST /execution/orders: Place a BUY LIMIT order."""
        req_id = request_id or f"AI-ENTRY-{datetime_now_id()}"
        payload = {
            "request_id": req_id,
            "instrument_id": instrument_id,
            "quantity": quantity,
            "limit_price": round_tick(limit_price)
        }
        logger.info(f"Submitting BUY order: {instrument_id} Qty={quantity} Limit={payload['limit_price']} ReqID={req_id}")
        if before_submit:
            before_submit()  # After logging; failure means no HTTP mutation was attempted.
        return self._request("POST", "/execution/orders", payload, with_auth=True)

    def get_order(self, order_id: str) -> dict:
        """GET /execution/orders/{order_id}: Retrieve order status and fill details."""
        return self._request("GET", f"/execution/orders/{order_id}", with_auth=True)

    def wait_for_fill(self, order_id: str, timeout_sec: float = 15, poll_interval: float = 0.5,
                      return_on_partial: bool = False) -> dict:
        deadline = time.monotonic() + timeout_sec
        last = {}
        while time.monotonic() < deadline:
            last = self._request("GET", f"/execution/orders/{order_id}",
                                 timeout=min(10, max(0.1, deadline - time.monotonic())), retry_reads=False)
            if not last.get("error") and (status(last) in TERMINAL or
                                           (return_on_partial and filled(last) > 0)):
                return last
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        return {"error": True, "detail": "FILL_POLL_TIMEOUT", "order_id": order_id,
                "outcome_unknown": True, "last_order": last}

    def cancel_entry_order(self, order_id: str) -> dict:
        return self._request("DELETE", f"/execution/orders/{order_id}")

    # -------------------------------------------------------------
    # 4. Resting Protective Stop-Loss Placement & Dynamic Trailing
    # -------------------------------------------------------------
    def place_stop_loss(self, entry_order_id: str, trigger_price: float, limit_price: float, request_id: Optional[str] = None, before_submit=None) -> dict:
        """POST /execution/stops: Place resting SELL SL-LIMIT on broker book."""
        req_id = request_id or f"AI-STOP-{datetime_now_id()}"
        payload = {
            "request_id": req_id,
            "entry_order_id": entry_order_id,
            "trigger_price": round_tick(trigger_price),
            "limit_price": round_tick(limit_price)
        }
        logger.info(f"Placing Resting Stop: EntryRef={entry_order_id} Trigger={payload['trigger_price']} Limit={payload['limit_price']}")
        if before_submit:
            blocked = before_submit()
            if blocked:
                return dict(blocked, outcome_unknown=False)
        return self._request("POST", "/execution/stops", payload, with_auth=True)

    def modify_stop_loss(self, stop_order_id: str, trigger_price: float, limit_price: float, before_submit=None) -> dict:
        """PATCH /execution/stops/{stop_order_id}: Raise an existing protective stop."""
        payload = {
            "trigger_price": round_tick(trigger_price),
            "limit_price": round_tick(limit_price)
        }
        logger.info(f"Ratcheting Resting Stop {stop_order_id}: New Trigger={payload['trigger_price']} Limit={payload['limit_price']}")
        if before_submit:
            blocked = before_submit()
            if blocked:
                return dict(blocked, outcome_unknown=False, not_submitted=True)
        return self._request("PATCH", f"/execution/stops/{stop_order_id}", payload, with_auth=True)

    def cancel_stop_loss(self, stop_order_id: str) -> dict:
        """DELETE /execution/stops/{stop_order_id}: Cancel resting stop."""
        logger.info(f"Requesting Cancellation of Resting Stop {stop_order_id}")
        return self._request("DELETE", f"/execution/stops/{stop_order_id}", with_auth=True)

    def wait_for_stop_cancellation(self, stop_order_id: str, timeout_sec: int = 10, poll_interval: float = 0.5) -> dict:
        deadline = time.monotonic() + timeout_sec
        while time.monotonic() < deadline:
            res = self._request("GET", f"/execution/orders/{stop_order_id}",
                                timeout=min(10, max(0.1, deadline - time.monotonic())), retry_reads=False)
            if not res.get("error") and status(res) in TERMINAL:
                return res  # FILLED is explicitly reconciled by the caller, never treated as cancelled.
            time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))
        return {"error": True, "detail": "STOP_CANCEL_TIMEOUT", "stop_order_id": stop_order_id}

    def cancel_all_resting_stops_for_symbol(self, symbol, *, known_stops=(), entry_order_ids=(), scope=None):
        """Cancel owned stops and verify terminal outcomes, including triggered OPEN stops."""
        scope = scope or {}
        try:
            orders = rows(self.get_orders(), "orders")
            known = {s["order_id"]: s for s in known_stops if s.get("order_id")}
            refs = set(entry_order_ids)
            for order in orders:
                if symbol_of(order) != symbol or str(order.get("kind", "")).upper() != "STOP":
                    continue
                owned = order.get("order_id") in known or order.get("entry_order_id") in refs
                if not same_scope(order, scope, owned):
                    if order.get("mode") and scope.get("mode") and order["mode"] != scope["mode"]:
                        continue
                    raise ReconciliationError("Ambiguous stop ownership")
                if status(order) not in TERMINAL:
                    known[order["order_id"]] = order
            outcomes = []
            for stop_id in known:
                current = self.get_order(stop_id)
                if current.get("error") or not current.get("status"):
                    raise ReconciliationError(f"Cannot verify stop {stop_id}")
                if (symbol_of(current) and symbol_of(current) != symbol) or not same_scope(current, scope, known=True):
                    raise ReconciliationError(f"Stop scope mismatch for {stop_id}")
                if current.get("kind", "STOP") != "STOP" or current.get("transaction_type", "SELL") != "SELL":
                    raise ReconciliationError(f"Not a protective SELL stop: {stop_id}")
                if status(current) not in TERMINAL:
                    self.cancel_stop_loss(stop_id)
                    current = self.wait_for_stop_cancellation(stop_id)
                    if current.get("error") or status(current) not in TERMINAL:
                        raise ReconciliationError(f"Cancellation unconfirmed for {stop_id}")
                outcomes.append(dict(current, order_id=stop_id))
            return {"status": "VERIFIED", "stops": outcomes}
        except (ReconciliationError, KeyError, TypeError, ValueError) as exc:
            return {"error": True, "detail": str(exc)}

    def exit_position(self, entry_order_id: str, limit_price: float, request_id: Optional[str] = None,
                      max_retries: int = 3, *, before_submit=None, cancel_and_verify=None,
                      fresh_price=None, price_preflight=None) -> dict:
        """Retry only explicit, definitive rejections; persist every intent before sending."""
        req_id = request_id or f"AI-EXIT-{datetime_now_id()}"
        price = round_tick(limit_price)
        for attempt in range(max_retries + 1):
            payload = {"request_id": req_id, "entry_order_id": entry_order_id, "limit_price": price}
            if before_submit:
                blocked = before_submit(payload)
                if blocked:
                    return blocked
            if price_preflight:
                blocked = price_preflight(payload)
                if blocked:
                    return blocked
            res = self._request("POST", "/execution/exit", payload)
            if not res.get("error") or res.get("outcome_unknown"):
                return res
            reason = str(res.get("detail", ""))
            if attempt == max_retries:
                return res
            if reason == "CANCEL_AND_VERIFY_STOP_BEFORE_EXIT" and cancel_and_verify:
                checked = cancel_and_verify()
                if checked.get("error"):
                    return checked
            elif "QUOTE_BAND" in reason and fresh_price:
                quote = fresh_price()
                if not quote or quote <= 0:
                    return res
                price = round_tick(quote)
            else:
                return res
            # The previous attempt was definitively rejected. A new persisted intent is safe.
            req_id = f"AI-EXIT-{datetime_now_id()}"
        return res

    def get_positions(self) -> dict:
        """GET /execution/positions: Return verified positions for the active mode."""
        return self._request("GET", "/execution/positions", with_auth=True)

    def get_orders(self) -> dict:
        """GET /execution/orders: Return up to 200 recent journal orders."""
        return self._request("GET", "/execution/orders", with_auth=True)

    def get_funds(self) -> dict:
        """GET /account/funds: Return available margin and cash balances."""
        root_url = self.base_url.replace("/ai", "")
        url = f"{root_url}/account/funds"
        return self._request("GET", url, with_auth=False)


def datetime_now_id() -> str:
    now_str = time.strftime("%Y%m%d%H%M%S")
    rand_suffix = uuid.uuid4().hex[:6]
    return f"{now_str}-{rand_suffix}"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    client = AIExecutionClient()
    print("Testing client connectivity against localhost:8000...")
    st = client.get_status()
    print("Execution Status:", json.dumps(st, indent=2))
