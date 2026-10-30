"""Serialized native execution with explicit arming and durable order correlation."""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import logging
from pathlib import Path
import threading
import time
import uuid
from typing import Any, Iterable, Optional

from execution_safety import (
    ReconciliationError,
    TERMINAL,
    filled,
    rows,
    same_scope,
    status,
    symbol_of,
)
from entry_policy import EntryBlocked
from trading.adapters.gateways.journal import GatewayJournal
from trading.adapters.gateways.rate_limiter import TokenBucketRateLimiter
from trading.application.oms_ownership import AccountSessionLease
from trading.domain.prices import round_tick

logger = logging.getLogger("BrokerGateway")


def datetime_now_id():
    return uuid.uuid4().hex


class BaseBrokerGateway(ABC):
    def __init__(
        self,
        *,
        broker_name,
        rate_limit_per_sec=5.0,
        burst_capacity=5.0,
        orders_cache_ttl_sec=0,
        positions_cache_ttl_sec=0,
        funds_cache_ttl_sec=0,
        journal_path=None,
    ):
        self.broker_name = broker_name
        self.rate_limiter = TokenBucketRateLimiter(
            rate=min(rate_limit_per_sec, 10), capacity=min(burst_capacity, 5)
        )
        self.quote_limiter = TokenBucketRateLimiter(rate=1, capacity=1)
        self._read_limit = ContextVar("native_read_deadline", default=None)
        self._check = ContextVar("native_submission_check", default=None)
        self._entry_context: ContextVar[dict[str, Any]] = ContextVar("native_entry_context", default={})
        self._order_payload: ContextVar[Optional[dict[str, Any]]] = ContextVar(
            "native_order_payload", default=None
        )
        self._lock = threading.RLock()
        self._mode = "PAPER"
        self._live_authorized = False
        self._account_lease = None
        self._leased_account = None
        self.journal = GatewayJournal(
            journal_path or Path(__file__).resolve().parents[3] / "logs/broker_intents.json", broker_name
        )
        # Reconciliation reads deliberately bypass TTL caches.

    @property
    def _read_deadline(self):
        return self._read_limit.get()

    @contextmanager
    def read_budget(self, seconds):
        previous = self._read_deadline
        deadline = time.monotonic() + seconds
        token = self._read_limit.set(min(previous, deadline) if previous is not None else deadline)
        try:
            yield
        finally:
            self._read_limit.reset(token)

    def invalidate_orders_cache(self):
        pass

    def invalidate_positions_cache(self):
        pass

    def invalidate_funds_cache(self):
        pass

    def invalidate_all_caches(self):
        pass

    def _acquire_rate_token(self, timeout=10.0):
        if self._read_deadline is not None:
            timeout = min(timeout, self._read_deadline - time.monotonic())
        return timeout > 0 and self.rate_limiter.acquire(timeout=timeout)

    def _owns_account_lease(self):
        return (
            self._account_lease is not None
            and self._leased_account == self.get_account_id()
            and self._account_lease.owns_current_process()
        )

    def get_status(self):
        connected = self.is_connected()
        account = self.get_account_id()
        if connected and account:
            self.journal.bind(account)
        return {
            "mode": self._mode,
            "broker": self.broker_name,
            "connected": connected,
            "live_authorized": (
                self._mode == "LIVE" and self._live_authorized and connected and self._owns_account_lease()
            ),
            "account_id": account,
        }

    def set_mode(self, mode):
        with self._lock:
            self._live_authorized = False
            self._mode = "PAPER"
            if mode not in ("LIVE", "PAPER"):
                return self._error("INVALID_MODE")
            if mode == "PAPER":
                return {"mode": "PAPER", "live_authorized": False}
            try:
                current = self.get_status()
                if current.get("error") or not current.get("connected") or not current.get("account_id"):
                    return self._error("BROKER_ACCOUNT_UNVERIFIED")
                account = current["account_id"]
                if self._account_lease is None:
                    lease = AccountSessionLease(
                        self.journal.path.parent,
                        broker=self.broker_name,
                        verified_account=account,
                    )
                    lease.__enter__()
                    self._account_lease = lease
                    self._leased_account = account
                elif self._leased_account != account or not self._owns_account_lease():
                    return self._error("OMS_ACCOUNT_OWNERSHIP_UNVERIFIED")
                self._mode, self._live_authorized = "LIVE", True
                return {"mode": "LIVE", "live_authorized": True, "account_id": current["account_id"]}
            except Exception as exc:
                return self._error(str(exc))

    @staticmethod
    def _error(detail, *, unknown=False):
        return {"error": True, "detail": detail, "outcome_unknown": unknown}

    def _authorize(self):
        if self._mode != "LIVE" or not self._live_authorized:
            raise ReconciliationError("NATIVE_LIVE_NOT_ARMED")
        if not self._owns_account_lease():
            raise ReconciliationError("OMS_ACCOUNT_OWNERSHIP_UNVERIFIED")
        current = self.get_status()
        if current.get("error") or not current.get("live_authorized"):
            raise ReconciliationError("BROKER_ACCOUNT_UNVERIFIED")

    def restore_recovery_state(self, state):
        with self._lock:
            if not state.get("entries"):
                return
            if not same_scope(
                state.get("scope", {}), {"mode": "LIVE", "account_id": self.get_account_id()}, known=True
            ):
                raise ReconciliationError("Recovery account mismatch")
            for key in ("entries", "stops", "exits"):
                for record in state.get(key, []):
                    if not record.get("request_id") and not record.get("order_id"):
                        raise ReconciliationError("Recovery record lacks an order/request identity")
                    request_id = record.get("request_id") or ("RECOVERED-" + str(record.get("order_id")))
                    old = self.journal.records.get(request_id, {})
                    updates = {
                        "kind": record.get(
                            "kind", {"entries": "ENTRY", "stops": "STOP", "exits": "EXIT"}[key]
                        ),
                        "entry_order_id": record.get("entry_order_id") or record.get("parent_order_id"),
                        "symbol": state.get("symbol"),
                        "phase": old.get(
                            "phase",
                            "REJECTED"
                            if status(record) == "REJECTED" and not record.get("order_id")
                            else "UNKNOWN",
                        ),
                    }
                    if old.get("symbol"):
                        if str(old["symbol"]).split(":")[-1] != str(state.get("symbol")).split(":")[-1]:
                            raise ReconciliationError("Recovery symbol mismatch")
                        updates["symbol"] = old["symbol"]
                    if key == "entries" and state.get("instrument_id"):
                        updates["instrument_id"] = old.get("instrument_id") or state["instrument_id"]
                    if record.get("order_id"):
                        updates["order_id"] = str(record["order_id"])
                    for field in ("kind", "entry_order_id", "order_id"):
                        if old.get(field) and updates.get(field) and old[field] != updates[field]:
                            raise ReconciliationError("Recovery intent identity mismatch")
                        if old.get(field) and not updates.get(field):
                            updates[field] = old[field]
                    self.journal.put(request_id, **updates)

    def get_entry_ref_for_stop(self, order_id):
        item = self.journal.match(order_id=order_id)
        return item.get("entry_order_id") if item else None

    def link_stop_to_entry(self, stop_order_id, entry_order_id):
        item = self.journal.match(order_id=stop_order_id)
        self.journal.put(
            item["request_id"] if item else "RECOVERED-" + str(stop_order_id),
            order_id=str(stop_order_id),
            entry_order_id=str(entry_order_id),
            kind="STOP",
            phase="ACKNOWLEDGED",
        )

    def map_request_id(self, request_id, order_id):
        self.journal.put(request_id, order_id=str(order_id))

    def get_orders(self):
        try:
            with self._lock:
                orders = self._fetch_broker_orders()
                if not isinstance(orders, list) or any(not isinstance(o, dict) for o in orders):
                    raise ReconciliationError("Malformed broker orders")
                return {"orders": copy.deepcopy(orders)}
        except Exception as exc:
            return self._error(str(exc))

    def get_positions(self):
        try:
            with self._lock:
                positions = self._fetch_broker_positions()
                if not isinstance(positions, list) or any(not isinstance(p, dict) for p in positions):
                    raise ReconciliationError("Malformed broker positions")
                return {"positions": copy.deepcopy(positions)}
        except Exception as exc:
            return self._error(str(exc))

    def get_funds(self):
        try:
            with self._lock:
                funds = self._fetch_broker_funds()
                if not isinstance(funds, dict) or funds.get("error") or funds.get("available_margin") is None:
                    raise ReconciliationError("Unverified broker funds")
                return copy.deepcopy(funds)
        except Exception as exc:
            return self._error(str(exc))

    def get_order(self, order_id):
        response = self.get_orders()
        if response.get("error"):
            return response
        matches = [o for o in response["orders"] if str(o.get("order_id")) == str(order_id)]
        return matches[0] if len(matches) == 1 else self._error("ORDER_NOT_FOUND_OR_AMBIGUOUS")

    @contextmanager
    def _submission(self, check=None, entry=None, order_payload=None):
        token = self._check.set(check)
        context = self._entry_context.set(entry or {})
        payload_context = self._order_payload.set(order_payload)
        try:
            yield
        finally:
            self._check.reset(token)
            self._entry_context.reset(context)
            self._order_payload.reset(payload_context)

    def _before_transmit(self):
        check = self._check.get()
        self._check.set(None)  # A lifecycle exit callback persists one intent, exactly once.
        return check() if check else None

    def _prepare(self, request_id, kind, symbol, ref=None, instrument_id=None):
        previous = self.journal.records.get(request_id)
        if previous:
            if (
                previous.get("kind") != kind
                or previous.get("symbol") != symbol
                or previous.get("entry_order_id") != ref
            ):
                raise ReconciliationError("Request ID reused for different order")
            if previous.get("phase") == "REJECTED":
                return self._error("PREVIOUS_REQUEST_REJECTED")
            response = self.get_orders()
            if not response.get("error"):
                matches = [o for o in response["orders"] if o.get("request_id") == request_id]
                if len(matches) == 1:
                    return dict(matches[0], recovered=True)
            return self._error("SUBMISSION_OUTCOME_UNKNOWN", unknown=True)
        if any(record.get("phase") in ("PREPARED", "UNKNOWN") for record in self.journal.records.values()):
            return self._error("ANOTHER_SUBMISSION_OUTCOME_UNKNOWN", unknown=True)
        self.journal.put(
            request_id,
            kind=kind,
            symbol=symbol,
            instrument_id=instrument_id,
            entry_order_id=ref,
            phase="PREPARED",
        )
        return None

    def _submit_intent(
        self,
        request_id,
        kind,
        symbol,
        send,
        *,
        ref=None,
        check=None,
        entry=None,
        instrument_id=None,
        order_payload=None,
    ):
        try:
            self._authorize()
            previous = self._prepare(request_id, kind, symbol, ref, instrument_id)
            if previous is not None:
                return previous
        except Exception as exc:
            return self._error(str(exc))  # No mutation has been sent.
        try:
            with self._submission(check, entry, order_payload):
                response = send(self.journal.records[request_id]["tag"])
        except EntryBlocked:
            self.journal.put(request_id, phase="REJECTED")
            raise
        except Exception:
            return self._error("SUBMISSION_OUTCOME_UNKNOWN", unknown=True)
        if not isinstance(response, dict) or (not response.get("error") and not response.get("order_id")):
            if isinstance(response, dict) and response.get("status") == "CLOSED":
                self.journal.put(request_id, phase="REJECTED")
                return response
            return self._error("INVALID_MUTATION_RESPONSE", unknown=True)
        try:
            updates = {
                "phase": "UNKNOWN"
                if response.get("outcome_unknown")
                else ("REJECTED" if response.get("error") else "ACKNOWLEDGED")
            }
            if response.get("order_id"):
                updates["order_id"] = str(response["order_id"])
            self.journal.put(request_id, **updates)
        except Exception:
            return dict(response, error=True, detail="ACK_PERSISTENCE_FAILED", outcome_unknown=True)
        return response

    def place_buy_order(self, instrument_id, quantity, limit_price, request_id=None, before_submit=None):
        with self._lock:
            try:
                symbol = self.execution_symbol(instrument_id)
            except ValueError as exc:
                return self._error(str(exc))
            request_id = request_id or "AI-ENTRY-" + datetime_now_id()
            return self._submit_intent(
                request_id,
                "ENTRY",
                symbol,
                lambda tag: self._submit_buy_order(symbol, quantity, round_tick(limit_price), tag),
                check=before_submit,
                instrument_id=instrument_id,
            )

    def execution_symbol(self, instrument_id):
        return str(instrument_id)

    def _residual(self, ref, *, require_no_sells=False, allow_pending_entry=False):
        orders = rows(self.get_orders(), "orders")
        entry = next((o for o in orders if o.get("order_id") == ref and o.get("kind") == "ENTRY"), None)
        if (
            not entry
            or entry.get("filled_quantity") is None
            or (not allow_pending_entry and status(entry) not in TERMINAL)
        ):
            raise ReconciliationError("Entry fills are unverified or still pending")
        if not self.journal.match(order_id=ref):
            raise ReconciliationError("Entry order ownership is unverified")
        balance = int(entry["filled_quantity"])
        if balance <= 0:
            raise ReconciliationError("No confirmed entry balance")
        relevant = []
        for order in orders:
            if order.get("kind") not in ("STOP", "EXIT") or symbol_of(order) != symbol_of(entry):
                continue
            if not same_scope(order, entry, known=True):
                continue
            parent = order.get("entry_order_id") or order.get("parent_order_id")
            if not parent and (filled(order) or status(order) not in TERMINAL):
                raise ReconciliationError("Unallocated SELL order")
            if parent == ref:
                if order.get("filled_quantity") is None:
                    raise ReconciliationError("SELL fill quantity missing")
                balance -= int(order["filled_quantity"])
                relevant.append(order)
        if balance <= 0:
            raise ReconciliationError("No residual long exposure")
        if require_no_sells and any(status(o) not in TERMINAL for o in relevant):
            raise ReconciliationError("CANCEL_AND_VERIFY_STOP_BEFORE_EXIT")
        positions = rows(self.get_positions(), "positions")
        matching = [
            p for p in positions if symbol_of(p) == symbol_of(entry) and same_scope(p, entry, known=True)
        ]
        if len(matching) != 1 or int(matching[0].get("quantity", 0)) < balance:
            raise ReconciliationError("Residual quantity disagrees with broker position")
        return entry, balance, relevant

    def place_stop_loss(
        self, entry_order_id, trigger_price, limit_price, request_id=None, before_submit=None
    ):
        with self._lock:
            try:
                self._authorize()
                entry, qty, orders = self._residual(
                    entry_order_id, require_no_sells=True, allow_pending_entry=True
                )
                if any(status(o) not in TERMINAL for o in orders):
                    raise ReconciliationError("Existing protective SELL order")
            except Exception as exc:
                return self._error(str(exc))

            def final_check():
                blocked = before_submit() if before_submit else None
                if blocked:
                    return blocked
                try:
                    _, fresh_qty, _ = self._residual(
                        entry_order_id, require_no_sells=True, allow_pending_entry=True
                    )
                    if fresh_qty != qty:
                        return self._error("STOP_QUANTITY_CHANGED")
                    return before_submit() if before_submit else None
                except Exception as exc:
                    return self._error(str(exc))

            return self._submit_intent(
                request_id or "AI-STOP-" + datetime_now_id(),
                "STOP",
                symbol_of(entry),
                lambda tag: self._submit_stop_loss(
                    symbol_of(entry), qty, round_tick(trigger_price), round_tick(limit_price), tag
                ),
                ref=entry_order_id,
                entry=entry,
                check=final_check,
            )

    def _mutate_existing(self, order_id, send, kind, check=None):
        with self._lock:
            try:
                self._authorize()
                order = self.get_order(order_id)
                if order.get("error") or not self.journal.match(order_id=order_id):
                    return self._error("Order ownership is unverified")
                if order.get("kind") != kind or order.get("variety", "regular") != "regular":
                    return self._error("Unexpected broker order kind or variety")
                if status(order) in TERMINAL:
                    return order
                with self._submission(check=check):
                    response = send()
                return (
                    response
                    if isinstance(response, dict)
                    else self._error("INVALID_MUTATION_RESPONSE", unknown=True)
                )
            except Exception as exc:
                return self._error(str(exc), unknown=True)

    def cancel_entry_order(self, order_id):
        return self._mutate_existing(order_id, lambda: self._submit_cancel_order(order_id), "ENTRY")

    def cancel_stop_loss(self, stop_order_id):
        return self._mutate_existing(stop_order_id, lambda: self._submit_cancel_order(stop_order_id), "STOP")

    def cancel_exit_order(self, order_id):
        return self._mutate_existing(order_id, lambda: self._submit_cancel_order(order_id), "EXIT")

    def reprice_exit_order(self, order_id, limit_price):
        return self._mutate_existing(
            order_id, lambda: self._submit_reprice_exit(order_id, limit_price), "EXIT"
        )

    def _submit_reprice_exit(self, order_id, limit_price):
        return self._error("EXIT_REPRICE_UNSUPPORTED")

    def modify_stop_loss(self, stop_order_id, trigger_price, limit_price, before_submit=None):
        def check():
            blocked = before_submit() if before_submit else None
            if blocked:
                return dict(blocked, outcome_unknown=False, not_submitted=True)
            current = self.get_order(stop_order_id)
            if current.get("error") or status(current) != "TRIGGER_PENDING":
                return dict(self._error("STOP_NOT_TRIGGER_PENDING"), not_submitted=True)
            if round_tick(trigger_price) <= float(current.get("trigger_price") or 0):
                return dict(self._error("STOP_ALREADY_AT_OR_ABOVE_TARGET"), not_submitted=True)
            blocked = before_submit() if before_submit else None
            if blocked:
                return dict(blocked, outcome_unknown=False, not_submitted=True)
            return None

        return self._mutate_existing(
            stop_order_id,
            lambda: self._submit_modify_stop(
                stop_order_id, round_tick(trigger_price), round_tick(limit_price)
            ),
            "STOP",
            check=check,
        )

    def wait_for_fill(self, order_id, timeout_sec=15, poll_interval=0.5, return_on_partial=False):
        last = {}
        with self.read_budget(timeout_sec):
            while self._read_deadline is not None and time.monotonic() < self._read_deadline:
                last = self.get_order(order_id)
                if not last.get("error") and (
                    status(last) in TERMINAL or (return_on_partial and filled(last) > 0)
                ):
                    return last
                time.sleep(min(poll_interval, max(0, self._read_deadline - time.monotonic())))
        return dict(self._error("FILL_POLL_TIMEOUT", unknown=True), last_order=last)

    def wait_for_stop_cancellation(self, stop_order_id, timeout_sec=10, poll_interval=0.5):
        return self.wait_for_fill(stop_order_id, timeout_sec, poll_interval)

    def cancel_all_resting_stops_for_symbol(
        self,
        symbol: str,
        *,
        known_stops: Iterable[dict] = (),
        entry_order_ids: Iterable[str] = (),
        scope: Optional[dict] = None,
    ) -> dict:
        """Cancel all resting protective SELL stops for the symbol and verify outcomes."""
        try:
            self._authorize()
        except Exception as exc:
            return self._error(str(exc))
        scope = scope or {}
        try:
            self.invalidate_orders_cache()
            orders = rows(self.get_orders(), "orders")
            known = {s["order_id"]: s for s in known_stops if s.get("order_id")}
            refs = set(entry_order_ids)

            for order in orders:
                if symbol_of(order) != symbol or str(order.get("kind", "")).upper() != "STOP":
                    continue
                owned = (
                    order.get("order_id") in known
                    or order.get("entry_order_id") in refs
                    or order.get("parent_order_id") in refs
                )
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
                if (symbol_of(current) and symbol_of(current) != symbol) or not same_scope(
                    current, scope, known=True
                ):
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

    def exit_position(
        self,
        entry_order_id,
        limit_price,
        request_id=None,
        max_retries=3,
        *,
        before_submit=None,
        cancel_and_verify=None,
        fresh_price=None,
        price_preflight=None,
    ):
        """One SELL attempt. An uncertain response is reconciled, never resent here."""
        with self._lock:
            try:
                self._authorize()
                if cancel_and_verify:
                    result = cancel_and_verify()
                    if result.get("error"):
                        return result
                entry, qty, _ = self._residual(entry_order_id, require_no_sells=True)
            except Exception as exc:
                return self._error(str(exc))
            request_id = request_id or "AI-EXIT-" + datetime_now_id()
            price = round_tick(limit_price)
            payload = {"request_id": request_id, "entry_order_id": entry_order_id, "limit_price": price}

            def final_check():
                blocked = before_submit(payload) if before_submit else None
                if blocked:
                    return blocked
                try:
                    _, fresh_qty, _ = self._residual(entry_order_id, require_no_sells=True)
                    if fresh_qty != qty:
                        return self._error("EXIT_QUANTITY_CHANGED")
                    return price_preflight(payload) if price_preflight else None
                except Exception as exc:
                    return self._error(str(exc))

            return self._submit_intent(
                request_id,
                "EXIT",
                symbol_of(entry),
                lambda tag: self._submit_exit_order(symbol_of(entry), qty, payload["limit_price"], tag),
                ref=entry_order_id,
                check=final_check,
                entry=entry,
                order_payload=payload,
            )

    @abstractmethod
    def is_connected(self): ...
    @abstractmethod
    def get_account_id(self): ...
    @abstractmethod
    def _fetch_broker_orders(self): ...
    @abstractmethod
    def _fetch_broker_positions(self): ...
    @abstractmethod
    def _fetch_broker_funds(self): ...
    @abstractmethod
    def _submit_buy_order(self, symbol, quantity, limit_price, tag): ...
    @abstractmethod
    def _submit_stop_loss(self, symbol, quantity, trigger_price, limit_price, tag): ...
    @abstractmethod
    def _submit_modify_stop(self, order_id, trigger_price, limit_price): ...
    @abstractmethod
    def _submit_cancel_order(self, order_id): ...
    @abstractmethod
    def _submit_exit_order(self, symbol, quantity, limit_price, tag): ...
    @abstractmethod
    def get_contract_quote(self, instrument_id, *, timeout_sec=1.0): ...
