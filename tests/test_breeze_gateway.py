"""Offline Breeze contract/OMS tests; the actual AI consultant is retained."""

import copy
from datetime import timedelta
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest.mock import patch

from ai_consultant import AIConsultant
from market_clock import MarketClock
from test_self_healing_exit import ROOT, Trader, approved_decision, entry_dossier
from trading.adapters.gateways import BreezeExecutionGateway, create_execution_gateway
from trading.adapters.gateways.breeze import broker_time, option_contract
from trading.application.scheduler import run_scheduler

INSTRUMENT = "INST-NIFTY-2026-10-27-23000-CE"
SYMBOL = "NIFTY26O2723000CE"
NOW = "2026-10-22T10:00:00+05:30"


class Response:
    def __init__(self, data, status=200, error=None):
        self.data = {"Success": data, "Status": status, "Error": error}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return json.dumps(self.data).encode()


class Server:
    def __init__(self):
        self.orders = {}
        self.calls = []
        self.account = "BREEZE_TEST"
        self.fail = None
        self.lose_next = None
        self.partial_cancel = False
        self.quote_change = {}
        self.funds = {"allocated_fno": 20000, "block_by_trade_fno": 0, "total_bank_balance": 999999}

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]

    def __call__(self, request, timeout):
        method = request.get_method()
        path = request.full_url.split("/v1", 1)[1]
        data = json.loads(request.data)
        headers = {k.lower(): v for k, v in request.header_items()}
        self.calls.append((method, path, data, headers, timeout))
        if self.fail:
            raise self.fail
        if path == "/customerdetails":
            return Response({"idirect_userid": self.account, "session_token": "signed-session"})
        if path == "/funds":
            return Response(self.funds)
        if path == "/quotes":
            raw = {
                **data,
                "expiry_date": "27-Oct-2026",
                "ltp": 67,
                "best_bid_price": 66.95,
                "best_offer_price": 67,
                "best_bid_quantity": "650",
                "best_offer_quantity": "650",
                "ltt": MarketClock.now_ist().strftime("%d-%b-%Y %H:%M:%S"),
            }
            if data["exchange_code"] == "NSE":
                raw["ltp"] = 23000
            raw.update(self.quote_change)
            return Response([raw])
        if path == "/historicalcharts":
            return Response(
                [
                    {
                        "datetime": "2026-10-22 09:15:00",
                        "open": 67,
                        "high": 68,
                        "low": 66,
                        "close": 67,
                        "volume": 130,
                    }
                ]
            )
        if path == "/optionchain":
            return Response([])
        if path == "/portfoliopositions":
            balance = sum(
                (1 if o["action"] == "Buy" else -1)
                * (int(o["quantity"]) - int(o["pending_quantity"]) - int(o["cancelled_quantity"]))
                for o in self.orders.values()
            )
            if not balance:
                return Response([])
            return Response(
                [
                    {
                        "stock_code": "NIFTY",
                        "exchange_code": "NFO",
                        "product_type": "Options",
                        "expiry_date": "27-Oct-2026",
                        "strike_price": "23000",
                        "right": "Call",
                        "action": "Buy" if balance > 0 else "Sell",
                        "quantity": str(abs(balance)),
                        "average_price": "67",
                        "ltp": "67",
                    }
                ]
            )
        if path == "/order" and method == "GET":
            return Response(list(self.orders.values()))
        if path == "/order" and method == "POST":
            oid = "B" + str(len(self.orders) + 1)
            stop = data["order_type"] == "stoploss"
            self.orders[oid] = {
                **data,
                "order_id": oid,
                "product_type": "Options",
                "expiry_date": "27-Oct-2026",
                "right": data["right"].title(),
                "action": data["action"].title(),
                "average_price": data["price"] if not stop else "0",
                "pending_quantity": data["quantity"] if stop else "0",
                "cancelled_quantity": "0",
                "status": "Ordered" if stop else "Executed",
                "order_datetime": MarketClock.now_ist().strftime("%d-%b-%Y %H:%M:%S"),
            }
            kind = "STOP" if stop else data["action"].upper()
            if self.lose_next == kind:
                self.lose_next = None
                raise TimeoutError("lost acknowledgement")
            return Response({"order_id": oid})
        if path == "/order" and method == "DELETE":
            order = self.orders[data["order_id"]]
            if self.partial_cancel and order["order_type"] == "stoploss":
                order["pending_quantity"] = str(int(order["pending_quantity"]) - 65)
                order["average_price"] = "60"
                self.partial_cancel = False
            order["cancelled_quantity"] = order["pending_quantity"]
            order["pending_quantity"] = "0"
            order["status"] = "Cancelled"
            return Response({"order_id": data["order_id"]})
        if path == "/order" and method == "PUT":
            self.orders[data["order_id"]].update(data)
            return Response({"order_id": data["order_id"]})
        raise AssertionError((method, path, data))


class BreezeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".breeze-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.now = MarketClock.parse_to_ist(NOW)
        clock = patch.object(MarketClock, "now_ist", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.server = Server()
        network = patch("urllib.request.urlopen", side_effect=self.server)
        network.start()
        self.addCleanup(network.stop)
        self.gateway = self.gateway_new()

    def gateway_new(self, arm=True):
        gateway = create_execution_gateway(
            "breeze",
            api_key="test-key",
            api_secret="test-secret",
            api_session="login-session",
            account_id="BREEZE_TEST",
            journal_path=self.root / "broker_intents.json",
        )
        gateway.rate_limiter.acquire = lambda **kwargs: True
        if arm:
            self.assertTrue(gateway.set_mode("LIVE").get("live_authorized"))
        return gateway

    def trader(self, gateway=None, qty=65):
        trader = Trader(self.root / "active_position.json", gateway or self.gateway)
        trader.trading_cfg = {"option_selection": {"max_option_premium": 70}}
        trader.strategy_cfg["compounding"] = {"max_order_quantity": qty}
        trader.calculate_compounding_quantity = lambda *args: qty
        return trader

    def decision(self, trader):
        return approved_decision(trader.trading_cfg, 67, symbol=SYMBOL, instrument_id=INSTRUMENT)

    def test_signed_get_hashes_exact_json_body_and_does_not_leak_login_session(self):
        self.gateway.get_funds()
        method, path, body, headers, timeout = self.server.calls[-1]
        payload = json.dumps(body, separators=(",", ":"))
        checksum = hashlib.sha256((headers["x-timestamp"] + payload + "test-secret").encode()).hexdigest()
        self.assertEqual(("GET", "/funds", {}), (method, path, body))
        self.assertEqual("token " + checksum, headers["x-checksum"])
        self.assertEqual("signed-session", headers["x-sessiontoken"])
        self.assertGreater(timeout, 0)
        self.assertNotIn("login-session", json.dumps(self.gateway.get_status()))
        self.assertNotIn("test-secret", (self.root / "breeze_api_usage.json").read_text())

    def test_missing_credentials_and_wrong_account_never_arm(self):
        gateway = BreezeExecutionGateway(
            api_key="key",
            api_secret="secret",
            api_session="session",
            account_id="OTHER",
            journal_path=self.root / "other.json",
        )
        gateway.rate_limiter.acquire = lambda **kwargs: True
        self.assertTrue(gateway.set_mode("LIVE")["error"])
        self.assertFalse(gateway.is_connected())
        self.assertFalse(gateway._live_authorized)
        self.assertFalse(self.server.posts())

    def test_paper_and_changed_credentials_block_mutations(self):
        self.gateway.register_contract(INSTRUMENT, SYMBOL)
        self.gateway.set_mode("PAPER")
        self.assertTrue(self.gateway.place_buy_order(INSTRUMENT, 65, 67)["error"])
        self.assertTrue(self.gateway.set_mode("LIVE")["live_authorized"])
        self.gateway.api_session = "different"
        self.assertTrue(self.gateway.place_buy_order(INSTRUMENT, 65, 67)["error"])
        self.assertFalse(self.server.posts())

    def test_verified_zero_fno_cash_does_not_use_bank_balance(self):
        self.server.funds.update(allocated_fno=500, block_by_trade_fno=500)
        self.assertEqual(0, self.gateway.get_funds()["available_margin"])
        self.assertEqual(
            "INSUFFICIENT_MARGIN_BLOCKED", self.trader().execute_trade(self.decision(self.trader()))["detail"]
        )
        self.assertFalse(self.server.posts())

    def test_actual_ai_entry_stop_restart_and_exit(self):
        trader = self.trader()
        result = trader.execute_trade(self.decision(trader))
        self.assertEqual("SUCCESS", result["status"], result)
        entry, stop = self.server.posts()
        self.assertEqual(
            ("NIFTY", "options", "call", "23000", "2026-10-27T06:00:00.000Z"),
            tuple(entry[2][key] for key in ("stock_code", "product", "right", "strike_price", "expiry_date")),
        )
        self.assertEqual("stoploss", stop[2]["order_type"])
        state = trader.load_active_position()
        self.assertEqual(INSTRUMENT, state["entry_execution"]["ai_verdict"]["entry_instrument_id"])
        other = self.trader(self.gateway_new())
        trades, _ = other.get_trades_state()
        self.assertTrue(other.state_verified, other.last_reconciliation_error)
        self.assertEqual(INSTRUMENT, trades[0]["instrument_id"])
        self.assertEqual("CLOSED", other.exit_trade(result["order_id"], "test")["status"])
        self.assertEqual("sell", self.server.posts()[-1][2]["action"])
        self.assertFalse(other.position_store.exists())

    def test_actual_ai_veto_and_timeout_do_not_submit(self):
        trader = self.trader()
        for timeout in (False, True):
            dossier = entry_dossier(67, instrument_id=INSTRUMENT, vwap_distance_pts=80 if not timeout else 10)
            ai = AIConsultant(
                mode="playbook", timeout_seconds=0 if timeout else 45, trading_config=trader.trading_cfg
            )
            decision = {
                "symbol": SYMBOL,
                "instrument_id": INSTRUMENT,
                "ltp": 67,
                "ai_verdict": ai.evaluate(dossier).to_dict(),
            }
            self.assertEqual("AI_APPROVAL_REQUIRED", trader.execute_trade(decision)["detail"])
        self.assertFalse(self.server.posts())

    def test_partial_stop_fill_during_cancel_uses_remaining_quantity(self):
        trader = self.trader(qty=130)
        result = trader.execute_trade(self.decision(trader))
        self.assertEqual("SUCCESS", result["status"], result)
        self.server.partial_cancel = True
        outcome = trader.exit_trade(result["order_id"], "partial fill")
        self.assertEqual("CLOSED", outcome["status"], outcome)
        self.assertEqual("65", self.server.posts()[-1][2]["quantity"])

    def test_lost_acknowledgement_recovers_by_tag_without_resubmission(self):
        trader = self.trader()
        self.server.lose_next = "BUY"
        result = trader.execute_trade(self.decision(trader))
        self.assertTrue(result.get("outcome_unknown"), result)
        self.assertEqual(1, len(self.server.posts()))
        other = self.trader(self.gateway_new())
        trades, _ = other.get_trades_state()
        self.assertTrue(other.state_verified, other.last_reconciliation_error)
        self.assertTrue(trades[0]["protection_confirmed"])
        self.assertEqual(2, len(self.server.posts()))

    def test_quote_identity_timestamp_and_depth_are_preserved(self):
        self.gateway.register_contract(INSTRUMENT, SYMBOL)
        quote = self.gateway.get_contract_quote(INSTRUMENT)
        self.assertEqual("650", quote["best_bid_qty"])
        self.assertEqual(NOW, quote["timestamp"])
        self.server.quote_change["strike_price"] = 23100
        self.assertTrue(self.gateway.get_contract_quote(INSTRUMENT)["error"])
        self.server.quote_change = {"ltt": ""}
        self.assertTrue(self.gateway.get_contract_quote(INSTRUMENT)["error"])

    def test_unverified_contracts_and_conflicting_aliases_are_rejected(self):
        before = len(self.server.calls)
        self.assertTrue(self.gateway.place_buy_order(INSTRUMENT, 65, 67)["error"])
        self.gateway.register_contract(INSTRUMENT, SYMBOL)
        with self.assertRaises(ValueError):
            self.gateway.register_contract(INSTRUMENT, "DIFFERENT")
        with self.assertRaises(ValueError):
            self.gateway.register_contract(INSTRUMENT.replace("23000", "23100"), SYMBOL)
        with self.assertRaises(ValueError):
            option_contract("NIFTY26O2723000CE")
        self.assertEqual(before, len(self.server.calls))

    def test_auth_error_revokes_and_mutations_never_retry(self):
        self.gateway.register_contract(INSTRUMENT, SYMBOL)
        self.server.fail = urllib.error.HTTPError(
            "https://broker.test", 403, "denied", {}, io.BytesIO(b"secret")
        )
        result = self.gateway.place_buy_order(INSTRUMENT, 65, 67, request_id="auth-error")
        self.assertTrue(result["error"])
        self.assertFalse(self.gateway._live_authorized)
        self.assertEqual(1, len(self.server.posts()))
        self.assertNotIn("secret", json.dumps(result))

    def test_stale_quote_after_pacing_cannot_submit(self):
        trader = self.trader()
        decision = self.decision(trader)

        def wait(**kwargs):
            if self.server.calls[-1][1] == "/quotes":
                self.now += timedelta(seconds=2)
            return True

        self.gateway.rate_limiter.acquire = wait
        result = trader.execute_trade(decision)
        self.assertEqual("ENTRY_QUOTE_STALE", result["detail"])
        self.assertFalse(self.server.posts())

    def test_daily_usage_survives_restart_and_exhaustion_blocks_http(self):
        path = self.root / "breeze_api_usage.json"
        data = json.loads(path.read_text())
        key = hashlib.sha256(b"test-key").hexdigest()
        data[key]["count"] = 5000
        path.write_text(json.dumps(data))
        before = len(self.server.calls)
        self.assertTrue(self.gateway.get_funds()["error"])
        self.assertTrue(self.gateway_new(arm=False).get_status()["error"])
        self.assertEqual(before, len(self.server.calls))

    def test_read_only_history_and_chain_use_explicit_contracts(self):
        history = self.gateway.get_historical_candles(
            INSTRUMENT, "2026-10-22T03:45:00.000Z", "2026-10-22T04:30:00.000Z", interval="1m"
        )
        self.assertEqual("breeze", history["source"])
        self.assertEqual("1minute", self.server.calls[-1][2]["interval"])
        self.assertEqual([], self.gateway.get_option_chain("2026-10-27", right="call")["contracts"])
        self.assertTrue(self.gateway.get_option_chain("2026-10-27", right="others")["error"])
        self.assertFalse(self.server.posts())

    def test_ambiguous_fills_or_foreign_contracts_fail_reconciliation(self):
        self.trader().execute_trade(self.decision(self.trader()))
        saved = copy.deepcopy(self.server.orders)
        for changes in (
            {"status": "unknown"},
            {"pending_quantity": "9999"},
            {"status": "Expired"},
            {"strike_price": "23100"},
        ):
            with self.subTest(changes=changes):
                self.server.orders = copy.deepcopy(saved)
                self.server.orders["B1"].update(changes)
                self.assertTrue(self.gateway.get_orders()["error"])

    def test_broker_time_does_not_treat_premarket_ist_as_utc(self):
        self.assertEqual("2026-10-22T07:15:00+05:30", broker_time("22-Oct-2026 07:15:00").isoformat())

    def test_native_breeze_cli_requires_live_before_construction(self):
        with patch("sys.argv", ["scheduler", "--broker", "breeze"]), patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit):
                run_scheduler(lambda **kwargs: self.fail("Trader must not be constructed"))

    def test_factory_rejects_conflicting_session_aliases(self):
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            create_execution_gateway("breeze", api_session="one", access_token="two")

    def test_lost_stop_ack_recovers_without_a_duplicate_protective_sell(self):
        trader = self.trader()
        self.server.lose_next = "STOP"
        trader.execute_trade(self.decision(trader))
        other = self.trader(self.gateway_new())
        trades, _ = other.get_trades_state()
        self.assertTrue(other.state_verified, other.last_reconciliation_error)
        self.assertTrue(trades[0]["protection_confirmed"])
        self.assertEqual(2, len(self.server.posts()))

    def test_triggered_stop_converted_to_limit_keeps_parent_and_requires_exit(self):
        trader = self.trader()
        trader.execute_trade(self.decision(trader))
        self.server.orders["B2"]["order_type"] = "limit"
        trades, _ = trader.get_trades_state()
        self.assertTrue(trader.state_verified, trader.last_reconciliation_error)
        stop = trader.load_active_position()["stops"][0]
        self.assertEqual(("STOP", "OPEN", "B1"), (stop["kind"], stop["status"], stop["entry_order_id"]))
        self.assertFalse(trades[0]["protection_confirmed"])
        self.assertIn("triggered", trades[0]["risk_exit_required"])

    def test_stop_modification_uses_broker_total_quantity_and_tick_prices(self):
        trader = self.trader()
        trader.execute_trade(self.decision(trader))
        response = self.gateway.modify_stop_loss("B2", 50, 49)
        self.assertFalse(response.get("error"), response)
        mutation = self.server.calls[-1]
        self.assertEqual("PUT", mutation[0])
        self.assertEqual(
            ("65", "50.00", "49.00"), tuple(mutation[2][key] for key in ("quantity", "stoploss", "price"))
        )
        self.assertEqual(50, self.gateway.get_order("B2")["trigger_price"])

    def test_semantic_server_error_is_unknown_and_blocks_a_new_request(self):
        self.gateway.register_contract(INSTRUMENT, SYMBOL)
        with patch("urllib.request.urlopen", return_value=Response(None, status=200, error="system error")):
            response = self.gateway.place_buy_order(INSTRUMENT, 65, 67, request_id="unknown-error")
        self.assertTrue(response["outcome_unknown"])
        self.assertEqual("UNKNOWN", self.gateway.journal.records["unknown-error"]["phase"])
        response = self.gateway.place_buy_order(INSTRUMENT, 65, 67, request_id="must-not-send")
        self.assertEqual("ANOTHER_SUBMISSION_OUTCOME_UNKNOWN", response["detail"])
        self.assertFalse(self.server.posts())

    def test_read_budget_exhaustion_or_budget_persistence_failure_never_sends(self):
        before = len(self.server.calls)
        with self.gateway.read_budget(0):
            self.assertTrue(self.gateway.get_funds()["error"])
        with patch("trading.adapters.gateways.breeze.atomic_save", side_effect=OSError("disk full")):
            self.assertTrue(self.gateway.get_funds()["error"])
        self.assertEqual(before, len(self.server.calls))

    def test_read_only_diagnostics_report_failure_without_arming_or_mutations(self):
        from tools.brokers import inspect_broker

        gateway = self.gateway_new(arm=False)
        with patch("tools.brokers.create_execution_gateway", return_value=gateway):
            report = inspect_broker("breeze")
            self.assertTrue(report["ready"])
            self.assertEqual("PAPER", report["mode"])
            self.assertFalse(report["live_authorized"])
            self.server.fail = TimeoutError()
            report = inspect_broker("breeze")
            self.assertFalse(report["ready"])
            self.assertEqual(["funds", "positions", "orders"], report["failed_reads"])
        self.assertFalse(self.server.posts())
