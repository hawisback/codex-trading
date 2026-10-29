"""Offline R06-R10 policy and provenance contract checks. Do NOT execute yet."""

import unittest
from datetime import datetime, timedelta, timezone

from trading.domain.pretrade_evidence import PreTradeEvidence, check_entry_evidence
from trading.domain.consultation_contract import ConsultationRecord, consultation_matches
from trading.domain.replay_provenance import (
    ReplayEvidenceError, ReplayManifest, canonical_sha256, reject_lookahead,
)
from trading.domain.audit_redaction import redact_for_audit
from trading.domain.incident_contract import classify_incident, IncidentSeverity


class RiskEvidenceTests(unittest.TestCase):
    def good(self):
        return dict(
            account_verified=True, consultation_verified=True,
            contract_identity_verified=True, quote_fresh=True,
            session_allows_entry=True, broker_funds_verified=True,
            no_unresolved_exposure=True, broker_limit_verified=True,
            loss_gate_passed=True, kill_switch_engaged=False,
            requested_quantity=65, lot_size=65, maximum_quantity=65,
            executable_option_price="100", available_margin="10000",
            fee_reserve="150",
        )

    def test_all_hard_evidence_required(self):
        self.assertTrue(check_entry_evidence(PreTradeEvidence(**self.good())).passed)
        for key in ("account_verified", "consultation_verified",
                    "contract_identity_verified", "quote_fresh",
                    "broker_funds_verified", "no_unresolved_exposure",
                    "loss_gate_passed"):
            with self.subTest(key=key):
                item = {**self.good(), key: False}
                self.assertFalse(check_entry_evidence(PreTradeEvidence(**item)).passed)

    def test_kill_switch_and_broker_affordability_are_independent(self):
        for key, value in (("kill_switch_engaged", True), ("available_margin", 100),
                           ("requested_quantity", 66)):
            result = check_entry_evidence(PreTradeEvidence(**{**self.good(), key: value}))
            self.assertFalse(result.passed)


class ConsultationEnvelopeTests(unittest.TestCase):
    def test_exact_contract_and_unused_fresh_verdict_required(self):
        now = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
        verdict = ConsultationRecord(
            verdict_id="v1", request_id="r1", instrument_id="NIFTY-TEST",
            account_id="TEST", action="APPROVED", trap_detected=False,
            valid_from=now - timedelta(seconds=10),
            valid_until=now + timedelta(seconds=5),
            min_price="70", max_price="100",
        )
        kwargs = dict(request_id="r1", instrument_id="NIFTY-TEST", account_id="TEST",
                      proposed_price="95", observed_at=now,
                      consumed_verdict_ids=frozenset())
        self.assertTrue(consultation_matches(verdict, **kwargs))
        self.assertFalse(consultation_matches(
            verdict, **{**kwargs, "instrument_id": "OTHER"}))
        self.assertFalse(consultation_matches(
            verdict, **{**kwargs, "consumed_verdict_ids": frozenset(("v1",))}))
        self.assertFalse(consultation_matches(
            verdict, **{**kwargs, "observed_at": now + timedelta(minutes=1)}))


class ReplayAndAuditTests(unittest.TestCase):
    def test_canonical_manifest_rejects_future_and_ambiguous_times(self):
        event = {"timestamp": "2026-10-29T10:30:00+05:30", "signal": "NONE"}
        digest = canonical_sha256({"policy": "test"})
        manifest = ReplayManifest.from_events(
            [event], source="offline-fixture", policy_hash=digest,
            calendar_hash=digest, fee_model_hash=digest)
        self.assertEqual("DECISION_ONLY", manifest.mode)
        self.assertEqual(1, manifest.event_count)
        with self.assertRaises(ReplayEvidenceError):
            reject_lookahead("2026-10-29T11:00:00+05:30",
                             "2026-10-29T10:30:00+05:30")
        with self.assertRaises(ReplayEvidenceError):
            canonical_sha256({"invalid": float("nan")})

    def test_audit_redaction_does_not_modify_original_data(self):
        data = {"scope": {"account_id": "real-account", "mode": "LIVE"},
                "headers": {"Authorization": "Bearer secret-value"},
                "metadata": [{"api_key": "value", "request_id": "request-123"}]}
        scrubbed = redact_for_audit(data)
        self.assertEqual("[REDACTED]", scrubbed["scope"]["account_id"])
        self.assertEqual("[REDACTED]", scrubbed["headers"]["Authorization"])
        self.assertEqual("[REDACTED]", scrubbed["metadata"][0]["api_key"])
        self.assertEqual("request-123", scrubbed["metadata"][0]["request_id"])
        self.assertEqual("real-account", data["scope"]["account_id"])

    def test_unknown_incident_is_critical_and_never_unblocks_entries(self):
        incident = classify_incident("UNRECOGNIZED_FAILURE")
        self.assertEqual(IncidentSeverity.CRITICAL, incident.severity)
        self.assertTrue(incident.new_entries_blocked)
        self.assertTrue(incident.position_state_unverified)


if __name__ == "__main__":
    unittest.main()
