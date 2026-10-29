"""Offline stop-consultation failure cases; all files stay in temporary workspace directories."""

import copy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import ai_consultant as ac
from market_clock import MarketClock
from nifty_trader_scheduler import NiftyOptionsTrader
from test_self_healing_exit import approved_decision
from tests.scenarios import make_trader, market_responses, NOW
from tools import watch_consultation as watcher
from trading.application.market_context import MarketContextService
from trading.application.position_monitor import PositionMonitor
from trading.domain.stop_loss import stop_loss_context

ROOT = Path(__file__).resolve().parents[1]


class StopLossConsultationTests(unittest.TestCase):
    def start_patch(self, patcher):
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix=".stop-consult-test-", dir=ROOT)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.paths = {
            "PENDING_SL_FILE_JSON": self.root / "pending_stop_loss.json",
            "PENDING_SL_FILE_MD": self.root / "pending_stop_loss.md",
            "SL_VERDICT_FILE": self.root / "ai_stop_verdict.json",
        }
        self.start_patch(patch.multiple(ac, **self.paths))
        self.now = MarketClock.parse_to_ist(NOW)
        self.start_patch(patch.object(MarketClock, "now_ist", side_effect=lambda: self.now))
        responses = market_responses()
        self.ctx = MarketContextService(lambda path, **kw: responses[path], lambda: {}).fetch(
            monitor_only=True
        )
        self.trade = {
            "trade_id": "E1",
            "entry_order_id": "E1",
            "symbol": "NIFTY-TEST-CE",
            "entry_price": 82.12,
            "quantity": 130,
            "status": "OPEN",
            "protection_confirmed": True,
            "stops": [{"status": "TRIGGER_PENDING", "quantity": 130, "trigger_price": 57.5}],
        }
        self.consultant = ac.AIConsultant(mode="chat", timeout_seconds=45)
        self.ratchet = MagicMock()
        self.save = MagicMock()

    def publish(self):
        self.consultant.request_stop_loss_consultation(self.trade, self.ctx, self.ratchet, self.save)

    def respond(self, **changes):
        payload = {
            "request_id": self.trade["ai_stop_request_id"],
            "trade_id": self.trade["trade_id"],
            "submitted_at": self.now.isoformat(),
            "ai_stop_price": 68.5,
            "spot_invalidation_level": 22985.0,
        }
        payload.update(changes)
        ac.SL_VERDICT_FILE.write_text(json.dumps(payload), encoding="utf-8")

    def poll(self):
        return self.consultant.poll_stop_loss_verdict(self.trade, self.ratchet, self.save)

    def test_live_context_supplies_complete_candle_and_real_fill(self):
        self.publish()
        payload = json.loads(ac.PENDING_SL_FILE_JSON.read_text())
        dossier = payload["dossier"]
        candle = self.ctx["candles_1m"][-1]
        for part in ("open", "high", "low", "close"):
            self.assertEqual(candle[part], dossier["trigger_candle_" + part])
        self.assertEqual(82.12, dossier["fill_price"])
        self.assertEqual(payload["request_id"], dossier["request_id"])
        self.assertIn("--request-id " + payload["request_id"], ac.PENDING_SL_FILE_MD.read_text())
        self.ratchet.assert_not_called()

    def test_entry_snapshot_survives_execution_and_later_context_changes(self):
        trader = make_trader(self.root / "active.json")
        snapshot = stop_loss_context(self.ctx)
        decision = approved_decision(trader.trading_cfg)
        decision["stop_loss_context"] = snapshot
        self.assertEqual("SUCCESS", trader.execute_trade(decision)["status"])
        state = trader.load_active_position()
        self.assertEqual(snapshot, state["entry_market_context"])
        snapshot["candle_low"] = 1
        self.ctx["spot"] = 24000
        self.consultant.request_stop_loss_consultation(
            state, self.ctx, trader.ratchet_stops, trader.save_active_position
        )
        self.assertEqual("ENTRY_SNAPSHOT", state["ai_stop_dossier"]["context_source"])
        self.assertNotEqual(24000, state["ai_stop_dossier"]["current_spot"])
        self.assertNotEqual(1, state["ai_stop_dossier"]["trigger_candle_low"])

    def test_missing_context_defers_for_both_option_directions_then_retries(self):
        for direction in ("CE", "PE"):
            with self.subTest(direction=direction):
                trade = copy.deepcopy(self.trade)
                trade["symbol"] = "NIFTY-TEST-" + direction
                consultant = ac.AIConsultant(mode="rules")
                consultant.request_stop_loss_consultation(trade, {}, self.ratchet, self.save)
                self.assertNotIn("ai_stop_status", trade)
                self.assertNotIn("invalidation_level", trade)
                consultant.request_stop_loss_consultation(trade, self.ctx, self.ratchet, self.save)
                reference = self.ctx["candles_1m"][-1]["low" if direction == "CE" else "high"]
                self.assertEqual(round(reference, 1), trade["invalidation_level"])
                self.assertEqual("APPLYING", trade["ai_stop_status"])

    def test_invalid_context_never_manufactures_structure(self):
        for value in (0, None, float("nan"), float("inf"), True):
            with self.subTest(value=value):
                ctx = dict(self.ctx, spot=value)
                self.assertIsNone(stop_loss_context(ctx))
        ctx = copy.deepcopy(self.ctx)
        ctx["candles_1m"][-1]["low"] = 99999
        self.assertIsNone(stop_loss_context(ctx))

    def test_consultation_waits_for_confirmed_baseline_protection(self):
        self.trade["protection_confirmed"] = False
        self.publish()
        self.assertNotIn("ai_stop_status", self.trade)
        self.assertFalse(ac.PENDING_SL_FILE_JSON.exists())

    def test_poll_is_nonblocking_and_valid_verdict_waits_for_confirmation(self):
        self.publish()
        with patch.object(ac.time, "sleep", side_effect=AssertionError("Blocking poll")):
            self.assertIsNone(self.poll())
            self.respond()
            verdict = self.poll()
        self.assertEqual(68.5, verdict.ai_stop_price)
        self.assertEqual("APPLYING", self.trade["ai_stop_status"])
        self.ratchet.assert_called_once_with(self.trade, 68.5)
        self.assertFalse(ac.PENDING_SL_FILE_JSON.exists())
        self.assertFalse(ac.SL_VERDICT_FILE.exists())
        self.trade["stops"][0]["trigger_price"] = 68.5
        self.consultant.confirm_stop_loss(self.trade, self.save)
        self.assertEqual("ARMED", self.trade["ai_stop_status"])

    def test_rejects_wrong_missing_and_stale_identity(self):
        self.publish()
        cases = (
            {"trade_id": "OLD-E0"},
            {"request_id": "OLD-R0"},
            {"request_id": None},
            {"submitted_at": (self.now - timedelta(seconds=1)).isoformat()},
            {"submitted_at": (self.now + timedelta(seconds=1)).isoformat()},
            {"submitted_at": self.now.replace(tzinfo=None).isoformat()},
            {"ai_stop_price": float("nan")},
            {"ai_stop_price": float("inf")},
            {"ai_stop_price": -1},
            {"spot_invalidation_level": 0},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                self.respond(**changes)
                self.assertIsNone(self.poll())
                self.assertEqual("PENDING", self.trade["ai_stop_status"])
                self.assertNotIn("ai_stop_price", self.trade)
        self.ratchet.assert_not_called()

    def test_malformed_or_partial_json_is_retried(self):
        self.publish()
        ac.SL_VERDICT_FILE.write_text('{"ai_stop_price":', encoding="utf-8")
        self.assertIsNone(self.poll())
        self.respond()
        self.assertIsNotNone(self.poll())

    def test_timeout_uses_configured_deadline_and_rejects_late_verdict(self):
        self.publish()
        self.now += timedelta(seconds=45)
        self.respond()
        self.assertIsNone(self.poll())
        self.assertEqual("TIMEOUT_BASELINE_RETAINED", self.trade["ai_stop_status"])
        self.assertNotIn("ai_stop_price", self.trade)
        self.assertFalse(ac.PENDING_SL_FILE_JSON.exists())
        self.ratchet.assert_not_called()

    def test_restart_recovers_interrupted_publication_with_same_request(self):
        with patch.object(ac, "atomic_save", side_effect=OSError("disk busy")):
            with self.assertRaises(OSError):
                self.publish()
        identity = self.trade["ai_stop_request_id"]
        self.assertEqual("PENDING", self.trade["ai_stop_status"])
        self.assertIsNone(self.poll())
        self.assertEqual(identity, json.loads(ac.PENDING_SL_FILE_JSON.read_text())["request_id"])
        self.respond()
        self.assertIsNotNone(self.poll())

    def test_failed_intent_save_keeps_verdict_for_restart(self):
        self.publish()
        self.respond()
        with self.assertRaises(OSError):
            self.consultant.poll_stop_loss_verdict(
                self.trade, self.ratchet, MagicMock(side_effect=OSError("disk"))
            )
        self.assertTrue(ac.SL_VERDICT_FILE.exists())
        self.ratchet.assert_not_called()

    def test_raises_after_durable_intent_leave_applying_for_retry(self):
        self.publish()
        self.respond()
        self.ratchet.side_effect = OSError("broker unavailable")
        with self.assertRaises(OSError):
            self.poll()
        self.assertEqual("APPLYING", self.trade["ai_stop_status"])
        self.assertFalse(ac.PENDING_SL_FILE_JSON.exists())
        self.ratchet.side_effect = None
        owner = SimpleNamespace(
            ai_consultant=self.consultant, ratchet_stops=self.ratchet, save_active_position=self.save
        )
        NiftyOptionsTrader._check_ai_stop_loss(owner, self.trade, {})
        self.assertEqual(2, self.ratchet.call_count)
        self.assertEqual("APPLYING", self.trade["ai_stop_status"])

    def test_existing_option_and_structural_floors_never_loosen(self):
        self.publish()
        self.trade.update(desired_stop_trigger=75, invalidation_level=22995)
        self.respond()
        self.poll()
        self.assertEqual(75, self.trade["ai_stop_price"])
        self.assertEqual(22995, self.trade["invalidation_level"])
        self.ratchet.assert_called_once_with(self.trade, 75)

    def test_verdict_below_baseline_cannot_lower_broker_floor(self):
        self.publish()
        self.respond(ai_stop_price=40)
        self.poll()
        self.assertEqual(57.5, self.trade["ai_stop_price"])
        self.assertEqual(57.5, self.trade["desired_stop_trigger"])

    def test_put_structural_invalidation_cannot_be_loosened(self):
        self.trade.update(symbol="NIFTY-TEST-PE", invalidation_level=23010)
        self.publish()
        self.respond(spot_invalidation_level=23030)
        self.poll()
        self.assertEqual(23010, self.trade["invalidation_level"])

    def test_actual_broker_ratchet_confirms_subthreshold_improvement(self):
        trader = make_trader(self.root / "active.json")
        self.assertEqual("SUCCESS", trader.execute_trade(approved_decision(trader.trading_cfg))["status"])
        state = trader.load_active_position()
        self.consultant.request_stop_loss_consultation(
            state, self.ctx, trader.ratchet_stops, trader.save_active_position
        )
        target = state["stops"][0]["trigger_price"] + 0.05
        ac.submit_stop_loss_verdict(state["ai_stop_request_id"], target)
        self.consultant.poll_stop_loss_verdict(state, trader.ratchet_stops, trader.save_active_position)
        self.assertEqual("ARMED", state["ai_stop_status"])
        self.assertEqual(target, state["stops"][0]["trigger_price"])
        self.assertTrue(state["protection_confirmed"])

    def test_unconfirmed_modification_cannot_be_reported_armed(self):
        self.trade.update(ai_stop_status="APPLYING", ai_stop_price=68.5)
        self.trade["stops"][0].update(trigger_price=68.5, pending_modification={"trigger_price": 68.5})
        self.consultant.confirm_stop_loss(self.trade, self.save)
        self.assertEqual("APPLYING", self.trade["ai_stop_status"])
        self.trade["stops"][0].pop("pending_modification")
        self.trade["stops"][0]["quantity"] = 65
        self.consultant.confirm_stop_loss(self.trade, self.save)
        self.assertEqual("APPLYING", self.trade["ai_stop_status"])

    def test_cli_requires_current_identity_and_writes_correlated_payload(self):
        self.publish()
        for request_id in (None, "OLD-R0"):
            with self.assertRaises(ValueError):
                ac.submit_stop_loss_verdict(request_id, 68.5)
        self.assertFalse(ac.SL_VERDICT_FILE.exists())
        payload = ac.submit_stop_loss_verdict(self.trade["ai_stop_request_id"], 68.5, 22985)
        self.assertEqual(self.trade["trade_id"], payload["trade_id"])
        self.assertIsNotNone(self.poll())

    def test_cli_rejects_expired_requests_without_writing_verdict(self):
        self.publish()
        self.now += timedelta(seconds=45)
        with self.assertRaises(ValueError):
            ac.submit_stop_loss_verdict(self.trade["ai_stop_request_id"], 68.5)
        self.assertFalse(ac.SL_VERDICT_FILE.exists())

    def test_consultation_io_failure_still_runs_position_management(self):
        managed = MagicMock()
        owner = SimpleNamespace(
            state_verified=True,
            fetch_market_context=lambda **kw: self.ctx,
            refresh_monitor_quote=lambda *a, **kw: True,
            save_active_position=self.save,
            _check_ai_stop_loss=MagicMock(side_effect=OSError("disk busy")),
            manage_open_trades=managed,
            position_store=SimpleNamespace(exists=lambda: True),
            _timed_call=lambda stage, function, *args, **kw: function(*args, **kw),
        )
        result = NiftyOptionsTrader.run_monitor_cycle(owner, [self.trade])
        managed.assert_called_once_with([self.trade], self.ctx, {})
        self.assertTrue(result["has_open_trades"])

    def test_monitor_exits_for_option_floor_and_both_spot_directions(self):
        for direction, bid, spot, expected in (
            ("CE", 67, 23000, "STOP LOSS"),
            ("CE", 80, 22984, "INVALIDATION"),
            ("PE", 80, 23001, "INVALIDATION"),
        ):
            with self.subTest(direction=direction, bid=bid):
                trade = copy.deepcopy(self.trade)
                trade.update(
                    symbol="NIFTY-TEST-" + direction,
                    last_bid=bid,
                    ai_stop_price=68.5,
                    invalidation_level=22985 if direction == "CE" else 23000,
                )
                exit_trade = MagicMock(return_value={"status": "CLOSED"})
                PositionMonitor({"exit": {"initial_stop_pct": 30}}, True, exit_trade, self.ratchet).manage(
                    [trade], {"spot": spot}, {}
                )
                self.assertIn(expected, exit_trade.call_args.args[1])

    def test_restarted_watcher_detects_existing_pending_stop(self):
        self.publish()
        payload = json.loads(ac.PENDING_SL_FILE_JSON.read_text())
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        ac.PENDING_SL_FILE_JSON.write_text(json.dumps(payload))
        with (
            patch.object(watcher, "PENDING_SL_FILE", ac.PENDING_SL_FILE_JSON),
            patch.object(watcher, "PENDING_FILE", self.root / "entry.json"),
            patch.object(watcher.time, "sleep", side_effect=AssertionError("Missed existing request")),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(0, watcher.watch(timeout_seconds=1))

    def test_watcher_ignores_stale_and_partial_requests(self):
        self.publish()
        payload = json.loads(ac.PENDING_SL_FILE_JSON.read_text())
        payload["created_at"] = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        ac.PENDING_SL_FILE_JSON.write_text(json.dumps(payload))
        self.assertIsNone(watcher.read_pending(ac.PENDING_SL_FILE_JSON, "AWAITING_STOP_LOSS"))
        ac.PENDING_SL_FILE_JSON.write_text("{")
        self.assertIsNone(watcher.read_pending(ac.PENDING_SL_FILE_JSON, "AWAITING_STOP_LOSS"))

    def test_watcher_rearms_for_second_event_and_detects_existing_entry(self):
        path = self.root / "entry.json"
        path.write_text(
            json.dumps(
                {
                    "status": "AWAITING_VERDICT",
                    "request_id": "ENTRY-R1",
                    "candidate_id": "CANDIDATE-C1",
                    "timeout_seconds": 45,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "dossier": {},
                }
            )
        )
        with (
            patch.object(watcher, "PENDING_SL_FILE", ac.PENDING_SL_FILE_JSON),
            patch.object(watcher, "PENDING_FILE", path),
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(0, watcher.watch(timeout_seconds=1))
            path.unlink()
            self.publish()
            payload = json.loads(ac.PENDING_SL_FILE_JSON.read_text())
            payload["created_at"] = datetime.now(timezone.utc).isoformat()
            ac.PENDING_SL_FILE_JSON.write_text(json.dumps(payload))
            self.assertEqual(0, watcher.watch(timeout_seconds=1))
