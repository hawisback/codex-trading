"""Compatibility checks for dependency boundaries and pre-refactor OMS traces."""

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

from ai_consultant import AIConsultant
from execution_client import AIExecutionClient
from execution_safety import atomic_save
from market_clock import MarketClock
from nifty_trader_scheduler import NiftyOptionsTrader
from test_self_healing_exit import Broker, ROOT, Trader, approved_decision
from tools.checks import forbid_network, static_checks
from trading.adapters.position_store import JsonPositionStore


class ReferenceTraceTests(unittest.TestCase):
    def test_entry_trace_preserves_orders_with_explicit_monitor_quote_extension(self):
        expected = json.loads((ROOT / "tests/fixtures/oms_reference.json").read_text(encoding="utf-8"))
        for scenario in expected:
            with (
                self.subTest(scenario=scenario),
                tempfile.TemporaryDirectory(prefix=".trace-test-", dir=ROOT) as directory,
            ):
                broker = Broker()
                broker.quote_ask = broker.fill_price = 68.2
                trader = Trader(Path(directory) / "active_position.json", broker)
                trader.trading_cfg = {"option_selection": {"max_option_premium": 70}}
                if scenario == "partial_cancelled":
                    broker.next_entry_status, broker.next_entry_filled = "OPEN", 65
                    trader.calculate_compounding_quantity = lambda *args: 130
                    trader.strategy_cfg["compounding"] = {"max_order_quantity": 130}
                if scenario == "unknown_submit":
                    broker.entry_error = {"error": True, "detail": "timed out", "outcome_unknown": True}
                count = [0]

                def request_id(kind):
                    count[0] += 1
                    return f"AI-{kind}-REFERENCE-{count[0]}"

                now = MarketClock.parse_to_ist("2026-10-19T10:00:00+05:30")
                with (
                    patch.object(MarketClock, "now_ist", return_value=now),
                    patch("time.monotonic", return_value=100),
                    patch("position_lifecycle.intent_id", side_effect=request_id),
                ):
                    result = trader.execute_trade(approved_decision(trader.trading_cfg, 67))
                    actual = {"result": result, "calls": broker.calls, "state": trader.load_active_position()}
                # The existing verdict.timestamp uses host wall time, independently
                # of MarketClock. Normalize only that display field; every trading
                # timestamp, expiry, request, fill, and state field stays compared.
                actual = json.loads(json.dumps(actual))
                reference = copy.deepcopy(expected[scenario])
                for trace in (actual, reference):
                    trace["state"]["entry_execution"]["ai_verdict"]["timestamp"] = "<host-wall-clock>"
                # Daily ordinal is now durable before submission; older fixtures
                # predate the first-trade-only morning trailing rule.
                self.assertEqual(1, actual["state"].pop("today_entry_number"))
                if scenario != "unknown_submit":
                    self.assertTrue(actual["state"].pop("quote_verified"))
                    self.assertEqual(now.isoformat(), actual["state"].pop("bid_timestamp"))
                    self.assertEqual(47.75, actual["state"].pop("current_stop_trigger"))
                    # The new quote protects stop placement after the BUY. Entry's
                    # original JIT quote, mutation payloads and AI evidence stay exact.
                    mutation_seen = False
                    calls = []
                    for call in actual["calls"]:
                        if call[:2] == ["POST", "/execution/orders"]:
                            mutation_seen = True
                        if mutation_seen and call[:2] == ["GET", "/market/quote/TEST"]:
                            continue
                        calls.append(call)
                    actual["calls"] = calls
                self.assertEqual(reference, actual)


