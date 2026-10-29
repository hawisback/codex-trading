"""Offline OMS recovery contract tests. Authored but NOT executed."""

import tempfile
import unittest
from pathlib import Path

from trading.domain.intent_transitions import (
    IntentPhase, InvalidIntentTransition, OrderIntentView, transition,
)
from trading.adapters.gateways.journal import GatewayJournal


class IntentTransitionTests(unittest.TestCase):
    def initial(self):
        return OrderIntentView.from_mapping(
            dict(request_id="req-1", symbol="NIFTY-TEST", kind="ENTRY",
                 phase="PREPARED"), account_id="demo-account", mode="PAPER")

    def test_unknown_never_becomes_ack_without_verified_order_identity(self):
        sent = transition(self.initial(), IntentPhase.SENT)
        unknown = transition(sent, IntentPhase.UNKNOWN)
        with self.assertRaises(InvalidIntentTransition):
            transition(unknown, IntentPhase.ACKNOWLEDGED)
        acknowledged = transition(unknown, IntentPhase.ACKNOWLEDGED,
                                  verified_broker_order_id="broker-1")
        self.assertEqual("broker-1", acknowledged.broker_order_id)
        final = transition(acknowledged, IntentPhase.RECONCILED)
        self.assertEqual(IntentPhase.RECONCILED, final.phase)

    def test_terminal_and_illegal_phase_transitions_rejected(self):
        with self.assertRaises(InvalidIntentTransition):
            transition(self.initial(), IntentPhase.RECONCILED)
        with self.assertRaises(InvalidIntentTransition):
            transition(self.initial(), IntentPhase.ACKNOWLEDGED)
        a = transition(self.initial(), IntentPhase.UNKNOWN)
        b = transition(a, IntentPhase.ACKNOWLEDGED,
                       verified_broker_order_id="broker-1")
        with self.assertRaises(InvalidIntentTransition):
            transition(b, IntentPhase.RECONCILED,
                       verified_broker_order_id="different")

    def test_identity_and_broker_mode_are_explicit(self):
        with self.assertRaises(InvalidIntentTransition):
            OrderIntentView.from_mapping(
                dict(request_id="request", symbol="NIFTY", kind="ENTRY",
                     phase="PREPARED"), account_id="", mode="LIVE")
        with self.assertRaises(InvalidIntentTransition):
            OrderIntentView.from_mapping(
                dict(request_id="request", symbol="NIFTY", kind="ENTRY",
                     phase="PREPARED"), account_id="demo", mode="UNVERIFIED")


class DurableGatewayJournalTests(unittest.TestCase):
    def test_sequential_process_views_do_not_erase_other_intents(self):
        # A lock is now acquired on EVERY journal put; two independent
        # gateway objects must reload before appending.
        workspace = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory(prefix=".journal-contract-", dir=workspace) as directory:
            path = Path(directory) / "orders.json"
            first = GatewayJournal(path, "kite")
            second = GatewayJournal(path, "kite")
            first.bind("TEST-ACCOUNT")
            second.bind("TEST-ACCOUNT")
            first.put("request-A", phase="PREPARED", kind="ENTRY", symbol="NIFTY-TEST")
            second.put("request-B", phase="PREPARED", kind="ENTRY", symbol="NIFTY-TEST")
            self.assertEqual({"request-A", "request-B"}, set(first.records))
            self.assertEqual({"request-A", "request-B"}, set(second.records))


if __name__ == "__main__":
    unittest.main()
