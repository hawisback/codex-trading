"""Owner-approved cash loss cap for each proposed entry's actual lots."""

import unittest
from datetime import datetime, timedelta

from market_clock import IST_TZ
from trading.domain.daily_loss_policy import daily_loss_decision


class DailyLossPolicyTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 29, 12, 0, tzinfo=IST_TZ)
        self.scope = {"mode": "LIVE", "account_id": "TEST"}
        self.funds = {
            "pnl_account_id": "TEST",
            "pnl_session_date": "2026-10-29",
            "pnl_asof": self.now.isoformat(),
            "realized_pnl_today": -500,
            "unrealized_pnl_today": -200,
        }

    def decide(self, data=None, *, lots=1, loss_per_lot=3000):
        return daily_loss_decision(
            self.funds if data is None else data,
            self.scope,
            self.now,
            lots=lots,
            loss_per_lot=loss_per_lot,
        )

    def test_limit_uses_realized_plus_unrealized(self):
        self.assertTrue(self.decide().allowed)
        self.assertEqual("OK", self.decide().reason)
        data = {**self.funds, "unrealized_pnl_today": -2500}
        self.assertFalse(self.decide(data).allowed)
        self.assertEqual("DAILY_LOSS_LIMIT", self.decide(data).reason)

    def test_missing_stale_or_wrong_account_blocks(self):
        for altered in (
            {"pnl_account_id": "WRONG"},
            {"pnl_session_date": "2026-10-28"},
            {"pnl_asof": (self.now - timedelta(minutes=2)).isoformat()},
            {"pnl_asof": "not a timestamp"},
            {"realized_pnl_today": None},
            {"unrealized_pnl_today": "NaN"},
        ):
            with self.subTest(altered=altered):
                self.assertFalse(self.decide({**self.funds, **altered}).allowed)

    def test_non_live_or_missing_account_is_not_authorized(self):
        self.assertFalse(
            daily_loss_decision(self.funds, {"mode": "PAPER", "account_id": "TEST"}, self.now, lots=1).allowed
        )
        self.assertFalse(daily_loss_decision(self.funds, {}, self.now, lots=1).allowed)

    def test_each_entry_lot_count_recalculates_cash_cap(self):
        for lots in (1, 2, 4, 6, 8, 10):
            with self.subTest(lots=lots):
                limit = lots * 3000
                data = {**self.funds, "realized_pnl_today": -limit, "unrealized_pnl_today": 0}
                result = self.decide(data, lots=lots)
                self.assertFalse(result.allowed)
                self.assertEqual(limit, result.limit_amount)
                data["realized_pnl_today"] += 0.01
                self.assertTrue(self.decide(data, lots=lots).allowed)
        data = {**self.funds, "realized_pnl_today": -4000, "unrealized_pnl_today": 0}
        self.assertFalse(self.decide(data, lots=1).allowed)
        self.assertTrue(self.decide(data, lots=2).allowed)

    def test_invalid_lots_or_cash_limits_fail_closed(self):
        for lots in (None, 0, -1, True, 1.0, "2", 11):
            with self.subTest(lots=lots):
                self.assertFalse(self.decide(lots=lots).allowed)
        for limit in (None, True, 0, -3000, "NaN", float("inf")):
            with self.subTest(limit=limit):
                self.assertFalse(self.decide(loss_per_lot=limit).allowed)


if __name__ == "__main__":
    unittest.main()
