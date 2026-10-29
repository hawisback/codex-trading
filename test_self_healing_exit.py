"""Offline OMS failure scenarios. All state lives in temporary repository directories.

These are execution-layer unit tests, not live/backtest runs. AI gate integration
uses the actual playbook consultant; it is never replaced. No broker is contacted.
"""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
from unittest.mock import patch

from execution_client import AIExecutionClient
from execution_safety import SchedulerLock, atomic_save, filled, status
from position_lifecycle import PositionLifecycle
from market_clock import MarketClock

ROOT = Path(__file__).resolve().parent
SYMBOL = "NIFTY-TEST-CE"


def entry_dossier(price=100, **changes):
    from ai_context_dossier import MarketDossier
    values = dict(
        date="2026-10-19", time_utc="04:30", time_ist="10:00", direction="CE", symbol=SYMBOL,
        strike=23000, option_entry_price=price, spot_price=23000, session_phase="MORNING_TREND",
        minutes_from_open=45, minutes_to_close=330, is_expiry_0dte=False, days_to_expiry=2,
        gamma_hazard_flag=False, session_vwap=22990, vwap_distance_pts=10, vwap_slope_15m=.2,
        vwap_cross_count_60m=0, vwap_blender_warning=False, box_range_15m=40, box_range_30m=60,
        box_position_pct=50, compression_hazard=False, ceiling_floor_hazard=False,
        ema9_5m=23000, ema20_5m=22994, ema_spread_5m=6, ribbon_compression_hazard=False,
        pullback_distance_pts=0, rsi_1m=55, day_high=23050, day_low=22900,
        day_range_pts=150, distance_to_day_extreme=50, last_trade_direction=None,
        last_trade_pnl=None, minutes_since_last_exit=None, consecutive_losses_today=0,
        is_directional_shift=False, realized_pnl_today=0, trades_taken_today=0,
        capital_preservation_active=False, instrument_id="TEST", setup_type="TREND_PULLBACK")
    values.update(changes)
    return MarketDossier(**values)


def approved_decision(config, price=100, **changes):
    from ai_consultant import AIConsultant
    decision = dict(symbol=SYMBOL, instrument_id="TEST", ltp=price, setup_type="TREND_PULLBACK")
    decision.update(changes)
    dossier = entry_dossier(price, instrument_id=decision["instrument_id"], setup_type=decision["setup_type"],
                            invalidation_level=decision.get("invalidation_level"),
                            risk_policy=copy.deepcopy(decision.get("stop_loss_policy", {})))
    decision["ai_verdict"] = AIConsultant(mode="playbook", trading_config=config).evaluate(dossier).to_dict()
    assert decision["ai_verdict"]["action"] == "APPROVED", decision["ai_verdict"]
    return decision


