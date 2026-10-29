"""Frozen strategy/data contracts; all AI verdicts come from real evaluation."""

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_consultant import AIConsultant
from market_clock import MarketClock
from test_self_healing_exit import entry_dossier
from tests.scenarios import (
    ROOT,
    NOW,
    STRATEGIES,
    INTELLIGENCE,
    market_responses,
    make_trader,
    context_variants,
    extra_contexts,
    approved_contexts,
    normalize_verdict,
)
from trading.application.market_context import MarketContextService
from trading.application.entry import EntryWorkflow
from trading.models import CandidateSignal
from trading.strategies.registry import StrategyRegistry
from trading.configuration import load_configuration
from trading.replay import ReplayService


class StagedParityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".staged-test-", dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "active.json"
        clock = patch.object(MarketClock, "now_ist", return_value=MarketClock.parse_to_ist(NOW))
        clock.start()
        self.addCleanup(clock.stop)
        monotonic = patch("time.monotonic", return_value=100)
        monotonic.start()
        self.addCleanup(monotonic.stop)
        self.reference = json.loads(
            (ROOT / "tests/fixtures/staged_reference.json").read_text(encoding="utf-8")
        )

    def test_market_data_formulas_fallbacks_and_call_order_match_baseline(self):
        trader = make_trader(self.path)
        for variant, expected in self.reference["contexts"].items():
            with self.subTest(variant=variant):
                payloads, calls = market_responses(), []
                if variant == "empty_candles":
                    payloads["/nifty/candles?interval=1m&limit=375"] = {"candles": []}
                if variant == "missing_ema":
                    payloads["/nifty/technicals?interval=5m&limit=50"] = {"metrics": {}}

                def read(path, **kwargs):
                    calls.append([path, kwargs])
                    if (variant == "heavyweights_error" and path == "/heavyweights") or (
                        variant == "snapshot_error" and path == "/nifty/snapshot"
                    ):
                        raise TimeoutError("fixture")
                    return copy.deepcopy(payloads[path])

                def funds():
                    calls.append(["funds", {}])
                    if variant == "funds_error":
                        raise TimeoutError("fixture")
                    return {"available_margin": 10000}

                with (
                    patch.object(trader, "market_data", new=read),
                    patch.object(trader.client, "get_funds", side_effect=funds),
                ):
                    try:
                        actual = {"result": trader.fetch_market_context(monitor_only=variant == "monitor")}
                    except Exception as exc:
                        actual = {"error": type(exc).__name__, "detail": str(exc)}
                self.assertEqual(expected, dict(actual, calls=calls))

    def test_all_strategy_decisions_and_actual_ai_verdicts_match_baseline(self):
        base = self.reference["contexts"]["normal"]["result"]
        for strategy in STRATEGIES:
            trader = make_trader(self.path, strategy)
            for name, context in context_variants(base).items():
                with self.subTest(strategy=strategy, scenario=name):
                    decision = trader.analyze(copy.deepcopy(context), copy.deepcopy(INTELLIGENCE))
                    verdict = None
                    if decision["signal"] in ("BUY_CE", "BUY_PE"):
                        dossier = trader.build_dossier(context, decision, [], 0, copy.deepcopy(INTELLIGENCE))
                        verdict = normalize_verdict(trader.ai_consultant.evaluate(dossier))
                    self.assertEqual(
                        self.reference["decisions"][strategy + ":" + name],
                        dict(decision=decision, verdict=verdict),
                    )

    def test_actual_ai_traps_and_current_exceptions_match_baseline(self):
        cases = {
            "normal": {},
            "vwap_blender": {"vwap_blender_warning": True},
            "penny_0dte": {"is_expiry_0dte": True, "option_entry_price": 10},
            "v_reversal": {"direction": "PE", "rsi_1m": 65},
            "box_ceiling": {"ceiling_floor_hazard": True, "compression_hazard": True},
            "preserve_capital": {"capital_preservation_active": True},
            "compressed_ribbon_current_policy": {"ribbon_compression_hazard": True, "ema_spread_5m": 2},
            "counter_flow": {"is_counter_trend_slope": True},
            "climax_cap": {"vwap_distance_pts": 80},
            "late_day": {
                "minutes_from_open": 310,
                "session_phase": "LATE_DAY_SQUAREOFF",
                "minutes_to_close": 65,
            },
        }
        for name, changes in cases.items():
            with self.subTest(scenario=name):
                dossier = entry_dossier(67)
                for key, value in changes.items():
                    setattr(dossier, key, value)
                self.assertEqual(
                    self.reference["verdicts"][name], normalize_verdict(AIConsultant().evaluate(dossier))
                )

    def test_climax_setups_and_margin_fallback_match_original_method_fixtures(self):
        expected = json.loads(
            (ROOT / "tests/fixtures/staged_extra_reference.json").read_text(encoding="utf-8")
        )
        trader = make_trader(self.path, "ai_opportunity_radar")
        replay = ReplayService(load_configuration("ai_opportunity_radar", "playbook"))
        for name, context in extra_contexts(self.reference["contexts"]["normal"]["result"]).items():
            with self.subTest(scenario=name):
                decision = trader.analyze(context, copy.deepcopy(INTELLIGENCE))
                verdict = None
                if decision["signal"] in ("BUY_CE", "BUY_PE"):
                    verdict = normalize_verdict(
                        trader.ai_consultant.evaluate(
                            trader.build_dossier(context, decision, [], 0, copy.deepcopy(INTELLIGENCE))
                        )
                    )
                self.assertEqual(expected[name], dict(decision=decision, verdict=verdict))
                result = replay.evaluate(context, copy.deepcopy(INTELLIGENCE), now=NOW)
                if result["verdict"]:
                    result["verdict"]["timestamp"] = "<host-wall-clock>"
                self.assertEqual(expected[name], dict(decision=result["decision"], verdict=result["verdict"]))

    def test_monitor_read_budget_stops_further_requests(self):
        calls = []
        times = iter((100, 100, 105))

        def read(path, **kwargs):
            calls.append(path)
            return market_responses()[path]

        service = MarketContextService(
            read, lambda: {"available_margin": 10000}, monotonic=lambda: next(times)
        )
        with self.assertRaisesRegex(TimeoutError, "Structural monitor read budget exhausted"):
            service.fetch(monitor_only=True)
        self.assertEqual(["/nifty/snapshot"], calls)

    def test_registry_extensions_still_pass_the_actual_ai_veto(self):
        class Proposal:
            def evaluate(self, ctx, intel=None):
                return CandidateSignal("BUY_CE", ["fixture extension"], "TREND_PULLBACK")

        registry = StrategyRegistry()
        registry.register("institutional_pullback", lambda cfg, radar, evaluator: Proposal())
        trader = make_trader(self.path)
        trader.strategy_registry = registry
        context = self.reference["contexts"]["normal"]["result"]
        decision = trader.analyze(context, copy.deepcopy(INTELLIGENCE))
        with patch.object(trader, "build_dossier", return_value=entry_dossier(67, vwap_distance_pts=80)):
            EntryWorkflow().run(trader, context, decision, [], 0, copy.deepcopy(INTELLIGENCE))
        self.assertEqual("VETOED", decision["ai_verdict"]["action"])
        self.assertFalse(any(call[0] == "POST" for call in trader.client.calls))

    def test_approved_call_and_put_candidates_match_original_functions_for_every_strategy(self):
        expected = json.loads(
            (ROOT / "tests/fixtures/staged_approved_reference.json").read_text(encoding="utf-8")
        )
        for strategy in STRATEGIES:
            trader = make_trader(self.path, strategy)
            replay = ReplayService(load_configuration(strategy, "playbook"))
            for name, context in approved_contexts(self.reference["contexts"]["normal"]["result"]).items():
                with self.subTest(strategy=strategy, scenario=name):
                    decision = trader.analyze(context, copy.deepcopy(INTELLIGENCE))
                    verdict = trader.ai_consultant.evaluate(
                        trader.build_dossier(context, decision, [], 0, copy.deepcopy(INTELLIGENCE))
                    )
                    self.assertEqual("APPROVED", verdict.action)
                    reference = expected[strategy + ":" + name]
                    self.assertEqual(reference, dict(decision=decision, verdict=normalize_verdict(verdict)))
                    result = replay.evaluate(context, copy.deepcopy(INTELLIGENCE), now=NOW)
                    result["verdict"]["timestamp"] = "<host-wall-clock>"
                    self.assertEqual(reference, dict(decision=result["decision"], verdict=result["verdict"]))
