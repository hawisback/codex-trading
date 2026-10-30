"""Offline native LIVE ownership and R01 funds-contract fixtures.

Author-only regression coverage. Do NOT run without the owner's separate
authorization; no fixture calls a real broker or opens an order.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from execution_safety import ReconciliationError
from trading.adapters.gateways.base import BaseBrokerGateway
from trading.domain.broker_contracts import BrokerContractError, BrokerFundsView
from trading.domain.daily_loss_policy import daily_loss_decision
from market_clock import IST_TZ
from datetime import datetime
from tests.gateway_lifecycle import end_gateway_process


ROOT = Path(__file__).resolve().parents[1]


class IsolatedGateway(BaseBrokerGateway):
    """No network; verifies the native BaseBrokerGateway arming boundary."""

    def __init__(self, path, account_id="DEMO-ACCOUNT"):
        self.demo_account = account_id
        super().__init__(broker_name="kite", journal_path=path)

    def is_connected(self):
        return True

    def get_account_id(self):
        return self.demo_account

    def get_contract_quote(self, instrument_id):
        raise AssertionError("OFFLINE_NO_QUOTE_TRANSPORT")

    def _fetch_broker_orders(self):
        return []

    def _fetch_broker_positions(self):
        return []

    def _fetch_broker_funds(self):
        return {"available_margin": 5000}

    def _submit_buy_order(self, *args):
        raise AssertionError("OFFLINE_NO_ORDER_TRANSPORT")

    def _submit_stop_loss(self, *args):
        raise AssertionError("OFFLINE_NO_ORDER_TRANSPORT")

    def _submit_modify_stop(self, *args):
        raise AssertionError("OFFLINE_NO_ORDER_TRANSPORT")

    def _submit_cancel_order(self, *args):
        raise AssertionError("OFFLINE_NO_ORDER_TRANSPORT")

    def _submit_exit_order(self, *args):
        raise AssertionError("OFFLINE_NO_ORDER_TRANSPORT")


class NativeAccountOwnerTests(unittest.TestCase):
    def test_released_gateway_cannot_borrow_replacement_lease(self):
        with TemporaryDirectory(dir=ROOT, prefix=".ownership-") as directory:
            one = IsolatedGateway(Path(directory) / "journal.json")
            two = IsolatedGateway(Path(directory) / "journal.json")
            try:
                self.assertTrue(one.set_mode("LIVE")["live_authorized"])
                # Retain the stale lease object to exercise exact ownership,
                # rather than merely looking for this path in a global set.
                one._account_lease.__exit__(None, None, None)
                self.assertTrue(two.set_mode("LIVE")["live_authorized"])
                self.assertFalse(one.get_status()["live_authorized"])
                with self.assertRaises(ReconciliationError):
                    one._authorize()
            finally:
                end_gateway_process(one)
                end_gateway_process(two)

    def test_inherited_gateway_cannot_authorize_or_unlock_parent_lease(self):
        with TemporaryDirectory(dir=ROOT, prefix=".ownership-") as directory:
            gate = IsolatedGateway(Path(directory) / "journal.json")
            try:
                self.assertTrue(gate.set_mode("LIVE")["live_authorized"])
                parent_pid = os.getpid()
                with patch("trading.application.oms_ownership.os.getpid", return_value=parent_pid + 1):
                    self.assertFalse(gate.get_status()["live_authorized"])
                    with self.assertRaises(ReconciliationError):
                        gate._authorize()
                    with self.assertRaisesRegex(RuntimeError, "another process"):
                        gate._account_lease.__exit__(None, None, None)
                self.assertTrue(gate.get_status()["live_authorized"])
            finally:
                end_gateway_process(gate)

    def test_only_one_gateway_can_arm_same_verified_account(self):
        with TemporaryDirectory(dir=ROOT, prefix=".ownership-") as directory:
            journal = Path(directory) / "journal.json"
            one = IsolatedGateway(journal)
            two = IsolatedGateway(journal)
            try:
                self.assertEqual("LIVE", one.set_mode("LIVE").get("mode"))
                result = two.set_mode("LIVE")
                self.assertTrue(result.get("error"))
                self.assertFalse(two._live_authorized)
                one.set_mode("PAPER")
                # A mid-process disarm is NOT confirmation of broker flatness,
                # therefore lease remains held until explicit operator cleanup.
                self.assertTrue(two.set_mode("LIVE").get("error"))
            finally:
                one.set_mode("PAPER")
                if one._account_lease is not None:
                    one._account_lease.__exit__(None, None, None)
                    one._account_lease = None

    def test_account_identity_change_revokes_transport_authorization(self):
        with TemporaryDirectory(dir=ROOT, prefix=".ownership-") as directory:
            gate = IsolatedGateway(Path(directory) / "journal.json")
            try:
                self.assertEqual("LIVE", gate.set_mode("LIVE").get("mode"))
                gate.demo_account = "OTHER-ACCOUNT"
                with self.assertRaises(ReconciliationError):
                    gate._authorize()
            finally:
                gate.set_mode("PAPER")
                if gate._account_lease is not None:
                    gate._account_lease.__exit__(None, None, None)
                    gate._account_lease = None


CHILD_OWNER = """
import json
from pathlib import Path
import sys
from tests.test_live_activation_guardrails import IsolatedGateway
from tests.gateway_lifecycle import end_gateway_process

