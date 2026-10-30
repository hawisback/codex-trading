"""Offline configuration/reporting contracts; never arm a real broker."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from tools.brokers import inspect_broker, inspect_configuration, main

ROOT = Path(__file__).resolve().parents[1]


def paused_configuration():
    return {
        "mode": "LIVE",
        "auto_trade_enabled": False,
        "system_armed": True,
        "kill_switch": False,
        "r01_policy": {"enabled": True, "unified_stop_enabled": True},
    }


class BrokerDiagnosticTests(unittest.TestCase):
    def test_legacy_scenarios_use_isolated_controls_without_changing_operator_configuration(self):
        from tests.scenarios import make_trader

        operator_path = ROOT / "config/trading.json"
        original = operator_path.read_bytes()
        with TemporaryDirectory(dir=ROOT, prefix=".broker-report-test-") as directory:
            root = Path(directory)
            trader = make_trader(root / "active.json")
            self.assertFalse(trader.trading_cfg["r01_policy"]["enabled"])
            self.assertTrue(trader.trading_cfg["auto_trade_enabled"])
            self.assertIsNone(trader.entry_control_reader())
            controls = root / "scenario-trading.json"
            config = json.loads(controls.read_text(encoding="utf-8"))
            config["auto_trade_enabled"] = False
            controls.write_text(json.dumps(config), encoding="utf-8")
            self.assertEqual("AUTO_TRADE_DISABLED_OR_UNVERIFIED", trader.entry_control_reader())
        self.assertEqual(original, operator_path.read_bytes())

    def configuration_report(self, data):
        with TemporaryDirectory(dir=ROOT, prefix=".broker-report-test-") as directory:
            path = Path(directory) / "trading.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            return inspect_configuration(path)

    def test_nested_policy_and_live_configuration_remain_paused(self):
        report = self.configuration_report(paused_configuration())
        self.assertTrue(report["valid"])
        self.assertEqual("LIVE", report["configured_mode"])
        self.assertTrue(report["r01_policy"]["enabled"])
        self.assertTrue(report["r01_policy"]["unified_stop_enabled"])
        self.assertFalse(report["new_entries_enabled_by_config"])
        self.assertEqual("AUTO_TRADE_DISABLED_OR_UNVERIFIED", report["entry_block_reason"])

    def test_configuration_flags_are_reported_without_claiming_authorization(self):
        data = paused_configuration()
        data["auto_trade_enabled"] = True
        report = self.configuration_report(data)
        self.assertTrue(report["new_entries_enabled_by_config"])
        self.assertNotIn("live_authorized", report)
        data["kill_switch"] = True
        self.assertFalse(self.configuration_report(data)["new_entries_enabled_by_config"])
        data["kill_switch"] = False
        data["system_armed"] = False
        self.assertFalse(self.configuration_report(data)["new_entries_enabled_by_config"])

    def test_missing_or_string_boolean_controls_are_invalid(self):
        for key in ("auto_trade_enabled", "system_armed", "kill_switch"):
            for value in ("true", 1, None):
                with self.subTest(key=key, value=value):
                    data = paused_configuration()
                    data[key] = value
                    report = self.configuration_report(data)
                    self.assertFalse(report["valid"])
                    self.assertFalse(report["new_entries_enabled_by_config"])
        report = self.configuration_report({})
        self.assertFalse(report["valid"])
        self.assertIn("R01_ENABLED_INVALID", report["errors"])

    def test_r01_requires_unified_stop_and_nested_booleans(self):
        for policy in (
            None,
            {"enabled": "true", "unified_stop_enabled": True},
            {"enabled": True, "unified_stop_enabled": False},
        ):
            with self.subTest(policy=policy):
                data = paused_configuration()
                data["r01_policy"] = policy
                self.assertFalse(self.configuration_report(data)["valid"])

    def test_paper_configuration_does_not_report_live_entries_enabled(self):
        data = paused_configuration()
        data.update(mode="PAPER", auto_trade_enabled=True)
        report = self.configuration_report(data)
        self.assertTrue(report["valid"])
        self.assertFalse(report["new_entries_enabled_by_config"])
        self.assertEqual("CONFIGURED_MODE_NOT_LIVE", report["entry_block_reason"])

    def test_configuration_output_excludes_arbitrary_fields_and_parser_details(self):
        data = paused_configuration()
        marker = "SYNTHETIC_PRIVATE_VALUE"
        data.update(api_key=marker, account_id=marker)
        data["r01_policy"]["unrelated_secret"] = marker
        self.assertNotIn(marker, json.dumps(self.configuration_report(data)))
        data["mode"] = marker
        self.assertNotIn(marker, json.dumps(self.configuration_report(data)))
        with TemporaryDirectory(dir=ROOT, prefix=".broker-report-test-") as directory:
            path = Path(directory) / "trading.json"
            self.assertFalse(inspect_configuration(path)["valid"])
            path.write_text(marker, encoding="utf-8")
            self.assertEqual(
                {"valid": False, "errors": ["CONFIGURATION_UNREADABLE"]}, inspect_configuration(path)
            )

    def test_cli_reports_configured_live_and_diagnostic_paper_without_arming(self):
        gateway = Mock()
        gateway.get_status.return_value = dict(connected=True, mode="PAPER", live_authorized=False)
        gateway.get_funds.return_value = dict(available_margin=10000)
        gateway.get_positions.return_value = dict(positions=[])
        gateway.get_orders.return_value = dict(orders=[])
        configuration = self.configuration_report(paused_configuration())
        output = io.StringIO()
        with (
            patch("tools.brokers.create_execution_gateway", return_value=gateway),
            patch("tools.brokers.inspect_configuration", return_value=configuration),
            redirect_stdout(output),
        ):
            self.assertEqual(0, main(["--broker", "kite"]))
        report = json.loads(output.getvalue())
        self.assertTrue(report["read_only"])
        self.assertEqual("LIVE", report["configuration"]["configured_mode"])
        self.assertEqual("NOT_OBSERVED", report["scheduler_execution_status"])
        broker = report["brokers"][0]
        self.assertEqual("PAPER", broker["mode"])
        self.assertFalse(broker["live_authorized"])
        self.assertEqual("DIAGNOSTIC_GATEWAY_ONLY", broker["mode_scope"])
        self.assertEqual("BROKER_READS_ONLY", broker["ready_scope"])
        self.assertEqual(
            ["get_status", "get_funds", "get_positions", "get_orders"],
            [call[0] for call in gateway.method_calls],
        )

    def test_cli_fails_for_invalid_configuration_or_broker_read_failure(self):
        with (
            patch("tools.brokers.inspect_configuration", return_value={"valid": False}),
            patch("tools.brokers.inspect_broker", return_value={"ready": True}),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(1, main(["--broker", "kite"]))
        gateway = Mock()
        gateway.get_status.return_value = dict(connected=True, mode="PAPER", live_authorized=False)
        gateway.get_funds.return_value = dict(error=True)
        gateway.get_positions.return_value = dict(positions=[])
        gateway.get_orders.return_value = dict(orders=[])
        with patch("tools.brokers.create_execution_gateway", return_value=gateway):
            report = inspect_broker("kite")
        self.assertFalse(report["ready"])
        self.assertEqual(["funds"], report["failed_reads"])
        gateway.set_mode.assert_not_called()
