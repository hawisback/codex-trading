"""Policy acceptance scenarios for the approved global broker-margin lot ladder.

Not executed in the initial GitHub refactor. Offline, no broker connectivity.
"""

import copy
from decimal import Decimal
import json
from pathlib import Path
import unittest

from trading.domain.lot_policy import BrokerMarginLotPolicy
from trading.domain.sizing import calculate_compounding_quantity

ROOT = Path(__file__).resolve().parents[1]


class BrokerMarginLotPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config/trading.json").read_text(encoding="utf-8"))
        cls.strategies = json.loads((ROOT / "config/strategies.json").read_text(encoding="utf-8"))["strategies"]

    def test_inclusive_boundaries_and_ten_lot_hard_ceiling(self):
        policy = BrokerMarginLotPolicy.from_trading_config(self.config)
        examples = (
            (0, 0), (1, 2), (20000, 2), (Decimal("20000.01"), 4),
            (40000, 4), (Decimal("40000.01"), 6),
            (60000, 6), (Decimal("60000.01"), 8),
            (80000, 8), (Decimal("80000.01"), 10),
            (100000, 10), (2000000, 10),
        )
        for capital, expected in examples:
            with self.subTest(capital=capital):
                self.assertEqual(expected, policy.max_lots_for_margin(capital))

    def test_executable_option_price_can_reduce_tier(self):
        policy = BrokerMarginLotPolicy.from_trading_config(self.config)
        self.assertEqual(130, policy.quantity_for(20000, 100))
        self.assertEqual(65, policy.quantity_for(20000, 200))
        self.assertEqual(0, policy.quantity_for(20000, 400))
        self.assertEqual(650, policy.quantity_for(100000, 100))

    def test_reserve_and_exact_affordability_boundary(self):
        policy = BrokerMarginLotPolicy.from_trading_config(self.config)
        self.assertEqual(65, policy.quantity_for(6650, 100))
        self.assertEqual(0, policy.quantity_for(Decimal("6649.99"), 100))
        self.assertEqual(0, policy.quantity_for(150, 1))

    def test_invalid_price_and_funds_fail_closed(self):
        policy = BrokerMarginLotPolicy.from_trading_config(self.config)
        for capital in (None, True, "20000", -10, float("nan"), float("inf")):
            with self.subTest(capital=capital):
                self.assertEqual(0, policy.quantity_for(capital, 100))
        for price in (None, False, "100", 0, -0.01, float("nan"), float("inf")):
            with self.subTest(price=price):
                self.assertEqual(0, policy.quantity_for(20000, price))

    def test_missing_or_modified_owner_policy_never_defaults_to_riskier_sizing(self):
        for mutated in (
            {"risk": {}},
            {"risk": {"max_lots_per_trade": 10, "max_order_quantity": 650}},
            {"risk": dict(self.config["risk"], max_lots_per_trade=11)},
            {"risk": dict(self.config["risk"], max_order_quantity=1300)},
            {"risk": dict(self.config["risk"], available_margin_lot_tiers=[])},
        ):
            with self.subTest(mutated=mutated):
                self.assertEqual(
                    0, calculate_compounding_quantity(
                        100000, 100, strategy_cfg={}, trading_cfg=mutated, quantity=65
                    )
                )

    def test_all_strategies_share_the_same_broker_money_cap(self):
        for name, strategy in self.strategies.items():
            with self.subTest(name=name):
                self.assertEqual(
                    260, calculate_compounding_quantity(
                        40000, 100, strategy_cfg=strategy, trading_cfg=self.config,
                        quantity=65
                    )
                )
                self.assertEqual(
                    650, calculate_compounding_quantity(
                        200000, 100, strategy_cfg=strategy, trading_cfg=self.config,
                        quantity=65
                    )
                )

    def test_deep_copy_prevents_config_mutation(self):
        policy = BrokerMarginLotPolicy.from_trading_config(copy.deepcopy(self.config))
        self.assertEqual(520, policy.quantity_for(80000, 100))
        self.assertEqual(650, policy.quantity_for(80000.01, 100))


if __name__ == "__main__":
    unittest.main()