root = Path(sys.argv[1])
gateway = IsolatedGateway(root / 'journal.json')
try:
    response = gateway.set_mode('LIVE')
    print(json.dumps(response), flush=True)
    if sys.argv[2] == 'hold' and response.get('live_authorized'):
        gateway.journal.put('crash-proof', kind='ENTRY', symbol='UNIT-CE', phase='REJECTED')
        (root / 'child-ready.json').write_text('ready', encoding='utf-8')
        sys.stdin.read()
finally:
    end_gateway_process(gateway)
"""


class NativeProcessOwnerTests(unittest.TestCase):
    def child_command(self, directory, mode):
        return [sys.executable, "-c", CHILD_OWNER, directory, mode]

    def test_independent_process_cannot_arm_held_account(self):
        with TemporaryDirectory(dir=ROOT, prefix=".ownership-process-") as directory:
            gate = IsolatedGateway(Path(directory) / "journal.json")
            try:
                self.assertTrue(gate.set_mode("LIVE")["live_authorized"])
                child = subprocess.run(
                    self.child_command(directory, "once"),
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                self.assertEqual(0, child.returncode, child.stderr)
                self.assertTrue(json.loads(child.stdout)["error"])
                self.assertTrue(gate.get_status()["live_authorized"])
            finally:
                end_gateway_process(gate)

    def test_process_crash_releases_os_lease_without_deleting_state(self):
        with TemporaryDirectory(dir=ROOT, prefix=".ownership-process-") as directory:
            gate = IsolatedGateway(Path(directory) / "journal.json")
            child = subprocess.Popen(
                self.child_command(directory, "hold"),
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            try:
                ready = Path(directory) / "child-ready.json"
                deadline = time.monotonic() + 10
                while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(ready.exists(), "Child did not acquire the lease before deadline")
                self.assertTrue(gate.set_mode("LIVE")["error"])
                child.kill()
                child.communicate(timeout=10)
                self.assertTrue(gate.set_mode("LIVE")["live_authorized"])
                self.assertTrue(gate.journal.path.exists())
                self.assertEqual("REJECTED", gate.journal.records["crash-proof"]["phase"])
                self.assertTrue(gate._account_lease.path.exists())
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=10)
                end_gateway_process(gate)


class LiveFundsProofTests(unittest.TestCase):
    def test_receipt_metadata_alone_does_not_supply_broker_order_limit(self):
        now = datetime(2026, 10, 30, 10, 0, tzinfo=IST_TZ)
        sample = dict(
            account_id="DEMO-ACCOUNT",
            source="kite:user/margins:authenticated-receipt",
            funds_asof=now.isoformat(),
            available_margin="50000",
        )
        with self.assertRaises(BrokerContractError):
            BrokerFundsView.validated(sample, account_id="DEMO-ACCOUNT", now=now)
        # Receipt provenance + margin is NOT evidence of a current-day
        # verified P&L baseline; do not mistake it for daily-loss approval.
        self.assertFalse(
            daily_loss_decision(
                sample,
                {"mode": "LIVE", "account_id": "DEMO-ACCOUNT"},
                now,
                lots=1,
            ).allowed
        )
        sample["max_single_order_quantity"] = 65
        self.assertEqual(
            65,
            BrokerFundsView.validated(sample, account_id="DEMO-ACCOUNT", now=now).max_single_order_quantity,
        )


if __name__ == "__main__":
    unittest.main()
