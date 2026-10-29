"""Offline characterization of the R01 owner ladder; do not run without approval."""

import unittest
from decimal import Decimal

from trading.domain.owner_lot_policy import (
    owner_ladder_max_lots, preview_owner_lot_ceiling,
)


class OwnerLotPolicyTests(unittest.TestCase):
    def preview(self, capital, *, ask="50", margin=None, basis="available_margin",
                broker_cap=650, lot_size=65):
        return preview_owner_lot_ceiling(
            capital_basis=basis, bracket_capital=capital,
            available_margin=capital if margin is None else margin,
            executable_option_ask=ask, lot_size=lot_size,
            broker_single_order_quantity_limit=broker_cap,
        )

    def test_all_inclusive_upper_band_boundaries(self):
        cases = [
            ("0", 0), ("-1", 0), ("20000", 2), ("20000.01", 4),
            ("40000", 4), ("40000.01", 6),
            ("60000", 6), ("60000.01", 8),
            ("80000", 8), ("80000.01", 10), ("100001", 10),
        ]
        for capital, expected in cases:
            with self.subTest(capital=capital):
                self.assertEqual(expected, owner_ladder_max_lots(capital))

    def test_full_ten_lots_only_when_margin_and_broker_support_them(self):
        result = self.preview("80000.01")
        self.assertEqual(10, result.ladder_lots)
        self.assertEqual(10, result.ceiling_lots)
        self.assertEqual(650, result.ceiling_contracts)
        self.assertIsNone(result.blocked_reason)

    def test_single_order_broker_limit_cannot_be_silently_split(self):
        result = self.preview("90000", broker_cap=65)
        self.assertEqual(1, result.broker_single_order_lots)
        self.assertEqual(65, result.ceiling_contracts)

    def test_affordability_uses_executable_option_ask_and_fee_reserve(self):
        result = self.preview("20000.01", ask="100", broker_cap=650)
        # floor((20000.01 - 150) / (100 * 65)) = 3 whole lots
        self.assertEqual(4, result.ladder_lots)
        self.assertEqual(3, result.ceiling_lots)
        self.assertEqual(195, result.ceiling_contracts)

    def test_equity_tier_does_not_override_broker_available_margin(self):
        result = self.preview("100000", basis="account_equity", margin="12000")
        self.assertEqual(10, result.ladder_lots)
        self.assertEqual(3, result.ceiling_lots)

    def test_available_margin_basis_rejects_inconsistent_input_fields(self):
        result = self.preview("25000", margin="12000")
        self.assertEqual("CAPITAL_AND_AVAILABLE_MARGIN_DISAGREE", result.blocked_reason)
        self.assertEqual(0, result.ceiling_contracts)

    def test_invalid_funds_ask_and_lot_size_fail_closed(self):
        for capital in (None, True, "NaN", "Infinity", -1, 0):
            with self.subTest(capital=capital):
                self.assertEqual(0, self.preview(capital).ceiling_contracts)
        self.assertEqual(0, self.preview("60000", ask="NaN").ceiling_contracts)
        self.assertEqual(0, self.preview("60000", ask="0").ceiling_contracts)
        self.assertEqual(0, self.preview("60000", lot_size=0).ceiling_contracts)
        self.assertEqual(0, self.preview("60000", broker_cap=0).ceiling_contracts)
        self.assertEqual(0, self.preview("60000", basis="unresolved").ceiling_contracts)

    def test_exact_fee_reserve_boundary(self):
        cost = Decimal("65") * Decimal("100")
        result = self.preview(cost + Decimal("150"), ask="100")
        self.assertEqual(1, result.affordable_lots)
        self.assertEqual(65, result.ceiling_contracts)
        below = self.preview(cost + Decimal("149.99"), ask="100")
        self.assertEqual(0, below.ceiling_contracts)

    def test_strange_broker_quantity_does_not_round_up(self):
        result = self.preview("90000", broker_cap=129)
        self.assertEqual(1, result.broker_single_order_lots)
        self.assertEqual(65, result.ceiling_contracts)


if __name__ == "__main__":
    unittest.main()
