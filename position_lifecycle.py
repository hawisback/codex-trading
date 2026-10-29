"""Durable position lifecycle for the scheduler's deterministic execution layer.

The journal is bounded and can contain both execution modes. Missing ownership,
missing records, and unknown submission outcomes block new exposure.
"""

from trading.domain.limits import FEE_RESERVE, HARD_ENTRY_CUTOFF, HARD_SQUARE_OFF, LOT_SIZE, MAX_POSITION_QUANTITY
from trading.domain.states import PositionStatus

import copy
import json
from contextlib import nullcontext
import logging
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

from execution_client import round_tick
from entry_policy import EntryBlocked, EntryPolicy, entry_limit, number, timestamp, validate_approval, validate_invalidation
from execution_safety import (ReconciliationError, TERMINAL, atomic_save, filled,
                              remaining, rows, same_scope, status, symbol_of, SchedulerLock)
from market_clock import MarketClock
from trading.adapters.position_store import JsonPositionStore
from trading.ports import ExecutionGateway, PositionStore
from trading import audit

logger = logging.getLogger("NiftyAI")


def intent_id(kind):
    return f"AI-{kind}-{uuid.uuid4().hex}"


class PositionLifecycle:
    client: ExecutionGateway
    _oms_lock = threading.RLock()  # Also serializes different trader objects in this process.
    _entry_guard = threading.Lock()

    def initialize_safety(self, state_path, *, store: PositionStore | None = None):
        self.state_path = Path(state_path)
        self.position_store = store if store is not None else JsonPositionStore(
            self.state_path, writer=lambda path, data: atomic_save(path, data))
        self.state_verified = False
        self.execution_scope = {}
        self.is_submitting_order = False
        self.last_reconciliation_error = None

    def save_active_position(self, data):
        self.position_store.save(data)  # Propagate failure BEFORE any mutation is sent.
        audit.position(self, data)

    def load_active_position(self):
        return self.position_store.load()

    def next_intent(self, kind):
        return intent_id(kind)

    def _record_flat_entry_limits(self, scoped, today_entries):
        """Persist the first verified flat observation per entry set, across restarts.

        Broker stop creation time is not its fill time. Start the ten completed
        one-minute-bar cooldown at verified flatness instead of guessing a fill.
        """
        if getattr(self, "strategy_mode", None) != "macd_momentum" or not today_entries:
            return
        path = self.state_path.with_name(self.state_path.stem + "_entry_limits.json")
        today = MarketClock.today_ist_str()
        entries = sorted(o["order_id"] for o in scoped if o["kind"] == "ENTRY" and filled(o) > 0
                         and str(o.get("created_at", "")).startswith(today))
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        if not isinstance(current, dict):
            raise ReconciliationError("Entry spacing ledger is invalid")
        identity = dict(session=today, scope=self.execution_scope, entries=entries)
        if any(current.get(k) != v for k, v in identity.items()):
            atomic_save(path, dict(identity, flat_since=MarketClock.now_ist().isoformat()))

    def _entry_limit_block(self, today_entries):
        if getattr(self, "strategy_mode", None) != "macd_momentum":
            return None
        entry = self.strategy_cfg.get("entry", {})
        if today_entries >= entry.get("max_daily_entries", 2):
            return "DAILY_ENTRY_CAP"
        if today_entries:
            try:
                path = self.state_path.with_name(self.state_path.stem + "_entry_limits.json")
                state = json.loads(path.read_text(encoding="utf-8"))
                now = MarketClock.now_ist()
                flat = timestamp(state["flat_since"])
                if (state["session"] != MarketClock.today_ist_str() or state["scope"] != self.execution_scope
                        or len(state["entries"]) != today_entries or flat > now):
                    return "ENTRY_SPACING_UNVERIFIED"
                # Match the existing backtest convention: completed 1m bars since exit.
                elapsed = (now.replace(second=0, microsecond=0) - flat.replace(
                    second=0, microsecond=0) - timedelta(minutes=bool(flat.second or flat.microsecond))).total_seconds()
                if elapsed < entry.get("min_spacing_bars", 10) * 60:
                    return "ENTRY_SPACING_COOLDOWN"
            except (OSError, ValueError, TypeError, KeyError, OverflowError):
                return "ENTRY_SPACING_UNVERIFIED"
        return None

    def _scope(self, state):
        response = self.client.get_status()
        if response.get("error") or response.get("mode") not in ("LIVE", "PAPER"):
            raise ReconciliationError("Execution mode is unverified")
        scope = {k: response[k] for k in ("mode", "account_id") if response.get(k)}
        previous = state.get("scope") or self.execution_scope
        if previous and not same_scope(scope, previous, known=True):
            raise ReconciliationError("Execution scope changed while a position is unresolved")
        self.execution_scope = scope
        state["scope"] = dict(previous or {}, **scope)
        return state["scope"]

    def _refresh_record(self, record, journal):
        if not record.get("order_id"):
            match = next((o for o in journal if record.get("request_id") and
                          o.get("request_id") == record["request_id"]), None)
            if match:
                record.update(match)
        if record.get("order_id"):
            verified = self.client.get_order(record["order_id"])
            if verified.get("error") or not verified.get("status"):
                raise ReconciliationError(f"Unverified order {record['order_id']}")
            if status(verified) == "UNKNOWN":
                raise ReconciliationError("Broker order status is unknown")
            if status(verified) != "REJECTED" and verified.get("filled_quantity") is None:
                raise ReconciliationError("Broker filled quantity missing")
            if record.get("kind") == "STOP" and status(verified) not in TERMINAL:
                if verified.get("trigger_price") is None or verified.get("quantity") is None:
                    raise ReconciliationError("Broker stop trigger/quantity missing")
            if verified.get("order_id") and verified["order_id"] != record["order_id"]:
                raise ReconciliationError("Order identity mismatch")
            previous_ref = record.get("entry_order_id") or record.get("parent_order_id")
            verified_ref = verified.get("entry_order_id") or verified.get("parent_order_id")
            if previous_ref and verified_ref and previous_ref != verified_ref:
                raise ReconciliationError("Broker parent identity mismatch")
            if previous_ref and not verified_ref:
                verified = {**verified, "entry_order_id": previous_ref, "parent_order_id": previous_ref}
            record.update(verified)
            if not record.get("entry_order_id") and record.get("parent_order_id"):
                record["entry_order_id"] = record["parent_order_id"]
            record["status"] = status(record)
        elif status(record) not in TERMINAL:
            raise ReconciliationError("Submission outcome unknown; resolve by persisted request_id")

    def _entry_balances(self, state):
        balances = {e["order_id"]: filled(e) for e in state["entries"] if e.get("order_id")}
        for order in state["stops"] + state["exits"]:
            qty = filled(order)
            ref = order.get("entry_order_id") or order.get("parent_order_id")
            if qty and ref not in balances:
                raise ReconciliationError("Cannot allocate SELL fills to entry references")
            if ref in balances:
                balances[ref] -= qty
        if any(q < 0 for q in balances.values()):
            raise ReconciliationError("SELL fills exceed tracked entry quantity")
        return balances

    def get_trades_state(self, ensure_protection=True):
        with self._oms_lock, self.client.read_budget(20):
            self.state_verified = False
            state = {}
            try:
                state = self.load_active_position()
                scope = self._scope(state)
                restore = getattr(self.client, "restore_recovery_state", None)
                if restore is not None:
                    restore(state)
                positions = rows(self.client.get_positions(), "positions")
                if any(p.get("quantity") is None for p in positions):
                    raise ReconciliationError("Position quantity missing")
                positions = [p for p in positions if int(p["quantity"]) != 0]
                if len(positions) > 1 or any(int(p["quantity"]) < 0 for p in positions):
                    raise ReconciliationError("Unexpected multiple positions or short exposure")
                if positions and not same_scope(positions[0], scope, known=True):
                    raise ReconciliationError("Broker position scope changed")
                journal = rows(self.client.get_orders(), "orders")
                validate = getattr(self.client, "validate_reconciliation", None)
                if validate is not None:
                    validate(state, positions, journal)
                if any(not o.get("order_id") or not o.get("kind") or not o.get("status") for o in journal):
                    raise ReconciliationError("Journal order identity/status missing")
                for order in journal:
                    order["kind"] = str(order["kind"]).upper()
                    if order["kind"] not in ("ENTRY", "STOP", "EXIT") and status(order) not in TERMINAL:
                        raise ReconciliationError("Unrecognized active journal order kind")
                symbol = symbol_of(positions[0]) if positions else state.get("symbol")
                if positions and not symbol:
                    raise ReconciliationError("Position instrument missing")
                if state.get("symbol") and positions and symbol != state["symbol"]:
                    raise ReconciliationError("Broker instrument differs from unresolved local state")
                known = {o.get("order_id") for key in ("entries", "stops", "exits") for o in state.get(key, [])}
                refs = {e.get("order_id") for e in state.get("entries", []) if e.get("order_id")}
                requests = {o.get("request_id") for key in ("entries", "stops", "exits") for o in state.get(key, []) if o.get("request_id")}
                scoped = []
                for order in journal:
                    if not order.get("entry_order_id") and order.get("parent_order_id"):
                        order["entry_order_id"] = order["parent_order_id"]
                    owned = (order["order_id"] in known or order.get("entry_order_id") in refs
                             or order.get("parent_order_id") in refs or order.get("request_id") in requests)
                    if same_scope(order, scope, owned):
                        scoped.append(order)
                    elif not order.get("mode") and (status(order) not in TERMINAL or symbol_of(order) == symbol):
                        raise ReconciliationError("Journal lacks mode/ownership for relevant orders")
                today = MarketClock.today_ist_str()
                today_entries = sum(1 for o in scoped if o["kind"] == "ENTRY" and filled(o) > 0
                                    and str(o.get("created_at", "")).startswith(today))
                pending_any = [o for o in scoped if o["kind"] == "ENTRY" and status(o) not in TERMINAL]
                if not symbol:
                    if pending_any:
                        symbol = symbol_of(pending_any[0])
                    else:
                        orphan = next((o for o in scoped if o["kind"] in ("STOP", "EXIT")
                                       and status(o) not in TERMINAL), None)
                        if orphan:
                            symbol = symbol_of(orphan)
                        else:
                            self._record_flat_entry_limits(scoped, today_entries)
                            self.state_verified = True
                            self.last_reconciliation_error = None
                            return [], today_entries
                    if not symbol:
                        raise ReconciliationError("Active order instrument missing")
                state.setdefault("entries", [])
                state.setdefault("stops", [])
                state.setdefault("exits", [])
                state["symbol"] = symbol
                # Exclude completed earlier round trips in the same contract. Their
                # profit floors must never become the initial stop for a new trade.
                for kind, key in (("ENTRY", "entries"), ("STOP", "stops"), ("EXIT", "exits")):
                    for order in scoped:
                        if order["kind"] == kind and symbol_of(order) == symbol:
                            if kind == "ENTRY" and status(order) in TERMINAL:
                                balance = filled(order) - sum(filled(child) for child in scoped
                                    if (child.get("entry_order_id") == order["order_id"] or child.get("parent_order_id") == order["order_id"])
                                    and child["kind"] in ("STOP", "EXIT"))
                                if balance <= 0 and order["order_id"] not in known:
                                    continue
                            if kind in ("STOP", "EXIT") and status(order) in TERMINAL:
                                active_refs = {e.get("order_id") for e in state["entries"]}
                                child_ref = order.get("entry_order_id") or order.get("parent_order_id")
                                if child_ref not in active_refs and order["order_id"] not in known:
                                    continue
                            if not any(o.get("order_id") == order["order_id"] or
                                       (o.get("request_id") and o["request_id"] == order.get("request_id"))
                                       for o in state[key]):
                                state[key].append(copy.deepcopy(order))
                for key in ("entries", "stops", "exits"):
                    for record in state[key]:
                        self._refresh_record(record, scoped)
                # Cancel remaining BUY quantity before considering the position fully reconciled.
                cancelled_entry = False
                for entry in state["entries"]:
                    if entry.get("order_id") and status(entry) not in TERMINAL:
                        entry["cancel_requested_at"] = MarketClock.now_ist().isoformat()
                        self.save_active_position(state)
                        self.client.cancel_entry_order(entry["order_id"])
                        self._refresh_record(entry, scoped)
                        cancelled_entry = True
                if cancelled_entry:
                    # A cancellation can race another fill. Refresh both sides of
                    # the ledger before protecting the confirmed residual exposure.
                    positions = rows(self.client.get_positions(), "positions")
                    if any(p.get("quantity") is None for p in positions):
                        raise ReconciliationError("Position quantity missing after entry cancellation")
                    positions = [p for p in positions if int(p["quantity"]) != 0]
                    if (len(positions) > 1 or any(int(p["quantity"]) < 0 or symbol_of(p) != symbol or
                            not same_scope(p, scope, known=True) for p in positions)):
                        raise ReconciliationError("Unexpected position after entry cancellation")
                    for entry in state["entries"]:
                        self._refresh_record(entry, scoped)
                entry_pending = any(status(e) not in TERMINAL for e in state["entries"])
                if any(symbol_of(o) != symbol for o in pending_any):
                    raise ReconciliationError("Another instrument has unresolved entry quantity")
                quantity = int(positions[0]["quantity"]) if positions else 0
                balances = self._entry_balances(state)
                if quantity and sum(balances.values()) != quantity:
                    raise ReconciliationError("Broker quantity does not match reconciled entry/SELL fills")
                state["quantity"] = quantity
                state["entry_balances"] = balances
                if quantity and today_entries > 0:
                    # Recover older position files from the verified daily order book.
                    # New entries already persist their ordinal before submission.
                    state.setdefault("today_entry_number", today_entries)
                if positions:
                    pos = positions[0]
                    state["instrument_id"] = pos.get("instrument_id") or state.get("instrument_id", symbol)
                    state["entry_price"] = float(pos.get("average_price") or state.get("entry_price") or 0)
                    self.refresh_monitor_quote(state)
                    for field in ("product", "exchange", "account_id"):
                        if pos.get(field):
                            state["scope"][field] = pos[field]
                if entry_pending:
                    state["status"] = PositionStatus.ENTRY_PENDING.value
                    self.save_active_position(state)
                    # Keep verified partial fills protected even if cancellation
                    # remains pending. Further BUY fills are reconciled next cycle.
                    if quantity and ensure_protection and not state.get("risk_exit_required"):
                        self.state_verified = True
                        try:
                            self._ensure_protection(state)
                        finally:
                            self.state_verified = False
                    raise ReconciliationError("Unfilled entry quantity remains unresolved")
                live_sells = any(status(o) not in TERMINAL for o in state["stops"] + state["exits"])
                if not quantity and not live_sells:
                    if sum(balances.values()) != 0:
                        raise ReconciliationError("Flat snapshot disagrees with reconciled fills")
                    self._record_flat_entry_limits(scoped, today_entries)
                    audit.position(self, state, closed=True)
                    self.position_store.delete(missing_ok=True)
                    self.state_verified = True
                    self.last_reconciliation_error = None
                    return [], today_entries
                if state.get("status") not in ("EXIT_PENDING", "EXIT_UNKNOWN"):
                    state["status"] = PositionStatus.OPEN.value if quantity else PositionStatus.EXIT_PENDING.value
                if MarketClock.now_ist().strftime("%H:%M") >= HARD_SQUARE_OFF:
                    state["status"] = PositionStatus.EXIT_PENDING.value
                    state["exit_reason"] = "Mandatory 15:15 IST square-off"
                state.setdefault("entry_time", MarketClock.now_ist().isoformat())
                self.state_verified = True
                self.last_reconciliation_error = None
                self.save_active_position(state)
                if state["status"] == "OPEN" and ensure_protection and not state.get("risk_exit_required"):
                    self._ensure_protection(state)
                return [state], today_entries
            except (ReconciliationError, OSError, ValueError, TypeError, KeyError) as exc:
                self.state_verified = False
                self.last_reconciliation_error = str(exc)
                logger.critical("Reconciliation UNKNOWN; new entries blocked: %s", exc)
                audit.event("reconciliation_unknown", self, reason=str(exc), state=state)
                # Never replace valid persisted state with a failed broker read.
                return ([state] if state.get("symbol") else []), 0

    def refresh_monitor_quote(self, state, *, reuse=False):
        """Use timestamped executable bids; positions LTP is never a monitoring quote."""
        cfg = self.strategy_cfg.get("exit", {})
        max_age = float(cfg.get("monitor_quote_max_age_sec", 2))
        try:
            if reuse and state.get("quote_verified"):
                age = (MarketClock.now_ist() - timestamp(state["bid_timestamp"])).total_seconds()
                if 0 <= age <= max_age:
                    return True
            instrument = next((e.get("instrument_id") for e in state.get("entries", [])
                               if e.get("instrument_id")), state.get("instrument_id"))
            quote = getattr(self, "quote_reader", self.client).get_contract_quote(instrument,
                timeout_sec=float(cfg.get("monitor_quote_timeout_sec", 1.5)))
            if not isinstance(quote, dict) or quote.get("error"):
                raise ValueError("Active-contract quote unavailable")
            if str(quote.get("status", "LIVE")).upper() not in ("LIVE", "FRESH", "OK"):
                raise ValueError("Active-contract quote status is not fresh")
            if quote.get("instrument_id") != instrument:
                raise ValueError("Active-contract quote identity mismatch")
            age = (MarketClock.now_ist() - timestamp(quote.get("timestamp"))).total_seconds()
            bid, qty = number(quote.get("best_bid")), number(quote.get("best_bid_qty"))
            if bid <= 0 or round_tick(bid) != bid or qty <= 0 or qty != int(qty) or not 0 <= age <= max_age:
                raise ValueError("Active-contract bid is stale or has no liquidity")
            state.update(last_bid=bid, peak_bid=max(float(state.get("peak_bid") or 0), bid),
                         bid_timestamp=quote["timestamp"], quote_verified=True)
            state.pop("last_quote_error", None)
            return True
        except (EntryBlocked, ValueError, TypeError, KeyError, OSError) as exc:
            state.update(quote_verified=False, last_quote_error=str(exc))
            logger.error("Active position quote unverified for %s: %s", state.get("symbol"), exc)
            return False

    def _ensure_protection(self, state):
        from trading.application.stop_manager import StopManager
        StopManager(self).ensure(state)

    def ratchet_stops(self, state, trigger):
        from trading.application.stop_manager import StopManager
        with self._oms_lock:
            if not self.state_verified or state.get("status") != "OPEN":
                return
            latest = self.load_active_position()
            if not latest or latest.get("status") != "OPEN" or latest.get("entry_order_ids") != state.get("entry_order_ids"):
                return
            state.clear()
            state.update(latest)
            try:
                StopManager(self).ratchet(state, trigger)
            except ReconciliationError as exc:
                state["protection_confirmed"] = False
                self.save_active_position(state)
                logger.error("Trailing update remains unverified: %s", exc)

    def _exit_limit(self, state):
        if not self.refresh_monitor_quote(state, reuse=True):
            return None
        buffer_pct = float(self.strategy_cfg.get("exit", {}).get("exit_marketable_buffer_pct", .5))
        return max(.05, round_tick(state["last_bid"] - max(.05, state["last_bid"] * buffer_pct / 100)))

    def _manage_pending_exits(self, state):
        """Manage the same SELL ID; never place a competing SELL after an uncertain write."""
        cfg = self.strategy_cfg.get("exit", {})
        timeout = float(cfg.get("stop_confirmation_timeout_sec", 10))
        for order in state["exits"]:
            if status(order) in TERMINAL:
                continue
            pending = order.get("pending_reprice")
            if pending and status(order) == "OPEN" and float(order.get("price") or float("inf")) <= pending["price"]:
                order.pop("pending_reprice")
                pending = None
            expired = pending and (MarketClock.now_ist() - timestamp(pending["requested_at"])).total_seconds() >= timeout
            cancel_requested = order.get("cancel_requested_at")
            cancel = state["quantity"] == 0 or int(order.get("modifications", 0)) >= 25 or expired or cancel_requested
            if cancel_requested and (
                MarketClock.now_ist() - timestamp(cancel_requested)
            ).total_seconds() < timeout:
                continue  # Allow an acknowledged/uncertain cancellation to settle.
            if status(order) != "OPEN" or (pending and not expired):
                continue
            if cancel:
                method = getattr(self.client, "cancel_exit_order", None)
                if method:
                    order["cancel_requested_at"] = MarketClock.now_ist().isoformat()
                    self.save_active_position(state)
                    response = method(order["order_id"])
                    if response.get("error"):
                        order["last_cancel_error"] = response.get("detail")
                        if not response.get("outcome_unknown", True):
                            # A known non-cancellation can be retried next cycle.
                            order.pop("cancel_requested_at", None)
                    else:
                        order.pop("last_cancel_error", None)
                else:
                    logger.critical("Execution proxy cannot cancel pending exit; operator reconciliation required")
                continue
            price = self._exit_limit(state)
            if price is None or price >= float(order.get("price") or order.get("limit_price") or 0):
                continue
            method = getattr(self.client, "reprice_exit_order", None)
            if method is None:
                logger.critical("Execution proxy cannot reprice pending exit; operator reconciliation required")
                continue
            order["pending_reprice"] = dict(price=price, requested_at=MarketClock.now_ist().isoformat())
            order["modifications"] = int(order.get("modifications", 0)) + 1
            self.save_active_position(state)
            response = method(order["order_id"], price)
            if response.get("error") and not response.get("outcome_unknown", True):
                order.pop("pending_reprice", None)
        self.save_active_position(state)

    def exit_trade(self, trade_id, reason, limit_price=None):
        """Attempt each entry reference once; rejected exits resume on a later cycle."""
        with self._oms_lock:
            attempted_refs = set()
            while True:
                count = len(attempted_refs)
                result = self._exit_trade_once(trade_id, reason, limit_price, attempted_refs)
                if result.get("error") or result.get("status") == "CLOSED" or len(attempted_refs) == count:
                    return result
                state = self.load_active_position()
                pending_refs = {e.get("entry_order_id") or e.get("parent_order_id")
                                for e in state.get("exits", []) if status(e) not in TERMINAL}
                if not any(qty > 0 and ref not in attempted_refs and ref not in pending_refs
                           for ref, qty in state.get("entry_balances", {}).items()):
                    return result

    def _exit_trade_once(self, trade_id, reason, limit_price, attempted_refs):
        with self._oms_lock:
            trades, _ = self.get_trades_state(ensure_protection=False)
            if not self.state_verified:
                return {"error": True, "detail": self.last_reconciliation_error}
            if not trades:
                return {"status": "CLOSED"}
            state = trades[0]
            if state["entry_order_ids"] and trade_id not in state["entry_order_ids"]:
                return {"error": True, "detail": "STALE_EXIT_REQUEST"}
            state["status"] = PositionStatus.EXIT_PENDING.value
            state["exit_reason"] = reason
            state.pop("stop_replacement", None)  # Exit owns all subsequent protection transitions.
            self.save_active_position(state)
            if state["quantity"] and not self.refresh_monitor_quote(state, reuse=True):
                self.save_active_position(state)
                return {"error": True, "detail": "EXIT_QUOTE_UNAVAILABLE", "status": "EXIT_PENDING"}
            if any(status(e) not in TERMINAL for e in state["exits"]):
                self._manage_pending_exits(state)
            current_intent = [None]

            def refresh():
                current, _ = self.get_trades_state()
                if not self.state_verified:
                    return {"error": True, "detail": self.last_reconciliation_error}
                if current:
                    state.clear()
                    state.update(current[0])
                else:
                    state["quantity"] = 0
                return {"status": "VERIFIED"}

            def mark_rejected():
                if current_intent[0] is not None:
                    current_intent[0]["status"] = "REJECTED"
                    self.save_active_position(state)

            def cancel_and_verify():
                mark_rejected()  # Called again only after a definitive HTTP rejection.
                result = self.client.cancel_all_resting_stops_for_symbol(
                    state["symbol"], known_stops=state["stops"],
                    entry_order_ids=state["entry_order_ids"], scope=state["scope"])
                if result.get("error"):
                    return result
                for outcome in result["stops"]:
                    stop = next((s for s in state["stops"] if s.get("order_id") == outcome["order_id"]), None)
                    if stop:
                        stop.update(outcome)
                self.save_active_position(state)
                checked = refresh()  # Stop fills during cancellation reduce entry balances here.
                if not checked.get("error") and any(status(s) not in TERMINAL for s in state["stops"]):
                    logger.critical("Unexpected active stops after cancellation; reconcile request and order history before exit")
                    return {"error": True, "detail": "STOPS_REAPPEARED_DURING_EXIT"}
                return checked

            checked = cancel_and_verify()
            if checked.get("error"):
                return checked
            if state["quantity"] == 0:
                if self.position_store.exists():
                    logger.critical("Flat broker snapshot still has unresolved SELL orders for %s", state["symbol"])
                    return {"status": "EXIT_PENDING", "detail": "UNRESOLVED_SELL_ORDERS"}
                return {"status": "CLOSED"}
            pending_refs = {e.get("entry_order_id") or e.get("parent_order_id")
                            for e in state["exits"] if status(e) not in TERMINAL}
            ref = next((ref for ref, qty in state["entry_balances"].items()
                        if qty > 0 and ref not in pending_refs and ref not in attempted_refs), None)
            if not ref:
                return {"status": "EXIT_PENDING"}

            price = self._exit_limit(state)
            if price is None:
                return {"error": True, "detail": "EXIT_QUOTE_UNAVAILABLE", "status": "EXIT_PENDING"}

            def before_submit(payload):
                checked = refresh()
                if checked.get("error"):
                    return checked
                if not state["quantity"] or state["entry_balances"].get(ref, 0) <= 0:
                    return {"status": "CLOSED"}
                if any(status(s) not in TERMINAL for s in state["stops"]):
                    return {"error": True, "detail": "STOPS_REAPPEARED_DURING_EXIT"}
                if any(status(e) not in TERMINAL and (e.get("entry_order_id") or e.get("parent_order_id")) == ref for e in state["exits"]):
                    return {"error": True, "detail": "EXIT_ALREADY_PENDING"}
                latest_price = self._exit_limit(state)
                if latest_price is None:
                    return {"error": True, "detail": "EXIT_QUOTE_UNAVAILABLE"}
                payload["limit_price"] = latest_price
                record = dict(payload, status="SUBMITTING", kind="EXIT")
                state["exits"].append(record)
                current_intent[0] = record
                self.save_active_position(state)
                return None

            def fresh_price():
                mark_rejected()
                checked = refresh()
                return self._exit_limit(state) if not checked.get("error") and state["quantity"] else None

            def price_preflight(payload):
                latest = self._exit_limit(state)
                if latest is None:
                    return {"error": True, "detail": "EXIT_QUOTE_UNAVAILABLE"}
                payload["limit_price"] = latest
                current_intent[0]["limit_price"] = latest
                self.save_active_position(state)
                return None

            attempted_refs.add(ref)
            response = self.client.exit_position(ref, price,
                request_id=intent_id("EXIT"), before_submit=before_submit,
                cancel_and_verify=cancel_and_verify, fresh_price=fresh_price, price_preflight=price_preflight)
            record = current_intent[0]
            if record is not None:
                if response.get("order_id"):
                    record.update(order_id=response["order_id"], status="UNKNOWN")
                elif response.get("error"):
                    record["status"] = "UNKNOWN" if response.get("outcome_unknown", False) else "REJECTED"
                else:
                    record["status"] = "REJECTED"
                if self.position_store.exists():
                    self.save_active_position(state)
                if response.get("error") and record["status"] == "REJECTED":
                    self._ensure_protection(state)
            if response.get("error"):
                return response
            checked = refresh()
            if checked.get("error"):
                return {"status": "EXIT_PENDING", "detail": checked["detail"]}
            return {"status": "CLOSED"} if not self.position_store.exists() else {"status": "EXIT_PENDING"}

    def execute_trade(self, decision):
        if not self._entry_guard.acquire(blocking=False):
            return {"error": True, "detail": "ENTRY_IN_FLIGHT"}
        try:
            lock_path = self.state_path.parent / "scheduler.lock"
            process_guard = nullcontext() if SchedulerLock.is_held(lock_path) else SchedulerLock(lock_path)
            with process_guard, self._oms_lock:
                self.is_submitting_order = True
                trades, today_entries = self.get_trades_state()  # Atomic revalidation after AI consultation.
                if not self.state_verified or trades:
                    return {"error": True, "detail": "POSITION_OR_ORDER_UNRESOLVED"}
                return self._submit_entry(decision, today_entries=today_entries)
        finally:
            self.is_submitting_order = False
            self._entry_guard.release()

    def _submit_entry(self, decision, *, today_entries=0):
        blocked = self._entry_limit_block(today_entries)
        if blocked:
            return {"error": True, "detail": blocked}
        if (getattr(self, "strategy_mode", None) == "macd_momentum" and
                MarketClock.now_ist().strftime("%H:%M") < self.strategy_cfg.get("entry", {}).get("entry_start_time", "09:15")):
            return {"error": True, "detail": "ENTRY_ACTIVATION_PENDING"}
        if MarketClock.now_ist().strftime("%H:%M") >= HARD_ENTRY_CUTOFF:
            return {"error": True, "detail": "ENTRY_TIME_WINDOW_CLOSED"}
        if self.execution_scope.get("mode") == "LIVE":
            session = self.trading_cfg.get("session", {})
            allowed, reason = MarketClock.is_new_trade_allowed(
                no_new_trade_before=session.get("no_new_trade_before", "09:20"),
                no_new_trade_after=min(session.get("no_new_trade_after", HARD_ENTRY_CUTOFF), HARD_ENTRY_CUTOFF))
            if not allowed:
                return {"error": True, "detail": reason}
        try:
            policy = EntryPolicy.from_config(self.trading_cfg)
            effective_band = validate_approval(decision, policy)
        except EntryBlocked as exc:
            return {"error": True, "detail": str(exc)}
        register_contract = getattr(self.client, "register_contract", None)
        if register_contract is not None:
            try:
                register_contract(decision["instrument_id"], decision.get("symbol"))
            except ValueError as exc:
                return {"error": True, "detail": str(exc)}
        funds = self.client.get_funds()
        try:
            if not isinstance(funds, dict) or funds.get("error"):
                raise EntryBlocked("UNVERIFIED_FUNDS_OR_PRICE")
            margin = number(funds.get("available_margin"))
        except EntryBlocked:
            return {"error": True, "detail": "UNVERIFIED_FUNDS_OR_PRICE"}
        spot_quote = None
        quote_reader = getattr(self, "quote_reader", self.client)
        batch_quotes = getattr(quote_reader, "get_entry_quotes", None)
        quote_started = time.monotonic()
        if batch_quotes is not None:
            bundle = batch_quotes(decision["instrument_id"],
                include_index=decision.get("invalidation_level") is not None, timeout_sec=policy.quote_timeout)
            quote, spot_quote = bundle["quote"], bundle.get("spot_quote")
        elif decision.get("invalidation_level") is not None:
            spot_quote = quote_reader.get_contract_quote("INST-NIFTY-INDEX", timeout_sec=policy.quote_timeout)
        if decision.get("invalidation_level") is not None:
            try:
                validate_invalidation(decision, spot_quote, policy)
            except EntryBlocked as exc:
                return {"error": True, "detail": str(exc)}
        if batch_quotes is None:
            quote_started = time.monotonic()
            quote = quote_reader.get_contract_quote(decision["instrument_id"], timeout_sec=policy.quote_timeout)
        try:
            price = entry_limit(decision, quote, policy)
        except EntryBlocked as exc:
            logger.warning("[ENTRY BLOCKED] %s instrument=%s reference=%s quote=%s", exc,
                           decision["instrument_id"], decision.get("ltp"), quote)
            return {"error": True, "detail": str(exc)}
        qty = self.calculate_compounding_quantity(margin, price)
        affordable = max(0, int((margin - FEE_RESERVE) // (price * LOT_SIZE))) * LOT_SIZE
        # The global broker-margin policy, not a strategy-specific maximum,
        # limits the entry to the owner-approved tier and ten full lots.
        # The quote-derived limit price was validated above and sizing is
        # recalculated using freshly retrieved broker available margin.
        qty = min(qty, affordable, MAX_POSITION_QUANTITY)
        qty = (qty // LOT_SIZE) * LOT_SIZE
        if qty <= 0:
            return {"error": True, "detail": "INSUFFICIENT_MARGIN_BLOCKED"}
        now = MarketClock.now_ist()
        verdict = decision["ai_verdict"]
        cancel_after = min(now + timedelta(seconds=policy.order_timeout),
                           timestamp(verdict["entry_valid_until"]),
                           timestamp(verdict["entry_candidate_at"]) + timedelta(seconds=policy.candidate_age),
                           now.replace(hour=14, minute=15, second=0, microsecond=0))
        entry = {"request_id": intent_id("ENTRY"), "quantity": qty, "status": "SUBMITTING", "kind": "ENTRY",
                 "limit_price": price, "cancel_after": cancel_after.isoformat()}
        evidence = {"ai_verdict": copy.deepcopy(decision["ai_verdict"]), "quote": copy.deepcopy(quote),
                    "spot_quote": copy.deepcopy(spot_quote),
                    "effective_band": list(effective_band),
                    "final_limit": price, "quantity": qty,
                    "quote_check_duration_ms": (time.monotonic() - quote_started) * 1000,
                    "prepared_at": MarketClock.now_ist().isoformat()}
        state = {"symbol": decision.get("symbol") or decision["instrument_id"],
                 "instrument_id": decision["instrument_id"], "scope": self.execution_scope,
                 "quantity": 0, "status": PositionStatus.ENTRY_PENDING.value, "entries": [entry], "stops": [], "exits": [],
                 "entry_price": price, "last_bid": quote["best_bid"], "peak_bid": quote["best_bid"],
                 "entry_time": MarketClock.now_ist().isoformat(),
                 "today_entry_number": today_entries + 1,
                 "setup_type": decision.get("setup_type", "TREND_PULLBACK"),
                 "invalidation_level": decision.get("invalidation_level"), "entry_execution": evidence}
        if decision.get("stop_loss_context") is not None:
            state["entry_market_context"] = copy.deepcopy(decision["stop_loss_context"])
        if decision.get("stop_loss_policy"):
            state["stop_loss_policy"] = copy.deepcopy(decision["stop_loss_policy"])
            if state.get("entry_market_context") is not None and spot_quote is not None:
                state["entry_market_context"]["spot"] = number(spot_quote["last_price"])
                state["entry_market_context"]["observed_at"] = spot_quote["timestamp"]
        self.save_active_position(state)
        # Atomic persistence can also stall. A pre-submit failure is a known non-order,
        # unlike a lost POST response, and is safe to discard after saving its rejection.
        def preflight():
            if MarketClock.now_ist().strftime("%H:%M") >= HARD_ENTRY_CUTOFF:
                raise EntryBlocked("ENTRY_TIME_WINDOW_CLOSED")
            if entry_limit(decision, quote, policy) != price:
                raise EntryBlocked("ENTRY_PRICE_CHANGED")
            validate_invalidation(decision, spot_quote, policy)
            if MarketClock.now_ist() >= cancel_after:
                raise EntryBlocked("AI_ENTRY_APPROVAL_EXPIRED")
            evidence["quote_age_ms_at_submit"] = (MarketClock.now_ist() - timestamp(quote["timestamp"])).total_seconds() * 1000

        def reject_before_submit(exc):
            entry["status"] = "REJECTED"
            entry["last_error"] = str(exc)
            self.save_active_position(state)
            self.position_store.delete()
            logger.warning("[ENTRY BLOCKED BEFORE SUBMIT] %s", exc)
            return {"error": True, "detail": str(exc)}

        try:
            preflight()
        except EntryBlocked as exc:
            return reject_before_submit(exc)
        logger.info("[ENTRY EXECUTION] instrument=%s reference=%.2f band=[%.2f, %.2f] ask=%.2f limit=%.2f qty=%s",
                    state["instrument_id"], decision["ltp"], decision["ai_verdict"]["min_entry_price"],
                    decision["ai_verdict"]["max_entry_price"], quote["best_ask"], price, qty)
        evidence["submitted_at"] = MarketClock.now_ist().isoformat()
        submitted = time.monotonic()
        try:
            response = self.client.place_buy_order(state["instrument_id"], qty, price,
                request_id=entry["request_id"], before_submit=preflight)
        except EntryBlocked as exc:
            return reject_before_submit(exc)
        evidence["acknowledged_at"] = MarketClock.now_ist().isoformat()
        evidence["submission_duration_ms"] = (time.monotonic() - submitted) * 1000
        if response.get("order_id"):
            entry.update(order_id=response["order_id"], status="UNKNOWN")
        else:
            entry["status"] = "UNKNOWN" if response.get("outcome_unknown", True) else "REJECTED"
        self.save_active_position(state)
        if not response.get("order_id"):
            return dict(response, error=True, detail=response.get("detail", "ENTRY_OUTCOME_UNKNOWN"))
        # Count acknowledgement latency toward the allowed resting lifetime.
        remaining_lifetime = max(0, policy.order_timeout - (time.monotonic() - submitted))
        remaining_lifetime = max(0, min(remaining_lifetime,
            (cancel_after - MarketClock.now_ist()).total_seconds()))
        fill = self.client.wait_for_fill(entry["order_id"], timeout_sec=remaining_lifetime,
                                         return_on_partial=True)
        if not fill.get("error"):
            entry.update(fill)
            evidence["fill_observed_at"] = MarketClock.now_ist().isoformat()
            self.save_active_position(state)
        trades, _ = self.get_trades_state()
        if not self.state_verified or not trades or not trades[0].get("protection_confirmed"):
            return {"error": True, "detail": "ENTRY_OR_PROTECTION_UNCONFIRMED", "order_id": entry["order_id"]}
        return {"status": "SUCCESS", "order_id": entry["order_id"], "stop_order_ids": trades[0]["stop_order_ids"]}
