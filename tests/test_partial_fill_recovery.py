"""Pure partial-fill exposure and stability checks. Offline only; NOT RUN."""
import unittest
from execution_safety import ReconciliationError
from trading.domain.mutation_evidence import (
    stable_order_fingerprint, verified_partial_cancel_exposure
)


def order(oid, kind, fill, status, *, qty=65, parent=None):
    return dict(order_id=oid, kind=kind, symbol="NIFTY-TEST",
                account_id="TEST", mode="LIVE", engine_owned=True,
                quantity=qty, filled_quantity=fill, status=status,
                request_id="R-" + oid, variety="regular",
                entry_order_id=parent)


class PartialFillBookTests(unittest.TestCase):
    def setUp(self):
        self.intent = dict(mutation_action="CANCEL", target_kind="STOP",
                           target_order_id="STOP1", target_quantity=65,
                           symbol="NIFTY-TEST")
        self.entry = order("BUY1", "ENTRY", 65, "FILLED")
        self.stop = order("STOP1", "STOP", 15, "CANCELLED", parent="BUY1")
        self.book = [self.entry, self.stop]
        self.positions = [dict(symbol="NIFTY-TEST", quantity=50,
                               account_id="TEST", mode="LIVE")]

    def reconcile(self, book=None, positions=None):
        return verified_partial_cancel_exposure(
            self.intent, self.stop, self.book if book is None else book,
            self.positions if positions is None else positions,
            account_id="TEST", original_request_id="R-STOP1")

    def test_partial_cancel_with_verified_residual(self):
        evidence = self.reconcile()
        self.assertEqual(15, evidence["verified_filled_quantity"])
        self.assertEqual(50, evidence["reconciled_remaining_exposure"])
        self.assertFalse(evidence["replacement_or_exit_authorized"])

    def test_mismatched_position_and_outstanding_sells_fail_closed(self):
        self.assertIsNone(self.reconcile(positions=[]))
        open_sell = order("STOP2", "STOP", 0, "TRIGGER_PENDING", parent="BUY1")
        self.assertIsNone(self.reconcile(book=self.book+[open_sell]))

    def test_missing_parent_and_foreign_order_fail_closed(self):
        missing_parent = dict(self.stop, entry_order_id=None)
        with self.assertRaises(ReconciliationError):
            self.reconcile(book=[self.entry, missing_parent])
        foreign = order("OTHER", "ENTRY", 1, "CANCELLED")
        foreign["engine_owned"] = False
        with self.assertRaises(ReconciliationError):
            self.reconcile(book=self.book+[foreign])

    def test_changed_order_book_fingerprint_detected(self):
        original = stable_order_fingerprint(self.book)
        self.assertNotEqual(original, stable_order_fingerprint([
            self.entry, dict(self.stop, filled_quantity=16)]))
        with self.assertRaises(ReconciliationError):
            stable_order_fingerprint([self.stop, self.stop])


if __name__ == "__main__":
    unittest.main()
