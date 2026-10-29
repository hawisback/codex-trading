"""Offline selected-token MACD evidence; no orders or companion substitution."""

import copy
from datetime import timedelta
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from market_clock import MarketClock
from nifty_trader_scheduler import NiftyOptionsTrader
from trading.adapters.market_data import BrokerMarketData
from trading.adapters.market_sources import MarketDataError
from trading.domain.market_data import resample_two_minutes, two_minute_macd_metrics
from trading.strategies.macd_momentum import MacdMomentumStrategy, calculate_macd

ROOT = Path(__file__).resolve().parents[1]


class StrikeHistory:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def _history(self, token, interval, start, end, budget):
        self.calls.append((token, interval, start, end))
        return copy.deepcopy(self.rows)


class StrikeMacdTests(unittest.TestCase):
    def setUp(self):
        self.opening = MarketClock.parse_to_ist("2026-10-28T09:15:00+05:30")
        self.now = self.opening + timedelta(minutes=64)
        self.clock = MarketClock.at(self.now)
        self.clock.__enter__()
        self.addCleanup(self.clock.__exit__, None, None, None)
        self.rows = [
            dict(
                start_time=(self.opening + timedelta(minutes=i)).isoformat(),
                open=p,
                high=p + 1,
                low=p - 1,
                close=p,
                volume=100,
            )
            for i in range(64)
            for p in [60 + i * i / 100]
        ]
        self.source = StrikeHistory(self.rows)
        self.contracts = [
            dict(symbol="NIFTY-EXACT-" + right, token=token, strike=23000, right=right, expiry="2026-11-03")
            for right, token in (("CE", 123), ("PE", 456))
        ]
        self.provider = BrokerMarketData(
            self.source, master=SimpleNamespace(options=lambda b: self.contracts)
        )
        self.config = json.loads((ROOT / "config/strategies.json").read_text())["strategies"]["macd_momentum"]
        # Legacy stepped evidence remains supported; active rolling evidence is
        # tested with matching prior-day Spot and option history separately.
        self.config["entry"].update(use_rolling_2m=False, prior_session_warmup_enabled=False)

    def dossier(self, right="CE", provider=None):
        ctx = dict(spot=23000, ema_9=23030, ema_20=23020, candles_1m=self.rows, expiry="2026-11-03")
        decision = dict(
            signal="BUY_" + right,
            instrument_id="NIFTY-EXACT-" + right,
            symbol="NIFTY-EXACT-" + right,
            target_strike=23000,
            ltp=80,
            setup_type="MACD_2M_MOMENTUM",
            invalidation_level=22985,
        )
        trader = object.__new__(NiftyOptionsTrader)
        trader.trading_cfg = {}
        trader.strategy_cfg = self.config
        trader.ai_consultant = SimpleNamespace(mode="rules")
        trader.market_data = provider or self.provider
        return trader.build_dossier(ctx, decision, [], 0)

    def test_exact_ce_and_pe_tokens_and_strategy_macd_formula(self):
        expected = calculate_macd([bar["close"] for bar in resample_two_minutes(self.rows)])
        for right, token in (("CE", 123), ("PE", 456)):
            metrics = self.provider.get_strike_macd("NIFTY-EXACT-" + right)
            self.assertEqual(token, self.source.calls[-1][0])
            self.assertEqual("minute", self.source.calls[-1][1])
            for key, series in zip(("macd", "signal", "histogram"), expected):
                self.assertAlmostEqual(series[-1], metrics[key])
            self.assertTrue(metrics["expanding_positive"])
            self.assertEqual("Bullish Expansion", metrics["momentum_status"])
            self.assertEqual(self.now.isoformat(), metrics["candle_closed_at"])

    def test_forming_candles_and_future_extremes_cannot_change_metrics(self):
        baseline = self.provider.get_strike_macd("NIFTY-EXACT-CE")
        for i in range(64, 67):
            self.source.rows.append(
                dict(
                    start_time=(self.opening + timedelta(minutes=i)).isoformat(),
                    open=999,
                    high=1000,
                    low=998,
                    close=999,
                    volume=100,
                )
            )
        self.assertEqual(baseline, self.provider.get_strike_macd("NIFTY-EXACT-CE"))
        with MarketClock.at(self.now + timedelta(minutes=1, seconds=30)):
            self.assertEqual(baseline, self.provider.get_strike_macd("NIFTY-EXACT-CE"))
            self.assertEqual(baseline, self.provider.get_strike_macd("NIFTY-EXACT-CE", as_of=self.now))

    def test_missing_gap_stale_warmup_and_bad_ohlc_are_unavailable(self):
        for rows in (
            self.rows[:20] + self.rows[21:],
            self.rows[:-2],
            self.rows[-20:],
            [],
            [dict(b, close=float("nan")) for b in self.rows],
        ):
            with self.subTest(count=len(rows)):
                self.source.rows = rows
                with self.assertRaises((MarketDataError, ValueError)):
                    self.provider.get_strike_macd("NIFTY-EXACT-CE")
        self.source.rows = self.rows
        with MarketClock.at(self.now + timedelta(minutes=4)):
            with self.assertRaisesRegex(MarketDataError, "stale"):
                self.provider.get_strike_macd("NIFTY-EXACT-CE", as_of=self.now)

    def test_unresolved_contract_future_cutoff_and_unsupported_sources_fail(self):
        with self.assertRaisesRegex(MarketDataError, "identity"):
            self.provider.get_strike_macd("NIFTY-OTHER")
        with self.assertRaisesRegex(MarketDataError, "observation"):
            self.provider.get_strike_macd("NIFTY-EXACT-CE", as_of=self.now + timedelta(seconds=1))
        self.provider.source = SimpleNamespace()
        with self.assertRaisesRegex(MarketDataError, "unsupported"):
            self.provider.get_strike_macd("NIFTY-EXACT-CE")

    def test_trader_wires_provider_and_dossier_preserves_metrics_and_risk(self):
        for right in ("CE", "PE"):
            dossier = self.dossier(right)
            self.assertIsNotNone(dossier.strike_macd_line)
            self.assertAlmostEqual(
                dossier.strike_macd_line - dossier.strike_signal_line, dossier.strike_histogram
            )
            self.assertTrue(dossier.strike_histogram_expanding_positive)
            self.assertEqual(dossier.spot_macd_2m["candle_closed_at"], dossier.strike_macd_candle_closed_at)
            self.assertIn("Strike Premium Momentum (Option MACD)", dossier.to_markdown())
            self.assertIn("Bullish Expansion", dossier.to_markdown())
            self.assertEqual(23030, dossier.ema9_5m)
            self.assertEqual(23020, dossier.ema20_5m)
            self.assertEqual(25, dossier.risk_policy["min_invalidation_buffer_pts"])
            self.assertEqual(15, self.config["exit"]["post_fill_stop_loss"]["min_loss_pct"])
            self.assertEqual(20, self.config["exit"]["post_fill_stop_loss"]["max_loss_pct"])
            self.assertEqual(25, self.config["exit"]["initial_stop_pct"])

    def test_mismatch_or_failure_never_publishes_neutral_or_false_confluence(self):
        metrics = self.provider.get_strike_macd("NIFTY-EXACT-CE")
        for changes in (
            dict(instrument_id="OTHER"),
            dict(right="PE"),
            dict(strike=23050),
            dict(expiry="2026-11-10"),
            dict(candle_closed_at=self.opening.isoformat()),
            dict(histogram=float("nan")),
        ):
            provider = SimpleNamespace(get_strike_macd=lambda *a, **kw: dict(metrics, **changes))
            dossier = self.dossier(provider=provider)
            self.assertIsNone(dossier.strike_macd_line)
            self.assertIsNone(dossier.strike_histogram)
            self.assertFalse(dossier.strike_histogram_expanding_positive)
            self.assertIn("No confluence inferred", dossier.to_markdown())
        dossier = self.dossier(provider=SimpleNamespace())
        self.assertEqual("Unavailable", dossier.strike_momentum_status)
        self.assertTrue(dossier.spot_macd_2m)

    def test_config_disables_both_ema_vetoes_but_retains_structural_buffer(self):
        strategy = MacdMomentumStrategy(self.config)
        self.assertFalse(strategy.require_ema_confirmation)
        self.assertFalse(strategy.require_ema20_trend_alignment)
        self.assertEqual(25, strategy.min_invalidation_buffer_pts)

    def test_flat_bearish_and_crossing_momentum_labels(self):
        bars = resample_two_minutes(self.rows)
        flat = [dict(b, close=100) for b in bars]
        self.assertEqual("Neutral", two_minute_macd_metrics(flat)["momentum_status"])
        falling = [dict(b, close=150 - i * i / 100) for i, b in enumerate(bars)]
        metrics = two_minute_macd_metrics(falling)
        self.assertEqual("Bearish", metrics["momentum_status"])
        self.assertFalse(metrics["expanding_positive"])
        for final, label in ((110, "Bullish Crossover"), (90, "Bearish Crossover")):
            self.assertEqual(
                label, two_minute_macd_metrics(flat[:-1] + [dict(flat[-1], close=final)])["momentum_status"]
            )


if __name__ == "__main__":
    unittest.main()
