"""Causal EMA timing and real gate coverage for the hybrid research entry point."""

import copy
from datetime import timedelta
import json
import math
from pathlib import Path
import tempfile
import unittest

from market_clock import MarketClock
from tests.scenarios import ROOT
from tools.replay_hybrid import review_session
from trading.adapters.historical import OptionHistory
from trading.domain.indicators import select_strike
from trading.domain.market_data import causal_hybrid_context, prior_session_warmup
from trading.hybrid_research import HybridHistoricalReview
from trading.strategies.macd_momentum import MacdMomentumStrategy


class HybridReplayTests(unittest.TestCase):
    def setUp(self):
        self.start = MarketClock.parse_to_ist("2026-10-27T09:15:00+05:30")
        self.prior = self.bars(self.start - timedelta(days=1), 375, flat=True)
        self.today = self.bars(self.start, 120)
        self.cfg = json.loads((ROOT / "config/strategies.json").read_text())["strategies"]["macd_momentum"]
        self.trading = json.loads((ROOT / "config/trading.json").read_text())
        # This fixture verifies the legacy penny-option trap, independent of
        # the operator's R01 opt-in (whose price-only veto is disabled).
        self.trading.setdefault("r01_policy", {})["enabled"] = False
        self.reviewer = HybridHistoricalReview(self.cfg, self.trading)

    def bars(self, start, count, flat=False):
        return [
            dict(
                start_time=(start + timedelta(minutes=i)).isoformat(),
                open=p - 0.2,
                high=p + 0.5,
                low=p - 0.5,
                close=p,
                volume=1000,
            )
            for i in range(count)
            for p in [23000 if flat else 23000 + 30 * math.sin(i * 0.31) + 0.1 * i]
        ]

    def context(self, rows=None, count=64):
        ctx = causal_hybrid_context(
            self.today if rows is None else rows,
            self.start + timedelta(minutes=count),
            expiry="2026-10-27",
            prior_rows=self.prior,
        )
        ctx["prior_session_warmup_candles"] = prior_session_warmup(self.prior, self.start)
        return ctx

    def crossover(self):
        for count in range(15, 121):
            with MarketClock.at(self.start + timedelta(minutes=count)):
                ctx = self.context(count=count)
                candidate = MacdMomentumStrategy(self.cfg).evaluate(ctx)
                if candidate.signal == "BUY_CE":
                    return count, ctx, candidate
        self.fail("The fixture must reach a genuine hybrid crossover")

    def test_future_candles_do_not_change_observed_context_or_completed_emas(self):
        altered = copy.deepcopy(self.today)
        for bar in altered[64:]:
            bar.update(open=99999, high=100001, low=99998, close=100000)
        self.assertEqual(self.context(self.today[:64]), self.context(altered))
        self.assertEqual("2026-10-27T10:10:00+05:30", self.context()["ema_observed_through"])

    def test_current_five_minute_bucket_does_not_enter_emas_until_it_closes(self):
        altered = copy.deepcopy(self.today)
        for bar in altered[60:65]:
            bar.update(open=40000, high=40002, low=39998, close=40000)
        self.assertEqual(self.context()["ema_9"], self.context(altered)["ema_9"])
        self.assertNotEqual(self.context(altered)["ema_9"], self.context(altered, count=65)["ema_9"])

    def test_missing_warmup_and_session_gaps_cannot_manufacture_confirmation(self):
        with self.assertRaisesRegex(ValueError, "50 completed"):
            causal_hybrid_context(self.today, self.start + timedelta(minutes=64), expiry="2026-10-27")
        with self.assertRaisesRegex(ValueError, "Incomplete replay"):
            self.context(self.today[:20] + self.today[21:])

    def test_missing_exact_option_history_blocks_instead_of_using_synthetic_prices(self):
        count, ctx, candidate = self.crossover()
        result = self.reviewer.evaluate(
            self.today,
            now=self.start + timedelta(minutes=count),
            expiry="2026-10-27",
            options=OptionHistory({}, []),
            prior_rows=self.prior,
        )
        self.assertEqual(candidate.signal, result["signal"])
        self.assertEqual("EXACT_OPTION_HISTORY_UNAVAILABLE", result["blocked"])
        self.assertIsNone(result["verdict"])

    def test_actual_consultant_veto_is_authoritative_and_dossier_matches_entry_emas(self):
        count, ctx, candidate = self.crossover()
        strike = select_strike(ctx["spot"], "CE", "STRICT_ITM")
        stamp = ctx["candles_1m"][-1]["start_time"]
        options = OptionHistory({(strike, "CE"): {stamp: dict(open=8, high=8, low=8, close=8)}}, [])
        result = self.reviewer.evaluate(
            self.today,
            now=self.start + timedelta(minutes=count),
            expiry="2026-10-27",
            options=options,
            prior_rows=self.prior,
        )
        self.assertEqual("CONSULTANT_VETOED", result["blocked"])
        self.assertEqual("VETOED", result["verdict"]["action"])
        self.assertIn("Trap 2", result["verdict"]["trap_detected"])
        self.assertIsNone(result["verdict"]["max_entry_price"])
        with MarketClock.at(self.start + timedelta(minutes=count)):
            decision = dict(
                signal=candidate.signal,
                setup_type=candidate.setup_type,
                ltp=67,
                instrument_id="TEST",
                symbol="NIFTY-CE",
                target_strike=strike,
                invalidation_level=candidate.invalidation_level,
            )
            dossier = self.reviewer.dossiers.build_dossier(ctx, decision, [], 0)
        self.assertEqual(ctx["ema_9"], dossier.ema9_5m)
        self.assertEqual(ctx["ema_20"], dossier.ema20_5m)
        self.assertEqual(25, dossier.risk_policy["min_invalidation_buffer_pts"])

    def test_session_report_exposes_missing_evidence_without_profit_claims(self):
        with tempfile.TemporaryDirectory(prefix=".hybrid-replay-", dir=ROOT) as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "data").mkdir()
            (root / "config/strategies.json").write_text(
                json.dumps({"strategies": {"macd_momentum": self.cfg}})
            )
            (root / "config/trading.json").write_text(json.dumps(self.trading))
            (root / "data/spot_candles_20261026.json").write_text(json.dumps(self.prior))
            (root / "data/spot_candles_20261027.json").write_text(json.dumps(self.today))
            report = review_session("2026-10-27", root=root)
        self.assertEqual("DECISION_REPLAY_ONLY", report["scope"])
        self.assertFalse(report["ai_used"])
        self.assertGreater(report["counts"].get("EXACT_OPTION_HISTORY_UNAVAILABLE", 0), 0)
        self.assertNotIn("pnl", report)
        self.assertNotIn("roi", report)