class Broker(AIExecutionClient):
    def __init__(self):
        super().__init__(base_url="http://invalid.test", api_key="test")
        self.orders = {}
        self.calls = []
        self.position_error = None
        self.journal_error = None
        self.position_override = None
        self.cancel_behavior = "cancel"
        self.exit_status = "OPEN"
        self.exit_error = None
        self.stop_error = None
        self.entry_error = None
        self.lost_entry_response = False
        self.lost_stop_response = False
        self.patch_failures = set()
        self.on_submit = None
        self.next_entry_status = "FILLED"
        self.next_entry_filled = None
        self.bid = 120.0
        self.quote_ask = 100.0
        self.quote_error = None
        self.fill_price = 100
        self.spot_price = 23000

    def get_contract_quote(self, instrument_id, **kwargs):
        self.calls.append(("GET", "/market/quote/" + instrument_id, None))
        if instrument_id == "INST-NIFTY-INDEX":
            return dict(instrument_id=instrument_id, last_price=self.spot_price,
                        timestamp=MarketClock.now_ist().isoformat(), request_started_monotonic=time.monotonic())
        exposed = any(o["kind"] == "ENTRY" and filled(o) > 0 for o in self.orders.values())
        bid = self.bid if exposed else round(self.quote_ask - .05, 2)
        ask = max(self.quote_ask, bid + .05) if exposed else self.quote_ask
        return copy.deepcopy(self.quote_error) if self.quote_error else dict(
            instrument_id=instrument_id, best_bid=bid, best_ask=ask,
            best_bid_qty=650, best_ask_qty=650, timestamp=MarketClock.now_ist().isoformat(),
            request_started_monotonic=time.monotonic())

    def add(self, kind, oid, quantity=65, order_status="FILLED", ref=None, **extra):
        record = dict(kind=kind, order_id=oid, quantity=quantity, status=order_status,
                      symbol=SYMBOL, mode="LIVE", created_at=MarketClock.today_ist_str() + "T10:00:00+05:30")
        if ref:
            record["entry_order_id"] = ref
        if order_status == "FILLED":
            record["filled_quantity"] = quantity
        else:
            record["filled_quantity"] = 0
        if kind == "STOP":
            record["trigger_price"] = 70
        record.update(extra)
        self.orders[oid] = record
        return record

    def balance(self, ref):
        return filled(self.orders[ref]) - sum(filled(o) for o in self.orders.values()
                                             if o.get("entry_order_id") == ref)

    def _request(self, method, path, payload=None, **kwargs):
        self.calls.append((method, path, copy.deepcopy(payload)))
        if method == "GET" and path == "/execution/status":
            return {"mode": "LIVE"}
        if method == "GET" and path == "/execution/orders":
            return copy.deepcopy(self.journal_error or list(self.orders.values()))
        if method == "GET" and path == "/execution/positions":
            if self.position_error:
                return copy.deepcopy(self.position_error)
            if self.position_override is not None:
                return copy.deepcopy(self.position_override)
            qty = sum(filled(o) * (1 if o["kind"] == "ENTRY" else -1) for o in self.orders.values()
                      if o.get("mode") == "LIVE" and o.get("symbol") == SYMBOL)
            return {"positions": [dict(symbol=SYMBOL, quantity=qty, average_price=self.fill_price, ltp=self.bid)] if qty else []}
        if method == "GET" and path.startswith("/execution/orders/"):
            return copy.deepcopy(self.orders.get(path.rsplit("/", 1)[-1], {"error": True, "code": 404}))
        if method == "GET" and path.endswith("/account/funds"):
            return {"available_margin": 10000}
        if self.on_submit and method != "GET":
            self.on_submit(method, path, payload)
        if method == "POST" and path == "/execution/orders":
            if self.entry_error:
                return copy.deepcopy(self.entry_error)
            oid = "E" + str(len(self.orders))
            extra = {"request_id": payload["request_id"], "average_price": self.fill_price}
            if self.next_entry_filled is not None:
                extra["filled_quantity"] = self.next_entry_filled
            self.add("ENTRY", oid, payload["quantity"], self.next_entry_status, **extra)
            if self.lost_entry_response:
                return {"error": True, "detail": "timed out", "outcome_unknown": True}
            return {"order_id": oid}
        if method == "POST" and path == "/execution/stops":
            if self.stop_error:
                return copy.deepcopy(self.stop_error)
            oid = "S" + str(len(self.orders))
            self.add("STOP", oid, self.balance(payload["entry_order_id"]), "TRIGGER_PENDING",
                     payload["entry_order_id"], request_id=payload["request_id"],
                     trigger_price=payload["trigger_price"], limit_price=payload["limit_price"])
            if self.lost_stop_response:
                return {"error": True, "detail": "timed out", "outcome_unknown": True}
            return {"order_id": oid}
        if method == "PATCH":
            oid = path.rsplit("/", 1)[-1]
            if oid in self.patch_failures:
                return {"error": True, "detail": "rejected", "outcome_unknown": False}
            self.orders[oid].update(payload)
            return {"order_id": oid}
        if method == "DELETE":
            oid = path.rsplit("/", 1)[-1]
            record = self.orders[oid]
            if record["kind"] == "ENTRY" or self.cancel_behavior == "cancel":
                record["status"] = "CANCELLED"
            elif self.cancel_behavior == "fill":
                record.update(status="FILLED", filled_quantity=record["quantity"])
            elif self.cancel_behavior == "partial":
                record.update(status="CANCELLED", filled_quantity=65)
            return {"order_id": oid}
        if method == "POST" and path == "/execution/exit":
            if self.exit_error:
                return copy.deepcopy(self.exit_error)
            ref = payload["entry_order_id"]
            qty = self.balance(ref)
            assert qty > 0, "Attempted SELL without residual long exposure"
            oid = "X" + str(len(self.orders))
            self.add("EXIT", oid, qty, self.exit_status, ref, request_id=payload["request_id"])
            return {"order_id": oid, "status": self.exit_status}
        raise AssertionError((method, path, payload))

    def wait_for_stop_cancellation(self, oid, **kwargs):
        order = self.get_order(oid)
        return order if status(order) in ("CANCELLED", "FILLED", "REJECTED") else {"error": True, "detail": "STOP_CANCEL_TIMEOUT"}

    def wait_for_fill(self, oid, **kwargs):
        order = self.get_order(oid)
        if status(order) == "FILLED":
            return order
        return {"error": True, "detail": "FILL_POLL_TIMEOUT", "outcome_unknown": True}


