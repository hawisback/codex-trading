"""Offline-only ownership/intent model contracts for the R03 increment.

Tests deliberately prepared, not run. No broker, market or credential access.
"""

from pathlib import Path
import tempfile
import unittest

from execution_safety import ReconciliationError
from trading.adapters.account_lease import AccountExecutionLease, account_lock_path
from trading.domain.intent_state import (
    IntentPhase, needs_reconciliation, proposed_transition,
)

ROOT = Path(__file__).resolve().parents[1]


class AccountExecutionLeaseTests(unittest.TestCase):
    def test_same_broker_and_account_cannot_hold_two_leases(self):
        with tempfile.TemporaryDirectory(prefix=".r03-lease-", dir=ROOT) as directory:
            a = AccountExecutionLease("kite", "ACCOUNT-ONE", directory=directory)
            b = AccountExecutionLease("kite", "ACCOUNT-ONE", directory=directory)
            with a:
                self.assertTrue(a.held)
                with self.assertRaisesRegex(RuntimeError, "ownership"):
                    with b:
                        pass
                self.assertFalse(b.held)
            self.assertFalse(a.held)
            with b:
                self.assertTrue(b.held)

    def test_account_key_is_stable_and_does_not_reveal_account_identifier(self):
        with tempfile.TemporaryDirectory(prefix=".r03-lease-", dir=ROOT) as directory:
            path = account_lock_path("KITE", "ACCOUNT-ONE", directory=directory)
            self.assertEqual(path, account_lock_path("kite", "ACCOUNT-ONE", directory=directory))
            self.assertNotIn("ACCOUNT-ONE", path.name)
            self.assertNotEqual(path, account_lock_path("kite", "ACCOUNT-TWO", directory=directory))
            self.assertNotEqual(path, account_lock_path("breeze", "ACCOUNT-ONE", directory=directory))

    def test_missing_broker_account_identity_blocks_lock_creation(self):
        with tempfile.TemporaryDirectory(prefix=".r03-lease-", dir=ROOT) as directory:
            for broker, account in (("kite", ""), ("invalid", "ACCOUNT-ONE"),
                                    ("kite", None), ("kite", True)):
                with self.subTest(broker=broker, account=account):
                    with self.assertRaises(ValueError):
                        AccountExecutionLease(broker, account, directory=directory)

    def test_reentry_is_forbidden_until_released(self):
        with tempfile.TemporaryDirectory(prefix=".r03-lease-", dir=ROOT) as directory:
            lease = AccountExecutionLease("proxy", "PAPER-OWNER", directory=directory)
            with lease:
                with self.assertRaisesRegex(RuntimeError, "already held"):
                    lease.__enter__()
            with lease:
                self.assertTrue(lease.held)


class IntentPhaseTests(unittest.TestCase):
    def test_unknown_and_missing_phase_must_not_authorize_new_order(self):
        for value in (None, "PREPARED", "SENT", "UNKNOWN", "UNRECOGNIZED", ""):
            with self.subTest(value=value):
                self.assertTrue(needs_reconciliation(value))
        for value in ("ACKNOWLEDGED", "REJECTED", "RECONCILED"):
            self.assertFalse(needs_reconciliation(value))

    def test_prepare_and_acknowledgement_do_not_imply_fill(self):
        self.assertEqual(IntentPhase.PREPARED,
                         proposed_transition(None, "PREPARED"))
        self.assertEqual(IntentPhase.ACKNOWLEDGED,
                         proposed_transition("PREPARED", "ACKNOWLEDGED"))
        self.assertTrue(needs_reconciliation("SENT"))

    def test_unknown_cannot_be_declared_rejected_without_broker_proof(self):
        for next_phase in ("ACKNOWLEDGED", "REJECTED", "RECONCILED"):
            with self.subTest(next_phase=next_phase):
                with self.assertRaisesRegex(ReconciliationError, "verification"):
                    proposed_transition("UNKNOWN", next_phase)
                self.assertEqual(
                    next_phase,
                    proposed_transition(
                        "UNKNOWN", next_phase, broker_verified=True
                    ).value,
                )

    def test_reconcile_only_with_broker_evidence(self):
        with self.assertRaisesRegex(ReconciliationError, "evidence"):
            proposed_transition("ACKNOWLEDGED", "RECONCILED")
        self.assertEqual(
            IntentPhase.RECONCILED,
            proposed_transition("ACKNOWLEDGED", "RECONCILED", broker_verified=True),
        )

    def test_rejected_or_reconciled_is_terminal_and_unknown_phases_are_invalid(self):
        for current in ("REJECTED", "RECONCILED"):
            with self.assertRaisesRegex(ReconciliationError, "Invalid"):
                proposed_transition(current, "PREPARED")
        with self.assertRaisesRegex(ReconciliationError, "Unknown"):
            proposed_transition("PREPARED", "FILLED")


if __name__ == "__main__":
    unittest.main()
