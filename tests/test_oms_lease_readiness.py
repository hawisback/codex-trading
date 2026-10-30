"""Offline R02/R09 activation contract examples. NOT executed."""

import json
from pathlib import Path
import tempfile
import unittest

from trading.application.oms_ownership import AccountSessionLease, lease_path
from tools.refactor_readiness import inspect_configuration

ROOT = Path(__file__).resolve().parents[1]


class OmsAccountLeaseTests(unittest.TestCase):
    def test_single_account_lease_excludes_second_owner(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".lease-test-") as directory:
            self.assertEqual(
                lease_path(Path(directory), "KITE", "DEMO"),
                lease_path(Path(directory), "kite", "DEMO"),
            )
            first = AccountSessionLease(Path(directory), broker="kite", verified_account="DEMO")
            second = AccountSessionLease(Path(directory), broker="kite", verified_account="DEMO")
            with first:
                with self.assertRaises(RuntimeError):
                    with second:
                        pass
            with second:
                self.assertTrue(second.path.exists())

    def test_account_identity_cannot_be_empty(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".lease-test-") as directory:
            with self.assertRaises(ValueError):
                AccountSessionLease(Path(directory), broker="kite", verified_account="")


class RefactorReadinessTests(unittest.TestCase):
    def test_config_check_never_reports_production_ready(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix=".lease-test-") as directory:
            path = Path(directory) / "trading.json"
            path.write_text(
                json.dumps(
                    {
                        "mode": "LIVE",
                        "session": {"no_new_trade_after": "14:15", "force_exit_time": "15:15"},
                        "r01_policy": {"enabled": False},
                    }
                ),
                encoding="utf-8",
            )
            report = inspect_configuration(path)
            self.assertFalse(report["release_ready"])
            self.assertEqual("BLOCKED", report["status"])
            self.assertIn("REGRESSION_EVIDENCE_NOT_PROVIDED", report["blockers"])
            path.write_text(
                json.dumps(
                    {
                        "mode": "LIVE",
                        "session": {"no_new_trade_after": "14:45", "force_exit_time": "15:20"},
                        "r01_policy": {"enabled": True},
                    }
                ),
                encoding="utf-8",
            )
            invalid = inspect_configuration(path)
            self.assertIn("R01_ENABLED_REQUIRES_BROKER_UAT", invalid["blockers"])
            self.assertIn("ENTRY_CUTOFF_MISMATCH", invalid["blockers"])


if __name__ == "__main__":
    unittest.main()
