"""Native Kite transport and OMS failure cases. No live broker or replacement AI."""

import copy
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.parse
from unittest.mock import patch

from execution_safety import ReconciliationError
from entry_policy import EntryBlocked, EntryPolicy, entry_limit
from market_clock import MarketClock
from test_self_healing_exit import Trader, approved_decision, entry_dossier, SYMBOL
from ai_consultant import AIConsultant
from trading.adapters.gateways import BreezeExecutionGateway, KiteExecutionGateway, create_execution_gateway
from trading.adapters.gateways.journal import broker_tag
from trading.adapters.gateways.rate_limiter import TokenBucketRateLimiter
from trading.application.scheduler import run_scheduler
from tests.gateway_lifecycle import end_gateway_process

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-21T10:00:00+05:30"


class Response:
    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps({"status": "success", "data": self.data}).encode()


class Server:
    def __init__(self):
        self.orders = {}
        self.calls = []
        self.account = "TEST_ACCOUNT"
        self.fail = None
        self.lose_next = None
        self.partial_cancel = False
        self.quote = None
        self.profile_calls = 0
        self.sequence = 0

    def add(self, oid, side="BUY", kind="LIMIT", qty=65, filled=65, state="COMPLETE", tag=None, price=67):
        self.orders[oid] = dict(
            order_id=oid,
            tradingsymbol=SYMBOL,
            exchange="NFO",
            product="NRML",
            transaction_type=side,
            order_type=kind,
            quantity=qty,
            filled_quantity=filled,
            status=state,
            tag=tag,
            order_timestamp=MarketClock.now_ist().isoformat(),
            average_price=price if filled else 0,
            price=price,
            trigger_price=45 if kind == "SL" else 0,
            variety="regular",
        )
        return self.orders[oid]

    def __call__(self, request, timeout):
        method = request.get_method()
        path = urllib.parse.urlparse(request.full_url).path
        data = {
            key: values[0] for key, values in urllib.parse.parse_qs((request.data or b"").decode()).items()
        }
        self.calls.append((method, path, data, timeout))
        if self.fail:
            raise self.fail
        if path == "/user/profile":
            self.profile_calls += 1
            return Response({"user_id": self.account})
        if path == "/orders" and method == "GET":
            return Response(list(copy.deepcopy(self.orders).values()))
        if path == "/portfolio/positions":
            balance = sum(
                o["filled_quantity"] * (1 if o["transaction_type"] == "BUY" else -1)
                for o in self.orders.values()
            )
            return Response(
                {
                    "net": [
                        dict(
                            tradingsymbol=SYMBOL,
                            exchange="NFO",
                            product="NRML",
                            quantity=balance,
                            average_price=67,
                            last_price=68,
                        )
                    ]
                    if balance
                    else []
                }
            )
        if path == "/user/margins":
            return Response(
                {"equity": {"available": {"live_balance": 10000, "cash": 10000}, "utilised": {"debits": 0}}}
            )
        if path == "/quote":
            keys = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)["i"]
            quote = (
                self.quote
                if self.quote is not None
                else dict(
                    last_price=67,
                    timestamp=MarketClock.now_ist().isoformat(),
                    depth={
                        "buy": [{"price": 66.95, "quantity": 650, "orders": 2}],
                        "sell": [{"price": 67, "quantity": 650, "orders": 1}],
                    },
                )
            )
            return Response(
                {key: {**quote, "last_price": 23000} if key == "NSE:NIFTY 50" else quote for key in keys}
            )
        if path == "/orders/regular" and method == "POST":
            self.sequence += 1
            oid = str(self.sequence)
            stop = data["order_type"] == "SL"
            self.add(
                oid,
                data["transaction_type"],
                data["order_type"],
                int(data["quantity"]),
                0 if stop else int(data["quantity"]),
                "TRIGGER PENDING" if stop else "COMPLETE",
                data["tag"],
            )
            self.orders[oid]["trigger_price"] = float(data.get("trigger_price", 0))
            self.orders[oid]["average_price"] = (
                67 if data["transaction_type"] == "BUY" else 68 if not stop else 0
            )
            if self.lose_next == data["order_type"] or self.lose_next == data["transaction_type"]:
                self.lose_next = None
                raise TimeoutError("lost acknowledgement")
            return Response({"order_id": oid})
        oid = path.rsplit("/", 1)[-1]
        if method == "DELETE":
            self.orders[oid]["status"] = "CANCELLED"
            if self.partial_cancel:
                self.orders[oid]["filled_quantity"] = 65
                self.orders[oid]["average_price"] = 60
                self.partial_cancel = False
            return Response({"order_id": oid})
        if method == "PUT":
            self.orders[oid]["trigger_price"] = float(data["trigger_price"])
            return Response({"order_id": oid})
        raise AssertionError((method, path))

    def posts(self):
        return [call for call in self.calls if call[:2] == ("POST", "/orders/regular")]


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".native-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gateways = []
        self.server = Server()
        self.now = MarketClock.parse_to_ist(NOW)
        clock = patch.object(MarketClock, "now_ist", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        http = patch("urllib.request.urlopen", side_effect=self.server)
        http.start()
        self.addCleanup(http.stop)
        self.gateway = self.gateway_new()

    def gateway_new(self, *, account="TEST_ACCOUNT", arm=True, journal_name="broker_intents.json"):
        gateway = KiteExecutionGateway(
            api_key="test-key",
            access_token="test-token",
            account_id=account,
            journal_path=self.root / journal_name,
        )
        self.gateways.append(gateway)
        self.addCleanup(end_gateway_process, gateway)
        # Broker pacing has separate tests; deterministic OMS cases don't sleep.
        gateway.rate_limiter.acquire = lambda **kw: True
        gateway.quote_limiter.acquire = lambda **kw: True
        if arm:
            self.assertTrue(gateway.set_mode("LIVE").get("live_authorized"))
        return gateway

    def restart_gateway(self, **kwargs):
        for gateway in self.gateways:
            end_gateway_process(gateway)
        self.gateway = self.gateway_new(**kwargs)
        return self.gateway

    def seed(self, qty=130, sell=65):
        self.gateway.journal.put(
            "entry-full-request-id",
            kind="ENTRY",
            symbol=SYMBOL,
            order_id="E1",
            entry_order_id=None,
            phase="ACKNOWLEDGED",
        )
        self.server.add("E1", qty=qty, filled=qty, tag=broker_tag("entry-full-request-id"))
        if sell:
            self.gateway.journal.put(
                "stop-full-request-id",
                kind="STOP",
                symbol=SYMBOL,
                order_id="S1",
                entry_order_id="E1",
                phase="ACKNOWLEDGED",
            )
            self.server.add(
                "S1",
                "SELL",
                "SL",
                qty=qty,
                filled=sell,
                state="CANCELLED",
                tag=broker_tag("stop-full-request-id"),
                price=60,
            )

    def trader(self, gateway=None, qty=65):
        trader = Trader(self.root / "active_position.json", gateway or self.gateway)
        trader.trading_cfg = {"option_selection": {"max_option_premium": 70}}
        trader.strategy_cfg["compounding"] = {"max_order_quantity": qty}
        trader.calculate_compounding_quantity = lambda *a: qty
        return trader

    def decision(self, trader):
        return approved_decision(trader.trading_cfg, 67, symbol=SYMBOL, instrument_id=SYMBOL)

    def test_default_is_unarmed_and_every_paper_mutation_is_blocked(self):
        gateway = self.gateway_new(arm=False)
        self.assertEqual("PAPER", gateway._mode)
        operations = [
            lambda: gateway.place_buy_order(SYMBOL, 65, 67),
            lambda: gateway.place_stop_loss("E", 45, 44),
            lambda: gateway.exit_position("E", 67),
            lambda: gateway.modify_stop_loss("S", 45, 44),
            lambda: gateway.cancel_stop_loss("S"),
            lambda: gateway.cancel_entry_order("E"),
            lambda: gateway._submit_buy_order(SYMBOL, 65, 67, "tag"),
        ]
        before = len(self.server.calls)
        for operation in operations:
            self.assertTrue(operation()["error"])
        self.assertEqual(before, len(self.server.calls))
        self.gateway.set_mode("PAPER")
        self.assertTrue(self.gateway.place_buy_order(SYMBOL, 65, 67)["error"])

    def test_profile_account_is_verified_and_wrong_account_refuses_live(self):
        other = self.gateway_new(account="WRONG", arm=False)
        self.assertTrue(other.set_mode("LIVE")["error"])
        self.assertEqual("PAPER", other._mode)
        self.assertEqual("TEST_ACCOUNT", self.gateway.get_status()["account_id"])

    def test_credentials_file_account_is_loaded_without_constructor_network(self):
        path = self.root / "credentials.json"
        path.write_text(
            json.dumps(
                dict(api_key="test-file-key", access_token="test-file-token", account_id="TEST_ACCOUNT")
            )
        )
        with (
            patch.dict("os.environ", {}, clear=True),
            patch("trading.adapters.gateways.kite.ensure_environment"),
        ):
            before = len(self.server.calls)
            gateway = KiteExecutionGateway(credentials_path=path, journal_path=self.root / "other.json")
            self.assertEqual("TEST_ACCOUNT", gateway.account_id)
            self.assertEqual(before, len(self.server.calls))

    def test_exit_places_one_sell_for_residual_not_original_quantity(self):
        self.seed()
        result = self.gateway.exit_position("E1", 68, request_id="exit-full-request-id")
        self.assertIn("order_id", result)
        self.assertEqual(["SELL"], [c[2]["transaction_type"] for c in self.server.posts()])
        self.assertEqual("65", self.server.posts()[0][2]["quantity"])
        order = self.gateway.get_order(result["order_id"])
        self.assertEqual("E1", order["entry_order_id"])
        self.assertEqual("exit-full-request-id", order["request_id"])

    def test_replacement_stop_uses_residual_and_no_duplicate_live_sell(self):
        self.seed()
        result = self.gateway.place_stop_loss("E1", 45, 44, request_id="new-stop")
        self.assertIn("order_id", result)
        self.assertEqual("65", self.server.posts()[0][2]["quantity"])
        second = self.gateway.place_stop_loss("E1", 45, 44, request_id="duplicate-stop")
        self.assertTrue(second["error"])
        self.assertEqual(1, len(self.server.posts()))
        self.assertTrue(self.gateway.exit_position("E1", 68)["error"])

    def test_zero_fill_pending_entry_cannot_arm_a_stop(self):
        self.seed(sell=0)
        self.server.orders["E1"].update(status="OPEN", filled_quantity=0)
        self.assertTrue(self.gateway.place_stop_loss("E1", 45, 44)["error"])
        self.assertEqual([], self.server.posts())

    def test_verified_partial_fill_gets_protection_while_entry_cancel_is_pending(self):
        self.seed(sell=0)
        self.server.orders["E1"].update(status="OPEN", filled_quantity=65)
        result = self.gateway.place_stop_loss("E1", 45, 44, request_id="partial-protection")
        self.assertIn("order_id", result, result)
        self.assertEqual("65", self.server.posts()[-1][2]["quantity"])

    def test_position_and_ledger_disagreement_blocks_sell(self):
        self.seed()
        self.server.orders["E1"]["filled_quantity"] = 50
        self.assertTrue(self.gateway.exit_position("E1", 68)["error"])
        self.assertFalse(self.server.posts())

    def test_exit_quantity_changed_during_preflight_blocks_stale_sell(self):
        self.seed()

        def changed(payload):
            self.server.orders["S1"]["filled_quantity"] = 100

        result = self.gateway.exit_position("E1", 68, request_id="changed-quantity", before_submit=changed)
        self.assertEqual("EXIT_QUANTITY_CHANGED", result["detail"])
        self.assertFalse(result["outcome_unknown"])
        self.assertFalse(self.server.posts())

    def test_unowned_entry_cannot_be_used_to_place_protection(self):
        self.server.add("foreign", qty=65, filled=65)
        result = self.gateway.place_stop_loss("foreign", 45, 44)
        self.assertIn("ownership", result["detail"])
        self.assertFalse(self.server.posts())

    def test_network_mutation_is_single_attempt_and_restart_recovers_same_request(self):
        request = "AI-ENTRY-" + "a" * 32
        self.server.lose_next = "BUY"
        result = self.gateway.place_buy_order(SYMBOL, 65, 67, request_id=request)
        self.assertTrue(result["outcome_unknown"])
        other = self.restart_gateway()
        recovered = other.place_buy_order(SYMBOL, 65, 67, request_id=request)
        self.assertEqual("1", recovered["order_id"])
        self.assertTrue(recovered["recovered"])
        self.assertEqual(1, len(self.server.posts()))
        self.assertEqual(request, other.get_orders()["orders"][0]["request_id"])
        self.assertTrue(self.server.posts()[0][2]["tag"].isalnum())
        self.assertEqual(20, len(self.server.posts()[0][2]["tag"]))

    def test_unknown_submission_not_found_is_never_retried(self):
        self.gateway.journal.put(
            "pending", kind="ENTRY", symbol=SYMBOL, entry_order_id=None, phase="PREPARED"
        )
        result = self.gateway.place_buy_order(SYMBOL, 65, 67, request_id="pending")
        self.assertTrue(result["outcome_unknown"])
        self.assertFalse(self.server.posts())

    def test_failed_mutation_http_responses_are_not_retried(self):
        for code in (400, 403, 429, 500, 502, 504):
            with self.subTest(code=code):
                gateway = self.restart_gateway(journal_name=f"http-{code}.json")
                self.server.fail = urllib.error.HTTPError("https://invalid.test", code, "test", {}, None)
                before = len(self.server.calls)
                result = gateway.place_buy_order(SYMBOL, 65, 67, request_id=f"failure-{code}")
                self.assertTrue(result["error"])
                self.assertEqual(code >= 500, result["outcome_unknown"])
                self.assertEqual(1, len(self.server.calls) - before)
                self.server.fail = None

    def test_reads_never_turn_errors_into_empty_books_or_expired_cache(self):
        self.assertEqual({"orders": []}, self.gateway.get_orders())
        self.assertEqual({"positions": []}, self.gateway.get_positions())
        self.server.fail = urllib.error.HTTPError("https://invalid.test", 403, "test", {}, None)
        self.assertTrue(self.gateway.get_orders()["error"])
        self.assertTrue(self.gateway.get_positions()["error"])
        self.assertTrue(self.gateway.get_funds()["error"])
        self.assertFalse(self.gateway.is_connected())

    def test_missing_or_malformed_broker_books_are_errors(self):
        for payload in ({"error": True}, {}, None, "invalid"):
            with self.subTest(payload=payload), patch.object(self.gateway, "_request", return_value=payload):
                self.assertTrue(self.gateway.get_orders()["error"])
                self.assertTrue(self.gateway.get_positions()["error"])
                self.assertTrue(self.gateway.get_funds()["error"])

    def test_reconciliation_reads_are_fresh_without_mutation_invalidation(self):
        self.assertFalse(self.gateway.get_orders()["orders"])
        self.seed(sell=0)
        self.assertEqual(1, len(self.gateway.get_orders()["orders"]))

    def test_zero_live_balance_does_not_fall_back_to_cash(self):
        result = {"equity": {"available": {"live_balance": 0, "cash": 10000}, "utilised": {"debits": 10000}}}
        with patch.object(self.gateway, "_request", return_value=result):
            self.assertEqual(0, self.gateway.get_funds()["available_margin"])

    def test_quote_preserves_missing_timestamp_and_zero_depth_and_uses_quantity(self):
        quote = self.gateway.get_contract_quote(SYMBOL)
        self.assertEqual(650, quote["best_ask_qty"])
        self.server.quote = {
            "last_price": 67,
            "depth": {
                "buy": [{"price": 0, "orders": 1, "quantity": 0}],
                "sell": [{"price": 0, "orders": 1, "quantity": 0}],
            },
        }
        quote = self.gateway.get_contract_quote(SYMBOL)
        self.assertEqual(0, quote["best_bid"])
        self.assertEqual(0, quote["best_ask_qty"])
        self.assertIsNone(quote["timestamp"])
        trader = self.trader()
        with self.assertRaises(EntryBlocked):
            entry_limit(self.decision(trader), quote, EntryPolicy.from_config(trader.trading_cfg))

    def test_preflight_runs_after_rate_wait_and_can_prevent_any_transmission(self):
        events = []
        self.gateway.rate_limiter.acquire = lambda **kw: events.append("rate_wait") or True

        def check():
            events.append("preflight")
            raise EntryBlocked("STALE_AFTER_WAIT")

        with self.assertRaisesRegex(EntryBlocked, "STALE_AFTER_WAIT"):
            self.gateway.place_buy_order(SYMBOL, 65, 67, request_id="stale", before_submit=check)
        self.assertEqual(["rate_wait", "preflight"], events)
        self.assertFalse(self.server.posts())
        self.assertEqual("REJECTED", self.gateway.journal.records["stale"]["phase"])

    def test_metadata_persistence_failure_prevents_transmission(self):
        with patch("trading.adapters.gateways.journal.atomic_save", side_effect=OSError("disk full")):
            result = self.gateway.place_buy_order(SYMBOL, 65, 67, request_id="no-disk")
        self.assertTrue(result["error"])
        self.assertFalse(result["outcome_unknown"])
        self.assertFalse(self.server.posts())

    def test_corrupt_metadata_refuses_live_start(self):
        (self.root / "broker_intents.json").write_text("invalid json")
        gateway = self.gateway_new(arm=False)
        self.assertTrue(gateway.set_mode("LIVE")["error"])
        self.assertFalse(self.server.posts())

    def test_request_id_cannot_be_reused_for_different_order(self):
        self.gateway.place_buy_order(SYMBOL, 65, 67, request_id="unique")
        result = self.gateway.place_buy_order("OTHER", 65, 67, request_id="unique")
        self.assertTrue(result["error"])
        self.assertEqual(1, len(self.server.posts()))

    def test_actual_ai_entry_restart_ratchet_and_exit(self):
        trader = self.trader()
        result = trader.execute_trade(self.decision(trader))
        self.assertEqual("SUCCESS", result["status"], result)
        other = self.restart_gateway()
        recovered = self.trader(other)
        trades, _ = recovered.get_trades_state()
        self.assertTrue(recovered.state_verified, recovered.last_reconciliation_error)
        recovered.ratchet_stops(trades[0], 50)
        self.assertEqual(50, self.server.orders[result["stop_order_ids"][0]]["trigger_price"])
        outcome = recovered.exit_trade(result["order_id"], "test exit")
        self.assertEqual("CLOSED", outcome["status"], outcome)
        self.assertFalse(recovered.position_store.exists())
        self.assertEqual(["BUY", "SELL", "SELL"], [c[2]["transaction_type"] for c in self.server.posts()])
        # A second round trip in the same contract must exclude completed earlier fills.
        self.assertEqual("SUCCESS", recovered.execute_trade(self.decision(recovered))["status"])

    def test_native_entry_batches_index_and_option_in_one_quote_request(self):
        trader = self.trader()
        decision = approved_decision(
            trader.trading_cfg,
            67,
            symbol=SYMBOL,
            instrument_id=SYMBOL,
            invalidation_level=22900,
            signal="BUY_CE",
        )
        result = trader.execute_trade(decision)
        self.assertEqual("SUCCESS", result["status"], result)
        quotes = [call for call in self.server.calls if call[1] == "/quote"]
        self.assertEqual(2, len(quotes))  # One batched entry quote, then a protective-stop quote.
        evidence = trader.load_active_position()["entry_execution"]
        self.assertEqual(23000, evidence["spot_quote"]["last_price"])

    def test_internal_instrument_identity_survives_native_translation_and_restart(self):
        trader = self.trader()
        internal = "INST-NIFTY-2026-10-27-23000-CE"
        decision = approved_decision(trader.trading_cfg, 67, symbol=SYMBOL, instrument_id=internal)
        result = trader.execute_trade(decision)
        self.assertEqual("SUCCESS", result["status"], result)
        self.assertEqual(SYMBOL, self.server.posts()[0][2]["tradingsymbol"])
        state = trader.load_active_position()
        self.assertEqual(internal, state["entry_execution"]["quote"]["instrument_id"])
        self.assertEqual(internal, state["entry_execution"]["ai_verdict"]["entry_instrument_id"])
        recovered = self.trader(self.restart_gateway())
        trades, _ = recovered.get_trades_state()
        self.assertTrue(recovered.state_verified, recovered.last_reconciliation_error)
        self.assertEqual(internal, trades[0]["instrument_id"])
        self.assertEqual("CLOSED", recovered.exit_trade(result["order_id"], "test translated exit")["status"])

    def test_unmapped_internal_id_and_conflicting_contract_alias_are_rejected(self):
        before = len(self.server.calls)
        self.assertTrue(self.gateway.get_contract_quote("INST-UNMAPPED")["error"])
        self.assertTrue(self.gateway.place_buy_order("INST-UNMAPPED", 65, 67)["error"])
        self.assertEqual(before, len(self.server.calls))
        self.gateway.register_contract("INST-MAPPED", SYMBOL)
        with self.assertRaisesRegex(ValueError, "mapping changed"):
            self.gateway.register_contract("INST-MAPPED", "DIFFERENT")

    def test_expired_actual_ai_entry_is_rejected_after_rate_wait(self):
        trader = self.trader()
        decision = self.decision(trader)

        def wait(**kwargs):
            if self.server.calls and self.server.calls[-1][1] == "/quote":
                self.now += timedelta(seconds=2)
            return True

        self.gateway.rate_limiter.acquire = wait
        result = trader.execute_trade(decision)
        self.assertEqual("ENTRY_QUOTE_STALE", result["detail"])
        self.assertFalse(self.server.posts())
        self.assertFalse(trader.position_store.exists())

    def test_actual_ai_veto_and_timeout_never_reach_native_broker(self):
        trader = self.trader()
        for timeout in (False, True):
            dossier = entry_dossier(67, instrument_id=SYMBOL, vwap_distance_pts=80 if not timeout else 10)
            consultant = AIConsultant(
                mode="playbook", timeout_seconds=0 if timeout else 45, trading_config=trader.trading_cfg
            )
            decision = {
                "symbol": SYMBOL,
                "instrument_id": SYMBOL,
                "ltp": 67,
                "ai_verdict": consultant.evaluate(dossier).to_dict(),
            }
            result = trader.execute_trade(decision)
            self.assertEqual("AI_APPROVAL_REQUIRED", result["detail"])
        self.assertFalse(self.server.posts())

    def test_metadata_from_other_instances_is_preserved_and_missing_file_blocks_writes(self):
        other = self.gateway_new(arm=False)
        other.get_status()  # Bind its read-only journal without acquiring a second LIVE lease.
        self.gateway.journal.put("first", kind="ENTRY", symbol=SYMBOL, phase="REJECTED")
        other.journal.put("second", kind="ENTRY", symbol=SYMBOL, phase="REJECTED")
        self.assertEqual({"first", "second"}, set(self.gateway.journal.records))
        (self.root / "broker_intents.json").unlink()
        self.assertTrue(self.gateway.place_buy_order(SYMBOL, 65, 67, request_id="never-sent")["error"])
        self.assertFalse(self.server.posts())

    def test_unresolved_intent_blocks_a_new_request_id(self):
        self.gateway.journal.put("unknown-entry", kind="ENTRY", symbol=SYMBOL, phase="UNKNOWN")
        result = self.gateway.place_buy_order(SYMBOL, 65, 67, request_id="another-entry")
        self.assertEqual("ANOTHER_SUBMISSION_OUTCOME_UNKNOWN", result["detail"])
        self.assertFalse(self.server.posts())

    def test_lost_entry_and_stop_ack_recover_without_duplicate_orders(self):
        for lost in ("BUY", "SL"):
            with self.subTest(lost=lost):
                self.server.orders.clear()
                self.server.calls.clear()
                trader = self.trader()
                self.server.lose_next = lost
                trader.execute_trade(self.decision(trader))
                other = self.trader(self.restart_gateway())
                trades, _ = other.get_trades_state()
                self.assertTrue(other.state_verified, other.last_reconciliation_error)
                self.assertTrue(trades[0]["protection_confirmed"])
                self.assertEqual(2, len(self.server.posts()))
                other.exit_trade(trades[0]["trade_id"], "cleanup")

    def test_partial_stop_fill_during_cancel_sells_only_remaining_65(self):
        trader = self.trader(qty=130)
        result = trader.execute_trade(self.decision(trader))
        self.assertEqual("SUCCESS", result["status"], result)
        self.server.partial_cancel = True
        outcome = trader.exit_trade(result["order_id"], "partial stop race")
        self.assertEqual("CLOSED", outcome["status"], outcome)
        self.assertEqual("65", self.server.posts()[-1][2]["quantity"])

    def test_lost_exit_ack_is_reconciled_flat_without_another_sell(self):
        trader = self.trader()
        result = trader.execute_trade(self.decision(trader))
        self.server.lose_next = "SELL"
        outcome = trader.exit_trade(result["order_id"], "lost exit")
        self.assertTrue(outcome["outcome_unknown"])
        other = self.trader(self.restart_gateway())
        self.assertEqual([], other.get_trades_state()[0])
        self.assertTrue(other.state_verified, other.last_reconciliation_error)
        self.assertEqual(3, len(self.server.posts()))

    def test_preserved_parent_cannot_be_erased_and_conflicting_parent_is_rejected(self):
        owner = self.trader()
        record = {"order_id": "S1", "kind": "STOP", "entry_order_id": "E1"}
        reply = {
            "order_id": "S1",
            "status": "TRIGGER_PENDING",
            "filled_quantity": 0,
            "quantity": 65,
            "trigger_price": 45,
            "entry_order_id": None,
            "parent_order_id": None,
        }
        with patch.object(self.gateway, "get_order", return_value=reply):
            owner._refresh_record(record, [])
        self.assertEqual("E1", record["entry_order_id"])
        reply["entry_order_id"] = "DIFFERENT"
        with (
            patch.object(self.gateway, "get_order", return_value=reply),
            self.assertRaises(ReconciliationError),
        ):
            owner._refresh_record(record, [])

    def test_legacy_state_hydrates_truncated_tags(self):
        request = "AI-ENTRY-" + "b" * 32
        self.gateway.restore_recovery_state(
            {
                "symbol": SYMBOL,
                "scope": {"mode": "LIVE", "account_id": "TEST_ACCOUNT"},
                "entries": [{"kind": "ENTRY", "request_id": request, "order_id": "E1"}],
                "stops": [],
                "exits": [],
            }
        )
        self.server.add("E1", tag=request[:20])
        self.assertEqual(request, self.gateway.get_order("E1")["request_id"])

    def test_unknown_manual_orders_block_reconciliation_and_are_not_cancelled(self):
        self.server.add("manual", filled=0, state="OPEN", tag=None)
        owner = self.trader()
        owner.get_trades_state()
        self.assertFalse(owner.state_verified)
        self.assertFalse(any(c[0] == "DELETE" for c in self.server.calls))

    def test_native_cli_requires_live_before_constructing_a_trader(self):
        with patch("sys.argv", ["scheduler", "--broker", "kite"]), patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit):
                run_scheduler(lambda **kwargs: self.fail("Trader must not be constructed"))

    def test_breeze_factory_constructs_disarmed_without_network(self):
        before = len(self.server.calls)
        gateway = create_execution_gateway(
            "breeze",
            api_key="test-key",
            api_secret="test-secret",
            access_token="test-token",
            account_id="TEST_ACCOUNT",
            journal_path=self.root / "breeze-intents.json",
        )
        self.assertIsInstance(gateway, BreezeExecutionGateway)
        self.assertFalse(gateway.is_connected())
        self.assertFalse(gateway._live_authorized)
        self.assertEqual(before, len(self.server.calls))

    def test_default_factory_preserves_proxy(self):
        from execution_client import AIExecutionClient

        self.assertIsInstance(create_execution_gateway(), AIExecutionClient)

    def test_history_requires_explicit_token_and_uses_official_kite_route(self):
        before = len(self.server.calls)
        response = self.gateway.get_historical_candles(
            "INST-NIFTY-INDEX", "2026-10-22 09:15:00", "2026-10-22 10:00:00"
        )
        self.assertTrue(response["error"])
        self.assertEqual(before, len(self.server.calls))
        candles = [["2026-10-22T09:15:00+0530", 23000, 23010, 22990, 23005, 0]]
        with patch.object(self.gateway, "_request", return_value={"candles": candles}) as request:
            response = self.gateway.get_historical_candles(
                "INST-NIFTY-INDEX", "2026-10-22 09:15:00", "2026-10-22 10:00:00", instrument_token=256265
            )
        self.assertEqual(candles, response["candles"])
        self.assertEqual("kite", response["source"])
        self.assertEqual(("GET", "/instruments/historical/256265/minute"), request.call_args.args)
        self.assertEqual(1, request.call_args.kwargs["params"]["oi"])


