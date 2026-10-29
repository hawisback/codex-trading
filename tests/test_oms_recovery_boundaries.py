"""Offline OMS recovery and stop-floor regression cases.

Prepared for review; intentionally not executed in this implementation turn.
No broker APIs are constructed. All journal paths remain inside test workspace.
"""

from pathlib import Path
import tempfile
import unittest

from execution_safety import ReconciliationError, SchedulerLock
from trading.application.reconciliation import reconciled_entry_balances
from trading.domain.protection import (
    entry_reference, existing_stop_floor, initial_stop_trigger,
)
from trading.adapters.gateways.journal import GatewayJournal

ROOT = Path(__file__).resolve().parents[1]


class ReconciliationBalanceTests(unittest.TestCase):
    def test_partial_fills_and_two_sells_preserve_verified_residual(self):
        state = {
            "entries": [
                {"order_id": "E1", "status": "PARTIAL", "quantity": 65, "filled_quantity": 45},
                {"order_id": "E2", "status": "FILLED", "quantity": 65, "filled_quantity": 65},
            ],
            "stops": [
                {"entry_order_id": "E1", "status": "FILLED", "quantity": 15, "filled_quantity": 15},
                {"parent_order_id": "E2", "status": "CANCELLED", "quantity": 25, "filled_quantity": 10},
            ],
            "exits": [
                {"entry_order_id": "E1", "status": "PARTIAL", "quantity": 20, "filled_quantity": 5},
            ],
        }
        self.assertEqual({"E1": 25, "E2": 55}, reconciled_entry_balances(state))

    def test_unrelated_sell_fill_blocks_reconciliation(self):
        state = {
            "entries": [{"order_id": "E1", "status": "FILLED", "quantity": 65}],
            "stops": [{"entry_order_id": "FOREIGN", "status": "FILLED", "quantity": 1}],
            "exits": [],
        }
        with self.assertRaisesRegex(ReconciliationError, "Cannot allocate SELL fills"):
            reconciled_entry_balances(state)

    def test_negative_exposure_from_duplicate_sells_blocks_reconciliation(self):
        state = {
            "entries": [{"order_id": "E1", "status": "FILLED", "quantity": 65}],
            "stops": [{"entry_order_id": "E1", "status": "FILLED", "quantity": 65}],
            "exits": [{"entry_order_id": "E1", "status": "FILLED", "quantity": 65}],
        }
        with self.assertRaisesRegex(ReconciliationError, "exceed tracked entry quantity"):
            reconciled_entry_balances(state)


class StopFloorBoundaryTests(unittest.TestCase):
    def test_stop_reference_accepts_legacy_parent_alias(self):
        self.assertEqual("E1", entry_reference({"parent_order_id": "E1"}))
        self.assertEqual("E2", entry_reference(
            {"entry_order_id": "E2", "parent_order_id": "OTHER"}
        ))

    def test_existing_stop_floor_preserves_desired_and_entry_stop_floor(self):
        state = {
            "entry_balances": {"E1": 65, "E2": 0},
            "stops": [
                {"entry_order_id": "E1", "trigger_price": 90.0, "status": "TRIGGER_PENDING"},
                {"entry_order_id": "E2", "trigger_price": 200.0, "status": "CANCELLED"},
            ],
            "desired_stop_trigger": 92.0,
        }
        self.assertEqual(92.0, existing_stop_floor(state))
        self.assertEqual(95.0, existing_stop_floor({
            **state, "desired_stop_trigger": 95.0
        }))

    def test_initial_stop_uses_existing_floor_and_tick_rounding(self):
        self.assertEqual(92.0, initial_stop_trigger(100.0, 30.0, 92.0))
        self.assertEqual(70.0, initial_stop_trigger(100.0, 30.0, 0.0))


class JournalOwnershipTests(unittest.TestCase):
    def test_interleaved_instances_preserve_all_intents(self):
        with tempfile.TemporaryDirectory(prefix=".r02-journal-", dir=ROOT) as directory:
            path = Path(directory) / "intents.json"
            first = GatewayJournal(path, "kite")
            second = GatewayJournal(path, "kite")
            first.bind("ACCOUNT")
            second.bind("ACCOUNT")
            first.put("ENTRY-1", kind="ENTRY", phase="PREPARED")
            second.put("STOP-1", kind="STOP", phase="UNKNOWN")
            # A previous in-memory snapshot must not overwrite a second writer.
            self.assertEqual({"ENTRY-1", "STOP-1"}, set(first.records))
            self.assertEqual({"ENTRY-1", "STOP-1"}, set(second.records))

    def test_writer_lock_rejects_uncoordinated_mutation(self):
        with tempfile.TemporaryDirectory(prefix=".r02-journal-", dir=ROOT) as directory:
            path = Path(directory) / "intents.json"
            journal = GatewayJournal(path, "kite")
            journal.bind("ACCOUNT")
            lock_path = path.with_name(path.name + ".writer.lock")
            with SchedulerLock(lock_path):
                with self.assertRaisesRegex(RuntimeError, "already holds"):
                    journal.put("ENTRY-1", kind="ENTRY", phase="PREPARED")
            self.assertFalse(path.exists())
            journal.put("ENTRY-1", kind="ENTRY", phase="PREPARED")
            self.assertEqual("PREPARED", journal.records["ENTRY-1"]["phase"])


if __name__ == "__main__":
    unittest.main()
