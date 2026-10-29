"""R01 no arbitrary option premium boundaries; not executed on this branch."""

import unittest

from entry_policy import EntryBlocked, EntryPolicy


class R01PriceBandTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "option_selection": {
                "min_option_premium": 15,
                "max_option_premium": 135,
            }
        }

    def test_legacy_price_limits_remain_by_default(self):
        policy = EntryPolicy.from_config(self.cfg)
        self.assertFalse(policy.price_only_bounds_disabled)
        with self.assertRaises(EntryBlocked):
            policy.band(10, "TREND_PULLBACK")
        with self.assertRaises(EntryBlocked):
            policy.band(200, "TREND_PULLBACK")

    def test_opt_in_no_fixed_minimum_or_maximum(self):
        cfg = {**self.cfg, "r01_policy": {
            "enabled": True, "price_only_veto_disabled": True,
        }}
        policy = EntryPolicy.from_config(cfg)
        self.assertTrue(policy.price_only_bounds_disabled)
        for price in (10, 200):
            with self.subTest(price=price):
                lower, upper = policy.band(price, "TREND_PULLBACK")
                self.assertLessEqual(lower, price)
                self.assertGreaterEqual(upper, price)

    def test_non_boolean_flag_cannot_activate_relaxation(self):
        cfg = {**self.cfg, "r01_policy": {
            "enabled": "true", "price_only_veto_disabled": True,
        }}
        self.assertFalse(EntryPolicy.from_config(cfg).price_only_bounds_disabled)


if __name__ == "__main__":
    unittest.main()