class AdapterCompositionTests(unittest.TestCase):
    def test_injected_transport_receives_the_unchanged_gateway_contract(self):
        class RecordingTransport:
            def __init__(self):
                self.calls = []

            def __bool__(self):
                return False  # Dependency selection must not depend on truthiness.

            def request(self, method, url, payload=None, **kwargs):
                self.calls.append((method, url, copy.deepcopy(payload), kwargs))
                return {"order_id": "E1"}

        transport = RecordingTransport()
        client = AIExecutionClient("http://invalid.test/api/v1/ai", "test", transport=transport)
        self.assertEqual(
            {"order_id": "E1"}, client.place_buy_order("TEST", 65, 67.05, request_id="persisted")
        )
        method, url, payload, options = transport.calls[0]
        self.assertEqual("POST", method)
        self.assertEqual("http://invalid.test/api/v1/ai/execution/orders", url)
        self.assertEqual(
            dict(instrument_id="TEST", quantity=65, limit_price=67.05, request_id="persisted"), payload
        )
        self.assertEqual("test", options["headers"]["X-AI-Execution-Key"])
        self.assertEqual(10, options["timeout"])
        self.assertTrue(options["retry_reads"])

    def test_injected_position_repository_is_used_by_the_real_lifecycle(self):
        with tempfile.TemporaryDirectory(prefix=".store-test-", dir=ROOT) as directory:
            path = Path(directory) / "active_position.json"
            writes = []

            def record_write(target, data):
                writes.append(copy.deepcopy(data))
                atomic_save(target, data)

            store = JsonPositionStore(path, writer=record_write)
            trader = Trader(path, Broker())
            trader.initialize_safety(path, store=store)
            trader.save_active_position({"symbol": "TEST", "entries": [], "stops": []})
            self.assertEqual("TEST", trader.load_active_position()["symbol"])
            self.assertEqual(2, writes[0]["schema_version"])
            self.assertTrue(store.exists())
            store.delete()
            self.assertEqual({}, trader.load_active_position())

    def test_repository_failure_prevents_a_buy_with_actual_ai_approval(self):
        with tempfile.TemporaryDirectory(prefix=".store-failure-", dir=ROOT) as directory:
            path = Path(directory) / "active_position.json"
            broker = Broker()
            trader = Trader(path, broker)

            def unavailable(*args):
                raise OSError("disk unavailable")

            trader.initialize_safety(path, store=JsonPositionStore(path, writer=unavailable))
            now = MarketClock.parse_to_ist("2026-10-19T10:00:00+05:30")
            with patch.object(MarketClock, "now_ist", return_value=now):
                decision = approved_decision(trader.trading_cfg)
                with self.assertRaises(OSError):
                    trader.execute_trade(decision)
            self.assertFalse(any(c[:2] == ("POST", "/execution/orders") for c in broker.calls))

    def test_trader_accepts_external_dependencies_and_keeps_actual_ai(self):
        with tempfile.TemporaryDirectory(prefix=".composition-test-", dir=ROOT) as directory:
            store = JsonPositionStore(Path(directory) / "active_position.json")
            broker = Broker()

            class Intelligence:
                def get_market_intelligence(self, spot_change_pct=0):
                    return {"ready": False}

                def stop_worker(self, timeout=1):
                    return True

            intelligence = Intelligence()
            with patch("nifty_trader_scheduler.MarketIntelligence") as background:
                trader = NiftyOptionsTrader(
                    strategy="institutional_pullback",
                    ai_mode="playbook",
                    client=broker,
                    intelligence=intelligence,
                    state_store=store,
                )
            background.assert_not_called()
            self.assertIs(broker, trader.client)
            self.assertIs(store, trader.position_store)
            self.assertIs(intelligence, trader.intelligence)
            self.assertIsInstance(trader.ai_consultant, AIConsultant)
            self.assertEqual([], broker.calls)

    def test_monitor_exposure_flag_uses_the_repository_contract(self):
        with tempfile.TemporaryDirectory(prefix=".monitor-store-test-", dir=ROOT) as directory:
            store = JsonPositionStore(Path(directory) / "active_position.json")
            trader = NiftyOptionsTrader.__new__(NiftyOptionsTrader)
            trader.initialize_safety(store.path, store=store)
            trader.state_verified = True
            with (
                patch.object(store, "exists", return_value=True),
                patch.object(trader, "exit_trade", return_value={"status": "EXIT_PENDING"}),
            ):
                result = trader.run_monitor_cycle([{"status": "EXIT_PENDING", "trade_id": "E1"}])
            self.assertTrue(result["has_open_trades"])


class OfflineBoundaryTests(unittest.TestCase):
    def test_network_guard_records_attempts_even_when_an_exception_is_caught(self):
        with forbid_network() as attempts:
            try:
                urllib.request.urlopen("http://invalid.test")
            except RuntimeError:
                pass
        self.assertEqual(1, len(attempts))

    def test_static_dependency_guard_rejects_transport_inside_policy(self):
        with tempfile.TemporaryDirectory(prefix=".boundary-test-", dir=ROOT) as directory:
            root = Path(directory)
            (root / "entry_policy.py").write_text("import urllib.request\n", encoding="utf-8")
            errors = static_checks(root)
        self.assertEqual(1, len(errors))
        self.assertIn("forbidden dependency urllib.request", errors[0])

    def test_new_boundary_modules_have_no_import_time_application_side_effects(self):
        script = """
import logging, os, threading
from pathlib import Path
from unittest.mock import patch
before = dict(os.environ)
handlers = list(logging.getLogger().handlers)
with patch('urllib.request.urlopen', side_effect=AssertionError('network')), \\
     patch('pathlib.Path.mkdir', side_effect=AssertionError('mkdir')), \\
     patch('threading.Thread.start', side_effect=AssertionError('worker')):
    import trading.ports
    import trading.adapters.http
    import trading.adapters.position_store
assert dict(os.environ) == before
assert logging.getLogger().handlers == handlers
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