class PacingTests(unittest.TestCase):
    def test_quote_limiter_paces_consecutive_requests_and_budget_caps_socket_timeout(self):
        with tempfile.TemporaryDirectory(prefix=".pacing-test-", dir=ROOT) as directory:
            clock = [0.0]
            sent = []

            def http(request, timeout):
                sent.append((clock[0], timeout))
                return Response({})

            with (
                patch("time.monotonic", side_effect=lambda: clock[0]),
                patch("time.sleep", side_effect=lambda n: clock.__setitem__(0, clock[0] + n)),
                patch("urllib.request.urlopen", side_effect=http),
            ):
                gateway = KiteExecutionGateway(
                    api_key="test", access_token="test", journal_path=Path(directory) / "intents.json"
                )
                gateway._request("GET", "/quote", timeout=2, max_retries=0)
                gateway._request("GET", "/quote", timeout=2, max_retries=0)
                self.assertGreaterEqual(sent[1][0] - sent[0][0], 1)
                with gateway.read_budget(0.2):
                    reply = gateway._request("GET", "/quote", timeout=10, max_retries=0)
                self.assertTrue(reply["error"])
                self.assertEqual(2, len(sent))
                with gateway.read_budget(0.15):
                    gateway._request("GET", "/orders", timeout=10, max_retries=0)
                self.assertLessEqual(sent[-1][1], 0.15 + 1e-9)

    def test_invalid_rate_configurations_are_rejected(self):
        for rate, capacity in ((0, 1), (-1, 1), (1, 0), (float("nan"), 1)):
            with self.assertRaises(ValueError):
                TokenBucketRateLimiter(rate, capacity)


if __name__ == "__main__":
    unittest.main()
