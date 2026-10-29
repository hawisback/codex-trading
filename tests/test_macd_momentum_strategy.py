"""Completed-candle behavior of Path A."""

from datetime import timedelta
import json
import math
from pathlib import Path
import unittest
from market_clock import MarketClock
from trading.strategies.macd_momentum import MacdMomentumStrategy, resample_1m_to_2m, calculate_macd
from trading.strategies.registry import StrategyRegistry


class TestMacdMomentumStrategy(unittest.TestCase):
    def bars(self, count):
        start = MarketClock.parse_to_ist("2026-10-27T09:15:00+05:30")
        return [dict(start_time=(start + timedelta(minutes=i)).isoformat(), open=p, high=p + 1,
                     low=p - 1, close=p, volume=100)
                for i in range(count) for p in [23000 + 30 * math.sin(i * .31) + .1 * i]]

    def evaluate(self, bars, elapsed=None):
        with MarketClock.at("2026-10-27T09:15:00+05:30") as start:
            with MarketClock.at(start + timedelta(minutes=elapsed or len(bars))):
                spot = bars[-1]["close"] if bars else 23000
                return MacdMomentumStrategy().evaluate({"candles_1m": bars, "spot": spot, "session_vwap": spot})

    def test_resampling_preserves_ohlcv_and_drops_incomplete_tail(self):
        bars = self.bars(5)
        res = resample_1m_to_2m(bars)
        self.assertEqual(2, len(res))
        self.assertEqual(bars[0]["open"], res[0]["open"])
        self.assertEqual(max(b["high"] for b in bars[:2]), res[0]["high"])
        self.assertEqual(min(b["low"] for b in bars[:2]), res[0]["low"])
        self.assertEqual(bars[1]["close"], res[0]["close"])
        self.assertEqual(200, res[0]["volume"])

    def test_live_time_excludes_the_forming_second_minute(self):
        bars = self.bars(64)
        now = MarketClock.parse_to_ist(bars[-1]["start_time"]) + timedelta(seconds=30)
        self.assertEqual(31, len(resample_1m_to_2m(bars, as_of=now)))
        self.assertEqual("NEUTRAL", self.evaluate(bars, elapsed=63).signal)

    def test_half_bar_crossover_is_never_proposed(self):
        candidate = self.evaluate(self.bars(63))
        self.assertEqual("NEUTRAL", candidate.signal)
        self.assertIn("Waiting", candidate.reasons[0])

    def test_completed_bullish_and_bearish_crossovers_have_swing_stops(self):
        found = set()
        for count in range(54, 121, 2):
            candidate = self.evaluate(self.bars(count))
            if candidate.signal != "NEUTRAL":
                found.add(candidate.signal)
                self.assertEqual("MACD_2M_MOMENTUM", candidate.setup_type)
                self.assertGreater(candidate.invalidation_level, 0)
        self.assertEqual({"BUY_CE", "BUY_PE"}, found)

    def test_timestamp_gaps_duplicates_unordered_missing_and_stale_fail_closed(self):
        bars = self.bars(64)
        for bad in (bars[:20] + bars[21:], bars[:20] + [bars[19]] + bars[21:], list(reversed(bars)),
                    [dict(b, start_time="invalid") for b in bars]):
            self.assertEqual("NEUTRAL", self.evaluate(bad, elapsed=64).signal)
        self.assertEqual("NEUTRAL", self.evaluate(bars, elapsed=90).signal)

    def test_macd_and_registry(self):
        macd, signal, hist = calculate_macd([float(100 + i) for i in range(35)])
        self.assertEqual((35, 35, 35), (len(macd), len(signal), len(hist)))
        self.assertGreater(macd[-1], 0)
        self.assertIsInstance(StrategyRegistry().create("macd_momentum", {}, None), MacdMomentumStrategy)

    def test_insufficient_bars_neutral(self):
        self.assertEqual("NEUTRAL", self.evaluate(self.bars(10)).signal)

    def hybrid_case(self, wanted):
        for count in range(54, 121, 2):
            bars = self.bars(count)
            if self.evaluate(bars).signal == wanted:
                return bars
        self.fail(f"Fixture did not contain a completed {wanted} crossover")

    def hybrid_evaluate(self, direction, changes=None, config_changes=None):
        bars = self.hybrid_case(direction)
        spot = bars[-1]["close"]
        ctx = dict(candles_1m=bars, spot=spot, session_vwap=spot, ema_9=spot, ema_20=spot)
        ctx.update(changes or {})
        entry = dict(require_ema_confirmation=True, require_ema20_trend_alignment=True,
                     ema_proximity_pts=10, min_invalidation_buffer_pts=15)
        entry.update(config_changes or {})
        now = MarketClock.parse_to_ist(bars[-1]["start_time"]) + timedelta(minutes=1)
        with MarketClock.at(now):
            return MacdMomentumStrategy({"entry": entry}).evaluate(ctx), spot

    def test_hybrid_accepts_completed_calls_and_puts_at_ema_boundaries(self):
        for direction in ("BUY_CE", "BUY_PE"):
            with self.subTest(direction=direction):
                bars = self.hybrid_case(direction)
                spot = bars[-1]["close"]
                for offset in (-10, 0, 10):
                    candidate, _ = self.hybrid_evaluate(direction, {"ema_9": spot + offset})
                    self.assertEqual(direction, candidate.signal)
                    self.assertIn("EMA20 trend aligned", candidate.reasons[0])
                expected = spot - 15 if direction == "BUY_CE" else spot + 15
                if direction == "BUY_CE":
                    self.assertLessEqual(candidate.invalidation_level, expected)
                else:
                    self.assertGreaterEqual(candidate.invalidation_level, expected)

    def test_hybrid_rejects_overextended_and_opposing_trend_for_both_directions(self):
        for direction in ("BUY_CE", "BUY_PE"):
            spot = self.hybrid_case(direction)[-1]["close"]
            candidate, _ = self.hybrid_evaluate(direction, {"ema_9": spot + 10.01})
            self.assertEqual("NEUTRAL", candidate.signal)
            self.assertIn("extended", candidate.reasons[0])
            candidate, _ = self.hybrid_evaluate(direction, {"ema_20": spot + (1 if direction == "BUY_CE" else -1)})
            self.assertEqual("NEUTRAL", candidate.signal)
            self.assertIn("wrong side", candidate.reasons[0])

    def test_required_spot_and_emas_fail_closed_for_missing_and_non_finite_prices(self):
        for direction in ("BUY_CE", "BUY_PE"):
            for key in ("spot", "ema_9", "ema_20"):
                for value in (None, 0, -1, float("nan"), float("inf"), True, "invalid"):
                    with self.subTest(direction=direction, key=key, value=value):
                        candidate, _ = self.hybrid_evaluate(direction, {key: value})
                        self.assertEqual("NEUTRAL", candidate.signal)
                        self.assertIn("invalid", candidate.reasons[0])

    def test_ema20_filter_is_independent_of_ema9_filter(self):
        spot = self.hybrid_case("BUY_CE")[-1]["close"]
        candidate, _ = self.hybrid_evaluate("BUY_CE", {"ema_20": spot + 1}, {"require_ema_confirmation": False})
        self.assertEqual("NEUTRAL", candidate.signal)
        self.assertIn("wrong side", candidate.reasons[0])

    def test_active_profile_proposes_crossovers_beyond_ema9_and_against_ema20(self):
        config = json.loads((Path(__file__).resolve().parents[1] / "config/strategies.json").read_text())
        config["strategies"]["macd_momentum"]["entry"].update(use_rolling_2m=False, prior_session_warmup_enabled=False)
        strategy = MacdMomentumStrategy(config["strategies"]["macd_momentum"])
        for direction in ("BUY_CE", "BUY_PE"):
            bars = self.hybrid_case(direction)
            spot = bars[-1]["close"]
            offset = 100 if direction == "BUY_CE" else -100
            now = MarketClock.parse_to_ist(bars[-1]["start_time"]) + timedelta(minutes=1)
            with MarketClock.at(now):
                candidate = strategy.evaluate(dict(candles_1m=bars, spot=spot, session_vwap=spot,
                                                    ema_9=spot + offset, ema_20=spot + offset))
            self.assertEqual(direction, candidate.signal)
            self.assertGreaterEqual(abs(candidate.invalidation_level - spot), 15)

    def test_invalid_hybrid_parameters_are_rejected(self):
        for entry in ({"ema_proximity_pts": float("nan")}, {"ema_proximity_pts": -1},
                      {"min_invalidation_buffer_pts": 0}, {"min_invalidation_buffer_pts": float("inf")},
                      {"require_ema_confirmation": "false"}, {"macd_fast": 1.5}, {"macd_slow": 1}):
            with self.subTest(entry=entry), self.assertRaises(ValueError):
                MacdMomentumStrategy({"entry": entry})
