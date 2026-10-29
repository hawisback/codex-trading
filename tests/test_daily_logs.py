"""Offline observability checks; actual AI gates and simulated broker transports."""

import copy
import csv
from datetime import date, datetime
import gzip
import io
import json
import logging
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from execution_safety import SchedulerLock
from market_clock import MarketClock
from test_self_healing_exit import Broker, Trader, approved_decision, entry_dossier
from tests.scenarios import INTELLIGENCE, make_trader
from tools.logs import compress_runtime_logs, main as logs_main
from trading import audit
from trading.adapters.daily_logs import (
    DailyJournalHandler,
    DailyRuntimeHandler,
    ISTFormatter,
    completed_trade,
    rebuild_reports,
)
from trading.logging_setup import LoggingSession
from trading.application.entry import EntryWorkflow

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-19T10:00:00+05:30"


def closed_event():
    return {
        "event": "position_closed",
        "timestamp": NOW,
        "state": {
            "symbol": "TEST",
            "instrument_id": "TEST-ID",
            "quantity": 0,
            "entry_time": NOW,
            "scope": {"mode": "LIVE", "account_id": "TEST-ACCOUNT"},
            "entries": [
                {
                    "order_id": "E1",
                    "status": "FILLED",
                    "filled_quantity": 130,
                    "average_price": 67,
                    "charges": 10,
                }
            ],
            "stops": [
                {
                    "order_id": "S1",
                    "entry_order_id": "E1",
                    "status": "CANCELLED",
                    "filled_quantity": 65,
                    "average_price": 75,
                    "charges": 2,
                }
            ],
            "exits": [
                {
                    "order_id": "X1",
                    "entry_order_id": "E1",
                    "status": "FILLED",
                    "filled_quantity": 65,
                    "average_price": 85,
                    "charges": 3,
                }
            ],
        },
    }


class DailyLogsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".daily-logs-test-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_runtime_uses_record_ist_date_across_midnight_and_restarts(self):
        for run in range(2):
            handler = DailyRuntimeHandler(self.root)
            handler.setFormatter(ISTFormatter("%(asctime)s [%(name)s] %(message)s"))
            try:
                for instant, text in (
                    ("2026-10-19T18:29:59+00:00", "before"),
                    ("2026-10-19T18:30:00+00:00", "after"),
                ):
                    record = logging.LogRecord("test", logging.INFO, "", 1, f"{text}-{run}", (), None)
                    record.created = datetime.fromisoformat(instant).timestamp()
                    handler.handle(record)
            finally:
                handler.close()
        before = (self.root / "trader-2026-10-19.log").read_text(encoding="utf-8")
        after = (self.root / "trader-2026-10-20.log").read_text(encoding="utf-8")
        self.assertIn("2026-10-19T23:59:59.000+05:30", before)
        self.assertIn("before-0", before)
        self.assertIn("before-1", before)
        self.assertNotIn("after", before)
        self.assertIn("2026-10-20T00:00:00.000+05:30", after)

    def test_partial_stop_and_exit_use_actual_fills_and_known_charges(self):
        row = completed_trade(closed_event())
        self.assertEqual(130, row["quantity"])
        self.assertEqual(80, row["average_exit_price"])
        self.assertEqual(1690, row["gross_pnl"])
        self.assertEqual(15, row["charges"])
        self.assertEqual(1675, row["net_pnl"])

    def test_missing_fill_prices_and_charges_never_use_limit_prices(self):
        item = closed_event()
        del item["state"]["stops"][0]["average_price"]
        item["state"]["stops"][0]["limit_price"] = 999
        row = completed_trade(item)
        self.assertIsNone(row["gross_pnl"])
        self.assertIsNone(row["net_pnl"])
        item = closed_event()
        del item["state"]["exits"][0]["charges"]
        row = completed_trade(item)
        self.assertEqual(1690, row["gross_pnl"])
        self.assertIsNone(row["charges"])
        self.assertIsNone(row["net_pnl"])

    def test_definitively_rejected_stop_does_not_discard_a_later_completed_trade(self):
        item = closed_event()
        item["state"]["stops"].append({"status": "REJECTED", "request_id": "never-accepted"})
        self.assertEqual(1675, completed_trade(item)["net_pnl"])

    def test_pending_unknown_unbalanced_or_unconfirmed_records_are_not_trades(self):
        for change in (
            "pending",
            "quantity",
            "balance",
            "explicit_fill",
            "negative",
            "identity",
            "fractional",
            "duplicate",
        ):
            with self.subTest(change=change):
                item = closed_event()
                state = item["state"]
                if change == "pending":
                    state["exits"][0]["status"] = "OPEN"
                elif change == "quantity":
                    state["quantity"] = 65
                elif change == "balance":
                    state["exits"][0]["filled_quantity"] = 64
                elif change == "explicit_fill":
                    del state["entries"][0]["filled_quantity"]
                elif change == "negative":
                    state["exits"][0]["filled_quantity"] = -65
                elif change == "identity":
                    state["exits"][0]["entry_order_id"] = "OTHER"
                elif change == "fractional":
                    state["exits"][0]["filled_quantity"] = 65.5
                else:
                    state["exits"].append(copy.deepcopy(state["exits"][0]))
                self.assertIsNone(completed_trade(item))

    def write_journal(self, *items):
        directory = self.root / "daily/2026-10-19"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "events.jsonl").open("a", encoding="utf-8") as stream:
            for item in items:
                stream.write(json.dumps(item) + "\n")
        return directory

    def test_rebuild_is_idempotent_and_does_not_mix_paper_with_live(self):
        live = closed_event()
        paper = copy.deepcopy(live)
        paper["state"]["scope"]["mode"] = "PAPER"
        directory = self.write_journal(live, live, paper)
        first = rebuild_reports(directory)
        self.assertEqual(first, rebuild_reports(directory))
        self.assertEqual(1, first["by_mode"]["LIVE"]["completed_positions"])
        self.assertEqual(1, first["by_mode"]["PAPER"]["completed_positions"])
        with (directory / "trades.csv").open(newline="", encoding="utf-8") as stream:
            self.assertEqual(2, len(list(csv.DictReader(stream))))

    def test_empty_day_and_torn_last_line_remain_rebuildable(self):
        directory = self.write_journal({"event": "candidate"})
        summary = rebuild_reports(directory)
        self.assertEqual({}, summary["by_mode"])
        self.assertTrue((directory / "trades.csv").read_text().startswith("position_id,"))
        with (directory / "events.jsonl").open("ab") as stream:
            stream.write(b'{"event": "torn')
        record = logging.LogRecord("TradeAudit", logging.INFO, "", 1, "close", (), None)
        record.run_id = "restart"
        record.audit_event = closed_event()
        handler = DailyJournalHandler(self.root)
        handler.handle(record)
        handler.close()
        summary = json.loads((directory / "summary.json").read_text())
        self.assertEqual(1, summary["malformed_lines"])
        self.assertEqual(1, summary["by_mode"]["LIVE"]["completed_positions"])
        self.assertIn('"torn', (directory / "events.jsonl").read_text())

    def test_queued_snapshots_do_not_change_when_caller_mutates_them(self):
        session = LoggingSession(self.root).install()
        self.addCleanup(session.close)
        owner = type("Owner", (), {"execution_scope": {"mode": "PAPER"}})()
        decision = {"signal": "BUY_CE", "ltp": 67}
        with MarketClock.at(NOW):
            audit.candidate(owner, decision, {}, {"ready": True})
            decision["ltp"] = 999
        self.assertTrue(session.close())
        payload = json.loads((self.root / "daily/2026-10-19/events.jsonl").read_text())
        self.assertEqual(67, payload["decision"]["ltp"])
        self.assertTrue(payload["candidate_id"])
        self.assertEqual(session.run_id, payload["run_id"])

    def test_candidate_dossier_actual_ai_verdict_and_execution_result_share_identity(self):
        for outcome in ("APPROVED", "VETOED", "TIMEOUT_EXPIRED"):
            with self.subTest(outcome=outcome):
                session = LoggingSession(self.root).install()
                self.addCleanup(session.close)
                trader = make_trader(self.root / outcome / "active_position.json")
                trader.client.quote_ask = trader.client.fill_price = 67
                decision = {
                    "signal": "BUY_CE",
                    "symbol": "NIFTY-TEST-CE",
                    "instrument_id": "TEST",
                    "ltp": 67,
                    "setup_type": "TREND_PULLBACK",
                    "candidate_timestamp": NOW,
                }
                dossier = entry_dossier(67, vwap_distance_pts=80 if outcome == "VETOED" else 10, candidate_timestamp=NOW)
                if outcome == "TIMEOUT_EXPIRED":
                    trader.ai_consultant.timeout_seconds = 0
                with MarketClock.at(NOW), patch.object(trader, "build_dossier", return_value=dossier):
                    audit.candidate(trader, decision, {"day_change": 0}, INTELLIGENCE)
                    EntryWorkflow().run(
                        trader, {"day_change": 0}, decision, [], 0, copy.deepcopy(INTELLIGENCE)
                    )
                self.assertTrue(session.close())
                events = [
                    json.loads(line)
                    for line in (self.root / "daily/2026-10-19/events.jsonl").read_text().splitlines()
                ]
                current = [e for e in events if e["run_id"] == session.run_id]
                self.assertEqual(
                    outcome, next(e["verdict"]["action"] for e in current if e["event"] == "ai_verdict")
                )
                self.assertTrue(
                    any(
                        e["event"] == "ai_consultation" and e["dossier"]["option_entry_price"] == 67
                        for e in current
                    )
                )
                self.assertTrue(all(e["candidate_id"] == trader._audit_candidate_id for e in current))
                orders = [c for c in trader.client.calls if c[:2] == ("POST", "/execution/orders")]
                self.assertEqual(1 if outcome == "APPROVED" else 0, len(orders))
                if outcome == "APPROVED":
                    self.assertEqual(
                        "SUCCESS",
                        next(e["result"]["status"] for e in current if e["event"] == "entry_result"),
                    )

    def test_actual_lifecycle_preserves_fills_ratchets_and_flat_history(self):
        session = LoggingSession(self.root).install()
        self.addCleanup(session.close)
        path = self.root / "active_position.json"
        broker = Broker()
        trader = Trader(path, broker)
        with MarketClock.at(NOW):
            result = trader.execute_trade(approved_decision(trader.trading_cfg))
            self.assertEqual("SUCCESS", result["status"])
            state = trader.load_active_position()
            trader.ratchet_stops(state, 75)
            stop = broker.orders[result["stop_order_ids"][0]]
            stop.update(status="FILLED", filled_quantity=65, average_price=110)
            self.assertEqual([], trader.get_trades_state()[0])
        self.assertTrue(session.close())
        self.assertFalse(path.exists())
        directory = self.root / "daily/2026-10-19"
        events = [json.loads(line) for line in (directory / "events.jsonl").read_text().splitlines()]
        self.assertTrue(
            any(
                item["event"] == "position_state"
                and item["state"].get("stops")
                and item["state"]["stops"][0].get("trigger_price") == 75
                for item in events
            )
        )
        self.assertEqual(1, sum(item["event"] == "position_closed" for item in events))
        summary = json.loads((directory / "summary.json").read_text())
        self.assertEqual(650, summary["by_mode"]["LIVE"]["gross_pnl"])
        self.assertIsNone(summary["by_mode"]["LIVE"]["net_pnl"])

    def test_disk_failure_is_visible_and_does_not_interrupt_actual_ai_entry(self):
        output = io.StringIO()
        with (
            patch("trading.adapters.daily_logs.DailyJournalHandler.emit", side_effect=OSError("full disk")),
            patch("trading.adapters.daily_logs.DailyRuntimeHandler.emit", side_effect=OSError("full disk")),
        ):
            session = LoggingSession(self.root).install()
            self.addCleanup(session.close)
            with patch("sys.stderr", output), MarketClock.at(NOW):
                trader = Trader(self.root / "active_position.json", Broker())
                self.assertEqual(
                    "SUCCESS", trader.execute_trade(approved_decision(trader.trading_cfg))["status"]
                )
                self.assertTrue(session.close())
        self.assertGreater(session.failures, 0)
        self.assertIn("LOGGING WARNING", output.getvalue())

    def test_bounded_queue_never_waits_for_a_slow_disk_and_reports_overflow(self):
        started, release = threading.Event(), threading.Event()

        def slow(record):
            started.set()
            release.wait(3)

        session = LoggingSession(self.root, queue_size=1)
        self.addCleanup(session.close)
        record = logging.LogRecord("test", logging.INFO, "", 1, "message", (), None)
        with (
            patch.object(session.handlers[0], "emit", side_effect=slow),
            patch("sys.stderr", new=io.StringIO()) as stderr,
        ):
            try:
                session.enqueue(record)
                self.assertTrue(started.wait(1))
                session.enqueue(record)
                session.enqueue(record)
                self.assertEqual(1, session.dropped)
                self.assertIn("queue full", stderr.getvalue())
            finally:
                release.set()
                self.assertTrue(session.close())

    def test_compression_keeps_legacy_logs_journals_and_recent_files(self):
        old = self.root / "trader-2026-09-01.log"
        old.write_text("old log\n", encoding="utf-8")
        recent = self.root / "trader-2026-10-19.log"
        recent.write_text("recent", encoding="utf-8")
        legacy = self.root / "trader.log"
        legacy.write_text("legacy", encoding="utf-8")
        journal = self.write_journal(closed_event()) / "events.jsonl"
        before = journal.read_bytes()
        self.assertEqual([old.name + ".gz"], compress_runtime_logs(self.root, 30, today=date(2026, 10, 20)))
        with gzip.open(old.with_suffix(".log.gz"), "rt", encoding="utf-8") as stream:
            self.assertEqual("old log\n", stream.read())
        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())
        self.assertTrue(legacy.exists())
        self.assertEqual(before, journal.read_bytes())

    def test_cli_refuses_maintenance_while_scheduler_holds_lock(self):
        with SchedulerLock(self.root / "scheduler.lock"), patch("sys.stderr", new=io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                logs_main(["--directory", str(self.root), "compress"])
        self.assertEqual(2, error.exception.code)

    def test_compression_does_not_overwrite_an_existing_archive(self):
        old = self.root / "trader-2026-09-01.log"
        old.write_text("uncompressed", encoding="utf-8")
        archive = old.with_suffix(".log.gz")
        archive.write_bytes(b"existing archive")
        with self.assertRaises(FileExistsError):
            compress_runtime_logs(self.root, 30, today=date(2026, 10, 20))
        self.assertEqual("uncompressed", old.read_text())
        self.assertEqual(b"existing archive", archive.read_bytes())

    def test_cli_startup_failure_is_logged_and_writer_is_drained(self):
        import nifty_trader_scheduler as scheduler

        with (
            patch.object(scheduler, "LOG_DIR", self.root),
            patch.object(scheduler, "configure_console"),
            patch.object(scheduler, "_main", side_effect=RuntimeError("startup fixture failure")),
            patch("sys.stdout", new=io.StringIO()),
        ):
            self.assertEqual(1, scheduler.main())
        with SchedulerLock(self.root / "scheduler.lock"):
            pass
        text = "".join(path.read_text(encoding="utf-8") for path in self.root.glob("trader-*.log"))
        self.assertIn("startup fixture failure", text)
        self.assertIn("session_stopped", text)
        self.assertFalse(any(t.name == "daily-log-writer" and t.is_alive() for t in threading.enumerate()))


if __name__ == "__main__":
    unittest.main()
