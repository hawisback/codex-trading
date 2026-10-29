"""Offline native LIVE ownership and R01 funds-contract fixtures.

Author-only regression coverage. Do NOT run without the owner's separate
authorization; no fixture calls a real broker or opens an order.
"""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from execution_safety import ReconciliationError
from trading.adapters.gateways.base import BaseBrokerGateway
from trading.domain.broker_contracts import BrokerContractError, BrokerFundsView
from market_clock import IST_TZ
from datetime import datetime


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


class LiveFundsProofTests(unittest.TestCase):
    def test_receipt_metadata_alone_does_not_supply_broker_order_limit(self):
        now = datetime(2026, 10, 30, 10, 0, tzinfo=IST_TZ)
        sample = dict(
            account_id="DEMO-ACCOUNT", source="kite:user/margins:authenticated-receipt",
            funds_asof=now.isoformat(), available_margin="50000",
        )
        with self.assertRaises(BrokerContractError):
            BrokerFundsView.validated(sample, account_id="DEMO-ACCOUNT", now=now)
        sample["max_single_order_quantity"] = 65
        self.assertEqual(
            65,
            BrokerFundsView.validated(
                sample, account_id="DEMO-ACCOUNT", now=now
            ).max_single_order_quantity
        )


if __name__ == "__main__":
    unittest.main()
