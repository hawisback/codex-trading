"""Offline companion transport/publication checks; no broker or real model call."""

from concurrent.futures import ThreadPoolExecutor
import copy
from datetime import datetime, timedelta
import json
import io
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import ai_consultant as ac
from execution_safety import atomic_save
from market_clock import IST_TZ, MarketClock
from test_self_healing_exit import entry_dossier
from trading.adapters.codex_judgment import CodexJudgment
from trading.application.companion_worker import CompanionWorker
from trading.domain.companion_contract import (
    CompanionError,
    judgment_schema,
    pending_consultation,
    strict_json,
    validate_judgment,
)

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 30, 10, 0, tzinfo=IST_TZ)


def pending(kind="ENTRY", *, request_id="REQUEST-1", now=NOW):
    dossier = dict(
        synthetic=True,
        direction="CE",
        fill_price=100,
        current_spot=23000,
        active_stop_price=75,
        request_id=request_id,
        trade_id="TRADE-1",
        risk_policy=dict(
            initial_stop_pct=25, min_loss_pct=15, max_loss_pct=20, min_invalidation_buffer_pts=25
        ),
    )
    result = dict(
        status="AWAITING_VERDICT" if kind == "ENTRY" else "AWAITING_STOP_LOSS",
        request_id=request_id,
        created_at=now.isoformat(),
        timeout_seconds=45,
        dossier=dossier,
        evaluation_rubric="Synthetic offline fixture; enforce frozen policy.",
    )
    result["candidate_id" if kind == "ENTRY" else "trade_id"] = (
        "CANDIDATE-1" if kind == "ENTRY" else "TRADE-1"
    )
    if kind == "ENTRY":
        result.update(
            authoritative_risk_policy=dict(initial_stop_pct=25),
            proposed_entry_band=dict(min_entry_price=90, max_entry_price=105, approval_ttl_seconds=15),
        )
    return result


def judgment(kind="ENTRY", *, request_id="REQUEST-1"):
    result = dict(
        kind=kind, request_id=request_id, reasoning="Synthetic fixture judgment", trailing="standard"
    )
    if kind == "ENTRY":
        result.update(candidate_id="CANDIDATE-1", action="APPROVED", confidence=88, trap=None)
    else:
        result.update(trade_id="TRADE-1", action="ADJUST", stop_price=82, spot_invalidation=22975)
    return result


class FakeModel:
    def __init__(self):
        self.calls, self.errors, self.gates = [], {}, {}

    def generate(self, packet, schema, deadline, cancel):
        self.calls.append((copy.deepcopy(packet), schema, deadline))
        gate = self.gates.get(packet["kind"])
        while gate is not None and not gate.is_set():
            if cancel.wait(0.005):
                raise CompanionError("MODEL_CANCELLED")
        if packet["request_id"] in self.errors:
            raise CompanionError(self.errors[packet["request_id"]])
        result = judgment(packet["kind"], request_id=packet["request_id"])
        subject = "candidate_id" if packet["kind"] == "ENTRY" else "trade_id"
        result[subject] = packet[subject]
        return json.dumps(result)


class CompanionContractTests(unittest.TestCase):
    def test_both_closed_schemas_require_ids_and_forbid_extra_fields(self):
        for kind in ("ENTRY", "STOP"):
            schema = judgment_schema(kind)
            self.assertFalse(schema["additionalProperties"])
            self.assertEqual(set(schema["properties"]), set(schema["required"]))
            request = pending_consultation(kind, pending(kind), NOW)
            self.assertEqual(kind, validate_judgment(request, judgment(kind))["kind"])

    def test_missing_stale_future_and_conflicting_deadlines_fail_closed(self):
        valid = pending()
        for changes in (
            dict(created_at=(NOW - timedelta(seconds=45)).isoformat()),
            dict(created_at=(NOW + timedelta(seconds=1)).isoformat()),
            dict(created_at="2026-10-30T10:00:00"),
            dict(timeout_seconds=True),
            dict(timeout_seconds=46),
            dict(timeout_seconds="45"),
            dict(timeout_seconds=float("nan")),
            dict(expires_at_timestamp=(NOW + timedelta(seconds=44)).timestamp()),
            dict(candidate_id=None),
            dict(dossier={}),
        ):
            with self.subTest(changes=changes), self.assertRaises(CompanionError):
                pending_consultation("ENTRY", {**valid, **changes}, NOW)

    def test_malformed_model_output_is_never_repaired_into_an_approval(self):
        request = pending_consultation("ENTRY", pending(), NOW)
        for changes in (
            dict(candidate_id="OLD"),
            dict(request_id="OLD"),
            dict(confidence=True),
            dict(confidence=100.1),
            dict(action="BUY_NOW"),
            dict(trailing="unknown"),
            dict(submitted_at=NOW.isoformat()),
            dict(reasoning=""),
            dict(trap=[]),
        ):
            with self.subTest(changes=changes), self.assertRaises(CompanionError):
                validate_judgment(request, {**judgment(), **changes})
        for text in ('{"action":"VETOED","action":"APPROVED"}', '{"confidence":NaN}', '{"price":Infinity}'):
            with self.assertRaises(CompanionError):
                strict_json(text)

    def test_explicit_trap_dominates_model_approval(self):
        request = pending_consultation("ENTRY", pending(), NOW)
        self.assertEqual("VETOED", validate_judgment(request, {**judgment(), "trap": "Trap 8"})["action"])

    def test_stop_hold_cannot_smuggle_a_price_change(self):
        request = pending_consultation("STOP", pending("STOP"), NOW)
        for changes in (
            dict(stop_price=True),
            dict(stop_price=None),
            dict(stop_price=float("nan")),
            dict(trade_id="OLD"),
            dict(action="HOLD"),
        ):
            with self.subTest(changes=changes), self.assertRaises(CompanionError):
                validate_judgment(request, {**judgment("STOP"), **changes})
        self.assertEqual(
            "HOLD",
            validate_judgment(
                request, {**judgment("STOP"), "action": "HOLD", "stop_price": None, "spot_invalidation": None}
            )["action"],
        )


class CompanionWorkerTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="companion-", dir=ROOT / ".tools/tmp")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        (self.root / "config").mkdir()
        (self.root / "logs").mkdir()
        (self.root / "AGENTS.md").write_text("Synthetic fixture charter: judgment only.", encoding="utf-8")
        (self.root / "config/rules_playbook.md").write_text(
            "Synthetic fixture rules; no removed Trap 1 veto.", encoding="utf-8"
        )
        self.now = NOW
        clock = patch.object(MarketClock, "now_ist", side_effect=lambda: self.now)
        clock.start()
        self.addCleanup(clock.stop)
        self.model = FakeModel()
        self.events = []
        self.worker = self.new_worker()

    def new_worker(self):
        worker = CompanionWorker(
            self.root, self.model, now=lambda: self.now, event=lambda **event: self.events.append(event)
        )
        self.addCleanup(worker.close)
        return worker

    def put(self, kind="ENTRY", **kwargs):
        payload = pending(kind, now=self.now, **kwargs)
        name = "pending_consultation.json" if kind == "ENTRY" else "pending_stop_loss.json"
        atomic_save(self.root / "logs" / name, payload)
        return pending_consultation(kind, payload, self.now)

    def finish(self):
        deadline = time.monotonic() + 2
        while any(not job.future.done() for job in self.worker.jobs.values()):
            if time.monotonic() >= deadline:
                self.fail("Fixture model did not complete")
            threading.Event().wait(0.005)
        self.worker.tick()

    def test_remains_armed_for_multiple_entries_and_stops(self):
        for kind, identity in (("ENTRY", "E1"), ("STOP", "S1"), ("ENTRY", "E2")):
            request = self.put(kind, request_id=identity)
            self.worker.tick()
            self.finish()
            self.assertEqual("SUBMITTED", self.worker.state["requests"][request.identity]["status"])
        self.assertEqual(3, len(self.model.calls))
        self.worker.tick()
        self.assertEqual(3, len(self.model.calls))
        result = json.loads((self.root / "logs/ai_verdict.json").read_text())
        self.assertEqual("E2", result["request_id"])
        self.assertEqual(88, result["confidence"])
        self.assertEqual(self.now.isoformat(), result["submitted_at"])

    def test_stop_slot_is_not_blocked_by_a_running_entry(self):
        gate = self.model.gates["ENTRY"] = threading.Event()
        self.put("ENTRY")
        self.worker.tick()
        self.put("STOP", request_id="STOP-URGENT")
        self.worker.tick()
        self.assertEqual({"ENTRY", "STOP"}, set(self.worker.jobs))
        self.worker.jobs["STOP"].future.result(timeout=1)
        self.worker.tick()
        self.assertTrue((self.root / "logs/ai_stop_verdict.json").exists())
        self.assertFalse((self.root / "logs/ai_verdict.json").exists())
        gate.set()
        self.finish()

    def test_model_errors_keep_worker_armed_for_next_request(self):
        self.model.errors["FAILED"] = "RATE_LIMITED"
        failed = self.put(request_id="FAILED")
        self.worker.tick()
        self.finish()
        self.assertEqual("FAILED_NO_VERDICT", self.worker.state["requests"][failed.identity]["status"])
        self.assertFalse((self.root / "logs/ai_verdict.json").exists())
        self.put(request_id="NEXT")
        self.worker.tick()
        self.finish()
        self.assertTrue((self.root / "logs/ai_verdict.json").exists())

    def test_restart_does_not_reinvoke_an_already_claimed_request(self):
        request = self.put()
        self.worker._record(request, "INVOKING")
        self.worker.close()
        self.worker = self.new_worker()
        self.worker.tick()
        self.assertEqual([], self.model.calls)
        self.put(request_id="NEW-AFTER-RESTART")
        self.worker.tick()
        self.finish()
        self.assertEqual(1, len(self.model.calls))

    def test_late_response_is_discarded(self):
        request = self.put()
        packet, sources = self.worker.packet(request)
        self.assertIn("evaluation_rubric", packet)
        self.now += timedelta(seconds=45)
        with self.assertRaises(CompanionError):
            self.worker.publish(request, json.dumps(judgment()), sources)
        self.assertFalse((self.root / "logs/ai_verdict.json").exists())

    def test_replaced_request_or_changed_policy_cannot_publish(self):
        request = self.put()
        _, sources = self.worker.packet(request)
        self.put(request_id="REPLACEMENT")
        with self.assertRaises(CompanionError):
            self.worker.publish(request, json.dumps(judgment()), sources)
        request = self.put()
        _, sources = self.worker.packet(request)
        (self.root / "config/rules_playbook.md").write_text("Changed policy", encoding="utf-8")
        with self.assertRaisesRegex(CompanionError, "POLICY_CHANGED"):
            self.worker.publish(request, json.dumps(judgment()), sources)
        self.assertFalse((self.root / "logs/ai_verdict.json").exists())

    def test_existing_manual_veto_is_not_overwritten(self):
        request = self.put()
        _, sources = self.worker.packet(request)
        veto = dict(request_id=request.request_id, candidate_id=request.subject_id, action="VETOED")
        atomic_save(self.root / "logs/ai_verdict.json", veto)
        with self.assertRaisesRegex(CompanionError, "VERDICT_ALREADY_PUBLISHED"):
            self.worker.publish(request, json.dumps(judgment()), sources)
        self.assertEqual(veto, json.loads((self.root / "logs/ai_verdict.json").read_text()))

    def test_stop_hold_and_invalid_refinement_leave_protection_unchanged(self):
        request = self.put("STOP")
        _, sources = self.worker.packet(request)
        hold = {**judgment("STOP"), "action": "HOLD", "stop_price": None, "spot_invalidation": None}
        self.assertEqual("HOLD_PROTECTION_RETAINED", self.worker.publish(request, json.dumps(hold), sources))
        self.assertFalse((self.root / "logs/ai_stop_verdict.json").exists())
        for price in (70, 90):
            with self.assertRaises(ValueError):
                self.worker.publish(request, json.dumps({**judgment("STOP"), "stop_price": price}), sources)
        self.assertFalse((self.root / "logs/ai_stop_verdict.json").exists())

    def test_generation_budget_reserves_handoff_and_never_resets_request_age(self):
        self.put()
        self.now += timedelta(seconds=10)
        started = time.monotonic()
        self.worker.tick()
        self.finish()
        deadline = self.model.calls[0][2]
        self.assertLessEqual(deadline - started, 33.5)
        self.assertGreater(deadline - started, 32)

    def test_application_helper_checks_expected_snapshot_and_prior_verdict(self):
        request = self.put()
        path, out = self.root / "logs/pending_consultation.json", self.root / "logs/ai_verdict.json"
        changed = {**request.payload, "candidate_id": "CHANGED"}
        atomic_save(path, changed)
        with self.assertRaises(ValueError):
            ac.submit_entry_verdict(
                request.request_id,
                "APPROVED",
                expected_pending=request.payload,
                pending_path=path,
                verdict_path=out,
            )
        self.assertFalse(out.exists())

    def test_model_packet_redacts_broker_credentials_without_rebinding_identity(self):
        request = self.put()
        request.payload["dossier"]["api_key"] = "DO-NOT-FORWARD"
        packet, _ = self.worker.packet(request)
        self.assertEqual("[REDACTED]", packet["dossier"]["api_key"])
        self.assertEqual(request.request_id, packet["request_id"])

    def test_r01_packet_has_one_initial_stop_authority_and_no_legacy_refinement_band(self):
        request = self.put()
        request.payload["authoritative_risk_policy"].update(
            source="R01_UNIFIED", post_fill_refinement_enabled=False
        )
        packet, _ = self.worker.packet(request)
        self.assertEqual(packet["authoritative_risk_policy"], packet["dossier"]["risk_policy"])
        self.assertEqual(25, packet["dossier"]["risk_policy"]["initial_stop_pct"])
        self.assertNotIn("min_loss_pct", packet["dossier"]["risk_policy"])

    def test_real_chat_consultant_accepts_worker_handoff_with_fifteen_second_ttl(self):
        paths = dict(
            PENDING_FILE_JSON=self.root / "logs/pending_consultation.json",
            PENDING_FILE_MD=self.root / "logs/pending_consultation.md",
            VERDICT_FILE=self.root / "logs/ai_verdict.json",
        )
        from contextlib import ExitStack

        config = dict(
            execution=dict(ai_approval_ttl_seconds=15, max_entry_candidate_age_seconds=60),
            option_selection=dict(max_option_premium=200),
        )
        strategy = dict(exit=dict(initial_stop_pct=25), entry=dict(min_invalidation_buffer_pts=25))
        with ExitStack() as stack:
            for key, value in paths.items():
                stack.enter_context(patch.object(ac, key, value))
            consultant = ac.AIConsultant(
                mode="chat", timeout_seconds=45, trading_config=config, strategy_config=strategy
            )
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(consultant.evaluate, entry_dossier(67))
                deadline = time.monotonic() + 3
                while not future.done() and time.monotonic() < deadline:
                    self.worker.tick()
                    threading.Event().wait(0.01)
                verdict = future.result(timeout=1)
        self.assertEqual("APPROVED", verdict.action)
        self.assertEqual((NOW + timedelta(seconds=15)).isoformat(), verdict.entry_valid_until)
        self.assertTrue(verdict.request_id)
        self.assertTrue(verdict.candidate_id)


