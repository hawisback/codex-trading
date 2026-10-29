"""Offline atomic journal intent transitions; not executed in this increment."""

from pathlib import Path
import tempfile
import unittest

from execution_safety import ReconciliationError
from trading.adapters.gateways.journal import GatewayJournal

ROOT = Path(__file__).resolve().parents[1]


class JournalIntentTransitionTests(unittest.TestCase):
    def _journal(self, path):
        journal = GatewayJournal(path, "kite")
        journal.bind("FAKE_ACCOUNT")
        return journal

    def test_prepared_unknown_requires_broker_evidence_to_resolve(self):
        with tempfile.TemporaryDirectory(prefix=".r04-phases-", dir=ROOT) as directory:
            path = Path(directory) / "intents.json"
            journal = self._journal(path)
            journal.put("ENTRY-1", kind="ENTRY", symbol="TEST", phase="PREPARED")
            self.assertEqual("UNKNOWN", journal.transition("ENTRY-1", "UNKNOWN")["phase"])
            with self.assertRaisesRegex(ReconciliationError, "verification"):
                journal.transition("ENTRY-1", "ACKNOWLEDGED", order_id="42")
            self.assertEqual("UNKNOWN", journal.records["ENTRY-1"]["phase"])
            ack = journal.transition(
                "ENTRY-1", "ACKNOWLEDGED", broker_verified=True, order_id="42"
            )
            self.assertEqual("ACKNOWLEDGED", ack["phase"])
            self.assertEqual("42", self._journal(path).records["ENTRY-1"]["order_id"])

    def test_missing_intent_cannot_be_transitioned_into_fake_order(self):
        with tempfile.TemporaryDirectory(prefix=".r04-phases-", dir=ROOT) as directory:
            journal = self._journal(Path(directory) / "intents.json")
            with self.assertRaisesRegex(ReconciliationError, "Missing durable"):
                journal.transition("NEVER-PREPARED", "ACKNOWLEDGED", broker_verified=True)
            self.assertFalse(journal.records)

    def test_illegal_or_duplicate_phase_update_leaves_evidence_unchanged(self):
        with tempfile.TemporaryDirectory(prefix=".r04-phases-", dir=ROOT) as directory:
            journal = self._journal(Path(directory) / "intents.json")
            journal.put("ENTRY-2", kind="ENTRY", symbol="TEST", phase="PREPARED")
            with self.assertRaisesRegex(ReconciliationError, "Invalid"):
                journal.transition("ENTRY-2", "RECONCILED", broker_verified=True)
            with self.assertRaisesRegex(ReconciliationError, "Duplicate phase"):
                journal.transition("ENTRY-2", "UNKNOWN", phase="REJECTED")
            self.assertEqual("PREPARED", journal.records["ENTRY-2"]["phase"])

    def test_stale_instance_reloads_before_advancing_existing_intent(self):
        with tempfile.TemporaryDirectory(prefix=".r04-phases-", dir=ROOT) as directory:
            path = Path(directory) / "intents.json"
            first = self._journal(path)
            second = self._journal(path)
            first.put("ENTRY-3", kind="ENTRY", symbol="TEST", phase="PREPARED")
            first.transition("ENTRY-3", "UNKNOWN")
            with self.assertRaisesRegex(ReconciliationError, "verification"):
                second.transition("ENTRY-3", "REJECTED")
            self.assertEqual("UNKNOWN", second.records["ENTRY-3"]["phase"])


if __name__ == "__main__":
    unittest.main()
