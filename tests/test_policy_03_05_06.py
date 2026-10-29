"""Offline POL-03/05/06 acceptance cases, prepared but deliberately not executed."""

import json
from decimal import Decimal
from pathlib import Path
import unittest

from execution_safety import ReconciliationError
from entry_policy import EntryPolicy
from trading.domain.daily_risk import broker_filled_day_pnl, checked_limit, entry_risk_quantity
from trading.domain.structural_exit import existing_structural_breach

ROOT = Path(__file__).resolve().parents[1]
DAY = "2026-10-29"
SCOPE = {"mode": "LIVE", "account_id": "TEST-BROKER"}


def filled_order(kind, price, *, order_id, instrument="NIFTY-OPT", quantity=65):
    return dict(
        order_id=order_id, kind=kind, instrument_id=instrument,
        filled_quantity=quantity, average_price=price,
        created_at=DAY + "T10:15:00+05:30",
        account_id=SCOPE["account_id"], mode="LIVE", engine_owned=True,
    )


class ApprovedPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "config/trading.json").read_text(encoding="utf-8"))

    def test_penny_floor_removed_without_permitting_invalid_quote(self):
        policy = EntryPolicy.from_config(self.config)
        self.assertEqual(0.0, policy.min_premium)
        lower, upper = policy.band(12.0, "TREND_PULLBACK")
        self.assertLess(lower, 12.0)
        self.assertGreaterEqual(upper, 12.0)

    def test_5k_2k_and_10_caps_are_typed_and_global(self):
        self.assertEqual(Decimal("5000"), checked_limit(self.config, "max_daily_loss_rupees", 5000))
        self.assertEqual(Decimal("2000"), checked_limit(self.config, "max_planned_loss_per_trade_rupees", 2000))
        self.assertEqual(Decimal("10"), checked_limit(self.config, "max_trades_per_day", 10))
        with self.assertRaises(ReconciliationError):
            checked_limit({"risk": {"max_daily_loss_rupees": 10000}}, "max_daily_loss_rupees", 5000)

    def test_broker_fills_determine_realized_loss(self):
        orders = [
            filled_order("ENTRY", 100, order_id="B1"),
            filled_order("EXIT", 90, order_id="S1"),
        ]
        pnl, entries = broker_filled_day_pnl(
            orders, DAY, SCOPE, fee_cushion_per_entry=Decimal("150")
        )
        self.assertEqual(Decimal("-800"), pnl)
        self.assertEqual(1, entries)

    def test_three_losing_round_trips_trip_daily_cutoff(self):
        orders = []
        for index in range(3):
            orders.extend((
                filled_order("ENTRY", 100, order_id=f"B{index}"),
                filled_order("EXIT", 75, order_id=f"S{index}"),
            ))
        pnl, count = broker_filled_day_pnl(
            orders, DAY, SCOPE, fee_cushion_per_entry=Decimal("150")
        )
        self.assertEqual(3, count)
        self.assertLessEqual(pnl, Decimal("-5000"))
        self.assertEqual(0, entry_risk_quantity(
            candidate_qty=650, option_limit_price=100,
            observed_net_pnl=pnl, config=self.config,
        ))

    def test_unverified_broker_book_fails_closed(self):
        base = filled_order("ENTRY", 100, order_id="B1")
        for altered in (
            {**base, "average_price": None},
            {**base, "engine_owned": False},
            {**base, "account_id": "OTHER"},
            {**base, "created_at": ""},
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(ReconciliationError):
                    broker_filled_day_pnl([altered], DAY, SCOPE, fee_cushion_per_entry=Decimal("150"))
        with self.assertRaisesRegex(ReconciliationError, "flat exposure"):
            broker_filled_day_pnl([base], DAY, SCOPE, fee_cushion_per_entry=Decimal("150"))

    def test_loss_budget_never_raises_global_lot_limit(self):
        def cap(pnl, option):
            return entry_risk_quantity(
                candidate_qty=650, option_limit_price=option,
                observed_net_pnl=Decimal(pnl), config=self.config,
            )
        self.assertEqual(65, cap("0", 100))
        self.assertEqual(0, cap("-4900", 100))
        self.assertEqual(0, cap("-5000", 100))
        self.assertEqual(650, cap("0", 5))
        self.assertEqual(130, entry_risk_quantity(
            candidate_qty=130, option_limit_price=20,
            observed_net_pnl=Decimal("0"), config=self.config,
        ))

    def test_ce_pe_structure_rule_is_independent_of_strategy(self):
        self.assertTrue(existing_structural_breach(22970, 22975, "CE"))
        self.assertTrue(existing_structural_breach(23025, 23025, "PE"))
        self.assertFalse(existing_structural_breach(23010, 22975, "CE"))
        self.assertFalse(existing_structural_breach(23000, 23025, "PE"))
        for spot in (None, 0, float("nan"), float("inf")):
            self.assertFalse(existing_structural_breach(spot, 23000, "CE"))


if __name__ == "__main__":
    unittest.main()
