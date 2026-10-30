"""Configuration/startup contracts and workspace-local replay with actual AI."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from ai_consultant import AIConsultant
from backtest_engine import BacktestEngine
from market_clock import MarketClock
from tests.scenarios import ROOT, NOW, INTELLIGENCE, STRATEGIES, context_variants, legacy_configuration
from trading.adapters.historical import WorkspaceHistoricalSource, workspace_path
from trading.bootstrap import ensure_environment, load_environment_file
from trading.configuration import load_configuration
from trading.domain.indicators import exponential_average, simple_rsi, select_strike
from trading.domain.states import PositionStatus, is_exiting
from trading.replay import ReplayService
from test_self_healing_exit import Broker, Trader, approved_decision


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix=".config-test-", dir=ROOT)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "config").mkdir()
        self.strategy = {
            "active_strategy": "structural_runner",
            "strategies": {
                "structural_runner": {"entry": {"require_pullback": False}},
                "institutional_pullback": {"entry": {"require_pullback": True}},
            },
            "ai_consultation": {"default_mode": "chat", "timeout_seconds": 30},
        }
        (self.root / "config/strategies.json").write_text(json.dumps(self.strategy))
        (self.root / "config/trading.json").write_text('{"risk":{"max_order_quantity":65}}')

    def test_explicit_arguments_override_environment_then_config(self):
        settings = load_configuration(
            "institutional_pullback",
            "playbook",
            root=self.root,
            environ={"STRATEGY_MODE": "structural_runner", "AI_CONSULTATION_MODE": "interactive"},
        )
        self.assertEqual("institutional_pullback", settings.strategy_name)
        self.assertEqual("playbook", settings.ai_mode)
        self.assertEqual(30, settings.ai_timeout)
        self.assertEqual(65, settings.trading["risk"]["max_order_quantity"])

    def test_environment_and_fallback_precedence_remain(self):
        settings = load_configuration(
            root=self.root,
            environ={"STRATEGY_MODE": "institutional_pullback", "AI_CONSULTATION_MODE": "interactive"},
        )
        self.assertEqual("institutional_pullback", settings.strategy_name)
        self.assertEqual("interactive", settings.ai_mode)
        fallback = load_configuration("unknown", root=self.root, environ={})
        self.assertEqual("institutional_pullback", fallback.strategy_name)
        self.assertTrue(fallback.strategy["entry"]["require_pullback"])

    def test_missing_and_corrupt_config_keep_original_distinct_outcomes(self):
        trading = self.root / "config/trading.json"
        trading.write_text("{bad")
        self.assertEqual({}, load_configuration(root=self.root, environ={}).trading)
        (self.root / "config/strategies.json").write_text("{bad")
        with self.assertRaises(json.JSONDecodeError):
            load_configuration(root=self.root, environ={})
        (self.root / "config/strategies.json").unlink()
        settings = load_configuration(root=self.root, environ={})
        self.assertEqual("institutional_pullback", settings.strategy_name)
        self.assertEqual(30, settings.strategy["exit"]["initial_stop_pct"])

    def test_disabled_ai_is_still_rejected(self):
        with self.assertRaises(ValueError):
            load_configuration(ai_mode="disabled", root=self.root, environ={})

    def test_environment_loading_is_explicit_and_never_overwrites_process_values(self):
        env_file = self.root / ".env"
        env_file.write_text("# fixture\nSTAGE_TEST_VALUE=file\nSTAGE_TEST_SECOND=second\n")
        with patch.dict(os.environ, {"STAGE_TEST_VALUE": "process"}):
            os.environ.pop("STAGE_TEST_SECOND", None)
            load_environment_file(env_file)
            self.assertEqual("process", os.environ["STAGE_TEST_VALUE"])
            self.assertEqual("second", os.environ["STAGE_TEST_SECOND"])

    def test_ensure_environment_does_not_repeat_disk_reads(self):
        env_file = self.root / ".env"
        env_file.write_text("# fixture")
        ensure_environment(env_file)
        with patch("trading.bootstrap.load_environment_file", side_effect=AssertionError("repeat read")):
            ensure_environment(env_file)

    def test_core_imports_perform_no_application_file_or_worker_operations(self):
        script = """
