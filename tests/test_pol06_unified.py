"""R06 MACD continuation, advisory confluence and common POL-06 exits.

Prepared for an offline test suite. No tests run and no broker constructed.
"""
from datetime import timedelta
from unittest.mock import patch
import unittest

from market_clock import MarketClock
from trading.strategies.macd_momentum import MacdMomentumStrategy
from trading.domain.unified_exit import (
    POLICY_VERSION, shared_profit_floor, structural_decision,
)
from trading.application.position_monitor import PositionMonitor


BASE = MarketClock.parse_to_ist("2026-10-29T09:15:00+05:30")


def candles(count=64, *, start=BASE, close=23000.0):
    return [
        {
            "start_time": (start + timedelta(minutes=i)).isoformat(),
            "open": close,
            "high": close + 2.0,
            "low": close - 2.0,
            "close": close,
            "volume": 100,
        }
        for i in range(count)
    ]


class MacdSwingContinuationTests(unittest.TestCase):
    def setUp(self):
        self.bars = candles()
        self.observed = BASE + timedelta(minutes=64)
        self.strategy = MacdMomentumStrategy({"entry": {
            "use_rolling_2m": False,
            "prior_session_warmup_enabled": False,
            "entry_start_time": "09:30",
            "require_candle_alignment": False,
            "require_vwap_alignment": False,
            "opening_range_filter_enabled": False,
            "early_orb_required": False,
            "midday_dead_zone_filter": {"enabled": False},
            "continuation_max_observations": 8,
        }})
        self.ctx = dict(
            candles_1m=self.bars, spot=23000.0, session_vwap=23030.0,
            ema_9=23010.0, ema_20=23020.0,
        )

    def check(self, macd, signal, histogram):
        with MarketClock.at(self.observed), patch(
            "trading.strategies.macd_momentum.calculate_macd",
            return_value=(macd, signal, histogram),
        ):
            return self.strategy.evaluate(self.ctx)

    def test_macd_bullish_cross_or_continuation_both_reach_companion(self):
        fresh = self.check([-0.2, 0.3], [0, 0], [-0.2, 0.3])
        self.assertEqual("BUY_CE", fresh.signal)
        continued = self.check([-0.2, 0.3, 0.4], [0, 0, 0], [-0.2, 0.3, 0.4])
        self.assertEqual("BUY_CE", continued.signal)
        self.assertIn("continuation", continued.reasons[0])
        self.assertIn("VWAP countertrend", continued.reasons[0])
        self.assertIn("ema_20: countertrend", continued.reasons[0])
        self.assertLess(continued.invalidation_level, self.ctx["spot"])

    def test_put_continuation_with_opposing_emas_is_advisory(self):
        result = self.check([0.2, -0.3, -0.4], [0, 0, 0], [0.2, -0.3, -0.4])
        self.assertEqual("BUY_PE", result.signal)
        self.assertGreater(result.invalidation_level, self.ctx["spot"])
        self.assertIn("continuation", result.reasons[0])

    def test_old_cross_missing_cross_and_opposing_momentum_are_blocked(self):
        self.assertEqual("NEUTRAL", self.check([0.3]*10, [0]*10, [0.3]*10).signal)
        # Once strength disappears, a past cross is not a tradable continuation.
        self.assertEqual("NEUTRAL", self.check([-0.2, 0.3, 0.01], [0, 0, 0], [-0.2, 0.3, 0.01]).signal)
        self.assertEqual("NEUTRAL", self.check([-0.2, 0.3], [0, 0], [-0.2, 0.01]).signal)

    def test_cross_older_than_continuation_window_fails(self):
        macd = [-0.3, 0.4] + [0.4] * 9
        signal = [0.0] * len(macd)
        self.assertEqual("NEUTRAL", self.check(macd, signal, macd).signal)


