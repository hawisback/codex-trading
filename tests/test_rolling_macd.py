"""Rolling observations, prior-session isolation and early activation, offline."""

from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from market_clock import MarketClock
from nifty_trader_scheduler import NiftyOptionsTrader
from trading.adapters.market_data import BrokerMarketData
from trading.adapters.market_sources import MarketDataError
from trading.application.dossier import DossierService
from trading.application.market_context import MarketContextService
from trading.domain.market_data import (
    macd_observation_bars,
    prior_session_warmup,
    resample_rolling_two_minutes,
    two_minute_macd_metrics,
)
from trading.strategies.macd_momentum import MacdMomentumStrategy, resample_1m_to_rolling_2m
from tests.scenarios import market_responses

ROOT = Path(__file__).resolve().parents[1]


def profile():
    return json.loads((ROOT / "config/strategies.json").read_text())["strategies"]["macd_momentum"]


def minutes(start, count, base=23000):
    return [
        dict(
            start_time=(start + timedelta(minutes=i)).isoformat(),
            open=base,
            close=base,
            high=base + 1,
            low=base - 1,
            volume=100,
        )
        for i in range(count)
    ]


class RollingFixture:
    def setUp(self):
        self.start = MarketClock.parse_to_ist("2026-10-27T09:15:00+05:30")
        self.prior = minutes(self.start - timedelta(days=1) + timedelta(hours=5, minutes=15), 60)


class RollingTests(RollingFixture, unittest.TestCase):
    def test_overlapping_ohlcv_every_minute_and_completed_candles_only(self):
        rows = minutes(self.start, 5)
        for i, bar in enumerate(rows):
            bar.update(open=23000 + i, high=23002 + i, low=22998 + i, close=23001 + i, volume=i + 1)
        bars = resample_1m_to_rolling_2m(rows, as_of=self.start + timedelta(minutes=5))
        self.assertEqual([1, 2, 3, 4], [b["minute_idx"] for b in bars])
        self.assertEqual(
            (23000, 23003, 22998, 23002, 3),
            tuple(bars[0][k] for k in ("open", "high", "low", "close", "volume")),
        )
        self.assertEqual(rows[1]["open"], bars[1]["open"])
        self.assertEqual(
            3, len(resample_rolling_two_minutes(rows, as_of=self.start + timedelta(minutes=4, seconds=59)))
        )
        rows[-1].update(open=99999, close=99999, high=100000, low=99998)
        self.assertEqual(
            bars[:-1], resample_rolling_two_minutes(rows, as_of=self.start + timedelta(minutes=4))
        )

    def test_no_cross_session_candle_and_intraday_ambiguity_is_rejected(self):
        today = minutes(self.start, 4)
        self.assertEqual(62, len(resample_rolling_two_minutes(self.prior + today)))
        for bad in (
            today[:1] + today[2:],
            [today[0], today[0]],
            list(reversed(today)),
            [dict(today[0], close=float("nan"))],
            [dict(today[0], open=True)],
            [dict(today[0], start_time=self.start.replace(hour=8).isoformat())],
        ):
            with self.subTest(bad=bad), self.assertRaises((ValueError, TypeError)):
                resample_rolling_two_minutes(bad)

    def test_warmup_is_exact_previous_close_and_validates_holidays_and_weekends(self):
        self.assertEqual(self.prior, prior_session_warmup(self.prior, self.start))
        for bad in ([], self.prior[:-1], self.prior[:20] + self.prior[21:], list(reversed(self.prior))):
            with self.assertRaises(ValueError):
                prior_session_warmup(bad, self.start)
        # Monday must use Friday; Wednesday after the configured Tuesday holiday uses Monday.
        monday = self.start - timedelta(days=1)
        friday = minutes(monday - timedelta(days=3) + timedelta(hours=5, minutes=15), 60)
        self.assertEqual(friday, prior_session_warmup(friday, monday))
        wednesday = self.start + timedelta(days=1)
        self.assertEqual(self.prior, prior_session_warmup(self.prior, wednesday, holidays=["2026-10-27"]))

    def test_indicator_warmup_never_builds_overnight_ohlc(self):
        today = minutes(self.start, 15)
        bars = macd_observation_bars(
            today, prior=self.prior, as_of=self.start + timedelta(minutes=15), rolling=True
        )
        self.assertEqual(73, len(bars))
        self.assertEqual(self.start.isoformat(), bars[59]["start_time"])
        metrics = two_minute_macd_metrics(bars, rolling=True)
        self.assertEqual("rolling_2m", metrics["interval"])
        self.assertEqual((self.start + timedelta(minutes=15)).isoformat(), metrics["candle_closed_at"])


