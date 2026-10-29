"""Shared R01 stop floor examples; authored but not run."""

import unittest

from trading.domain.unified_stop_policy import unified_floor


class UnifiedStopPolicyTests(unittest.TestCase):
    def test_initial_policy_never_loosens_existing_stop(self):
        result = unified_floor(100, 100, 94, "09:45", initial_loss_pct=25)
        self.assertEqual(94, float(result.trigger_floor))

    def test_same_schedule_for_all_strategies(self):
        morning = unified_floor(100, 115, 75, "10:30")
        midday = unified_floor(100, 115, 75, "12:30")
        self.assertGreaterEqual(float(morning.trigger_floor), 110)
        self.assertGreaterEqual(float(midday.trigger_floor), 103)

    def test_monotonic_floor_on_profit_drawdown(self):
        old = 105
        for peak in (140, 135, 110):
            result = unified_floor(100, peak, old, "14:00")
            self.assertGreaterEqual(float(result.trigger_floor), old)
            old = float(result.trigger_floor)

    def test_invalid_quote_context_does_not_create_order_proposal(self):
        for value in (None, True, "NaN", 0, -1):
            with self.subTest(value=value):
                self.assertIsNone(unified_floor(value, 100, 0, "09:30"))
        self.assertIsNone(unified_floor(100, 100, 0, "25:00"))


if __name__ == "__main__":
    unittest.main()
