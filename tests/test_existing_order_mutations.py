"""Offline mutation write-ahead/recovery regressions (prepared, NOT RUN).

Uses existing in-memory Kite simulator and isolated test journal. Does not
connect to Kite, Breeze or a market feed and does not create live orders.
"""

from pathlib import Path
import tempfile
import unittest

from execution_safety import ReconciliationError
from trading.adapters.gateways.journal import GatewayJournal
from tests.test_gateways import GatewayTests


ROOT = Path(__file__).resolve().parents[1]


class MutationJournalAtomicityTests(unittest.TestCase):
    def test_distinct_mutation_does_not_alias_original_order_id(self):
        with tempfile.TemporaryDirectory(prefix=".mutation-intents-", dir=ROOT) as directory:
            journal = GatewayJournal(Path(directory) / "intents.json", "kite")
            journal.bind("FAKE_ACCOUNT")
            journal.put("original-stop", kind="STOP", symbol="TEST", order_id="S1",
                        phase="ACKNOWLEDGED")
            m = journal.prepare_mutation(
                "cancel-stop-1", target_order_id="S1", action="CANCEL",
                target_kind="STOP", symbol="TEST"
            )
            self.assertEqual("PREPARED", m["phase"])
            self.assertEqual("S1", m["target_order_id"])
            self.assertNotIn("order_id", m)
            self.assertEqual("original-stop", journal.match(order_id="S1")["request_id"])

    def test_second_writer_cannot_prepare_unknown_target_mutation(self):
        with tempfile.TemporaryDirectory(prefix=".mutation-intents-", dir=ROOT) as directory:
            path = Path(directory) / "intents.json"
            first, second = (GatewayJournal(path, "kite") for _ in range(2))
            first.bind("FAKE_ACCOUNT")
            second.bind("FAKE_ACCOUNT")
            first.prepare_mutation("modify-1", target_order_id="S1",
                                   action="MODIFY_STOP", target_kind="STOP",
                                   symbol="TEST")
            first.transition("modify-1", "UNKNOWN")
            with self.assertRaisesRegex(ReconciliationError, "Unresolved mutation"):
                second.prepare_mutation("modify-2", target_order_id="S1",
                                        action="MODIFY_STOP", target_kind="STOP",
                                        symbol="TEST")
            self.assertEqual("UNKNOWN", second.records["modify-1"]["phase"])
            self.assertNotIn("modify-2", second.records)

    def test_unrelated_target_not_blocked_by_local_unknown(self):
        with tempfile.TemporaryDirectory(prefix=".mutation-intents-", dir=ROOT) as directory:
            journal = GatewayJournal(Path(directory) / "intents.json", "kite")
            journal.bind("FAKE_ACCOUNT")
            journal.prepare_mutation("cancel-a", target_order_id="A",
                                     action="CANCEL", target_kind="ENTRY", symbol="TEST")
            journal.transition("cancel-a", "UNKNOWN")
            second = journal.prepare_mutation("cancel-b", target_order_id="B",
                                              action="CANCEL", target_kind="STOP", symbol="TEST")
            self.assertEqual("PREPARED", second["phase"])

    def test_phase_resolution_still_requires_external_broker_proof(self):
        with tempfile.TemporaryDirectory(prefix=".mutation-intents-", dir=ROOT) as directory:
            journal = GatewayJournal(Path(directory) / "intents.json", "kite")
            journal.bind("FAKE_ACCOUNT")
            journal.prepare_mutation("cancel-a", target_order_id="A",
                                     action="CANCEL", target_kind="ENTRY", symbol="TEST")
            journal.transition("cancel-a", "UNKNOWN")
            with self.assertRaisesRegex(ReconciliationError, "verification"):
                journal.transition("cancel-a", "RECONCILED")


class MutationGatewayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = GatewayTests(methodName="test_default_is_unarmed_and_every_paper_mutation_is_blocked")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.gateway = self.fixture.gateway
        self.server = self.fixture.server
        # Create an actual zero-fill protective STOP with its matching durable
        # placement intent. seed(sell=0) alone creates no S1 order.
        from trading.adapters.gateways.journal import broker_tag
        from test_self_healing_exit import SYMBOL
        self.fixture.seed(qty=65, sell=0)
        self.gateway.journal.put(
            "stop-full-request-id", kind="STOP", symbol=SYMBOL,
            order_id="S1", entry_order_id="E1", phase="ACKNOWLEDGED",
        )
        self.server.add(
            "S1", side="SELL", kind="SL", qty=65, filled=0,
            state="TRIGGER PENDING", tag=broker_tag("stop-full-request-id"),
            price=60,
        )

    def _mutations(self):
        return [r for r in self.gateway.journal.records.values()
                if r.get("kind") == "MUTATION"]

    def test_successful_cancel_is_separate_from_original_stop_identity(self):
        result = self.gateway.cancel_stop_loss("S1")
        self.assertFalse(result.get("error"), result)
        self.assertEqual("CANCELLED", self.server.orders["S1"]["status"])
        records = self._mutations()
        self.assertEqual(1, len(records))
        self.assertEqual("ACKNOWLEDGED", records[0]["phase"])
        self.assertEqual("S1", records[0]["target_order_id"])
        self.assertEqual("CANCEL", records[0]["mutation_action"])
        self.assertNotIn("order_id", records[0])
        self.assertEqual("E1", self.gateway.get_entry_ref_for_stop("S1"))

    def test_successful_modify_has_durable_ack(self):
        result = self.gateway.modify_stop_loss("S1", 47, 46)
        self.assertFalse(result.get("error"), result)
        self.assertEqual(47.0, self.server.orders["S1"]["trigger_price"])
        mutation, = self._mutations()
        self.assertEqual("MODIFY_STOP", mutation["mutation_action"])
        self.assertEqual("ACKNOWLEDGED", mutation["phase"])

    def test_unknown_modify_blocks_retry_until_broker_reconciliation(self):
        outcome = self.gateway._mutate_existing(
            "S1",
            lambda: {"error": True, "detail": "TIMEOUT", "outcome_unknown": True},
            "STOP", action="MODIFY_STOP",
            expected_trigger_price=48, expected_limit_price=47,
        )
        self.assertTrue(outcome["outcome_unknown"])
        self.assertEqual("UNKNOWN", self._mutations()[0]["phase"])
        result = self.gateway.modify_stop_loss("S1", 48, 47)
        self.assertIn("Unresolved mutation", result["detail"])
        self.assertEqual("TRIGGER PENDING", self.server.orders["S1"]["status"])
        self.assertEqual(1, len(self._mutations()))

    def test_explicit_preflight_veto_is_not_unknown(self):
        result = self.gateway.modify_stop_loss("S1", 44, 43)
        self.assertEqual("STOP_ALREADY_AT_OR_ABOVE_TARGET", result["detail"])
        self.assertFalse(result.get("outcome_unknown"))
        self.assertEqual("REJECTED", self._mutations()[0]["phase"])


if __name__ == "__main__":
    unittest.main()
