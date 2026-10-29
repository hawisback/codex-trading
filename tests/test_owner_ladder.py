"""Offline-only characterization of an opt-in lot ladder; never contacts brokers."""

import math
import unittest

from trading.domain.owner_ladder import owner_ladder_decision
from trading.domain.sizing import calculate_compounding_quantity


class OwnerLadderTests(unittest.TestCase):
    def test_exact_inclusive_upper_boundaries(self):
        for capital, expected_lots in (
            (20_000.0, 2), (20_000.01, 4),
            (40_000.0, 4), (40_000.01, 6),
            (60_000.0, 6), (60_000.01, 8),
            (80_000.0, 8), (80_000.01, 10),
            (200_000.0, 10),
        ):
            with self.subTest(capital=capital):
                # Low option price ensures affordability does not mask tier boundary.
                result = owner_ladder_decision(capital, 1.0)
                self.assertEqual(expected_lots, result.tier_lots)
                self.assertEqual(expected_lots * 65, result.quantity)

    def test_expensive_option_limits_quantity_below_tier(self):
        result = owner_ladder_decision(21_000.0, 100.0)
        self.assertEqual(4, result.tier_lots)
        self.assertEqual(3, result.affordable_lots)
        self.assertEqual(195, result.quantity)

    def test_nonfinite_or_missing_funds_or_price_cannot_authorize_quantity(self):
        for invalid in (None, True, -1, 0, math.nan, math.inf, -math.inf):
            with self.subTest(invalid=invalid):
                self.assertEqual(0, owner_ladder_decision(invalid, 25.0).quantity)
                self.assertEqual(0, owner_ladder_decision(100_000.0, invalid).quantity)

    def test_strict_broker_and_position_caps(self):
        self.assertEqual(
            130, owner_ladder_decision(200_000.0, 2.0, max_order_quantity=130).quantity
        )
        self.assertEqual(
            195, owner_ladder_decision(200_000.0, 2.0, max_lots_cap=3).quantity
        )
        self.assertEqual(
            0, owner_ladder_decision(200_000.0, 2.0, max_lots_cap=True).quantity
        )
        self.assertEqual(
            0, owner_ladder_decision(200_000.0, 2.0, max_order_quantity=64).quantity
        )

    def test_explicit_mode_wiring_and_legacy_default(self):
        strategy = {
            "compounding": {
                "enabled": True, "mode": "owner_capital_ladder_v1",
                "max_lots_cap": 10, "max_order_quantity": 650,
            }
        }
        new = calculate_compounding_quantity(
            90_000.0, 25.0, strategy_cfg=strategy,
            trading_cfg={}, quantity=65, environ={},
        )
        self.assertEqual(650, new)
        strategy["compounding"]["mode"] = "step_ladder"
        strategy["compounding"]["milestones"] = [
            {"min_capital": 0.0, "lots": 2},
            {"min_capital": 20_000.0, "lots": 4},
            {"min_capital": 40_000.0, "lots": 6},
            {"min_capital": 70_000.0, "lots": 8},
            {"min_capital": 100_000.0, "lots": 10},
        ]
        legacy = calculate_compounding_quantity(
            90_000.0, 25.0, strategy_cfg=strategy,
            trading_cfg={}, quantity=65, environ={},
        )
        self.assertEqual(520, legacy)
        # Explicit opt-in is mandatory: legacy result remains unchanged.
        self.assertNotEqual(new, legacy)

    def test_disabled_compounding_still_follows_old_quantity_path(self):
        cfg = {"compounding": {
            "enabled": False, "mode": "owner_capital_ladder_v1",
            "max_order_quantity": 650,
        }}
        self.assertEqual(65, calculate_compounding_quantity(
            100_000, 1, strategy_cfg=cfg, trading_cfg={}, quantity=65, environ={}
        ))


if __name__ == "__main__":
    unittest.main()
