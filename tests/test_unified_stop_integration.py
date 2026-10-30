"""R01 unified stop integration regression scenarios.

These are deliberately authored but NOT executed. The fake callbacks have no
broker transport. Existing legacy runner tests retain their original behavior.
"""

from datetime import datetime, timedelta

from market_clock import IST_TZ
from trading.application.position_monitor import PositionMonitor
from trading.application.stop_manager import StopManager
from trading.domain.unified_stop_workflow import (
    R01_STOP_VERSION, decide_unified_stop, r01_stop_floor,
    r01_unified_active,
)
import unittest


class UnifiedR01DecisionTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 30, 10, 30, tzinfo=IST_TZ)

    def state(self, *, bid=115, peak=115, entry=100, **overrides):
        result = dict(
            status="OPEN", trade_id="BUY-1", symbol="NIFTY-TEST-CE",
            instrument_id="INST-NIFTY-2026-11-03-24000-CE",
            entry_price=entry, last_bid=bid, peak_bid=peak,
            quote_verified=True, bid_timestamp=self.now.isoformat(),
            r01_policy_version=R01_STOP_VERSION, r01_initial_stop_pct=25,
            entry_balances={"BUY-1": 65}, stops=[],
            desired_stop_trigger=0, current_stop_trigger=0,
            protection_confirmed=False,
        )
        result.update(overrides)
        return result

    def test_same_time_based_floor_across_all_strategy_names(self):
        for strategy in ("legacy_scalper", "structural_runner",
                         "institutional_pullback", "macd_momentum", "ai_opportunity_radar"):
            with self.subTest(strategy=strategy):
                state = self.state(setup_type=strategy)
                result = decide_unified_stop(state, self.now)
                self.assertEqual("RATCHET", result.kind)
                self.assertEqual(110.0, result.trigger)
                self.assertEqual("MORNING", result.phase)

    def test_midday_and_afternoon_tiers_share_one_policy(self):
        state = self.state(bid=105, peak=105)
        noon = self.now.replace(hour=12)
        state["bid_timestamp"] = noon.isoformat()
        self.assertEqual(103.0, decide_unified_stop(state, noon).trigger)
        after = noon.replace(hour=14)
        state["bid_timestamp"] = after.isoformat()
        self.assertEqual(75.0, decide_unified_stop(state, after).trigger)

    def test_late_day_squareoff_does_not_depend_on_fresh_quote(self):
        state = self.state(quote_verified=False, bid_timestamp=None)
        self.assertEqual("HOLD", decide_unified_stop(state, self.now).kind)
        self.assertEqual(
            "SESSION_HARD_SQUARE_OFF",
            decide_unified_stop(state, self.now.replace(hour=15, minute=15)).reason,
        )

    def test_stale_bid_does_not_ratchet_from_old_peak(self):
        state = self.state(bid_timestamp=(self.now - timedelta(seconds=5)).isoformat())
        self.assertEqual("HOLD", decide_unified_stop(state, self.now).kind)
        # Initial protection still exists, but no historical profit ratchet
        # is authorized without a fresh broker observation.
        self.assertEqual(75.0, r01_stop_floor(state, self.now)[0])

    def test_confirmed_stronger_stop_never_moves_backwards(self):
        state = self.state(
            stops=[dict(entry_order_id="BUY-1", status="TRIGGER_PENDING",
                        trigger_price=123.05)], desired_stop_trigger=120)
        result = decide_unified_stop(state, self.now)
        self.assertEqual("EXIT", result.kind)  # Bid=115 is below the real stop.
        state["last_bid"] = 126
        state["peak_bid"] = 126  # A newly verified bid also updates the recorded peak.
        self.assertEqual(123.05, decide_unified_stop(state, self.now).trigger)

    def test_round_up_does_not_lose_a_partial_tick(self):
        state = self.state(entry=101.01, bid=102, peak=102)
        # 25% initial stop=75.7575, must be 75.80, never 75.75
        self.assertEqual(75.8, r01_stop_floor(state, self.now)[0])

    def test_version_is_sticky_when_feature_is_disabled(self):
        state = self.state()
        self.assertTrue(r01_unified_active(
            state, {"r01_policy": {"enabled": False, "unified_stop_enabled": False}}))
        state.pop("r01_policy_version")
        self.assertFalse(r01_unified_active(
            state, {"r01_policy": {"enabled": True, "unified_stop_enabled": True}}))