class CodexTransportTests(unittest.TestCase):
    def test_command_uses_cli_schema_and_disables_execution_surfaces(self):
        with patch("shutil.which", return_value="codex.exe"):
            backend = CodexJudgment(ROOT)
        command = backend.command(ROOT, ROOT / "schema.json", ROOT / "result.json")
        self.assertIn("--ignore-user-config", command)
        self.assertIn("read-only", command)
        self.assertIn("shell_tool", command)
        self.assertIn("--output-schema", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
        with patch.dict(
            "os.environ", {
                "KITE_ACCESS_TOKEN": "never-forward",
                "BREEZE_API_SECRET": "never-forward",
                "TRADING_API_KEY": "never-forward",
                "trading_api_key": "never-forward",
                "PATH": "keep-runtime-path",
            }, clear=True
        ):
            environment = backend.environment()
        self.assertNotIn("KITE_ACCESS_TOKEN", environment)
        self.assertNotIn("BREEZE_API_SECRET", environment)
        self.assertNotIn("TRADING_API_KEY", environment)
        self.assertNotIn("trading_api_key", environment)
        self.assertEqual("keep-runtime-path", environment["PATH"])

    def test_cli_reports_missing_executable_without_exposing_arbitrary_error_text(self):
        from tools import codex_companion

        for message, expected_code in (
            ("CODEX_EXECUTABLE_NOT_FOUND", "CODEX_EXECUTABLE_NOT_FOUND"),
            ("sensitive-value-must-not-be-printed", None),
        ):
            with self.subTest(message=message), patch.object(
                codex_companion, "CodexJudgment", side_effect=CompanionError(message)
            ), patch("sys.stdout", new_callable=io.StringIO) as output:
                self.assertEqual(2, codex_companion.main(["--check"]))
                report = json.loads(output.getvalue())
                self.assertEqual(expected_code, report.get("error_code"))
                self.assertNotIn("sensitive-value", output.getvalue())

    def test_deadline_kills_model_before_any_output_can_be_used(self):
        from unittest.mock import Mock

        with patch("shutil.which", return_value="codex.exe"):
            backend = CodexJudgment(ROOT)
        process = Mock()
        process.poll.return_value = None
        with patch("subprocess.Popen", return_value=process), patch("time.monotonic", side_effect=[0, 2]):
            with self.assertRaisesRegex(CompanionError, "DEADLINE_EXPIRED"):
                backend.generate({"synthetic": True}, judgment_schema("ENTRY"), 1, threading.Event())
        process.kill.assert_called_once()
        process.wait.assert_called_once_with(timeout=2)

    def test_model_failure_or_preexisting_cancellation_has_no_fallback_approval(self):
        from unittest.mock import Mock

        with patch("shutil.which", return_value="codex.exe"):
            backend = CodexJudgment(ROOT)
        cancel = threading.Event()
        cancel.set()
        with patch("subprocess.Popen") as launch:
            with self.assertRaises(CompanionError):
                backend.generate({}, judgment_schema("ENTRY"), time.monotonic() + 5, cancel)
        launch.assert_not_called()
        process = Mock(returncode=1)
        process.poll.return_value = 1
        with patch("subprocess.Popen", return_value=process):
            with self.assertRaisesRegex(CompanionError, "PROCESS_FAILED"):
                backend.generate({}, judgment_schema("ENTRY"), time.monotonic() + 5, threading.Event())
        process.kill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