class Trader(PositionLifecycle):
    def __init__(self, path, broker):
        self.initialize_safety(path)
        self.client = broker
        self.quantity = 65
        self.strategy_cfg = {"exit": {"initial_stop_pct": 30}}
        self.trading_cfg = {"option_selection": {"max_option_premium": 200}}

    def calculate_compounding_quantity(self, margin, price):
        return 65


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".oms-test-", dir=ROOT)
        self.path = Path(self.directory.name) / "active_position.json"
        self.assertTrue(self.path.resolve().is_relative_to(ROOT))
        self.addCleanup(self.directory.cleanup)
        self.broker = Broker()
        self.trader = Trader(self.path, self.broker)
        self.clock = patch.object(MarketClock, "now_ist", return_value=MarketClock.parse_to_ist("2026-10-19T10:00:00+05:30"))
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def existing(self, quantity=65, stops=True):
        self.broker.add("ENTRY", "E1", quantity)
        if stops:
            self.broker.add("STOP", "S1", quantity, "TRIGGER_PENDING", "E1", trigger_price=70, limit_price=68.6)
        return self.trader.get_trades_state()[0]

    def posts(self, path):
        return [c for c in self.broker.calls if c[0] == "POST" and c[1] == path]

    def decision(self):
        return approved_decision(self.trader.trading_cfg)

    def test_failed_positions_read_preserves_state_and_blocks_entry(self):
        self.existing()
        before = self.path.read_bytes()
        self.broker.position_error = {"error": True, "code": 500}
        self.trader.get_trades_state()
        self.assertFalse(self.trader.state_verified)
        self.assertEqual(before, self.path.read_bytes())
        self.assertTrue(self.trader.execute_trade({"instrument_id": "TEST", "ltp": 100})["error"])
        self.assertFalse(self.posts("/execution/orders"))

    def test_failed_journal_read_does_not_erase_known_stop(self):
        self.existing()
        before = self.path.read_bytes()
        self.broker.journal_error = {"error": True, "detail": "timed out"}
        self.trader.get_trades_state()
        self.assertEqual(before, self.path.read_bytes())
        self.assertEqual(["S1"], self.trader.load_active_position()["stop_order_ids"])

    def test_restart_discovers_both_entries_and_stops_without_replacement(self):
        self.existing()
        self.broker.add("ENTRY", "E2")
        self.broker.add("STOP", "S2", 65, "TRIGGER_PENDING", "E2", trigger_price=75)
        self.path.unlink()
        state = self.trader.get_trades_state()[0][0]
        self.assertTrue(self.trader.state_verified)
        self.assertEqual({"E1", "E2"}, set(state["entry_order_ids"]))
        self.assertEqual({"S1", "S2"}, set(state["stop_order_ids"]))
        self.assertTrue(state["protection_confirmed"])
        self.assertFalse(self.posts("/execution/stops"))

    def test_legacy_state_migrates(self):
        self.broker.add("ENTRY", "E1")
        self.broker.add("STOP", "S1", 65, "TRIGGER_PENDING", "E1", trigger_price=70)
        atomic_save(self.path, {"symbol": SYMBOL, "entry_order_id": "E1", "stop_order_id": "S1", "quantity": 65})
        state = self.trader.get_trades_state()[0][0]
        self.assertEqual(2, state["schema_version"])
        self.assertEqual(["S1"], state["stop_order_ids"])

    def test_synthetic_reference_is_replaced_by_real_journal_entry(self):
        self.broker.add("ENTRY", "E1")
        self.broker.add("STOP", "S1", 65, "TRIGGER_PENDING", "E1", trigger_price=70)
        atomic_save(self.path, {"symbol": SYMBOL, "entry_order_id": "ACTIVE-POS-old", "quantity": 65})
        state = self.trader.get_trades_state()[0][0]
        self.assertEqual(["E1"], state["entry_order_ids"])

    def test_partial_ratchet_failure_retries_only_lagging_stop(self):
        self.existing()
        self.broker.add("ENTRY", "E2")
        self.broker.add("STOP", "S2", 65, "TRIGGER_PENDING", "E2", trigger_price=70)
        state = self.trader.get_trades_state()[0][0]
        self.broker.patch_failures = {"S2"}
        self.trader.ratchet_stops(state, 90)
        self.assertEqual(90, self.broker.orders["S1"]["trigger_price"])
        self.assertEqual(70, self.broker.orders["S2"]["trigger_price"])
        self.broker.patch_failures.clear()
        state = self.trader.get_trades_state()[0][0]
        self.trader.ratchet_stops(state, 90)
        patches = [c[1] for c in self.broker.calls if c[0] == "PATCH"]
        self.assertEqual(["/execution/stops/S1", "/execution/stops/S2", "/execution/stops/S2"], patches)

    def test_ratchet_does_not_lower_a_stronger_stop(self):
        state = self.existing()[0]
        self.broker.orders["S1"]["trigger_price"] = 110
        state = self.trader.get_trades_state()[0][0]
        self.trader.ratchet_stops(state, 90)
        self.assertFalse([c for c in self.broker.calls if c[0] == "PATCH"])

    def test_cancellation_timeout_blocks_sell_and_preserves_state(self):
        self.existing()
        self.broker.cancel_behavior = "timeout"
        result = self.trader.exit_trade("E1", "test")
        self.assertTrue(result["error"])
        self.assertTrue(self.path.exists())
        self.assertFalse(self.posts("/execution/exit"))

    def test_stop_fills_during_cancel_does_not_place_extra_sell(self):
        self.existing()
        self.broker.cancel_behavior = "fill"
        result = self.trader.exit_trade("E1", "test")
        self.assertEqual("CLOSED", result["status"])
        self.assertFalse(self.posts("/execution/exit"))
        self.assertFalse(self.path.exists())

    def test_partial_stop_fill_exits_only_remaining_quantity(self):
        self.existing(quantity=130)
        self.broker.cancel_behavior = "partial"
        self.broker.exit_status = "FILLED"
        result = self.trader.exit_trade("E1", "test")
        exits = [o for o in self.broker.orders.values() if o["kind"] == "EXIT"]
        self.assertEqual([65], [o["quantity"] for o in exits])
        self.assertEqual("CLOSED", result["status"])

    def test_open_exit_keeps_state_and_is_not_duplicated_after_restart(self):
        self.existing()
        result = self.trader.exit_trade("E1", "test")
        self.assertEqual("EXIT_PENDING", result["status"])
        self.assertTrue(self.path.exists())
        restarted = Trader(self.path, self.broker)
        restarted.exit_trade("E1", "retry")
        self.assertEqual(1, len(self.posts("/execution/exit")))

    def test_two_entries_are_exited_without_orphan_stops(self):
        self.existing()
        self.broker.add("ENTRY", "E2")
        self.broker.add("STOP", "S2", 65, "OPEN", "E2", trigger_price=70)
        self.broker.exit_status = "FILLED"
        self.trader.exit_trade("E1", "test")
        self.trader.exit_trade("E2", "test")
        self.assertEqual({"E1", "E2"}, {c[2]["entry_order_id"] for c in self.posts("/execution/exit")})
        self.assertEqual("CANCELLED", self.broker.orders["S1"]["status"])
        self.assertEqual("CANCELLED", self.broker.orders["S2"]["status"])
        self.assertFalse(self.path.exists())

    def test_unknown_exit_outcome_blocks_resubmission_and_rearming(self):
        self.existing()
        self.broker.exit_error = {"error": True, "detail": "timed out", "outcome_unknown": True}
        self.trader.exit_trade("E1", "test")
        restarted = Trader(self.path, self.broker)
        restarted.exit_trade("E1", "retry")
        self.assertEqual(1, len(self.posts("/execution/exit")))
        self.assertFalse(self.posts("/execution/stops"))

    def test_rejected_exit_rearms_previous_trailing_floor(self):
        self.existing()
        self.broker.orders["S1"]["trigger_price"] = 105
        self.broker.exit_error = {"error": True, "code": 422, "detail": "REJECTED", "outcome_unknown": False}
        self.trader.exit_trade("E1", "test")
        self.assertEqual(105, self.posts("/execution/stops")[-1][2]["trigger_price"])
        self.assertTrue(self.path.exists())

    def test_unknown_entry_survives_restart_without_second_buy(self):
        self.broker.entry_error = {"error": True, "detail": "timed out", "outcome_unknown": True}
        self.trader.execute_trade(self.decision())
        restarted = Trader(self.path, self.broker)
        restarted.execute_trade(self.decision())
        self.assertEqual(1, len(self.posts("/execution/orders")))
        self.assertTrue(self.path.exists())

    def test_lost_entry_response_is_recovered_by_request_id(self):
        self.broker.lost_entry_response = True
        self.trader.execute_trade(self.decision())
        restarted = Trader(self.path, self.broker)
        state = restarted.get_trades_state()[0][0]
        self.assertTrue(restarted.state_verified)
        self.assertTrue(state["protection_confirmed"])
        self.assertEqual(1, len(self.posts("/execution/orders")))

    def test_lost_stop_response_is_recovered_without_duplicate(self):
        self.broker.lost_stop_response = True
        result = self.trader.execute_trade(self.decision())
        self.assertTrue(result["error"])
        state = self.trader.get_trades_state()[0][0]
        self.assertTrue(state["protection_confirmed"])
        self.assertEqual(1, len(self.posts("/execution/stops")))

    def test_stop_timeout_is_not_reported_as_success(self):
        self.broker.stop_error = {"error": True, "detail": "timed out", "outcome_unknown": True}
        result = self.trader.execute_trade(self.decision())
        self.assertTrue(result["error"])
        self.assertFalse(self.trader.load_active_position()["protection_confirmed"])
        self.trader.get_trades_state()
        self.assertFalse(self.trader.state_verified)
        self.assertEqual(1, len(self.posts("/execution/stops")))

    def test_partial_entry_is_cancelled_and_only_filled_quantity_protected(self):
        self.broker.next_entry_status = "OPEN"
        self.broker.next_entry_filled = 65
        self.trader.calculate_compounding_quantity = lambda *args: 130
        self.trader.strategy_cfg["compounding"] = {"max_order_quantity": 130}
        self.broker.get_funds = lambda: {"available_margin": 20000}
        result = self.trader.execute_trade(self.decision())
        self.assertEqual("SUCCESS", result["status"])
        entry = next(o for o in self.broker.orders.values() if o["kind"] == "ENTRY")
        stop = next(o for o in self.broker.orders.values() if o["kind"] == "STOP")
        self.assertEqual("CANCELLED", entry["status"])
        self.assertEqual(65, stop["quantity"])

    def test_state_is_durable_before_buy_stop_and_exit_posts(self):
        def check(method, path, payload):
            if method == "POST":
                state = json.loads(self.path.read_text())
                self.assertIn(payload["request_id"], [o.get("request_id") for k in ("entries", "stops", "exits") for o in state[k]])
        self.broker.on_submit = check
        self.trader.execute_trade(self.decision())
        self.trader.exit_trade(self.trader.load_active_position()["trade_id"], "test")

    def test_corrupt_state_and_truncated_journal_block_entry(self):
        self.path.write_text("{bad", encoding="utf-8")
        self.trader.execute_trade({"instrument_id": "TEST", "ltp": 100})
        self.assertFalse(self.posts("/execution/orders"))
        self.path.unlink()
        self.broker.journal_error = {"orders": [], "has_more": True}
        self.trader.get_trades_state()
        self.assertFalse(self.trader.state_verified)

    def test_paper_stop_is_not_adopted_or_cancelled(self):
        self.existing()
        self.broker.add("STOP", "PAPER-S", 65, "TRIGGER_PENDING", "OTHER", mode="PAPER")
        self.trader.exit_trade("E1", "test")
        self.assertEqual("TRIGGER_PENDING", self.broker.orders["PAPER-S"]["status"])

    def test_atomic_save_failure_preserves_previous_state(self):
        atomic_save(self.path, {"old": True})
        with patch("execution_safety.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                atomic_save(self.path, {"new": True})
        self.assertEqual({"old": True}, json.loads(self.path.read_text()))
        self.assertFalse(list(self.path.parent.glob("*.tmp")))

    def test_entry_semaphore_rejects_overlapping_call(self):
        self.trader._entry_guard.acquire()
        try:
            self.assertEqual("ENTRY_IN_FLIGHT", self.trader.execute_trade({})["detail"])
        finally:
            self.trader._entry_guard.release()
        self.assertFalse(self.broker.calls)

    def test_modification_budget_replaces_stop_without_exiting_position(self):
        state = self.existing()[0]
        state["stops"][0]["modifications"] = 25
        self.trader.save_active_position(state)
        self.trader.ratchet_stops(state, 90)
        self.assertNotIn("risk_exit_required", state)
        self.assertEqual("CANCELLED", self.broker.orders["S1"]["status"])
        self.assertEqual(0, state["stops"][-1]["modifications"])
        self.assertEqual(90, state["stops"][-1]["trigger_price"])
        self.assertTrue(state["protection_confirmed"])
        self.assertFalse([c for c in self.broker.calls if c[0] == "PATCH"])

    def test_orphan_stop_on_flat_book_blocks_entry_and_is_cancelled(self):
        self.broker.add("STOP", "ORPHAN", 65, "TRIGGER_PENDING", "MISSING")
        self.broker.position_override = {"positions": []}
        state = self.trader.get_trades_state()[0][0]
        self.assertEqual("EXIT_PENDING", state["status"])
        self.assertTrue(self.trader.execute_trade({"instrument_id": "TEST", "ltp": 100})["error"])
        result = self.trader.exit_trade("unused", "Orphan stop cleanup")
        self.assertEqual("CLOSED", result["status"])
        self.assertEqual("CANCELLED", self.broker.orders["ORPHAN"]["status"])
        self.assertFalse(self.posts("/execution/exit"))

    def test_flat_book_with_open_exit_is_not_reported_closed(self):
        self.broker.add("EXIT", "ORPHAN-X", 65, "OPEN", "MISSING")
        result = self.trader.exit_trade("unused", "Unresolved SELL")
        self.assertEqual("EXIT_PENDING", result["status"])
        self.assertTrue(self.path.exists())
        self.assertFalse(self.posts("/execution/exit"))

    def test_overlapping_stops_request_safe_exit_instead_of_more_protection(self):
        self.existing()
        self.broker.add("STOP", "EXTRA", 65, "TRIGGER_PENDING", "E1", trigger_price=70)
        state = self.trader.get_trades_state()[0][0]
        self.assertFalse(state["protection_confirmed"])
        self.assertIn("quantities", state["risk_exit_required"])
        self.assertFalse(self.posts("/execution/stops"))

    def test_flat_snapshot_cannot_erase_a_recent_confirmed_fill(self):
        self.broker.add("ENTRY", "E1")
        self.broker.position_override = {"positions": []}
        atomic_save(self.path, {"symbol": SYMBOL, "entry_order_id": "E1", "quantity": 65})
        before = self.path.read_bytes()
        self.trader.get_trades_state()
        self.assertFalse(self.trader.state_verified)
        self.assertEqual(before, self.path.read_bytes())

    def test_margin_buffer_never_falls_back_to_unaffordable_lot(self):
        self.broker.get_funds = lambda: {"available_margin": 6500}
        result = self.trader.execute_trade(self.decision())
        self.assertEqual("INSUFFICIENT_MARGIN_BLOCKED", result["detail"])
        self.assertFalse(self.posts("/execution/orders"))

    def test_state_write_failure_prevents_buy(self):
        with patch("position_lifecycle.atomic_save", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                self.trader.execute_trade(self.decision())
        self.assertFalse(self.posts("/execution/orders"))

    def test_confirmed_exit_closes_state_only_after_broker_fill(self):
        self.existing()
        self.trader.exit_trade("E1", "test")
        self.assertTrue(self.path.exists())
        exit_order = next(o for o in self.broker.orders.values() if o["kind"] == "EXIT")
        exit_order.update(status="FILLED", filled_quantity=65)
        self.assertEqual([], self.trader.get_trades_state()[0])
        self.assertFalse(self.path.exists())

    def test_scope_change_preserves_state_and_blocks_execution(self):
        self.existing()
        self.broker.get_status = lambda: {"mode": "PAPER"}
        before = self.path.read_bytes()
        self.trader.get_trades_state()
        self.assertFalse(self.trader.state_verified)
        self.assertEqual(before, self.path.read_bytes())

    def test_unknown_account_mode_on_recovery_is_not_guessed(self):
        self.broker.add("ENTRY", "E1").pop("mode")
        self.broker.position_override = {"positions": [{"symbol": SYMBOL, "quantity": 65, "average_price": 100, "ltp": 120}]}
        self.trader.get_trades_state()
        self.assertFalse(self.trader.state_verified)
        self.assertFalse(self.posts("/execution/stops"))

    def test_post_ai_revalidation_blocks_a_position_that_appeared_during_consultation(self):
        self.existing()
        result = self.trader.execute_trade(self.decision())
        self.assertEqual("POSITION_OR_ORDER_UNRESOLVED", result["detail"])
        self.assertFalse(self.posts("/execution/orders"))

    def scheduler(self):
        from nifty_trader_scheduler import NiftyOptionsTrader
        scheduler = NiftyOptionsTrader.__new__(NiftyOptionsTrader)
        scheduler.initialize_safety(self.path)
        scheduler.client = self.broker
        scheduler.strategy_cfg = self.trader.strategy_cfg
        scheduler.strategy_mode = "institutional_pullback"
        scheduler.trading_cfg = self.trader.trading_cfg
        return scheduler

    def test_open_position_monitor_does_not_require_news_or_feed_readiness(self):
        self.existing()
        scheduler = self.scheduler()
        with patch.object(scheduler, "fetch_market_context", return_value={}) as context:
            result = scheduler.run_cycle()
        self.assertTrue(result["has_open_trades"])
        context.assert_called_once_with(monitor_only=True)

    def test_mandatory_squareoff_precedes_structural_market_reads(self):
        self.existing()
        scheduler = self.scheduler()
        self.broker.exit_status = "FILLED"
        with patch.object(MarketClock, "now_ist", return_value=MarketClock.parse_to_ist("2026-10-19T15:15:00+05:30")), patch.object(scheduler, "fetch_market_context") as context:
            result = scheduler.run_cycle()
        self.assertFalse(result["has_open_trades"])
        context.assert_not_called()
        self.assertEqual(1, len(self.posts("/execution/exit")))

    def test_option_price_exit_survives_structural_data_timeout(self):
        self.existing()
        scheduler = self.scheduler()
        self.broker.bid = 60
        self.broker.exit_status = "FILLED"
        with patch.object(scheduler, "fetch_market_context", side_effect=TimeoutError("data unavailable")):
            scheduler.run_cycle()
        self.assertEqual(1, len(self.posts("/execution/exit")))

    def test_entry_cutoff_is_rechecked_after_consultation(self):
        with patch.object(MarketClock, "now_ist", return_value=MarketClock.parse_to_ist("2026-10-19T14:16:00+05:30")):
            result = self.trader.execute_trade(self.decision())
        self.assertEqual("ENTRY_TIME_WINDOW_CLOSED", result["detail"])
        self.assertFalse(self.posts("/execution/orders"))

    def test_stale_ratchet_cannot_resurrect_exiting_state(self):
        stale = self.existing()[0]
        self.trader.exit_trade("E1", "test")
        self.trader.ratchet_stops(stale, 90)
        self.assertEqual("EXIT_PENDING", self.trader.load_active_position()["status"])
        self.assertFalse([c for c in self.broker.calls if c[0] == "PATCH"])

    def test_broker_stop_raised_after_snapshot_is_never_lowered(self):
        stale = self.existing()[0]
        self.broker.orders["S1"]["trigger_price"] = 110
        self.trader.ratchet_stops(stale, 90)
        self.assertEqual(110, self.broker.orders["S1"]["trigger_price"])
        self.assertFalse([c for c in self.broker.calls if c[0] == "PATCH"])

    def test_excess_existing_stop_prevents_arming_another_entry(self):
        self.broker.add("ENTRY", "E1")
        self.broker.add("ENTRY", "E2")
        self.broker.add("STOP", "S1", 130, "TRIGGER_PENDING", "E1")
        state = self.trader.get_trades_state()[0][0]
        self.assertIn("quantities", state["risk_exit_required"])
        self.assertFalse(self.posts("/execution/stops"))

    def test_missing_broker_fill_quantity_is_not_assumed_zero(self):
        self.broker.add("ENTRY", "E1").pop("filled_quantity")
        self.trader.get_trades_state()
        self.assertFalse(self.trader.state_verified)
        self.assertFalse(self.posts("/execution/stops"))

    def test_previous_round_trip_does_not_leak_its_profit_floor_into_new_trade(self):
        self.broker.add("ENTRY", "OLD")
        self.broker.add("STOP", "OLD-S", 65, "FILLED", "OLD", trigger_price=150)
        self.broker.add("ENTRY", "NEW")
        state = self.trader.get_trades_state()[0][0]
        self.assertTrue(self.trader.state_verified)
        self.assertEqual(["NEW"], state["entry_order_ids"])
        self.assertEqual(70, self.posts("/execution/stops")[0][2]["trigger_price"])

    def test_cancel_conflict_recovers_through_verified_retry_with_durable_intents(self):
        self.existing()
        original = self.broker._request
        rejected = []

        def request(method, path, payload=None, **kwargs):
            if method == "POST" and path == "/execution/exit" and not rejected:
                rejected.append(payload["request_id"])
                stored = self.trader.load_active_position()
                self.assertIn(payload["request_id"], [o.get("request_id") for o in stored["exits"]])
                self.broker.calls.append((method, path, copy.deepcopy(payload)))
                return {"error": True, "code": 409, "detail": "CANCEL_AND_VERIFY_STOP_BEFORE_EXIT", "outcome_unknown": False}
            return original(method, path, payload, **kwargs)

        self.broker.exit_status = "FILLED"
        with patch.object(self.broker, "_request", side_effect=request):
            result = self.trader.exit_trade("E1", "test")
        self.assertEqual("CLOSED", result["status"])
        attempts = self.posts("/execution/exit")
        self.assertEqual(2, len(attempts))
        self.assertNotEqual(attempts[0][2]["request_id"], attempts[1][2]["request_id"])

    def entry_cycle(self, veto=False, snapshots=None):
        from types import SimpleNamespace
        from ai_consultant import AIConsultant
        from ai_context_dossier import MarketDossier
        scheduler = self.scheduler()
        scheduler.quantity = 65
        scheduler.ai_consultant = AIConsultant(mode="playbook", trading_config=scheduler.trading_cfg)
        dossier = MarketDossier(
            date="2026-10-19", time_utc="04:30", time_ist="10:00", direction="CE", symbol=SYMBOL,
            strike=23000, option_entry_price=100, spot_price=23000, session_phase="MORNING_TREND",
            minutes_from_open=45, minutes_to_close=330, is_expiry_0dte=False, days_to_expiry=2,
            gamma_hazard_flag=False, session_vwap=22990, vwap_distance_pts=80 if veto else 10, vwap_slope_15m=.2,
            vwap_cross_count_60m=0, vwap_blender_warning=False, box_range_15m=40, box_range_30m=60,
            box_position_pct=50, compression_hazard=False, ceiling_floor_hazard=False,
            ema9_5m=23000, ema20_5m=22994, ema_spread_5m=6, ribbon_compression_hazard=False,
            pullback_distance_pts=0, rsi_1m=55, day_high=23050, day_low=22900,
            day_range_pts=150, distance_to_day_extreme=50, last_trade_direction=None,
            last_trade_pnl=None, minutes_since_last_exit=None, consecutive_losses_today=0,
            is_directional_shift=False, realized_pnl_today=0, trades_taken_today=0,
            capital_preservation_active=False, instrument_id="TEST")
        intel = {"global_cues": {"global_bias": "NEUTRAL"}, "news": {"news_bias": "NEUTRAL", "sentiment_score": 0}, "composite_bias": "NEUTRAL", "ready": True, "status": "FRESH"}
        reads = iter(snapshots) if snapshots is not None else None
        scheduler.intelligence = SimpleNamespace(get_market_intelligence=lambda **kw: next(reads) if reads is not None else intel)
        ctx = {"spot": 23000, "day_change": .1, "ema_9": 23000, "ema_20": 22994, "session_vwap": 22990,
               "box_low_15m": 22970, "box_high_15m": 23010, "box_spread_15m": 40, "is_consolidation_box": False,
               "order_flow": {}, "pcr_oi": 1.0}
        decision = {"signal": "BUY_CE", "symbol": SYMBOL, "instrument_id": "TEST", "ltp": 100, "reasons": []}
        with patch("nifty_trader_scheduler.LOG_DIR", self.path.parent), patch.object(scheduler, "check_feed_health", return_value={"healthy": True}), patch.object(scheduler, "fetch_market_context", return_value=ctx), patch.object(scheduler, "analyze", return_value=decision), patch.object(scheduler, "build_dossier", return_value=dossier):
            result = scheduler.run_cycle()
        return result, decision

    def test_real_ai_approval_with_stop_timeout_retains_fast_monitoring(self):
        self.broker.stop_error = {"error": True, "detail": "timed out", "outcome_unknown": True}
        result, decision = self.entry_cycle()
        self.assertEqual("APPROVED", decision["ai_verdict"]["action"])
        self.assertTrue(result["has_open_trades"])
        self.assertEqual(1, len(self.posts("/execution/orders")))
        self.assertTrue(self.path.exists())

    def test_real_ai_veto_prevents_buy(self):
        result, decision = self.entry_cycle(veto=True)
        self.assertEqual("VETOED", decision["ai_verdict"]["action"])
        self.assertFalse(self.posts("/execution/orders"))
        self.assertFalse(result["has_open_trades"])

    def test_unavailable_intelligence_blocks_new_entries(self):
        result, decision = self.entry_cycle(snapshots=[{"ready": False, "status": "INITIALIZING"}])
        self.assertEqual("INTELLIGENCE_UNAVAILABLE", result["blocked"])
        self.assertNotIn("ai_verdict", decision)
        self.assertFalse(self.posts("/execution/orders"))

    def test_intelligence_expiring_during_real_ai_consultation_blocks_entry(self):
        fresh = {"ready": True, "global_cues": {"global_bias": "NEUTRAL"}, "news": {"news_bias": "NEUTRAL", "sentiment_score": 0}, "composite_bias": "NEUTRAL"}
        result, decision = self.entry_cycle(snapshots=[fresh, {"ready": False, "status": "STALE"}])
        self.assertEqual("APPROVED", decision["ai_verdict"]["action"])
        self.assertEqual("INTELLIGENCE_UNAVAILABLE", result["blocked"])
        self.assertFalse(self.posts("/execution/orders"))

    def test_changed_news_requires_a_new_real_ai_decision(self):
        fresh = {"ready": True, "global_cues": {"global_bias": "NEUTRAL"}, "news": {"news_bias": "NEUTRAL", "sentiment_score": 0}, "composite_bias": "NEUTRAL"}
        changed = copy.deepcopy(fresh)
        changed["news"].update(news_bias="BEARISH", sentiment_score=-4)
        result, decision = self.entry_cycle(snapshots=[fresh, changed])
        self.assertEqual("APPROVED", decision["ai_verdict"]["action"])
        self.assertEqual("INTELLIGENCE_CHANGED_DURING_CONSULTATION", result["blocked"])
        self.assertFalse(self.posts("/execution/orders"))


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.client = AIExecutionClient(base_url="http://invalid.test", api_key="test")

    def test_get_timeout_retries_once(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'{"positions": []}'
        with patch("execution_client.urllib.request.urlopen", side_effect=[TimeoutError(), response]) as call, patch("execution_client.time.sleep") as sleep:
            self.assertEqual({"positions": []}, self.client.get_positions())
            self.assertEqual(2, call.call_count)
            self.assertEqual(10, call.call_args.kwargs["timeout"])
            sleep.assert_called_once_with(.5)

    def test_post_timeout_never_retries(self):
        with patch("execution_client.urllib.request.urlopen", side_effect=TimeoutError()) as call:
            result = self.client.place_buy_order("TEST", 65, 100, request_id="persisted")
            self.assertTrue(result["outcome_unknown"])
            self.assertEqual(1, call.call_count)

    def test_wrapped_timeout_retries_but_http_rejection_does_not(self):
        with patch("execution_client.urllib.request.urlopen", side_effect=urllib.error.URLError(TimeoutError())) as call, patch("execution_client.time.sleep"):
            self.assertTrue(self.client.get_positions()["error"])
            self.assertEqual(2, call.call_count)
        error = urllib.error.HTTPError("http://invalid.test", 422, "rejected", {}, io.BytesIO(b'{"detail":"REJECTED"}'))
        with patch("execution_client.urllib.request.urlopen", side_effect=error) as call:
            result = self.client.place_buy_order("TEST", 65, 100)
            self.assertFalse(result["outcome_unknown"])
            self.assertEqual(1, call.call_count)

    def test_stop_conflict_is_not_quote_band_retry(self):
        with patch.object(self.client, "_request", return_value={"error": True, "code": 409, "detail": "CANCEL_AND_VERIFY_STOP_BEFORE_EXIT"}) as call:
            self.client.exit_position("E1", 100)
            self.assertEqual(1, call.call_count)

    def test_quote_band_retry_uses_exact_quote_and_persist_hook(self):
        persisted = []
        with patch.object(self.client, "_request", side_effect=[{"error": True, "code": 409, "detail": "EXIT_LIMIT_OUTSIDE_QUOTE_BAND"}, {"order_id": "X1"}]) as call:
            result = self.client.exit_position("E1", 100, before_submit=lambda p: persisted.append(dict(p)), fresh_price=lambda: 99.5)
            self.assertEqual("X1", result["order_id"])
            self.assertEqual(99.5, call.call_args.args[2]["limit_price"])
            self.assertNotEqual(persisted[0]["request_id"], persisted[1]["request_id"])

    def test_cancel_conflict_retry_requires_verified_cancellation(self):
        with patch.object(self.client, "_request", return_value={"error": True, "code": 409, "detail": "CANCEL_AND_VERIFY_STOP_BEFORE_EXIT"}) as call:
            result = self.client.exit_position("E1", 100, cancel_and_verify=lambda: {"error": True, "detail": "UNVERIFIED"})
            self.assertEqual("UNVERIFIED", result["detail"])
            self.assertEqual(1, call.call_count)

    def test_expired_read_budget_never_starts_another_network_request(self):
        with patch("execution_client.time.monotonic", side_effect=[100, 121]), patch("execution_client.urllib.request.urlopen") as call:
            with self.client.read_budget(20):
                result = self.client.get_positions()
        self.assertEqual("READ_BUDGET_EXHAUSTED", result["detail"])
        call.assert_not_called()


class LockTests(unittest.TestCase):
    def test_second_process_is_excluded_and_stale_file_is_reusable(self):
        with tempfile.TemporaryDirectory(prefix=".oms-lock-test-", dir=ROOT) as directory:
            self.assertTrue(Path(directory).resolve().is_relative_to(ROOT))
            lock_path = Path(directory) / "scheduler.lock"
            code = "from execution_safety import SchedulerLock; import sys; lock=SchedulerLock(sys.argv[1]); lock.__enter__(); lock.__exit__()"
            with SchedulerLock(lock_path):
                child = subprocess.run([sys.executable, "-c", code, str(lock_path)], cwd=ROOT, capture_output=True, text=True)
                self.assertNotEqual(0, child.returncode)
            child = subprocess.run([sys.executable, "-c", code, str(lock_path)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(0, child.returncode, child.stderr)


if __name__ == "__main__":
    unittest.main()
