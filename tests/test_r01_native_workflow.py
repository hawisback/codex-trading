"""R01 OMS integration with fake HTTP/funds evidence and the actual consultant.

These fixtures prove offline workflow behavior, not native broker P&L or
instrument-master integration. No fixture can reach a real broker.
"""

import copy
import json
from datetime import timedelta
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import test_gateways as fixtures
from trading.application.position_monitor import PositionMonitor
from trading.adapters.entry_controls import read_entry_control_block
from trading.domain.pretrade_evidence import entry_control_block
from trading.domain.unified_stop_workflow import R01_STOP_VERSION


class R01NativeWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GatewayTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.funds = dict(
            account_id="TEST_ACCOUNT",
            source="offline:normalized-funds-fixture",
            funds_asof=self.fixture.now.isoformat(),
            available_margin=20000,
            max_single_order_quantity=130,
            expiry_sessions_remaining=3,
            pnl_account_id="TEST_ACCOUNT",
            pnl_session_date=self.fixture.now.date().isoformat(),
            pnl_asof=self.fixture.now.isoformat(),
            realized_pnl_today=0,
            unrealized_pnl_today=0,
        )
        self.trader = self.prepare_trader(self.fixture.gateway)

    def prepare_trader(self, gateway, *, enabled=True):
        funds = patch.object(gateway, "_fetch_broker_funds", side_effect=lambda: copy.deepcopy(self.funds))
        funds.start()
        self.addCleanup(funds.stop)
        entry_funds = patch.object(
            gateway, "get_entry_funds", side_effect=lambda _: copy.deepcopy(self.funds)
        )
        entry_funds.start()
        self.addCleanup(entry_funds.stop)
        trader = self.fixture.trader(gateway, qty=130)
        trader.trading_cfg.update(
            r01_policy=dict(enabled=enabled, unified_stop_enabled=True, price_only_veto_disabled=True),
            risk=dict(option_hard_stop_pct=25),
        )
        return trader

    def enter(self):
        result = self.trader.execute_trade(self.fixture.decision(self.trader))
        self.assertEqual("SUCCESS", result["status"], result)
        return result

    def quote(self, bid):
        self.fixture.server.quote = dict(
            last_price=bid,
            timestamp=self.fixture.now.isoformat(),
            depth=dict(buy=[dict(price=bid, quantity=650)], sell=[dict(price=bid + 0.05, quantity=650)]),
        )

    def monitor(self):
        states, _ = self.trader.get_trades_state()
        self.assertTrue(self.trader.state_verified, self.trader.last_reconciliation_error)
        return PositionMonitor(
            self.trader.strategy_cfg,
            True,
            self.trader.exit_trade,
            self.trader.ratchet_stops,
            self.trader.save_active_position,
            self.trader.trading_cfg,
        ).manage(states, {}, {})

    def test_initial_stop_and_ratchet_survive_restart_and_disabled_entry_flag(self):
        result = self.enter()
        self.assertEqual("130", self.fixture.server.posts()[0][2]["quantity"])
        stop_id = result["stop_order_ids"][0]
        self.assertEqual(50.25, self.fixture.server.orders[stop_id]["trigger_price"])
        self.quote(77.05)  # +15% peak in the morning protects +10%.
        self.monitor()
        self.assertEqual(73.7, self.fixture.server.orders[stop_id]["trigger_price"])
        self.trader = self.prepare_trader(self.fixture.restart_gateway(), enabled=False)
        self.trader.trading_cfg["risk"]["option_hard_stop_pct"] = 99
        states, _ = self.trader.get_trades_state()
        self.assertTrue(self.trader.state_verified)
        self.assertEqual(R01_STOP_VERSION, states[0]["r01_policy_version"])
        self.assertEqual(25, states[0]["r01_initial_stop_pct"])
        self.assertEqual(73.7, states[0]["current_stop_trigger"])
        self.quote(73)
        self.assertEqual([], self.monitor())
        self.assertEqual(
            0,
            sum(
                order["filled_quantity"] * (1 if order["transaction_type"] == "BUY" else -1)
                for order in self.fixture.server.orders.values()
            ),
        )

    def test_missing_funds_or_day_ledger_never_reaches_buy_transport(self):
        original = self.funds.copy()
        for key in original:
            with self.subTest(missing=key):
                self.funds = {name: value for name, value in original.items() if name != key}
                result = self.trader.execute_trade(self.fixture.decision(self.trader))
                self.assertTrue(result.get("error"), result)
                self.assertFalse(self.fixture.server.posts())

    def test_loss_threshold_blocks_entry_but_does_not_block_existing_exit(self):
        self.funds["realized_pnl_today"] = -6000
        result = self.trader.execute_trade(self.fixture.decision(self.trader))
        self.assertEqual("DAILY_LOSS_LIMIT", result["detail"])
        self.assertFalse(self.fixture.server.posts())
        self.funds["realized_pnl_today"] = 0
        entry = self.enter()
        self.funds.clear()
        self.assertEqual("CLOSED", self.trader.exit_trade(entry["order_id"], "test risk exit")["status"])

    def test_pacing_cannot_transmit_after_funds_proof_expires(self):
        self.funds["funds_asof"] = (self.fixture.now - timedelta(seconds=59)).isoformat()

        def delayed(**kwargs):
            if self.fixture.server.calls[-1][1] == "/quote":
                self.fixture.now += timedelta(seconds=2)
            return True

        self.fixture.gateway.rate_limiter.acquire = delayed
        result = self.trader.execute_trade(self.fixture.decision(self.trader))
        self.assertEqual("BROKER_SNAPSHOT_STALE", result["detail"])
        self.assertFalse(self.fixture.server.posts())

    def test_affordable_one_lot_has_one_lot_budget_and_breach_does_not_force_exit(self):
        self.funds["available_margin"] = 5000
        self.funds["realized_pnl_today"] = -3000
        result = self.trader.execute_trade(self.fixture.decision(self.trader))
        self.assertEqual("DAILY_LOSS_LIMIT", result["detail"])
        self.assertFalse(self.fixture.server.posts())
        self.funds["realized_pnl_today"] = -2999
        self.enter()
        states, _ = self.trader.get_trades_state()
        self.assertEqual(65, states[0]["quantity"])
        self.assertEqual("3000", states[0]["entry_execution"]["daily_risk"]["limit_inr"])
        self.funds["realized_pnl_today"] = -4000
        self.quote(67)
        self.assertTrue(self.monitor())
        self.assertEqual(
            1, len([post for post in self.fixture.server.posts() if post[2]["order_type"] == "LIMIT"])
        )

    def test_partial_stop_fill_during_r01_exit_sells_only_residual(self):
        entry = self.enter()
        self.fixture.server.partial_cancel = True
        outcome = self.trader.exit_trade(entry["order_id"], "partial stop race")
        self.assertEqual("CLOSED", outcome["status"], outcome)
        self.assertEqual("65", self.fixture.server.posts()[-1][2]["quantity"])

    def test_insufficient_verified_expiry_sessions_never_reaches_buy(self):
        for remaining in (None, True, -1, 0, 1):
            self.funds["expiry_sessions_remaining"] = remaining
            with self.subTest(remaining=remaining):
                result = self.trader.execute_trade(self.fixture.decision(self.trader))
                self.assertEqual("EXPIRY_SESSION_BUDGET_UNVERIFIED", result["detail"])
                self.assertFalse(self.fixture.server.posts())

    def controls_file(self):
        path = self.fixture.root / "operator_controls.json"
        controls = dict(kill_switch=False, auto_trade_enabled=True, system_armed=True)
        path.write_text(json.dumps(controls), encoding="utf-8")
        self.trader.entry_control_reader = lambda: read_entry_control_block(path)
        return path, controls

    def test_operator_controls_require_exact_boolean_values(self):
        valid = dict(kill_switch=False, auto_trade_enabled=True, system_armed=True)
        self.assertIsNone(entry_control_block(valid))
        for key in valid:
            for invalid in (None, "true", 0, 1):
                with self.subTest(key=key, invalid=invalid):
                    self.assertIsNotNone(entry_control_block({**valid, key: invalid}))
            self.assertIsNotNone(
                entry_control_block({name: value for name, value in valid.items() if name != key})
            )

    def test_live_pause_controls_and_unreadable_file_block_only_new_entries(self):
        path, controls = self.controls_file()
        for key, value in (("kill_switch", True), ("auto_trade_enabled", False), ("system_armed", False)):
            path.write_text(json.dumps({**controls, key: value}), encoding="utf-8")
            result = self.trader.execute_trade(self.fixture.decision(self.trader))
            self.assertTrue(result.get("error"), result)
            self.assertFalse(self.fixture.server.posts())
        path.write_text("{", encoding="utf-8")
        self.assertEqual(
            "ENTRY_CONTROLS_UNAVAILABLE",
            self.trader.execute_trade(self.fixture.decision(self.trader))["detail"],
        )
        path.write_text(json.dumps(controls), encoding="utf-8")
        entry = self.enter()
        path.write_text(json.dumps({**controls, "kill_switch": True}), encoding="utf-8")
        self.quote(77.05)
        self.assertTrue(self.monitor())  # Stop ratchets continue with new entries paused.
        self.assertEqual(
            "CLOSED", self.trader.exit_trade(entry["order_id"], "operator control test")["status"]
        )

    def test_pause_after_pacing_is_rechecked_before_buy_transport(self):
        path, controls = self.controls_file()

        def paced(**kwargs):
            # The last completed read is the entry quote. Switch controls only
            # when the next (BUY) mutation reaches the broker pacing boundary.
            if self.fixture.server.calls[-1][1] == "/quote":
                path.write_text(json.dumps({**controls, "kill_switch": True}), encoding="utf-8")
            return True

        self.fixture.gateway.rate_limiter.acquire = paced
        result = self.trader.execute_trade(self.fixture.decision(self.trader))
        self.assertEqual("KILL_SWITCH_ENGAGED_OR_UNVERIFIED", result["detail"])
        self.assertFalse(self.fixture.server.posts())

    def test_operator_can_start_paused_then_resume_using_fresh_controls(self):
        path, controls = self.controls_file()
        self.trader.trading_cfg.update({**controls, "auto_trade_enabled": False})
        path.write_text(json.dumps({**controls, "auto_trade_enabled": False}), encoding="utf-8")
        result = self.trader.execute_trade(self.fixture.decision(self.trader))
        self.assertEqual("AUTO_TRADE_DISABLED_OR_UNVERIFIED", result["detail"])
        self.assertFalse(self.fixture.server.posts())
        path.write_text(json.dumps(controls), encoding="utf-8")
        self.enter()

    def test_scheduler_binds_the_current_workspace_operator_control_file(self):
        from nifty_trader_scheduler import NiftyOptionsTrader

        trader = NiftyOptionsTrader.__new__(NiftyOptionsTrader)
        with patch("nifty_trader_scheduler.read_entry_control_block", return_value="TEST_PAUSE") as reader:
            trader.load_strategy_config("macd_momentum", ai_mode="rules")
            self.assertEqual("TEST_PAUSE", trader.entry_control_reader())
        reader.assert_called_once_with(Path("config/trading.json").resolve())

    def test_paused_entry_cycle_skips_feed_and_companion_work(self):
        from trading.application.workflows import CycleWorkflow
        from unittest.mock import Mock

        path, controls = self.controls_file()
        path.write_text(json.dumps({**controls, "auto_trade_enabled": False}), encoding="utf-8")
        self.trader.strategy_mode = "macd_momentum"
        self.trader._timed_call = lambda stage, function, *args, **kwargs: function(*args, **kwargs)
        self.trader.check_feed_health = Mock(
            side_effect=AssertionError("Paused entry must not discover candidates")
        )
        result = CycleWorkflow(self.fixture.root, 10).run(self.trader)
        self.assertEqual("AUTO_TRADE_DISABLED_OR_UNVERIFIED", result["blocked"])
        self.trader.check_feed_health.assert_not_called()


if __name__ == "__main__":
    unittest.main()
