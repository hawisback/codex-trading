"""Frozen hybrid risk bounds across CLI, restart, broker ratchet and entry quotes."""

import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import ai_consultant as ac
from entry_policy import EntryBlocked, EntryPolicy, validate_invalidation
from market_clock import MarketClock
from test_self_healing_exit import approved_decision
from tests.scenarios import ROOT, make_trader
from trading.domain.stop_loss import configured_stop_policy, stop_price_band
from trading.configuration import load_configuration


class HybridStopPolicyTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix=".hybrid-stop-", dir=ROOT)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.now = MarketClock.parse_to_ist("2026-10-28T11:00:00+05:30")
        patches = [patch.object(MarketClock, "now_ist", side_effect=lambda: self.now)]
        patches += [
            patch.object(ac, name, self.root / filename)
            for name, filename in (
                ("PENDING_SL_FILE_JSON", "pending.json"),
                ("PENDING_SL_FILE_MD", "pending.md"),
                ("SL_VERDICT_FILE", "verdict.json"),
            )
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.cfg = json.loads((ROOT / "config/strategies.json").read_text())["strategies"]["macd_momentum"]
        self.consultant = ac.AIConsultant(mode="chat", strategy_config=self.cfg)
        self.ctx = dict(
            spot=23000,
            session_vwap=22990,
            ema_9=23000,
            ema_20=22995,
            candles_1m=[
                dict(start_time=self.now.isoformat(), open=22999, high=23008, low=22992, close=23000)
            ],
        )
        self.calls = []

    def trade(self, direction="CE"):
        return dict(
            status="OPEN",
            trade_id="E1",
            symbol="NIFTY-TEST-" + direction,
            setup_type="MACD_2M_MOMENTUM",
            quantity=130,
            entry_price=100,
            invalidation_level=22975 if direction == "CE" else 23025,
            protection_confirmed=True,
            stops=[dict(status="TRIGGER_PENDING", quantity=130, trigger_price=75)],
        )

    def request(self, trade):
        self.consultant.request_stop_loss_consultation(trade, self.ctx, self.ratchet, lambda t: None)

    def ratchet(self, trade, target):
        self.calls.append(target)

    def respond(self, trade, price=82, level=None):
        ac.submit_stop_loss_verdict(trade["ai_stop_request_id"], price, level)

    def poll(self, trade, consultant=None):
        return (consultant or self.consultant).poll_stop_loss_verdict(trade, self.ratchet, lambda t: None)

    def test_cli_rejects_out_of_band_stops_and_eight_point_spot_invalidations(self):
        for direction, too_close in (("CE", 22992), ("PE", 23008)):
            trade = self.trade(direction)
            self.request(trade)
            for price, level in ((79.95, None), (85.05, None), (82, too_close)):
                with (
                    self.subTest(direction=direction, price=price, level=level),
                    self.assertRaises(ValueError),
                ):
                    self.respond(trade, price, level)
                self.assertNotIn("ai_stop_price", trade)
                self.assertEqual(75, trade["stops"][0]["trigger_price"])
                self.assertFalse(ac.SL_VERDICT_FILE.exists())

    def test_file_responses_cannot_bypass_bounds_or_mutate_protection(self):
        trade = self.trade()
        self.request(trade)
        original = copy.deepcopy(trade)
        for price, level in ((82, 22992), (90, 22975), (75, 22975)):
            ac.atomic_save(
                ac.SL_VERDICT_FILE,
                dict(
                    request_id=trade["ai_stop_request_id"],
                    trade_id="E1",
                    submitted_at=self.now.isoformat(),
                    ai_stop_price=price,
                    spot_invalidation_level=level,
                ),
            )
            self.assertIsNone(self.poll(trade))
            self.assertEqual(original, trade)
        self.assertFalse(self.calls)

    def test_valid_band_endpoints_preserve_buffer_for_calls_and_puts(self):
        for direction in ("CE", "PE"):
            for price in (80, 82, 85):
                trade = self.trade(direction)
                self.request(trade)
                self.respond(trade, price, trade["invalidation_level"])
                self.assertIsNotNone(self.poll(trade))
                self.assertEqual(price, trade["ai_stop_price"])
                self.assertEqual(22975 if direction == "CE" else 23025, trade["invalidation_level"])
                self.assertEqual("APPLYING", trade["ai_stop_status"])

    def test_restart_uses_frozen_policy_even_if_configuration_and_spot_change(self):
        trade = self.trade()
        self.request(trade)
        recovered = json.loads(json.dumps(trade))
        changed = copy.deepcopy(self.cfg)
        changed["entry"]["min_invalidation_buffer_pts"] = 5
        changed["exit"]["post_fill_stop_loss"] = dict(min_loss_pct=5, max_loss_pct=25)
        restarted = ac.AIConsultant(mode="chat", strategy_config=changed)
        self.ctx["spot"] = 24000
        ac.atomic_save(
            ac.SL_VERDICT_FILE,
            dict(
                request_id=trade["ai_stop_request_id"],
                trade_id="E1",
                submitted_at=self.now.isoformat(),
                ai_stop_price=90,
                spot_invalidation_level=22995,
            ),
        )
        self.assertIsNone(self.poll(recovered, restarted))
        self.respond(recovered, 82, 22975)
        self.assertIsNotNone(self.poll(recovered, restarted))
        self.assertEqual(25, recovered["stop_loss_policy"]["min_invalidation_buffer_pts"])

    def test_timeout_retains_initial_broker_stop_and_entry_structure(self):
        trade = self.trade()
        self.request(trade)
        self.now += timedelta(seconds=45)
        self.assertIsNone(self.poll(trade))
        self.assertEqual("TIMEOUT_BASELINE_RETAINED", trade["ai_stop_status"])
        self.assertEqual(75, trade["stops"][0]["trigger_price"])
        self.assertEqual(22975, trade["invalidation_level"])
        self.assertFalse(self.calls)

    def test_existing_tighter_option_and_legacy_structural_protection_never_loosen(self):
        trade = self.trade()
        trade.update(desired_stop_trigger=105, invalidation_level=22992)
        self.request(trade)
        self.respond(trade, 82, 22992)
        self.poll(trade)
        self.assertEqual(105, trade["ai_stop_price"])
        self.assertEqual(22992, trade["invalidation_level"])

    def test_deterministic_refinement_obeys_configured_band_and_structural_buffer(self):
        for direction in ("CE", "PE"):
            trade = self.trade(direction)
            rules = ac.AIConsultant(mode="rules", strategy_config=self.cfg)
            rules.request_stop_loss_consultation(trade, self.ctx, self.ratchet, lambda t: None)
            self.assertGreaterEqual(trade["ai_stop_price"], 80)
            self.assertLessEqual(trade["ai_stop_price"], 85)
            self.assertEqual(22975 if direction == "CE" else 23025, trade["invalidation_level"])
        lower, upper = stop_price_band(82.12, configured_stop_policy(self.cfg))
        self.assertEqual((65.70, 69.80), (lower, upper))

    def test_real_broker_stop_arms_at_twenty_five_percent_then_confirms_valid_refinement(self):
        trader = make_trader(self.root / "active.json", "macd_momentum")
        trader.client.fill_price = trader.client.quote_ask = 100
        decision = approved_decision(
            trader.trading_cfg,
            100,
            signal="BUY_CE",
            setup_type="MACD_2M_MOMENTUM",
            invalidation_level=22975,
            stop_loss_policy=configured_stop_policy(self.cfg),
        )
        decision["stop_loss_context"] = copy.deepcopy(self.ctx)
        trader.client.spot_price = 23000
        self.assertEqual("SUCCESS", trader.execute_trade(decision)["status"])
        trade = trader.load_active_position()
        self.assertTrue(trade["protection_confirmed"])
        self.assertEqual(75, trade["stops"][0]["trigger_price"])
        self.consultant.request_stop_loss_consultation(
            trade, {}, trader.ratchet_stops, trader.save_active_position
        )
        self.assertEqual(23000, trade["ai_stop_dossier"]["current_spot"])
        self.respond(trade, 82, 22975)
        self.consultant.poll_stop_loss_verdict(trade, trader.ratchet_stops, trader.save_active_position)
        self.assertEqual("ARMED", trade["ai_stop_status"])
        self.assertEqual(82, trade["stops"][0]["trigger_price"])
        self.assertEqual(22975, trader.load_active_position()["invalidation_level"])

    def test_last_moment_spot_quotes_must_preserve_twenty_five_point_buffer(self):
        policy = configured_stop_policy(self.cfg)
        for signal, level, spot in (("BUY_CE", 22975, 22993), ("BUY_PE", 23025, 23007)):
            decision = dict(signal=signal, invalidation_level=level, stop_loss_policy=policy)
            quote = dict(
                instrument_id="INST-NIFTY-INDEX",
                last_price=spot,
                timestamp=self.now.isoformat(),
                request_started_monotonic=ac.time.monotonic(),
            )
            with self.subTest(signal=signal), self.assertRaisesRegex(EntryBlocked, "BUFFER_TOO_SMALL"):
                validate_invalidation(decision, quote, EntryPolicy())

    def test_execution_blocks_buffer_shortfall_and_freezes_final_spot_for_consultation(self):
        trader = make_trader(self.root / "jit.json", "macd_momentum")
        trader.client.fill_price = trader.client.quote_ask = 100
        trader.client.spot_price = 22993
        decision = approved_decision(
            trader.trading_cfg,
            100,
            signal="BUY_CE",
            setup_type="MACD_2M_MOMENTUM",
            invalidation_level=22975,
            stop_loss_policy=configured_stop_policy(self.cfg),
        )
        decision["stop_loss_context"] = copy.deepcopy(self.ctx)
        result = trader.execute_trade(decision)
        self.assertEqual("ENTRY_STRUCTURE_BUFFER_TOO_SMALL", result["detail"])
        self.assertFalse(any(call[0] == "POST" for call in trader.client.calls))
        self.assertFalse(trader.position_store.exists())
        decision = approved_decision(
            trader.trading_cfg,
            100,
            signal="BUY_CE",
            setup_type="MACD_2M_MOMENTUM",
            invalidation_level=22960,
            stop_loss_policy=configured_stop_policy(self.cfg),
        )
        decision["stop_loss_context"] = copy.deepcopy(self.ctx)
        self.assertEqual("SUCCESS", trader.execute_trade(decision)["status"])
        trade = trader.load_active_position()
        self.consultant.request_stop_loss_consultation(
            trade, {}, trader.ratchet_stops, trader.save_active_position
        )
        self.assertEqual(22993, trade["ai_stop_dossier"]["current_spot"])
        with self.assertRaises(ValueError):
            self.respond(trade, 82, 22975)
        self.respond(trade, 82, 22968)
        self.consultant.poll_stop_loss_verdict(trade, trader.ratchet_stops, trader.save_active_position)
        self.assertEqual(22968, trade["invalidation_level"])

    def test_invalid_policy_configuration_is_rejected(self):
        for value in (float("nan"), -1, 31, True):
            config = copy.deepcopy(self.cfg)
            config["exit"]["post_fill_stop_loss"]["max_loss_pct"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                ac.AIConsultant(mode="chat", strategy_config=config)

    def test_approved_risk_policy_cannot_be_removed_or_replaced_before_execution(self):
        trader = make_trader(self.root / "policy-bound.json", "macd_momentum")
        decision = approved_decision(
            trader.trading_cfg,
            100,
            signal="BUY_CE",
            setup_type="MACD_2M_MOMENTUM",
            invalidation_level=22975,
            stop_loss_policy=configured_stop_policy(self.cfg),
        )
        for remove in (True, False):
            changed = copy.deepcopy(decision)
            if remove:
                changed.pop("stop_loss_policy")
            else:
                changed["stop_loss_policy"]["min_invalidation_buffer_pts"] = 5
            self.assertEqual("AI_ENTRY_RISK_POLICY_MISMATCH", trader.execute_trade(changed)["detail"])
        self.assertFalse(any(call[0] == "POST" for call in trader.client.calls))

    def test_missing_requested_hybrid_profile_cannot_start_another_strategy(self):
        with tempfile.TemporaryDirectory(prefix=".hybrid-config-", dir=ROOT) as directory:
            with self.assertRaisesRegex(ValueError, "requested macd_momentum profile is missing"):
                load_configuration("macd_momentum", "chat", root=Path(directory), environ={})