class EarlyEntryTests(RollingFixture, unittest.TestCase):
    def evaluate(
        self, direction="CE", count=16, spot=None, prior=True, config=None, box_range=None, vwap=None
    ):
        cfg = config or profile()
        rows = minutes(self.start, count)
        spot = spot if spot is not None else (23010 if direction == "CE" else 22990)
        if count > 15:
            rows[-1].update(open=spot, close=spot, high=spot + 1, low=spot - 1)
        if box_range is not None:
            for bar in rows[-15:]:
                bar.update(high=23000 + box_range / 2, low=23000 - box_range / 2)
        ctx = dict(
            candles_1m=rows,
            spot=spot,
            session_vwap=spot if vwap is None else vwap,
            prior_session_warmup_candles=self.prior if prior else [],
        )
        value = 0.2 if direction == "CE" else -0.2
        with (
            MarketClock.at(self.start + timedelta(minutes=count)),
            patch(
                "trading.strategies.macd_momentum.calculate_macd",
                return_value=([0, value], [0, 0], [0, value]),
            ),
        ):
            return MacdMomentumStrategy(cfg).evaluate(ctx)

    def test_every_minute_early_crosses_require_breakout_in_both_directions(self):
        for direction in ("CE", "PE"):
            self.assertIn("Early ORB", self.evaluate(direction, count=15, spot=23000).reasons[0])
            for count in (16, 17, 18):
                self.assertEqual("BUY_" + direction, self.evaluate(direction, count=count).signal)
            self.assertIn("Early ORB", self.evaluate(direction, count=44, spot=23000).reasons[0])
        cfg = profile()
        cfg["entry"]["opening_range_filter_enabled"] = False
        self.assertEqual("BUY_CE", self.evaluate(count=45, spot=23000, config=cfg).signal)

    def test_missing_prior_blocks_even_after_intraday_warmup_and_later_start_is_supported(self):
        self.assertEqual("NEUTRAL", self.evaluate(prior=False, count=90).signal)
        cfg = profile()
        cfg["entry"].update(
            entry_start_time="09:50", early_orb_required=False, opening_range_filter_enabled=False
        )
        self.assertIn("09:50", self.evaluate(count=34, config=cfg).reasons[0])
        self.assertEqual("BUY_CE", self.evaluate(count=35, config=cfg).signal)

    def test_config_aliases_conflicts_and_times(self):
        self.assertEqual(8, MacdMomentumStrategy(dict(entry=dict(fast_period=8))).fast_period)
        for entry in (
            dict(macd_fast=12, fast_period=8),
            dict(use_rolling_2m="true"),
            dict(entry_start_time="9:30"),
            dict(entry_start_time="14:15"),
            dict(early_orb_required=True, entry_start_time="09:20"),
        ):
            with self.assertRaises(ValueError):
                MacdMomentumStrategy(dict(entry=entry))

    def test_active_climax_and_midday_range_thresholds(self):
        for direction, spot, sign in (("CE", 23010, -1), ("PE", 22990, 1)):
            self.assertIn("climax", self.evaluate(direction, count=60, vwap=spot + sign * 72).reasons[0])
            self.assertEqual(
                "BUY_" + direction, self.evaluate(direction, count=60, vwap=spot + sign * 71.99).signal
            )
        cfg = profile()
        cfg["entry"]["opening_range_filter_enabled"] = False  # Isolate the midday threshold.
        self.assertIn(
            "Midday flatline", self.evaluate(count=136, spot=23000, box_range=17.99, config=cfg).reasons[0]
        )
        self.assertEqual("BUY_CE", self.evaluate(count=136, spot=23000, box_range=18, config=cfg).signal)


