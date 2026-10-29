"""R01 daily loss contract checks; deliberately NOT executed in this change."""

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
            "start_of_day_equity": 50000,
            "realized_pnl_today": -500,
            "unrealized_pnl_today": -200,
        }

    def decide(self, data=None):
        return daily_loss_decision(self.funds if data is None else data,
                                   self.scope, self.now, 1.5)

    def test_limit_uses_realized_plus_unrealized(self):
        self.assertTrue(self.decide().allowed)
        self.assertEqual("OK", self.decide().reason)
        data = {**self.funds, "unrealized_pnl_today": -250}
        self.assertFalse(self.decide(data).allowed)
        self.assertEqual("DAILY_LOSS_LIMIT", self.decide(data).reason)

    def test_missing_stale_or_wrong_account_blocks(self):
        for altered in (
            {"pnl_account_id": "WRONG"},
            {"pnl_session_date": "2026-10-28"},
            {"pnl_asof": (self.now - timedelta(minutes=2)).isoformat()},
            {"pnl_asof": "not a timestamp"},
            {"start_of_day_equity": 0},
            {"realized_pnl_today": None},
            {"unrealized_pnl_today": "NaN"},
        ):
            with self.subTest(altered=altered):
                self.assertFalse(self.decide({**self.funds, **altered}).allowed)

    def test_non_live_or_missing_account_is_not_authorized(self):
        self.assertFalse(daily_loss_decision(self.funds, {"mode":"PAPER",
                         "account_id":"TEST"}, self.now).allowed)
        self.assertFalse(daily_loss_decision(self.funds, {}, self.now).allowed)


if __name__ == "__main__":
    unittest.main()
