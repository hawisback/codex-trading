"""OTM fallback selection with the real purchasing-power calculator, offline."""

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from trading.application.dossier import DossierService
from trading.application.selection import CandidateSelectionService
from trading.domain.sizing import calculate_compounding_quantity
from trading.models import CandidateSignal

ROOT = Path(__file__).resolve().parents[1]


class OtmSelectionTests(unittest.TestCase):
    def setUp(self):
        self.strategy_cfg = json.loads((ROOT / "config/strategies.json").read_text())["strategies"][
            "macd_momentum"
        ]
        # Exercise legacy ATM/OTM fallback independently of the active strict-ITM policy.
        self.strategy_cfg["entry"]["strike_selection"] = "ATM_ROUNDED"
        self.trading_cfg = json.loads((ROOT / "config/trading.json").read_text())
        self.atm = 22700

    def context(self, direction="CE", prices=(180, 160, 140, 124.95, 115, 100), margin=8500):
        sign = 1 if direction == "CE" else -1
        key = "call" if direction == "CE" else "put"
        return dict(
            spot=self.atm,
            atm_strike=self.atm,
            available_margin=margin,
            strikes=[
                dict(
                    strike=self.atm + sign * step * 50,
                    **{
                        key: dict(
                            ltp=price,
                            instrument_id=f"EXACT-{step}-{direction}",
                            symbol=f"NIFTY-{step}-{direction}",
                        )
                    },
                )
                for step, price in enumerate(prices)
            ],
        )

    def analyze(self, ctx, direction="CE", max_otm=4, quantity_calculator=None):
        trading = copy.deepcopy(self.trading_cfg)
        trading["option_selection"]["max_otm_strikes"] = max_otm

        def quantity(margin, price):
            return calculate_compounding_quantity(
                margin, price, strategy_cfg=self.strategy_cfg, trading_cfg=trading, quantity=65, environ={}
            )

        strategy = SimpleNamespace(
            evaluate=lambda *a, **kw: CandidateSignal(
                "BUY_" + direction, ["Selection fixture"], "MACD_2M_MOMENTUM", self.atm - 15
            )
        )
        service = CandidateSelectionService(
            "macd_momentum", self.strategy_cfg, 65, quantity_calculator or quantity, strategy, trading
        )
        return service.analyze(ctx)

    def test_selects_22850_ce_after_two_over_cap_otm_strikes(self):
        decision = self.analyze(self.context())
        self.assertEqual("BUY_CE", decision["signal"])
        self.assertEqual(22850, decision["target_strike"])
        self.assertEqual("EXACT-3-CE", decision["instrument_id"])
        self.assertEqual("NIFTY-3-CE", decision["symbol"])
        self.assertEqual(124.95, decision["ltp"])
        self.assertEqual(65, decision["order_qty"])
        self.assertEqual(65, decision["quantity"])
        self.assertAlmostEqual(8121.75, decision["ltp"] * decision["order_qty"])
        self.assertIn("selected 3-strike OTM 22850", decision["reasons"][-1])
        dossier = DossierService({}).build_dossier(
            dict(self.context(), ema_9=self.atm, ema_20=self.atm), decision, [], 0
        )
        self.assertEqual(decision["instrument_id"], dossier.instrument_id)
        self.assertEqual(22850, dossier.strike)
        self.assertEqual(124.95, dossier.option_entry_price)
        self.assertNotIn("ai_verdict", decision)

    def test_puts_scan_downward_and_keep_the_selected_put_identity(self):
        decision = self.analyze(self.context("PE"), "PE")
        self.assertEqual("BUY_PE", decision["signal"])
        self.assertEqual(22550, decision["target_strike"])
        self.assertEqual("EXACT-3-PE", decision["instrument_id"])

    def test_nearest_qualifying_strike_wins_even_if_later_contracts_are_cheaper(self):
        decision = self.analyze(self.context(prices=(180, 125, 120, 100, 90)))
        self.assertEqual(22750, decision["target_strike"])

    def test_fourth_strike_is_included_but_configured_limit_is_respected(self):
        ctx = self.context(prices=(180, 160, 150, 140, 125, 90))
        self.assertEqual(22900, self.analyze(ctx)["target_strike"])
        for limit in (0, 1, 2, 3):
            decision = self.analyze(ctx, max_otm=limit)
            self.assertEqual("NEUTRAL", decision["signal"])
            self.assertIsNone(decision["instrument_id"])
        ctx["strikes"][4]["call"]["ltp"] = 140
        self.assertEqual("NEUTRAL", self.analyze(ctx)["signal"])

    def test_one_lot_budget_includes_fee_reserve_and_accepts_exact_boundary(self):
        ctx = self.context(prices=(180, 100, 90), margin=6650)
        self.assertEqual(22750, self.analyze(ctx)["target_strike"])
        ctx["available_margin"] = 6649.99
        self.assertEqual(22800, self.analyze(ctx)["target_strike"])

    def test_missing_legs_invalid_prices_and_missing_identity_are_skipped(self):
        for changes in (
            dict(ltp=None),
            dict(ltp=0),
            dict(ltp=-1),
            dict(ltp=float("nan")),
            dict(ltp=float("inf")),
            dict(instrument_id=None),
            dict(symbol=None),
        ):
            ctx = self.context(prices=(180, 125, 124))
            ctx["strikes"][1]["call"].update(changes)
            self.assertEqual(22800, self.analyze(ctx)["target_strike"])
        for missing in ("strike", "leg"):
            ctx = self.context(prices=(180, 125, 124))
            if missing == "strike":
                ctx["strikes"].pop(1)
            else:
                ctx["strikes"][1].pop("call")
            self.assertEqual(22800, self.analyze(ctx)["target_strike"])

    def test_exhausted_budget_cannot_leave_a_zero_quantity_directional_candidate(self):
        decision = self.analyze(self.context(prices=(100,) * 6, margin=5000))
        self.assertEqual("NEUTRAL", decision["signal"])
        self.assertEqual(0, decision["order_qty"])
        self.assertIsNone(decision["instrument_id"])
        self.assertIn("INSUFFICIENT FUNDS VETO", decision["reasons"][-1])

    def test_whole_order_must_fit_even_when_one_lot_is_affordable(self):
        decision = self.analyze(self.context(), quantity_calculator=lambda *a: 130)
        self.assertEqual("NEUTRAL", decision["signal"])
        self.assertIsNone(decision["instrument_id"])


if __name__ == "__main__":
    unittest.main()