class UnifiedR01MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 30, 10, 30, tzinfo=IST_TZ)
        self.exits = []
        self.ratchets = []
        self.trading_cfg = {"r01_policy": {"enabled": True, "unified_stop_enabled": True},
                            "risk": {"option_hard_stop_pct": 25}}
        self.strategy = {"exit": {
            "initial_stop_pct": 6, "profit_target_enabled": True,
            "target_pct": 5, "max_hold_seconds": 1,
            "runner_trailing_enabled": True,
        }}
        self.monitor = PositionMonitor(
            self.strategy, True,
            lambda _, reason, **kwargs: self.exits.append(reason) or {"status": "CLOSED"},
            lambda state, trigger: self.ratchets.append(trigger),
            trading_cfg=self.trading_cfg,
        )
        self.state = dict(
            status="OPEN", trade_id="BUY-1", symbol="UNIT-CE",
            instrument_id="INST-NIFTY-2026-11-03-24000-CE",
            entry_price=100, last_bid=115, peak_bid=115,
            r01_policy_version=R01_STOP_VERSION,
            r01_initial_stop_pct=25,
            bid_timestamp=self.now.isoformat(), quote_verified=True,
            protection_confirmed=False, entry_balances={"BUY-1": 65},
            stops=[], entry_time="2026-10-30T09:15:00+05:30",
        )

    def evaluate(self):
        from unittest.mock import patch
        with patch("market_clock.MarketClock.now_ist", return_value=self.now):
            return self.monitor.manage([self.state], {}, {})

    def test_replaces_legacy_target_timer_and_trail_for_r01(self):
        self.evaluate()
        self.assertEqual([], self.exits)
        self.assertEqual([110], self.ratchets)

    def test_breached_shared_floor_routes_through_existing_exit_callback(self):
        self.state.update(last_bid=109, peak_bid=115, desired_stop_trigger=110)
        self.evaluate()
        self.assertEqual([], self.ratchets)
        self.assertIn("UNIFIED_PROTECTIVE_FLOOR_BREACHED", self.exits[-1])

    def test_unconfirmed_stop_is_rechecked_but_confirmed_stop_is_not(self):
        self.state.update(desired_stop_trigger=110, current_stop_trigger=110,
                          protection_confirmed=True)
        self.evaluate()
        self.assertFalse(self.ratchets)
        self.state["protection_confirmed"] = False
        self.evaluate()
        self.assertEqual([110], self.ratchets)

    def test_stale_quote_never_drives_price_exit(self):
        self.state["quote_verified"] = False
        self.evaluate()
        self.assertFalse(self.ratchets or self.exits)
        self.now = self.now.replace(hour=15, minute=15)
        self.evaluate()
        self.assertIn("SESSION_HARD_SQUARE_OFF", self.exits[-1])

    def test_disabling_r01_flag_does_not_change_open_trade_stop(self):
        self.trading_cfg["r01_policy"]["enabled"] = False
        self.evaluate()
        self.assertEqual([110], self.ratchets)


class UnifiedStopManagerTests(unittest.TestCase):
    def test_r01_entry_uses_one_initial_stop_not_strategy_specific_six_percent(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        now = datetime(2026, 10, 30, 10, 30, tzinfo=IST_TZ)
        recorded, placed = [], []
        owner = SimpleNamespace(
            client=object(), state_verified=True,
            strategy_cfg={"exit": {"initial_stop_pct": 6}},
            trading_cfg={"risk": {"option_hard_stop_pct": 25},
                         "r01_policy": {"enabled": False}},
            save_active_position=lambda state: recorded.append(state.get("desired_stop_trigger")),
        )
        mgr = StopManager(owner)
        state = dict(
            r01_policy_version=R01_STOP_VERSION,
            r01_initial_stop_pct=25, entry_price=100,
            last_bid=100, peak_bid=100,
            quote_verified=True, bid_timestamp=now.isoformat(),
            entry_balances={"BUY-1": 65}, stops=[], exits=[],
        )
        mgr.place = lambda state, ref, trigger: placed.append((ref, trigger))
        with patch("market_clock.MarketClock.now_ist", return_value=now):
            mgr.ensure(state)
        self.assertEqual([("BUY-1", 75)], placed)


if __name__ == "__main__":
    unittest.main()
