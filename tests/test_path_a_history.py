"""Exact-contract and causal OHLC estimates; no broker or synthetic pricing."""

from datetime import timedelta
import json
from pathlib import Path
import tempfile
import unittest
from market_clock import MarketClock
from tests.scenarios import ROOT
from trading.adapters.historical import load_option_history, OptionHistory
from trading.domain.historical_execution import simulate_option_path


class PathAHistoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix=".path-a-history-", dir=ROOT)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "data").mkdir()
        self.start = MarketClock.parse_to_ist("2026-10-27T10:00:00+05:30")
        self.spot = [dict(start_time=(self.start + timedelta(minutes=i)).isoformat(),
                          open=23000, high=23002, low=22998, close=23000) for i in range(4)]
        self.rows = [dict(start_time=b["start_time"], open=100, high=101, low=99, close=100) for b in self.spot]
        self.config = dict(initial_stop_pct=20, runner_activation_pct=15, trail_pullback_pct=10)

    def history(self):
        return OptionHistory({(23000, "CE"): {b["start_time"]: b for b in self.rows}}, [])

    def simulate(self, history=None, strike=23000):
        return simulate_option_path(0, "CE", self.spot, history or self.history(), strike, self.config)

    def test_missing_strike_or_timestamp_cannot_use_another_contract_or_position(self):
        self.assertIsNone(self.simulate(strike=23050))
        self.rows[2]["start_time"] = (self.start + timedelta(seconds=125)).isoformat()
        self.assertIsNone(self.simulate())

    def test_entry_uses_next_minute_open_not_signal_close(self):
        self.rows[0]["close"] = 200
        self.rows[1].update(open=90, high=92, low=89, close=91)
        self.rows[2].update(open=70, high=75, low=69, close=70)
        result = self.simulate()
        self.assertEqual(1, result["entry_idx"])
        self.assertEqual(90, result["entry_price"])
        self.assertFalse(result["ai_used"])

    def test_old_stop_is_checked_before_same_minute_high_can_raise_it(self):
        self.rows[1].update(high=150, low=79, close=140)
        result = self.simulate()
        self.assertEqual(80, result["exit_price"])
        self.assertEqual(1, result["exit_idx"])

    def test_incomplete_lifecycle_and_gaps_are_not_reported_as_realized_profit(self):
        self.assertIsNone(self.simulate())
        self.spot[2]["start_time"] = (self.start + timedelta(minutes=10)).isoformat()
        self.assertIsNone(self.simulate())

    def test_ratchet_is_effective_next_minute_and_gap_uses_worse_open(self):
        self.rows[1].update(high=150, low=90, close=140)
        self.rows[2].update(open=100, high=101, low=99, close=100)
        result = self.simulate()
        self.assertEqual(2, result["exit_idx"])
        self.assertEqual(100, result["exit_price"])
        self.rows[1].update(high=101, low=99, close=100)
        self.rows[2].update(open=70, high=75, low=65, close=70)
        self.assertEqual(70, self.simulate()["exit_price"])

    def test_loader_requires_matching_session_expiry_strike_and_right_metadata(self):
        path = self.root / "data/opt_20261027_23000_CE.json"
        path.write_text(json.dumps(self.rows))
        result = load_option_history("2026-10-27", "2026-10-27", root=self.root)
        self.assertFalse(result.contracts)
        self.assertEqual([path.name], result.excluded_files)
        meta = dict(session="2026-10-27", expiry="2026-10-27", strike=23000, right="CE", symbol="NIFTY-TEST-CE")
        path.with_suffix(".meta.json").write_text(json.dumps(meta))
        result = load_option_history("2026-10-27", "2026-10-27", root=self.root)
        self.assertEqual(100, result.bar(23000, "CE", self.start)["close"])
        self.assertIsNone(result.bar(23050, "CE", self.start))
        for changes in (dict(expiry="2026-11-03"), dict(strike=23050), dict(right="PE"), dict(session="2026-10-26")):
            path.with_suffix(".meta.json").write_text(json.dumps(dict(meta, **changes)))
            self.assertFalse(load_option_history("2026-10-27", "2026-10-27", root=self.root).contracts)