import os, sys, threading
from unittest.mock import patch
before = dict(os.environ)
calls = []
class Stream:
    def __init__(self, original): self.original=original
    def __getattr__(self, name): return getattr(self.original, name)
    def reconfigure(self, **kwargs): calls.append(kwargs)
sys.stdout=Stream(sys.stdout);sys.stderr=Stream(sys.stderr)
with patch('builtins.open', side_effect=AssertionError('application file read')), \\
     patch('pathlib.Path.mkdir', side_effect=AssertionError('application mkdir')), \\
     patch('threading.Thread.start', side_effect=AssertionError('worker')), \\
     patch('urllib.request.urlopen', side_effect=AssertionError('network')):
    import nifty_trader_scheduler, ai_consultant, market_clock, execution_client
    import trading.application.scheduler, trading.replay, backtest_engine
assert dict(os.environ)==before
assert not calls
"""
        result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_list_strategies_cli_preserves_names_without_constructing_a_trader(self):
        import io
        import nifty_trader_scheduler as scheduler

        output = io.StringIO()
        with (
            patch("sys.argv", ["scheduler", "--list-strategies"]),
            patch("sys.stdout", output),
            patch.object(
                scheduler, "NiftyOptionsTrader", side_effect=AssertionError("unexpected construction")
            ),
        ):
            scheduler._main()
        for name in STRATEGIES:
            self.assertIn(name, output.getvalue())


class SharedCalculationTests(unittest.TestCase):
    def test_shared_indicators_match_pre_extraction_values_and_legacy_wrappers(self):
        cases = json.loads((ROOT / "tests/fixtures/indicators_reference.json").read_text())
        for case in cases:
            with self.subTest(prices=case["prices"]):
                self.assertEqual(
                    case["ema9"], exponential_average(case["prices"], 9, last_during_warmup=True)
                )
                self.assertEqual(case["ema9"], BacktestEngine.calculate_ema(case["prices"], 9))
                self.assertEqual(case["rsi14"], simple_rsi(case["prices"], 14))
                self.assertEqual(case["rsi14"], BacktestEngine.calculate_rsi(case["prices"], 14))

    def test_strike_selection_matches_legacy_contract_names_without_loading_data(self):
        engine = BacktestEngine.__new__(BacktestEngine)
        engine.target_date = "2026-10-19"
        for spot in (22999, 23000, 23025, 23049.95, 23050):
            for direction in ("CE", "PE"):
                for mode in ("STRICT_ITM", "ATM_ROUNDED"):
                    strike = select_strike(spot, direction, mode)
                    self.assertEqual(
                        (f"NIFTY_2026-10-19_{strike}_{direction}", strike),
                        engine.select_contract(spot, direction, mode),
                    )

    def test_state_names_keep_json_values_and_unknown_legacy_values(self):
        self.assertEqual('"OPEN"', json.dumps(PositionStatus.OPEN))
        self.assertEqual("OPEN", str(PositionStatus.OPEN))
        self.assertTrue(is_exiting({"status": "EXIT_UNKNOWN"}))
        self.assertFalse(is_exiting({"status": "FUTURE_LEGACY_STATUS"}))

    def test_confirmed_recovery_open_exit_and_flat_transitions_keep_their_wire_values(self):
        with (
            tempfile.TemporaryDirectory(prefix=".transition-test-", dir=ROOT) as directory,
            MarketClock.at(NOW),
        ):
            broker = Broker()
            broker.quote_ask = broker.fill_price = 67
            broker.lost_entry_response = True
            trader = Trader(Path(directory) / "position.json", broker)
            trader.execute_trade(approved_decision(trader.trading_cfg, 67))
            self.assertEqual(PositionStatus.ENTRY_PENDING.value, trader.load_active_position()["status"])
            trades, _ = trader.get_trades_state()
            self.assertEqual(PositionStatus.OPEN.value, trades[0]["status"])
            trader.exit_trade(trades[0]["trade_id"], "fixture")
            self.assertEqual(PositionStatus.EXIT_PENDING.value, trader.load_active_position()["status"])
            exit_order = next(order for order in broker.orders.values() if order["kind"] == "EXIT")
            exit_order.update(status="FILLED", filled_quantity=exit_order["quantity"])
            self.assertEqual([], trader.get_trades_state()[0])
            self.assertFalse(trader.position_store.exists())


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.reference = json.loads(
            (ROOT / "tests/fixtures/staged_reference.json").read_text(encoding="utf-8")
        )
        self.context = self.reference["contexts"]["normal"]["result"]

    def test_all_live_strategy_decisions_and_actual_ai_verdicts_replay_identically(self):
        for strategy in STRATEGIES:
            replay = ReplayService(legacy_configuration(strategy))
            self.assertIs(type(replay.ai_consultant), AIConsultant)
            for name, context in context_variants(self.context).items():
                with self.subTest(strategy=strategy, scenario=name):
                    result = replay.evaluate(context, copy.deepcopy(INTELLIGENCE), now=NOW)
                    verdict = result["verdict"]
                    if verdict:
                        verdict["timestamp"] = "<host-wall-clock>"
                    self.assertEqual(
                        self.reference["decisions"][strategy + ":" + name],
                        dict(decision=result["decision"], verdict=verdict),
                    )

    def test_replay_clock_is_nested_exception_safe_and_thread_local(self):
        live_year = MarketClock.now_ist().year
        with MarketClock.at(NOW):
            self.assertEqual("10:00", MarketClock.now_ist().strftime("%H:%M"))
            observed = []
            with MarketClock.at("2001-01-01T09:30:00+05:30"):
                thread = threading.Thread(target=lambda: observed.append(MarketClock.now_ist().year))
                thread.start()
                thread.join(2)
            with self.assertRaises(RuntimeError):
                with MarketClock.at("2001-01-01T09:30:00+05:30"):
                    raise RuntimeError("fixture")
            self.assertEqual("10:00", MarketClock.now_ist().strftime("%H:%M"))
            self.assertEqual([live_year], observed)
        with self.assertRaises(ValueError):
            with MarketClock.at("10:00:00"):
                pass

    def test_news_and_time_gates_and_actual_ai_timeout_preserve_cash(self):
        replay = ReplayService(legacy_configuration("institutional_pullback"))
        self.assertEqual(
            "INTELLIGENCE_UNAVAILABLE", replay.evaluate(self.context, {"ready": False}, now=NOW)["blocked"]
        )
        late = replay.evaluate(self.context, INTELLIGENCE, now="2026-10-19T15:15:00+05:30")
        self.assertIsNone(late["verdict"])
        self.assertIsNotNone(late["blocked"])
        replay.ai_consultant.timeout_seconds = 0
        expired = replay.evaluate(self.context, INTELLIGENCE, now=NOW)
        self.assertEqual("TIMEOUT_EXPIRED", expired["verdict"]["action"])
        self.assertEqual("AI_VETOED", expired["blocked"])

    def test_explicit_historical_source_does_not_open_any_database(self):
        with tempfile.TemporaryDirectory(prefix=".historical-test-", dir=ROOT) as directory:
            path = Path(directory) / "day.json"
            path.write_text(
                json.dumps(
                    {
                        "target_date": "2026-10-19",
                        "spot_candles": self.context["candles_1m"],
                        "options_data": {},
                        "is_synthetic_options": True,
                    }
                )
            )
            with patch("backtest_engine.sqlite3.connect", side_effect=AssertionError("database access")):
                engine = BacktestEngine("2026-10-19", data_source=WorkspaceHistoricalSource(path))
            self.assertEqual(self.context["candles_1m"], engine.spot_candles)
            self.assertTrue(engine.is_synthetic_options)

    def test_local_source_rejects_escape_before_reading(self):
        with tempfile.TemporaryDirectory(prefix=".scope-test-", dir=ROOT) as directory:
            with self.assertRaises(ValueError):
                workspace_path(ROOT / "AGENTS.md", root=directory)

    def test_replay_cli_creates_only_a_workspace_report_with_real_ai(self):
        from tools.replay import main

        with tempfile.TemporaryDirectory(prefix=".replay-cli-test-", dir=ROOT) as directory:
            report = Path(directory) / "report.json"
            self.assertEqual(
                0,
                main(
                    [
                        "tests/fixtures/replay_example.json",
                        "--strategy",
                        "institutional_pullback",
                        "--output",
                        str(report),
                    ]
                ),
            )
            evaluation = json.loads(report.read_text(encoding="utf-8"))["evaluations"][0]
            self.assertEqual("BUY_CE", evaluation["decision"]["signal"])
            expected = self.reference["decisions"]["institutional_pullback:bull"]["verdict"]
            self.assertEqual(expected["action"], evaluation["verdict"]["action"])