class WarmupPipelineTests(RollingFixture, unittest.TestCase):
    def test_premarket_provider_cache_and_daily_rollover(self):
        calls = []
        source = SimpleNamespace(
            history=lambda *args: [], warmup_history=lambda *args: calls.append(args) or self.prior
        )
        provider = BrokerMarketData(source)
        with MarketClock.at(self.start.replace(hour=9, minute=0)):
            cached = provider.get_prior_session_warmup()
            cached[0]["close"] = 1
            self.assertEqual(23000, provider.get_prior_session_warmup()[0]["close"])
            self.assertEqual(1, len(calls))
        with MarketClock.at(self.start + timedelta(days=1)):
            with self.assertRaises(ValueError):
                provider.get_prior_session_warmup()

    def test_live_context_vwap_box_and_rsi_ignore_prior_history(self):
        responses = market_responses()
        with MarketClock.at("2026-10-19T10:00:00+05:30"):
            read = lambda key, **kwargs: responses[key]
            before = MarketContextService(read, lambda: dict(available_margin=10000)).fetch()
            prior = minutes(self.start - timedelta(days=9), 60, base=99999)
            responses["/nifty/candles?interval=1m&limit=375"]["candles"] = prior + before["candles_1m"]
            after = MarketContextService(read, lambda: dict(available_margin=10000)).fetch()
            for key in ("session_vwap", "candles_1m", "box_spread_15m", "rsi_14"):
                self.assertEqual(before[key], after[key])

    def test_scheduler_primes_and_attaches_separate_warmup_with_failure_closed(self):
        trader = NiftyOptionsTrader.__new__(NiftyOptionsTrader)
        trader.strategy_mode, trader.strategy_cfg = "macd_momentum", profile()
        trader.trading_cfg = {}
        trader.market_data = SimpleNamespace(get_prior_session_warmup=lambda **kwargs: self.prior)
        with MarketClock.at(self.start):
            trader.prepare_strategy_warmup()
            self.assertEqual(self.prior, trader.prior_session_warmup_candles)
            trader.client = SimpleNamespace(get_funds=lambda: {})
            today = minutes(self.start, 15)
            with patch(
                "nifty_trader_scheduler.MarketContextService.fetch",
                return_value=dict(candles_1m=today, session_vwap=23000),
            ):
                ctx = trader.fetch_market_context()
            self.assertEqual(today, ctx["candles_1m"])
            self.assertEqual(self.prior, ctx["prior_session_warmup_candles"])
            self.assertEqual(23000, ctx["session_vwap"])
        with MarketClock.at(self.start + timedelta(days=1)):
            trader.prepare_strategy_warmup()
            self.assertEqual([], trader.prior_session_warmup_candles)

    def test_option_and_spot_share_rolling_cadence_warmup_and_close_time(self):
        today = minutes(self.start, 17)
        now = self.start + timedelta(minutes=17)
        contract = dict(symbol="EXACT-CE", token=123, strike=22950, right="CE", expiry="2026-11-03")
        source = SimpleNamespace(_history=lambda *args: self.prior + today)
        provider = BrokerMarketData(source, master=SimpleNamespace(options=lambda budget: [contract]))
        with MarketClock.at(now):
            option = provider.get_strike_macd("EXACT-CE", as_of=now, use_rolling_2m=True, warmup_enabled=True)
            spot = two_minute_macd_metrics(
                macd_observation_bars(today, prior=self.prior, as_of=now, rolling=True), rolling=True
            )
            self.assertEqual(spot["macd"], option["macd"])
            self.assertEqual(now.isoformat(), option["candle_closed_at"])
            self.assertEqual("rolling_2m", option["interval"])
            cfg = profile()
            ctx = dict(
                candles_1m=today,
                prior_session_warmup_candles=self.prior,
                expiry="2026-11-03",
                spot=23000,
                ema_9=23000,
                ema_20=22994,
            )
            decision = dict(
                signal="BUY_CE",
                instrument_id="EXACT-CE",
                symbol="EXACT-CE",
                ltp=67,
                target_strike=22950,
                setup_type="MACD_2M_MOMENTUM",
                invalidation_level=22975,
            )
            dossier = DossierService({}, strategy_config=cfg, market_data=provider).build_dossier(
                ctx, decision, [], 0
            )
            self.assertEqual(option["histogram"], dossier.strike_histogram)
            self.assertEqual(spot, dossier.spot_macd_2m)
            self.assertFalse(dossier.is_reversal_inflection)  # Flat trigger cannot grant Trap 7 exception.
            self.assertIn("rolling 2m, evaluated every completed minute", dossier.to_markdown())
            source._history = lambda *args: self.prior + today[1:]
            with self.assertRaisesRegex(MarketDataError, "incomplete"):
                provider.get_strike_macd("EXACT-CE", as_of=now, use_rolling_2m=True, warmup_enabled=True)
