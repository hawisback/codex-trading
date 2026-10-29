"""Offline evidence-backed mutation recovery cases. NOT EXECUTED."""

from pathlib import Path
import tempfile
import unittest

from execution_safety import ReconciliationError
from trading.adapters.gateways.journal import GatewayJournal
from trading.domain.mutation_evidence import verified_mutation_evidence
from tests.test_gateways import GatewayTests

ROOT = Path(__file__).resolve().parents[1]


def context(kind="STOP", *, request_id="AI-STOP-1", **overrides):
    record = dict(order_id="S1", request_id=request_id, symbol="TEST",
                  kind=kind, mode="LIVE", account_id="FAKE_ACCOUNT",
                  variety="regular", engine_owned=True, quantity=65,
                  filled_quantity=0, status="TRIGGER_PENDING",
                  trigger_price=47, price=46)
    record.update(overrides)
    return record


def mutation(action="MODIFY_STOP", **overrides):
    record = dict(kind="MUTATION", mutation_action=action,
                  target_kind="STOP", target_order_id="S1",
                  target_quantity=65, symbol="TEST",
                  expected_trigger_price=47, expected_limit_price=46)
    record.update(overrides)
    return record


class PureMutationEvidenceTests(unittest.TestCase):
    def test_stop_modify_reconciles_only_when_both_prices_match(self):
        self.assertEqual(
            "CONFIRMED_RESTING_STOP_PRICES",
            verified_mutation_evidence(mutation(), context(),
                                       account_id="FAKE_ACCOUNT",
                                       original_request_id="AI-STOP-1")["effect"],
        )
        for order in (context(price=45), context(trigger_price=48),
                      context(status="OPEN"), context(filled_quantity=1)):
            self.assertIsNone(verified_mutation_evidence(
                mutation(), order, account_id="FAKE_ACCOUNT",
                original_request_id="AI-STOP-1",
            ))

    def test_cancelled_not_filled_does_not_prove_cancelled_with_partial_fill(self):
        record = mutation("CANCEL", expected_trigger_price=None, expected_limit_price=None)
        self.assertEqual("CANCELLED_ZERO_FILL", verified_mutation_evidence(
            record, context(status="CANCELLED"), account_id="FAKE_ACCOUNT",
            original_request_id="AI-STOP-1")["effect"])
        for status in ("FILLED", "OPEN", "REJECTED", "EXPIRED", "TRIGGER_PENDING"):
            self.assertIsNone(verified_mutation_evidence(
                record, context(status=status), account_id="FAKE_ACCOUNT",
                original_request_id="AI-STOP-1"))
        self.assertIsNone(verified_mutation_evidence(
            record, context(status="CANCELLED", filled_quantity=17),
            account_id="FAKE_ACCOUNT", original_request_id="AI-STOP-1"))

    def test_old_unparameterized_modify_cannot_be_cleared(self):
        self.assertIsNone(verified_mutation_evidence(
            mutation(expected_trigger_price=None), context(),
            account_id="FAKE_ACCOUNT", original_request_id="AI-STOP-1"))

    def test_exact_order_and_account_identity_is_required(self):
        for change in (
            {"account_id": "OTHER"}, {"request_id": "WRONG"},
            {"engine_owned": False}, {"symbol": "OTHER"},
            {"order_id": "S2"}, {"kind": "EXIT"}, {"mode": "PAPER"},
        ):
            with self.subTest(change=change), self.assertRaises(ReconciliationError):
                verified_mutation_evidence(
                    mutation(), context(**change), account_id="FAKE_ACCOUNT",
                    original_request_id="AI-STOP-1")

    def test_exit_reprice_requires_open_unfilled_order_at_exact_price(self):
        record = mutation("REPRICE_EXIT", target_kind="EXIT",
                          expected_trigger_price=None)
        self.assertEqual("CONFIRMED_OPEN_EXIT_PRICE", verified_mutation_evidence(
            record, context(kind="EXIT", status="OPEN"),
            account_id="FAKE_ACCOUNT", original_request_id="AI-STOP-1")["effect"])
        self.assertIsNone(verified_mutation_evidence(
            record, context(kind="EXIT", status="OPEN", price=45),
            account_id="FAKE_ACCOUNT", original_request_id="AI-STOP-1"))


class GatewayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = GatewayTests(methodName="test_default_is_unarmed_and_every_paper_mutation_is_blocked")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.gateway = self.fixture.gateway
        self.server = self.fixture.server
        self.fixture.seed(sell=0)
        self.server.orders["S1"]["status"] = "TRIGGER PENDING"

    def mutations(self):
        return [r for r in self.gateway.journal.records.values()
                if r.get("kind") == "MUTATION"]

    def test_cancel_ack_reconciles_only_after_broker_terminal_status(self):
        self.gateway.cancel_stop_loss("S1")
        self.assertEqual("ACKNOWLEDGED", self.mutations()[0]["phase"])
        report = self.gateway.reconcile_pending_mutations()
        self.assertEqual(1, len(report["resolved"]))
        self.assertFalse(report["positions_verified"])
        self.assertEqual("RECONCILED", self.mutations()[0]["phase"])
        self.assertEqual("CANCELLED_ZERO_FILL",
                         self.mutations()[0]["broker_evidence"]["effect"])

    def test_unknown_cancel_can_reconcile_without_retrying_network_mutation(self):
        reply = self.gateway._mutate_existing(
            "S1", lambda: {"error": True, "outcome_unknown": True},
            "STOP", action="CANCEL")
        self.assertTrue(reply["outcome_unknown"])
        self.server.orders["S1"]["status"] = "CANCELLED"
        before = len([call for call in self.server.calls if call[0] == "DELETE"])
        report = self.gateway.reconcile_pending_mutations()
        self.assertEqual(1, len(report["resolved"]))
        self.assertEqual("RECONCILED", self.mutations()[0]["phase"])
        self.assertEqual(before, len([call for call in self.server.calls if call[0] == "DELETE"]))

    def test_missing_or_partially_filled_target_remains_unresolved(self):
        self.gateway._mutate_existing(
            "S1", lambda: {"error": True, "outcome_unknown": True},
            "STOP", action="CANCEL")
        self.server.orders["S1"].update(status="CANCELLED", filled_quantity=5,
                                        average_price=46)
        report = self.gateway.reconcile_pending_mutations()
        self.assertEqual([], report["resolved"])
        self.assertEqual("UNKNOWN", self.mutations()[0]["phase"])
        self.server.orders.pop("S1")
        report = self.gateway.reconcile_pending_mutations()
        self.assertEqual([], report["resolved"])
        self.assertEqual(1, len(report["unresolved"]))

    def test_unknown_modify_clears_only_when_exact_broker_prices_observed(self):
        self.gateway._mutate_existing(
            "S1", lambda: {"error": True, "outcome_unknown": True},
            "STOP", action="MODIFY_STOP", expected_trigger_price=47,
            expected_limit_price=46)
        self.server.orders["S1"].update(trigger_price=47, price=45)
        self.assertEqual([], self.gateway.reconcile_pending_mutations()["resolved"])
        self.server.orders["S1"]["price"] = 46
        report = self.gateway.reconcile_pending_mutations()
        self.assertEqual(1, len(report["resolved"]))
        self.assertEqual("CONFIRMED_RESTING_STOP_PRICES",
                         self.mutations()[0]["broker_evidence"]["effect"])

    def test_prepared_crash_record_never_assumes_request_not_sent(self):
        self.gateway.journal.prepare_mutation(
            "crash-before-ack", target_order_id="S1", target_kind="STOP",
            action="MODIFY_STOP", symbol=self.gateway.get_order("S1")["symbol"],
            target_quantity=65, expected_trigger_price=47,
            expected_limit_price=46)
        self.server.orders["S1"].update(trigger_price=47, price=46)
        report = self.gateway.reconcile_pending_mutations()
        self.assertEqual(1, len(report["resolved"]))
        self.assertEqual("RECONCILED",
                         self.gateway.journal.records["crash-before-ack"]["phase"])

    def test_unknown_cancel_must_not_be_resent(self):
        self.gateway._mutate_existing(
            "S1", lambda: {"error": True, "outcome_unknown": True},
            "STOP", action="CANCEL")
        self.server.orders["S1"]["status"] = "TRIGGER PENDING"
        result = self.gateway.cancel_stop_loss("S1")
        self.assertIn("Unresolved mutation", result["detail"])
        self.assertEqual("UNKNOWN", self.mutations()[0]["phase"])


if __name__ == "__main__":
    unittest.main()
