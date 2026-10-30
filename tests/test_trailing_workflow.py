"""Offline protective-order races and runner decisions, never live or trading backtests."""

from datetime import timedelta
import json
import io
from pathlib import Path
import unittest
import urllib.error
from unittest.mock import patch

from market_clock import MarketClock
import test_self_healing_exit as lifecycle_fixtures
import tests.test_gateways as gateway_fixtures
from test_self_healing_exit import Trader
from tests.test_gateways import Response
from backtest_engine import StrategyConfig, Trade
from trading.configuration import validate_trailing_configuration
from trading.application.position_monitor import PositionMonitor

ROOT = Path(__file__).resolve().parents[1]


class StopTransitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = lifecycle_fixtures.LifecycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.trader = self.fixture.trader
        self.broker = self.fixture.broker
        self.state = self.fixture.existing()[0]

    def exhaust(self):
        self.state["stops"][0]["modifications"] = 25
        self.trader.save_active_position(self.state)

    def test_replacement_is_durable_before_cancel_and_create_and_does_not_reset_peak(self):
        self.exhaust()
        self.state["peak_bid"] = 200
        self.trader.save_active_position(self.state)
        observed = []

        def check(method, path, payload):
            saved = self.trader.load_active_position()
            observed.append((method, path))
            self.assertIn("stop_replacement", saved)
            if method == "POST":
                self.assertEqual("CANCELLED", self.broker.orders["S1"]["status"])
                self.assertEqual(payload["request_id"], saved["stops"][-1]["request_id"])

        self.broker.on_submit = check
        self.trader.ratchet_stops(self.state, 90)
        self.assertEqual(["DELETE", "POST"], [x[0] for x in observed])
        self.assertEqual(200, self.state["peak_bid"])
        self.assertEqual(100, self.state["entry_price"])
        self.assertEqual(90, self.state["desired_stop_trigger"])
        self.assertEqual(0, self.state["stops"][-1]["modifications"])
        self.assertTrue(self.state["protection_confirmed"])
        self.assertNotIn("stop_replacement", self.state)

    def test_unconfirmed_cancel_never_creates_competing_stop_and_resumes_after_restart(self):
        self.exhaust()
        self.broker.cancel_behavior = "pending"
        self.trader.ratchet_stops(self.state, 90)
        self.assertFalse(self.fixture.posts("/execution/stops"))
        self.assertFalse(self.state["protection_confirmed"])
        restarted = Trader(self.fixture.path, self.broker)
        self.broker.orders["S1"]["status"] = "CANCELLED"
        trades, _ = restarted.get_trades_state()
        self.assertTrue(trades[0]["protection_confirmed"])
        self.assertEqual(1, len(self.fixture.posts("/execution/stops")))

    def test_fill_during_cancel_closes_without_replacement(self):
        self.exhaust()
        self.broker.cancel_behavior = "fill"
        self.trader.ratchet_stops(self.state, 90)
        self.assertFalse(self.trader.position_store.exists())
        self.assertFalse(self.fixture.posts("/execution/stops"))

    def test_partial_fill_during_cancel_protects_only_residual(self):
        self.broker.orders["E1"]["quantity"] = self.broker.orders["E1"]["filled_quantity"] = 130
        self.broker.orders["S1"]["quantity"] = 130
        self.state = self.trader.get_trades_state()[0][0]
        self.exhaust()
        self.broker.cancel_behavior = "partial"
        self.trader.ratchet_stops(self.state, 90)
        self.assertEqual(65, self.state["quantity"])
        self.assertEqual(65, self.state["stops"][-1]["quantity"])

    def test_quote_breached_during_cancel_routes_to_exit_instead_of_lowering_stop(self):
        self.exhaust()

        def fall(method, path, payload):
            if method == "DELETE":
                self.broker.bid = 85

        self.broker.on_submit = fall
        self.trader.ratchet_stops(self.state, 90)
        self.assertIn("breached", self.state["risk_exit_required"])
        self.assertFalse(self.fixture.posts("/execution/stops"))

    def test_lost_replacement_ack_is_recovered_without_another_post(self):
        self.exhaust()
        self.broker.lost_stop_response = True
        self.trader.ratchet_stops(self.state, 90)
        self.assertIn("stop_replacement", self.trader.load_active_position())
        restarted = Trader(self.fixture.path, self.broker)
        state = restarted.get_trades_state()[0][0]
        self.assertTrue(state["protection_confirmed"])
        self.assertNotIn("stop_replacement", state)
        self.assertEqual(1, len(self.fixture.posts("/execution/stops")))

    def test_rejected_replacement_requests_exit_without_reposting(self):
        self.exhaust()
        self.broker.stop_error = dict(error=True, outcome_unknown=False, detail="REJECTED")
        self.trader.ratchet_stops(self.state, 90)
        self.assertIn("rejected", self.state["risk_exit_required"])
        self.trader.get_trades_state()
        self.assertEqual(1, len(self.fixture.posts("/execution/stops")))

    def test_acknowledgement_of_old_trigger_is_not_confirmation_and_is_not_resent(self):
        request = self.broker._request

        def delayed(method, path, payload=None, **kwargs):
            if method == "PATCH":
                self.broker.calls.append((method, path, payload))
                return {"order_id": "S1"}
            return request(method, path, payload, **kwargs)

        with patch.object(self.broker, "_request", side_effect=delayed):
            self.trader.ratchet_stops(self.state, 90)
            self.trader.ratchet_stops(self.state, 95)
        self.assertEqual(1, len([c for c in self.broker.calls if c[0] == "PATCH"]))
        self.assertFalse(self.state["protection_confirmed"])
        self.assertEqual(1, self.state["stops"][0]["modifications"])
        self.broker.orders["S1"]["trigger_price"] = 90
        self.state = self.trader.get_trades_state()[0][0]
        self.trader.ratchet_stops(self.state, 95)
        self.assertEqual(95, self.broker.orders["S1"]["trigger_price"])
        self.assertTrue(self.state["protection_confirmed"])

    def test_unknown_modify_timeout_exits_without_resending_modification(self):
        with patch.object(
            self.broker, "modify_stop_loss", return_value=dict(error=True, outcome_unknown=True)
        ) as modify:
            self.trader.ratchet_stops(self.state, 90)
            later = MarketClock.now_ist() + timedelta(seconds=11)
            with patch.object(MarketClock, "now_ist", return_value=later):
                state = self.trader.get_trades_state()[0][0]
            self.assertIn("timed out", state["risk_exit_required"])
            self.assertEqual(1, modify.call_count)

    def test_triggered_open_stop_is_not_confirmed_protection(self):
        self.broker.orders["S1"]["status"] = "OPEN"
        state = self.trader.get_trades_state()[0][0]
        self.assertFalse(state["protection_confirmed"])
        self.assertIn("triggered", state["risk_exit_required"])

    def test_partial_stop_coverage_does_not_count_as_protected(self):
        self.broker.orders["S1"]["quantity"] = 30
        state = self.trader.get_trades_state()[0][0]
        self.assertFalse(state["protection_confirmed"])
        self.assertIn("quantities", state["risk_exit_required"])

    def test_replacement_cancellation_timeout_requests_exit_without_creating_stop(self):
        self.exhaust()
        self.broker.cancel_behavior = "pending"
        self.trader.ratchet_stops(self.state, 90)
        later = MarketClock.now_ist() + timedelta(seconds=11)
        with patch.object(MarketClock, "now_ist", return_value=later):
            state = self.trader.get_trades_state()[0][0]
        self.assertIn("unconfirmed", state["risk_exit_required"])
        self.assertFalse(self.fixture.posts("/execution/stops"))

    def test_exit_does_not_submit_when_reconciliation_recreates_a_stop(self):
        def reconcile(method, path, payload):
            if method == "DELETE":
                self.broker.add("STOP", "RECON", 65, "TRIGGER_PENDING", "E1", trigger_price=70)

        self.broker.on_submit = reconcile
        result = self.trader.exit_trade("E1", "test exit")
        self.assertEqual("STOPS_REAPPEARED_DURING_EXIT", result["detail"])
        self.assertFalse(self.fixture.posts("/execution/exit"))

    def test_our_reconciliation_reads_do_not_rearm_stops_during_exit(self):
        original = self.broker._request
        observed = []
        self.broker.exit_status = "FILLED"

        def request(method, path, payload=None, **kwargs):
            response = original(method, path, payload, **kwargs)
            if method == "DELETE":
                for _ in range(3):
                    states, _ = self.trader.get_trades_state()
                    observed.append(states[0]["status"])
            return response

        with patch.object(self.broker, "_request", side_effect=request):
            result = self.trader.exit_trade("E1", "test engine-owned exit")
        self.assertEqual("CLOSED", result["status"])
        self.assertEqual(["EXIT_PENDING"] * 3, observed)
        self.assertFalse(self.fixture.posts("/execution/stops"))
        self.assertEqual(1, len(self.fixture.posts("/execution/exit")))

    def test_exit_does_not_cancel_protection_when_quote_is_already_unavailable(self):
        self.broker.quote_error = dict(error=True, detail="unavailable")
        result = self.trader.exit_trade("E1", "test exit")
        self.assertEqual("EXIT_QUOTE_UNAVAILABLE", result["detail"])
        self.assertEqual("TRIGGER_PENDING", self.broker.orders["S1"]["status"])
        self.assertFalse([c for c in self.broker.calls if c[0] == "DELETE"])

    def test_exit_submits_for_both_entry_references_even_if_first_remains_open(self):
        self.broker.add("ENTRY", "E2")
        self.broker.add("STOP", "S2", 65, "TRIGGER_PENDING", "E2", trigger_price=70)
        result = self.trader.exit_trade("E1", "test exit")
        self.assertEqual("EXIT_PENDING", result["status"])
        posts = self.fixture.posts("/execution/exit")
        self.assertEqual({"E1", "E2"}, {p[2]["entry_order_id"] for p in posts})
        self.assertEqual(
            130,
            sum(
                self.broker.orders[o]["quantity"]
                for o in self.broker.orders
                if self.broker.orders[o]["kind"] == "EXIT"
            ),
        )

    def test_quote_validation_rejects_stale_empty_and_mismatched_packets(self):
        original = self.broker.get_contract_quote(self.state["instrument_id"])
        for fields in (
            dict(timestamp=None),
            dict(timestamp=(MarketClock.now_ist() - timedelta(seconds=3)).isoformat()),
            dict(best_bid_qty=0),
            dict(instrument_id="OTHER"),
            dict(status="STALE"),
        ):
            with (
                self.subTest(fields=fields),
                patch.object(self.broker, "get_contract_quote", return_value={**original, **fields}),
            ):
                self.assertFalse(self.trader.refresh_monitor_quote(self.state))

    def test_positions_ltp_cannot_drive_peak_or_override_stale_quote(self):
        self.broker.position_override = dict(
            positions=[dict(symbol="NIFTY-TEST-CE", quantity=65, average_price=100, ltp=999)]
        )
        state = self.trader.get_trades_state()[0][0]
        self.assertEqual(120, state["last_bid"])
        self.assertEqual(120, state["peak_bid"])
        self.broker.quote_error = dict(error=True, detail="unavailable")
        state = self.trader.get_trades_state()[0][0]
        self.assertFalse(state["quote_verified"])
        self.assertEqual(120, state["peak_bid"])
        self.assertTrue(self.trader.state_verified)  # Exposure ledger is still authoritative.

    def test_new_stop_from_another_reconciler_is_adopted_and_raised(self):
        self.exhaust()

        def reconcile(method, path, payload):
            if method == "DELETE":
                self.broker.add("STOP", "RECON", 65, "TRIGGER_PENDING", "E1", trigger_price=70)

        self.broker.on_submit = reconcile
        self.trader.ratchet_stops(self.state, 90)
        self.assertFalse(self.fixture.posts("/execution/stops"))
        self.assertEqual(90, self.broker.orders["RECON"]["trigger_price"])
        self.assertTrue(self.state["protection_confirmed"])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "config/strategies.json").read_text())["strategies"][
            "ai_opportunity_radar"
        ]
        self.now = MarketClock.parse_to_ist("2026-10-21T10:00:00+05:30")
        self.clock = patch.object(MarketClock, "now_ist", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.exits = []
        self.updates = []
        self.monitor = PositionMonitor(
            self.cfg,
            True,
            lambda *a, **kw: self.exits.append(a[1]) or {"status": "CLOSED"},
            lambda state, trigger: self.updates.append(trigger),
        )
        self.state = dict(
            status="OPEN",
            trade_id="UNIT",
            symbol="UNIT-CE",
            entry_price=100,
            last_bid=100,
            peak_bid=100,
            quote_verified=True,
        )

    def tick(self, price):
        self.state.update(last_bid=price, peak_bid=max(self.state["peak_bid"], price))
        self.monitor.manage([self.state], {}, {})

    def test_progressive_floors_and_uncapped_aggressive_runner(self):
        for bid, expected in (
            (120, 110),
            (125, 112.5),
            (130, 120),
            (140, 130),
            (150, 142.5),
            (160, 152),
            (200, 190),
        ):
            self.tick(bid)
            self.assertEqual(expected, self.updates[-1])
            self.assertFalse(self.exits)

    def test_five_percent_tier_remains_active_on_pullback(self):
        self.tick(160)
        self.tick(153)
        self.assertEqual(152, self.updates[-1])
        self.assertFalse(self.exits)
        self.tick(152)
        self.assertIn("RATCHET", self.exits[-1])

    def test_persisted_floor_is_enforced_even_before_runner_activation(self):
        self.state.update(desired_stop_trigger=110, peak_bid=115)
        self.tick(109)
        self.assertIn("PERSISTED", self.exits[-1])

    def test_stale_quote_skips_price_actions_but_not_squareoff(self):
        self.state["quote_verified"] = False
        self.tick(200)
        self.assertFalse(self.updates or self.exits)
        self.now = self.now.replace(hour=15, minute=15)
        self.tick(200)
        self.assertIn("SQUARE-OFF", self.exits[-1])

    def test_late_day_micro_floor_and_preserved_legacy_target(self):
        self.now = self.now.replace(hour=14)
        self.tick(104)
        self.assertEqual(101, self.updates[-1])
        self.cfg["exit"]["profit_target_enabled"] = True
        self.tick(150)
        self.assertIn("PROFIT TARGET", self.exits[-1])

    def test_morning_micro_trail_activation_and_pullback(self):
        self.now = self.now.replace(hour=9, minute=30)
        self.state["entry_time"] = "2026-10-22T09:25:00+05:30"
        self.state["today_entry_number"] = 1
        self.tick(108)
        self.assertFalse(self.updates)
        self.tick(110)
        self.assertEqual(101, self.updates[-1])
        self.tick(115)
        self.assertEqual(103.5, self.updates[-1])
        self.tick(103.5)
        self.assertIn("AI MORNING MICRO-TRAIL", self.exits[-1])

    def test_morning_micro_trail_requires_first_entry_or_explicit_opt_out(self):
        self.now = self.now.replace(hour=9, minute=30)
        self.state["entry_time"] = self.now.replace(minute=25).isoformat()
        for ordinal in (None, 2):
            with self.subTest(ordinal=ordinal):
                self.state["today_entry_number"] = ordinal
                self.tick(115)
                self.assertFalse(self.updates or self.exits)
        self.cfg["exit"]["morning_micro_trail_first_trade_only"] = False
        self.tick(115)
        self.assertEqual([103.5], self.updates)

    def test_historical_trade_morning_floor_uses_recorded_peak_price(self):
        # Exit calculation only: no historical strategy run or AI substitution.
        cfg = StrategyConfig.load_from_config("ai_opportunity_radar", str(ROOT / "config/strategies.json"))
        trade = Trade(1, "UNIT-CE", "CE", 23000, 10, "09:25", 100, peak_price=110)
        self.assertEqual(101, trade.morning_trail_floor(cfg))
        trade.peak_price = 115
        self.assertEqual(103.5, trade.morning_trail_floor(cfg))

    def test_backtest_configuration_uses_the_same_uncapped_aggressive_settings(self):
        cfg = StrategyConfig.load_from_config("ai_opportunity_radar", str(ROOT / "config/strategies.json"))
        self.assertFalse(cfg.profit_target_enabled)
        self.assertTrue(cfg.aggressive_trail_enabled)
        self.assertEqual(50, cfg.aggressive_trail_activation_pct)
        self.assertEqual(5, cfg.aggressive_trail_pullback_pct)

    def test_invalid_aggressive_configuration_is_rejected(self):
        self.cfg["exit"]["aggressive_trail_pullback_pct"] = 20
        with self.assertRaises(ValueError):
            validate_trailing_configuration(self.cfg)


class NativeTrailingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = gateway_fixtures.GatewayTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.trader = self.fixture.trader()
        # Uses the actual mandatory AI consultant and fake HTTP transport.
        self.entry = self.trader.execute_trade(self.fixture.decision(self.trader))
        self.assertEqual("SUCCESS", self.entry["status"])

    def exit_posts(self):
        return [
            c
            for c in self.fixture.server.posts()
            if c[2]["transaction_type"] == "SELL" and c[2]["order_type"] == "LIMIT"
        ]

    def open_exit(self):
        server = self.fixture.server

        def pending(request, timeout):
            response = server(request, timeout)
            if (
                request.get_method() == "POST"
                and b"transaction_type=SELL" in (request.data or b"")
                and b"order_type=LIMIT" in (request.data or b"")
            ):
                server.orders[response.data["order_id"]].update(
                    status="OPEN", filled_quantity=0, average_price=0, price=67
                )
            return response

        with patch("urllib.request.urlopen", side_effect=pending):
            self.assertEqual(
                "EXIT_PENDING", self.trader.exit_trade(self.entry["order_id"], "test exit")["status"]
            )
        state = self.trader.load_active_position()
        state["exits"][0]["modifications"] = 25
        self.trader.save_active_position(state)
        return state["exits"][0]["order_id"]

    def test_definitively_failed_exit_cancel_is_retried_after_restart(self):
        oid = self.open_exit()
        server = self.fixture.server
        saved = []

        def reject_cancel(request, timeout):
            if request.get_method() == "DELETE":
                saved.append(self.trader.load_active_position()["exits"][0]["cancel_requested_at"])
                raise urllib.error.HTTPError(request.full_url, 429, "rate limited", {}, io.BytesIO(b"{}"))
            return server(request, timeout)

        with patch("urllib.request.urlopen", side_effect=reject_cancel):
            result = self.trader.exit_trade(self.entry["order_id"], "resume")
        self.assertEqual("EXIT_PENDING", result["status"])
        self.assertEqual(1, len(saved))
        state = self.trader.load_active_position()
        self.assertNotIn("cancel_requested_at", state["exits"][0])
        self.assertEqual("KITE_HTTP_429", state["exits"][0]["last_cancel_error"])
        self.assertEqual(1, len(self.exit_posts()))
        restarted = self.fixture.trader(self.fixture.restart_gateway())
        self.assertEqual("CLOSED", restarted.exit_trade(self.entry["order_id"], "resume")["status"])
        self.assertEqual("CANCELLED", server.orders[oid]["status"])
        self.assertEqual(2, len(self.exit_posts()))

    def test_uncertain_exit_cancel_waits_then_retries_same_open_order(self):
        oid = self.open_exit()
        server = self.fixture.server
        cancels = []

        def lost_cancel(request, timeout):
            if request.get_method() == "DELETE":
                cancels.append(request.full_url.rsplit("/", 1)[-1])
                raise TimeoutError("cancellation not received")
            return server(request, timeout)

        with patch("urllib.request.urlopen", side_effect=lost_cancel):
            self.trader.exit_trade(self.entry["order_id"], "resume")
            self.fixture.now += timedelta(seconds=5)
            self.trader.exit_trade(self.entry["order_id"], "resume")
        self.assertEqual([oid], cancels)
        self.assertEqual(1, len(self.exit_posts()))
        self.fixture.now += timedelta(seconds=6)
        restarted = self.fixture.trader(self.fixture.restart_gateway())
        self.assertEqual("CLOSED", restarted.exit_trade(self.entry["order_id"], "resume")["status"])
        self.assertEqual("CANCELLED", server.orders[oid]["status"])
        self.assertEqual(2, len(self.exit_posts()))

    def test_fill_after_uncertain_exit_cancel_does_not_create_another_sell(self):
        oid = self.open_exit()
        with patch.object(
            self.fixture.gateway, "cancel_exit_order", return_value=dict(error=True, outcome_unknown=True)
        ):
            self.trader.exit_trade(self.entry["order_id"], "resume")
        self.fixture.server.orders[oid].update(status="COMPLETE", filled_quantity=65, average_price=67)
        self.fixture.now += timedelta(seconds=11)
        self.assertEqual("CLOSED", self.trader.exit_trade(self.entry["order_id"], "resume")["status"])
        self.assertEqual(1, len(self.exit_posts()))

    def test_broker_side_exit_rejections_are_bounded_and_resume_next_cycle(self):
        server = self.fixture.server

        def reject_exit(request, timeout):
            response = server(request, timeout)
            if (
                request.get_method() == "POST"
                and b"transaction_type=SELL" in (request.data or b"")
                and b"order_type=LIMIT" in (request.data or b"")
            ):
                server.orders[response.data["order_id"]].update(
                    status="REJECTED", filled_quantity=0, average_price=0
                )
                # Bound the regression fixture as well as the production behavior.
                if len(self.exit_posts()) > 3:
                    raise AssertionError("Repeated exit submissions in one cycle")
            return response

        with patch("urllib.request.urlopen", side_effect=reject_exit):
            self.assertEqual("EXIT_PENDING", self.trader.exit_trade(self.entry["order_id"], "exit")["status"])
            self.assertEqual(1, len(self.exit_posts()))
            self.assertEqual(
                "EXIT_PENDING", self.trader.exit_trade(self.entry["order_id"], "resume")["status"]
            )
            self.assertEqual(2, len(self.exit_posts()))
        self.assertEqual("CLOSED", self.trader.exit_trade(self.entry["order_id"], "resume")["status"])
        self.assertEqual(3, len(self.exit_posts()))

    def test_daily_entry_number_is_persisted_and_recovered_from_broker_history(self):
        self.assertEqual(1, self.trader.load_active_position()["today_entry_number"])
        self.assertEqual("CLOSED", self.trader.exit_trade(self.entry["order_id"], "close first")["status"])
        restarted = self.fixture.trader(self.fixture.restart_gateway())
        self.fixture.now += timedelta(minutes=1)
        result = restarted.execute_trade(self.fixture.decision(restarted))
        self.assertEqual("SUCCESS", result["status"])
        state = restarted.load_active_position()
        self.assertEqual(2, state["today_entry_number"])
        state.pop("today_entry_number")  # Migrate older position files on restart.
        restarted.save_active_position(state)
        recovered = self.fixture.trader(self.fixture.restart_gateway())
        self.assertEqual(2, recovered.get_trades_state()[0][0]["today_entry_number"])
        self.assertEqual(2, recovered.load_active_position()["today_entry_number"])

    def test_native_replacement_uses_new_id_and_keeps_entry_link(self):
        state = self.trader.get_trades_state()[0][0]
        state["stops"][0]["modifications"] = 25
        self.trader.save_active_position(state)
        self.trader.ratchet_stops(state, 50)
        self.assertNotEqual(self.entry["stop_order_ids"][0], state["stop_order_ids"][0])
        self.assertEqual(self.entry["order_id"], state["stops"][-1]["entry_order_id"])
        self.assertTrue(state["protection_confirmed"])

    def test_broker_modification_limit_response_triggers_verified_replacement(self):
        state = self.trader.get_trades_state()[0][0]
        original = self.fixture.server

        def reject(request, timeout):
            if request.get_method() == "PUT":
                raise urllib.error.HTTPError(
                    request.full_url,
                    400,
                    "limit",
                    {},
                    io.BytesIO(
                        json.dumps(
                            dict(status="error", message="Maximum allowed order modifications exceeded")
                        ).encode()
                    ),
                )
            return original(request, timeout)

        with patch("urllib.request.urlopen", side_effect=reject):
            self.trader.ratchet_stops(state, 50)
        self.assertEqual(25, state["stops"][0]["modifications"])
        self.trader.ratchet_stops(state, 50)
        self.assertTrue(state["protection_confirmed"])
        self.assertEqual("CANCELLED", state["stops"][0]["status"])
        self.assertEqual(0, state["stops"][-1]["modifications"])

    def test_native_exit_uses_quote_refreshed_after_rate_wait(self):
        shifted = []

        def acquire(**kwargs):
            if self.fixture.gateway._check.get() is not None and not shifted:
                shifted.append(True)
                self.fixture.now += timedelta(seconds=3)
                self.fixture.server.quote = dict(
                    last_price=60,
                    timestamp=self.fixture.now.isoformat(),
                    depth=dict(buy=[dict(price=60, quantity=650)], sell=[dict(price=60.05, quantity=650)]),
                )
            return True

        self.fixture.gateway.rate_limiter.acquire = acquire
        self.assertEqual("CLOSED", self.trader.exit_trade(self.entry["order_id"], "test JIT exit")["status"])
        sell = [
            c
            for c in self.fixture.server.posts()
            if c[2]["transaction_type"] == "SELL" and c[2]["order_type"] == "LIMIT"
        ]
        self.assertEqual("59.70", sell[0][2]["price"])

    def test_native_exit_revalidates_quote_after_slow_final_quantity_read(self):
        original = self.fixture.server
        shifted = []

        def slow_position(request, timeout):
            if request.full_url.endswith("/portfolio/positions") and not shifted:
                state = self.trader.load_active_position()
                if any(e["status"] == "SUBMITTING" for e in state.get("exits", [])):
                    shifted.append(True)
                    self.fixture.now += timedelta(seconds=3)
                    original.quote = dict(
                        last_price=60,
                        timestamp=self.fixture.now.isoformat(),
                        depth=dict(
                            buy=[dict(price=60, quantity=650)], sell=[dict(price=60.05, quantity=650)]
                        ),
                    )
            return original(request, timeout)

        with patch("urllib.request.urlopen", side_effect=slow_position):
            self.assertEqual(
                "CLOSED", self.trader.exit_trade(self.entry["order_id"], "test slow read")["status"]
            )
        self.assertTrue(shifted)
        sell = [
            c
            for c in original.posts()
            if c[2]["transaction_type"] == "SELL" and c[2]["order_type"] == "LIMIT"
        ]
        self.assertEqual("59.70", sell[0][2]["price"])

    def test_actual_ai_trade_trails_beyond_fifty_percent_across_multiple_stop_generations(self):
        self.trader.strategy_cfg = json.loads((ROOT / "config/strategies.json").read_text())["strategies"][
            "ai_opportunity_radar"
        ]
        monitor = PositionMonitor(
            self.trader.strategy_cfg, True, self.trader.exit_trade, self.trader.ratchet_stops
        )
        for bid in [80.4] + list(range(81, 201)):
            self.fixture.server.quote = dict(
                last_price=bid,
                timestamp=self.fixture.now.isoformat(),
                depth=dict(buy=[dict(price=bid, quantity=650)], sell=[dict(price=bid + 0.05, quantity=650)]),
            )
            state = self.trader.get_trades_state()[0][0]
            monitor.manage([state], {}, {})
            saved = self.trader.load_active_position()
            self.assertEqual(67, saved["entry_price"])
            self.assertEqual(bid, saved["peak_bid"])
            self.assertTrue(saved["protection_confirmed"])
            self.assertTrue(all(s.get("modifications", 0) <= 25 for s in saved["stops"]))
        self.assertGreaterEqual(len(saved["stops"]), 4)
        self.assertEqual(190, saved["current_stop_trigger"])
        self.assertEqual(65, saved["quantity"])
        self.fixture.server.quote["depth"]["buy"][0]["price"] = 190
        state = self.trader.get_trades_state()[0][0]
        monitor.manage([state], {}, {})
        self.assertFalse(self.trader.position_store.exists())

    def test_pending_native_exit_is_repriced_without_another_sell(self):
        original = self.fixture.server

        def pending(request, timeout):
            if request.get_method() == "PUT" and b"order_type=LIMIT" in (request.data or b""):
                oid = request.full_url.rsplit("/", 1)[-1]
                original.calls.append(("PUT", "/orders/regular/" + oid, {}, timeout))
                original.orders[oid].update(status="COMPLETE", filled_quantity=65)
                return Response({"order_id": oid})
            response = original(request, timeout)
            if (
                request.get_method() == "POST"
                and b"transaction_type=SELL" in (request.data or b"")
                and b"order_type=LIMIT" in (request.data or b"")
            ):
                original.orders[response.data["order_id"]].update(
                    status="OPEN", filled_quantity=0, average_price=0, price=67
                )
            return response

        with patch("urllib.request.urlopen", side_effect=pending):
            self.assertEqual(
                "EXIT_PENDING", self.trader.exit_trade(self.entry["order_id"], "trailing stop")["status"]
            )
            outcome = self.trader.exit_trade(self.entry["order_id"], "resume")
        self.assertEqual("CLOSED", outcome["status"])
        sells = [
            c
            for c in original.posts()
            if c[2]["transaction_type"] == "SELL" and c[2]["order_type"] == "LIMIT"
        ]
        self.assertEqual(1, len(sells))