class SharedProfitProtectionTests(unittest.TestCase):
    def test_morning_stages_and_generic_tiers(self):
        self.assertIsNone(shared_profit_floor(100, 104, "10:00"))
        self.assertEqual(92, shared_profit_floor(100, 105, "10:00"))
        self.assertEqual(101, shared_profit_floor(100, 110, "10:00"))
        self.assertEqual(110, shared_profit_floor(100, 115, "10:00"))
        self.assertGreaterEqual(shared_profit_floor(100, 130, "10:00"), 120)
        self.assertGreaterEqual(shared_profit_floor(100, 140, "10:00"), 130)
        self.assertGreaterEqual(shared_profit_floor(100, 150, "10:00"), 144.75)

    def test_midday_afternoon_and_late_day(self):
        self.assertEqual(103, shared_profit_floor(100, 105, "12:00"))
        self.assertEqual(101, shared_profit_floor(100, 104, "14:05"))
        self.assertIsNone(shared_profit_floor(100, 104, "13:45"))
        self.assertGreaterEqual(shared_profit_floor(100, 115, "13:20"), 110)
        self.assertIsNone(shared_profit_floor(100, 110, "15:15"))

    def test_existing_tighter_floor_never_lowers(self):
        calls = []
        p = PositionMonitor({}, True, lambda *a, **kw: {"status": "CLOSED"},
                            lambda t, floor: calls.append(floor))
        trade = dict(
            status="OPEN", trade_id="TEST-ENTRY", symbol="TESTCE", option_right="CE",
            instrument_id="TEST-CE", exit_policy_version=POLICY_VERSION,
            entry_price=100, last_bid=114, peak_bid=115,
            current_stop_trigger=112, desired_stop_trigger=112,
            invalidation_level=22950, quote_verified=True,
        )
        with MarketClock.at("2026-10-29T10:15:00+05:30"):
            result = p.manage([trade], {"spot": 23000}, {})
        self.assertEqual([trade], result)
        self.assertFalse(calls)


class HybridStructuralExitTests(unittest.TestCase):
    def test_latest_completed_close_not_current_forming_candle(self):
        now = MarketClock.parse_to_ist("2026-10-29T10:00:00+05:30")
        bars = candles(15, start=now-timedelta(minutes=15), close=23000)
        bars[-1]["close"] = 22990
        bars[-1]["low"] = 22988
        bars.append(dict(start_time=now.isoformat(), open=23000,
                         high=23002, low=22970, close=22970))  # incomplete
        reason, _ = structural_decision(
            {"option_right": "CE", "invalidation_level": 22995},
            {"candles_1m": bars, "spot": 23000}, now,
        )
        self.assertIn("completed 1m", reason)

    def test_decisive_requires_two_distinct_source_timestamps(self):
        now = MarketClock.parse_to_ist("2026-10-29T10:00:00+05:30")
        bars = candles(16, start=now-timedelta(minutes=16))
        state = {"option_right": "CE", "invalidation_level": 22990}
        first = {"spot": 22980, "candles_1m": bars,
                 "spot_observed_at": (now-timedelta(seconds=6)).isoformat()}
        reason, update = structural_decision(state, first, now)
        self.assertIsNone(reason)
        self.assertEqual(1, update["count"])
        state["structural_breach_confirmation"] = update
        reason, _ = structural_decision(state, first, now)
        self.assertIsNone(reason)  # same provider quote does not count twice
        second = dict(first, spot_observed_at=(now-timedelta(seconds=3)).isoformat())
        reason, _ = structural_decision(state, second, now)
        self.assertIn("Two fresh decisive", reason)

    def test_stale_missing_or_unconfirmed_structure_does_not_fake_early_exit(self):
        now = MarketClock.parse_to_ist("2026-10-29T10:00:00+05:30")
        state = {"option_right": "PE", "invalidation_level": 23010}
        for ctx in ({}, {"spot": 23030, "spot_observed_at": now.isoformat()},
                    {"candles_1m": candles(14), "spot": 23030}):
            self.assertIsNone(structural_decision(state, ctx, now)[0])


if __name__ == "__main__":
    unittest.main()
