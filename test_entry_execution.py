"""Offline entry failure tests. All approvals use the actual consultant evaluation."""

from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from ai_consultant import AIConsultant
from entry_policy import EntryBlocked, EntryPolicy, tick_price
from execution_client import AIExecutionClient
from market_clock import MarketClock
from test_self_healing_exit import Broker, ROOT, SYMBOL, Trader, approved_decision, entry_dossier


class EntryExecutionTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".entry-test-", dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "active_position.json"
        self.now = MarketClock.parse_to_ist("2026-10-19T10:00:00+05:30")
        self.clock = patch.object(MarketClock, "now_ist", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.broker = Broker()
        self.broker.quote_ask = self.broker.fill_price = 67
        self.trader = Trader(self.path, self.broker)
        self.trader.trading_cfg = {"option_selection": {"max_option_premium": 70}}

    def decision(self, price=67, **changes):
        return approved_decision(self.trader.trading_cfg, price, **changes)

    def buys(self):
        return [call[2] for call in self.broker.calls if call[:2] == ("POST", "/execution/orders")]

    def assert_blocked(self, decision, reason):
        result = self.trader.execute_trade(decision)
        self.assertEqual(reason, result["detail"])
        self.assertFalse(self.buys())
        self.assertFalse(self.path.exists())

    def test_jit_ask_moves_up_during_real_ai_consultation(self):
        decision = self.decision()
        self.broker.quote_ask = self.broker.fill_price = 68.20
        self.assertEqual("SUCCESS", self.trader.execute_trade(decision)["status"])
        self.assertEqual(68.25, self.buys()[0]["limit_price"])
        state = self.trader.load_active_position()
        self.assertEqual(68.20, state["entry_price"])
        self.assertEqual(47.75, state["stops"][0]["trigger_price"])
        self.assertEqual(68.20, state["entry_execution"]["quote"]["best_ask"])
        self.assertIn("acknowledged_at", state["entry_execution"])
        self.assertEqual(70, state["entry_execution"]["ai_verdict"]["max_entry_price"])

    def test_runaway_above_hard_premium_cap_is_rejected(self):
        decision = self.decision()
        self.broker.quote_ask = 70.10
        self.assert_blocked(decision, "AI_ENTRY_CEILING_EXCEEDED")

    def test_at_ceiling_submits_without_buffer_exceeding_ceiling(self):
        decision = self.decision()
        self.broker.quote_ask = 70
        self.assertEqual("SUCCESS", self.trader.execute_trade(decision)["status"])
        self.assertEqual(70, self.buys()[0]["limit_price"])

    def test_below_floor_requires_new_ai_evaluation(self):
        decision = self.decision()
        self.broker.quote_ask = 61.60
        self.assert_blocked(decision, "AI_ENTRY_FLOOR_BREACHED")

    def test_failed_quote_never_falls_back_to_old_ltp(self):
        self.broker.quote_error = {"error": True, "detail": "TIMEOUT"}
        self.assert_blocked(self.decision(), "ENTRY_QUOTE_UNAVAILABLE")

    def test_invalid_quote_fields_block_entry(self):
        quote = self.broker.get_contract_quote("TEST")
        cases = [
            ({"status": "STALE"}, "ENTRY_QUOTE_UNAVAILABLE"),
            ({"instrument_id": "OTHER"}, "ENTRY_QUOTE_IDENTITY_MISMATCH"),
            ({"timestamp": None}, "INVALID_ENTRY_TIMESTAMP"),
            ({"timestamp": "10:00:00"}, "INVALID_ENTRY_TIMESTAMP"),
            ({"timestamp": (self.now - timedelta(seconds=2)).isoformat()}, "ENTRY_QUOTE_STALE"),
            ({"timestamp": (self.now + timedelta(seconds=2)).isoformat()}, "ENTRY_QUOTE_STALE"),
            ({"request_started_monotonic": time.monotonic() - 2}, "ENTRY_QUOTE_STALE"),
            ({"best_bid": 68}, "INVALID_ENTRY_QUOTE_DEPTH"),
            ({"best_ask": 67.01}, "INVALID_ENTRY_QUOTE_DEPTH"),
            ({"best_ask_qty": 0}, "INVALID_ENTRY_QUOTE_DEPTH"),
            ({"best_bid_qty": 1.5}, "INVALID_ENTRY_QUOTE_DEPTH"),
            ({"best_ask": float("nan")}, "INVALID_ENTRY_NUMBER"),
            ({"best_bid": 60}, "ENTRY_SPREAD_TOO_WIDE"),
        ]
        for changes, reason in cases:
            with self.subTest(changes=changes), patch.object(self.broker, "get_contract_quote", return_value=dict(quote, **changes)):
                self.assert_blocked(self.decision(), reason)

    def test_missing_or_vetoed_approval_blocks_direct_entry(self):
        decision = self.decision()
        decision.pop("ai_verdict")
        self.assert_blocked(decision, "AI_APPROVAL_REQUIRED")
        decision["ai_verdict"] = AIConsultant(trading_config=self.trader.trading_cfg).evaluate(
            entry_dossier(67, vwap_distance_pts=80)).to_dict()
        self.assert_blocked(decision, "AI_APPROVAL_REQUIRED")

    def test_approval_cannot_be_reused_for_another_contract_or_reference(self):
        for changes, reason in [({"instrument_id": "OTHER"}, "AI_ENTRY_IDENTITY_MISMATCH"),
                                ({"setup_type": "CLIMAX_SPRING"}, "AI_ENTRY_IDENTITY_MISMATCH"),
                                ({"ltp": 66}, "AI_ENTRY_REFERENCE_MISMATCH")]:
            with self.subTest(changes=changes):
                decision = self.decision()
                decision.update(changes)
                self.assert_blocked(decision, reason)

    def test_missing_band_and_invalid_or_expired_approval_block_entry(self):
        for changes, reason in [({"max_entry_price": None}, "INVALID_ENTRY_NUMBER"),
                                ({"min_entry_price": 68}, "INVALID_AI_ENTRY_BAND"),
                                ({"entry_approved_at": (self.now + timedelta(seconds=1)).isoformat()}, "AI_ENTRY_APPROVAL_EXPIRED"),
                                ({"entry_valid_until": self.now.isoformat()}, "AI_ENTRY_APPROVAL_EXPIRED")]:
            with self.subTest(changes=changes):
                decision = self.decision()
                decision["ai_verdict"].update(changes)
                self.assert_blocked(decision, reason)

    def test_expiry_during_funds_read_blocks_before_quote_submission(self):
        decision = self.decision()
        def funds():
            self.now += timedelta(seconds=6)
            return {"available_margin": 10000}
        self.broker.get_funds = funds
        self.assert_blocked(decision, "AI_ENTRY_APPROVAL_EXPIRED")

    def test_candidate_age_is_checked_separately_from_approval_age(self):
        dossier = entry_dossier(67, candidate_timestamp=(self.now - timedelta(seconds=16)).isoformat())
        decision = self.decision()
        decision["ai_verdict"] = AIConsultant(trading_config=self.trader.trading_cfg).evaluate(dossier).to_dict()
        self.assert_blocked(decision, "AI_ENTRY_APPROVAL_EXPIRED")

    def test_funds_read_precedes_jit_quote_and_final_limit_controls_sizing(self):
        decision = self.decision()
        self.broker.quote_ask = 70
        # Old price would permit one lot: (4600 - 150) / 67 > 65.
        # The executable price does not: (4600 - 150) / 70 < 65.
        self.broker.get_funds = lambda: {"available_margin": 4600}
        self.assert_blocked(decision, "INSUFFICIENT_MARGIN_BLOCKED")
        self.assertTrue(any(c[1] == "/market/quote/TEST" for c in self.broker.calls))

    def test_reconciliation_and_funds_reads_precede_the_final_contract_quote(self):
        self.trader.execute_trade(self.decision())
        paths = [c[1] for c in self.broker.calls]
        quote_index = paths.index("/market/quote/TEST")
        self.assertLess(paths.index("/execution/positions"), quote_index)
        self.assertLess(next(i for i, path in enumerate(paths) if path.endswith("/account/funds")), quote_index)

    def test_approval_expiry_shortens_a_longer_configured_order_wait(self):
        self.broker.next_entry_status = "OPEN"
        with patch.object(self.broker, "wait_for_fill", wraps=self.broker.wait_for_fill) as wait:
            self.trader.execute_trade(self.decision())
        self.assertLessEqual(wait.call_args.kwargs["timeout_sec"], 5)

    def test_entry_cutoff_shortens_a_live_order_wait(self):
        self.now = self.now.replace(hour=14, minute=14, second=59)
        self.broker.next_entry_status = "OPEN"
        with patch.object(self.broker, "wait_for_fill", wraps=self.broker.wait_for_fill) as wait:
            self.trader.execute_trade(self.decision())
        self.assertLessEqual(wait.call_args.kwargs["timeout_sec"], 1)

    def test_slow_atomic_save_expires_quote_without_leaving_unknown_intent(self):
        decision = self.decision()
        save = self.trader.save_active_position
        def slow_save(state):
            save(state)
            self.now += timedelta(seconds=2)
        with patch.object(self.trader, "save_active_position", side_effect=slow_save):
            self.assert_blocked(decision, "ENTRY_QUOTE_STALE")

    def test_slow_order_logging_triggers_last_pre_submit_check(self):
        decision = self.decision()
        def slow_log(*args, **kwargs):
            self.now += timedelta(seconds=2)
        with patch("execution_client.logger.info", side_effect=slow_log):
            self.assert_blocked(decision, "ENTRY_QUOTE_STALE")

    def test_ai_approved_structural_boundary_is_checked_against_fresh_spot(self):
        decision = self.decision(setup_type="CLIMAX_SPRING", invalidation_level=22990)
        self.broker.spot_price = 22989
        self.assert_blocked(decision, "ENTRY_STRUCTURE_INVALIDATED")
        self.assertFalse(any(c[1] == "/market/quote/TEST" for c in self.broker.calls))

    def test_approved_structural_boundary_cannot_be_removed(self):
        decision = self.decision(setup_type="CLIMAX_SPRING", invalidation_level=22990)
        decision.pop("invalidation_level")
        self.assert_blocked(decision, "AI_ENTRY_INVALIDATION_MISMATCH")

    def test_structural_check_precedes_final_contract_quote(self):
        decision = self.decision(setup_type="CLIMAX_SPRING", invalidation_level=22990)
        self.assertEqual("SUCCESS", self.trader.execute_trade(decision)["status"])
        quotes = [c[1] for c in self.broker.calls if c[1].startswith("/market/quote/")]
        self.assertEqual(["/market/quote/INST-NIFTY-INDEX", "/market/quote/TEST", "/market/quote/TEST"], quotes)

    def test_malformed_funds_fail_closed_without_submitting(self):
        decision = self.decision()
        self.broker.get_funds = lambda: {"available_margin": "invalid"}
        self.assert_blocked(decision, "UNVERIFIED_FUNDS_OR_PRICE")

    def test_submission_timeout_preserves_intent_without_repricing(self):
        decision = self.decision()
        self.broker.lost_entry_response = True
        self.assertTrue(self.trader.execute_trade(decision)["error"])
        self.assertTrue(self.path.exists())
        state = self.trader.load_active_position()
        self.assertEqual(67.05, state["entry_execution"]["final_limit"])
        restarted = Trader(self.path, self.broker)
        restarted.get_trades_state()
        self.assertEqual(1, len(self.buys()))

    def test_unfilled_order_is_cancelled_with_configured_bounded_wait(self):
        self.trader.trading_cfg["risk"] = {"entry_order_timeout_sec": 2}
        self.broker.next_entry_status = "OPEN"
        original = self.broker.wait_for_fill
        with patch.object(self.broker, "wait_for_fill", wraps=original) as wait:
            self.trader.execute_trade(self.decision())
        self.assertGreater(wait.call_args.kwargs["timeout_sec"], 0)
        self.assertLessEqual(wait.call_args.kwargs["timeout_sec"], 2)
        self.assertTrue(wait.call_args.kwargs["return_on_partial"])
        self.assertEqual("CANCELLED", next(iter(self.broker.orders.values()))["status"])
        self.assertFalse(self.path.exists())

    def test_acknowledgement_delay_consumes_order_lifetime(self):
        self.trader.trading_cfg["risk"] = {"entry_order_timeout_sec": .01}
        self.broker.next_entry_status = "OPEN"
        def delayed_ack(method, path, payload):
            if path == "/execution/orders":
                time.sleep(.02)
        self.broker.on_submit = delayed_ack
        with patch.object(self.broker, "wait_for_fill", wraps=self.broker.wait_for_fill) as wait:
            self.trader.execute_trade(self.decision())
        self.assertEqual(0, wait.call_args.kwargs["timeout_sec"])
        self.assertEqual("CANCELLED", next(iter(self.broker.orders.values()))["status"])

    def test_partial_fill_gets_protection_while_cancel_remains_pending(self):
        self.trader.calculate_compounding_quantity = lambda *args: 130
        self.trader.strategy_cfg["compounding"] = {"max_order_quantity": 130}
        self.broker.next_entry_status, self.broker.next_entry_filled = "OPEN", 65
        original = self.broker._request
        def pending_cancel(method, path, payload=None, **kwargs):
            if method == "DELETE" and self.broker.orders[path.rsplit("/", 1)[-1]]["kind"] == "ENTRY":
                self.broker.calls.append((method, path, payload))
                return {"error": True, "outcome_unknown": True}
            return original(method, path, payload, **kwargs)
        with patch.object(self.broker, "_request", side_effect=pending_cancel):
            result = self.trader.execute_trade(self.decision())
        self.assertEqual("ENTRY_OR_PROTECTION_UNCONFIRMED", result["detail"])
        self.assertFalse(self.trader.state_verified)
        state = self.trader.load_active_position()
        self.assertEqual("ENTRY_PENDING", state["status"])
        self.assertTrue(state["protection_confirmed"])
        self.assertEqual(65, state["stops"][0]["quantity"])
        self.assertEqual(1, len(self.buys()))

    def test_fill_during_cancel_refreshes_position_before_protection(self):
        self.trader.calculate_compounding_quantity = lambda *args: 130
        self.trader.strategy_cfg["compounding"] = {"max_order_quantity": 130}
        self.broker.next_entry_status, self.broker.next_entry_filled = "OPEN", 65
        original = self.broker._request
        def cancel_race(method, path, payload=None, **kwargs):
            if method == "DELETE":
                self.broker.orders[path.rsplit("/", 1)[-1]]["filled_quantity"] = 130
            return original(method, path, payload, **kwargs)
        with patch.object(self.broker, "_request", side_effect=cancel_race):
            self.assertEqual("SUCCESS", self.trader.execute_trade(self.decision())["status"])
        self.assertEqual(130, self.trader.load_active_position()["stops"][0]["quantity"])


class EnvelopeTests(unittest.TestCase):
    def test_percentage_absolute_cap_and_tick_direction(self):
        policy = EntryPolicy.from_config({"option_selection": {"max_option_premium": 200}})
        self.assertEqual((61.65, 70.35), policy.band(67, "TREND_PULLBACK"))
        self.assertEqual((61.65, 69), policy.band(67, "CLIMAX_SPRING"))
        self.assertEqual((92, 104), policy.band(100, "TREND_PULLBACK"))
        self.assertEqual(70.30, tick_price(70.34999))
        self.assertEqual(61.65, tick_price(61.64, up=True))

    def test_climax_type_is_explicit_not_directional_shift_flag(self):
        config = {"option_selection": {"max_option_premium": 200}}
        consultant = AIConsultant(trading_config=config)
        normal = consultant.evaluate(entry_dossier(67, is_directional_shift=True))
        climax = consultant.evaluate(entry_dossier(67, setup_type="CLIMAX_SPRING"))
        self.assertEqual(70.35, normal.max_entry_price)
        self.assertEqual(69, climax.max_entry_price)

    def test_invalid_config_fails_closed(self):
        for changes in [{"marketable_limit_ticks": 1.5}, {"entry_buffer_pct": float("nan")},
                        {"entry_downside_buffer_pct": 100}, {"entry_quote_timeout_sec": 0},
                        {"climax_entry_buffer_pct": 6}]:
            with self.subTest(changes=changes), self.assertRaises(EntryBlocked):
                EntryPolicy.from_config({"execution": changes})

    def test_real_interactive_approval_gets_same_policy_and_identity(self):
        with patch("builtins.input", return_value="yes"), patch("sys.stdout", new=io.StringIO()):
            verdict = AIConsultant(mode="interactive").evaluate(entry_dossier(67))
        self.assertEqual("APPROVED", verdict.action)
        self.assertEqual(70, verdict.max_entry_price)
        self.assertEqual("TEST", verdict.entry_instrument_id)

    def test_real_chat_approval_can_narrow_but_cannot_expand_policy(self):
        import ai_consultant
        for upper in [68, 80]:
            with self.subTest(upper=upper), tempfile.TemporaryDirectory(prefix=".entry-chat-", dir=ROOT) as directory:
                root = Path(directory)
                verdict_file = root / "verdict.json"
                def submit_verdict(_):
                    pending = json.loads((root / "pending.json").read_text())
                    verdict_file.write_text(json.dumps({"action": "APPROVED", "max_entry_price": upper,
                        "request_id": pending["request_id"], "candidate_id": pending["candidate_id"],
                        "submitted_at": MarketClock.now_ist().isoformat()}))
                with patch.object(ai_consultant, "VERDICT_FILE", verdict_file), patch.object(ai_consultant, "PENDING_FILE_JSON", root / "pending.json"), patch.object(ai_consultant, "PENDING_FILE_MD", root / "pending.md"), patch("ai_consultant.time.sleep", side_effect=submit_verdict):
                    verdict = AIConsultant(mode="chat").evaluate(entry_dossier(67))
                self.assertEqual("APPROVED", verdict.action)
                self.assertEqual(min(upper, 70), verdict.max_entry_price)

    def test_actual_ai_veto_has_no_executable_band(self):
        verdict = AIConsultant().evaluate(entry_dossier(67, vwap_distance_pts=80))
        self.assertEqual("VETOED", verdict.action)
        self.assertIsNone(verdict.max_entry_price)

    def test_ai_deadline_cannot_produce_executable_approval(self):
        with patch("ai_consultant.time.monotonic", side_effect=[100, 146]):
            verdict = AIConsultant().evaluate(entry_dossier(67))
        self.assertEqual("TIMEOUT_EXPIRED", verdict.action)
        self.assertIsNone(verdict.max_entry_price)


class QuoteTransportTests(unittest.TestCase):
    def test_gateway_quote_path_encoding_and_no_timeout_retry(self):
        client = AIExecutionClient("http://invalid.test/api/v1/ai", "test")
        with patch("execution_client.urllib.request.urlopen", side_effect=TimeoutError()) as call:
            result = client.get_contract_quote("NFO:ABC/CE", timeout_sec=.7)
        self.assertTrue(result["error"])
        self.assertEqual(1, call.call_count)
        self.assertEqual(.7, call.call_args.kwargs["timeout"])
        self.assertEqual("http://invalid.test/api/v1/market/quote/NFO%3AABC%2FCE", call.call_args.args[0].full_url)

    def test_gateway_depth_and_timestamp_are_preserved(self):
        payload = dict(instrument_id="TEST", best_bid=67, best_ask=67.05,
                       best_bid_qty=65, best_ask_qty=130, timestamp="2026-10-19T04:30:00Z")
        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(payload).encode()
        with patch("execution_client.urllib.request.urlopen", return_value=response):
            result = AIExecutionClient("http://invalid.test/api/v1/ai", "test").get_contract_quote("TEST")
        self.assertEqual(payload, {k: result[k] for k in payload})
        self.assertLessEqual(result["request_started_monotonic"], result["received_monotonic"])

    def test_fill_poll_returns_on_partial_without_waiting_for_full_quantity(self):
        client = AIExecutionClient("http://invalid.test", "test")
        partial = dict(order_id="E1", quantity=130, filled_quantity=65, status="OPEN")
        with patch.object(client, "_request", return_value=partial) as request, patch("execution_client.time.sleep") as sleep:
            self.assertEqual(partial, client.wait_for_fill("E1", timeout_sec=10, return_on_partial=True))
        self.assertEqual(1, request.call_count)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
