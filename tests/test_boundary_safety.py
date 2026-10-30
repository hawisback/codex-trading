"""Offline fail-closed tests for persistence and broker request budgets."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from execution_safety import ReconciliationError
from trading.adapters.gateways.rate_limiter import TokenBucketRateLimiter
from trading.adapters.position_store import JsonPositionStore

ROOT = Path(__file__).resolve().parents[1]


class PositionStoreBoundaryTests(unittest.TestCase):
    def test_legacy_aliases_are_loaded_without_changing_the_saved_file(self):
        with tempfile.TemporaryDirectory(prefix=".position-boundary-", dir=ROOT) as directory:
            path = Path(directory) / "position.json"
            original = {
                "entry_order_id": "ENTRY-1",
                "stop_order_ids": ["STOP-1"],
                "quantity": 65,
                "current_stop_trigger": 42.5,
            }
            path.write_text(json.dumps(original), encoding="utf-8")
            loaded = JsonPositionStore(path).load()
            self.assertEqual(["ENTRY-1"], [row["order_id"] for row in loaded["entries"]])
            self.assertEqual(["STOP-1"], [row["order_id"] for row in loaded["stops"]])
            self.assertEqual([], loaded["exits"])
            self.assertEqual(original, json.loads(path.read_text(encoding="utf-8")))

            # Older broker integrations may persist numeric order references.
            path.write_text(json.dumps({"stop_order_ids": [123456]}), encoding="utf-8")
            self.assertEqual(123456, JsonPositionStore(path).load()["stops"][0]["order_id"])

    def test_invalid_persisted_order_collections_block_recovery(self):
        invalid = (
            ("entries", {}),
            ("entries", ["ENTRY-1"]),
            ("stops", None),
            ("stops", [42]),
            ("exits", {"bad": "shape"}),
            ("stop_order_ids", "STOP-1"),
            ("stop_order_ids", ["STOP-1", None]),
            ("stop_order_ids", [""]),
            ("stop_order_ids", [-3]),
        )
        with tempfile.TemporaryDirectory(prefix=".position-boundary-", dir=ROOT) as directory:
            path = Path(directory) / "position.json"
            store = JsonPositionStore(path)
            for field, value in invalid:
                with self.subTest(field=field, value=value):
                    persisted = {"schema_version": 2, field: value}
                    path.write_text(json.dumps(persisted), encoding="utf-8")
                    with self.assertRaisesRegex(ReconciliationError, "entries blocked"):
                        store.load()
                    self.assertEqual(persisted, json.loads(path.read_text(encoding="utf-8")))


class RateLimiterBoundaryTests(unittest.TestCase):
    def test_both_apis_reject_bad_token_requests_without_spending_or_minting_tokens(self):
        invalid = (0, -1, True, float("nan"), float("inf"), float("-inf"), 3, "1")
        with patch("time.monotonic", return_value=100.0):
            limiter = TokenBucketRateLimiter(rate=1, capacity=2)
            self.assertTrue(limiter.try_acquire())
            for tokens in invalid:
                for method in (limiter.acquire, limiter.try_acquire):
                    with self.subTest(method=method.__name__, tokens=tokens):
                        with self.assertRaises(ValueError):
                            method(tokens)
                        self.assertEqual(1, limiter.tokens)
            self.assertTrue(limiter.try_acquire())
            self.assertFalse(limiter.try_acquire())

    def test_invalid_wait_budgets_fail_before_consulting_bucket(self):
        invalid = (-1, True, float("nan"), float("inf"), "10")
        with patch("time.monotonic", return_value=100.0):
            limiter = TokenBucketRateLimiter(rate=1, capacity=1)
            for timeout in invalid:
                with self.subTest(timeout=timeout):
                    with self.assertRaises(ValueError):
                        limiter.acquire(timeout=timeout)
                    self.assertEqual(1, limiter.tokens)
            self.assertTrue(limiter.acquire(timeout=0))
            self.assertFalse(limiter.acquire(timeout=0))

    def test_clock_regression_cannot_spend_future_refills(self):
        clock = [100.0]
        with patch("time.monotonic", side_effect=lambda: clock[0]):
            limiter = TokenBucketRateLimiter(rate=1, capacity=1)
            self.assertTrue(limiter.try_acquire())
            clock[0] = 99.0
            self.assertFalse(limiter.try_acquire())
            clock[0] = 100.5
            self.assertFalse(limiter.try_acquire())
            clock[0] = 101.0
            self.assertTrue(limiter.try_acquire())


class PositionCodecBoundaryTests(unittest.TestCase):
    def test_save_compatibility_aliases_include_only_nonterminal_stops(self):
        from trading.adapters.position_codec import PositionStateCodec

        state = {
            "entries": [{"order_id": "E1"}],
            "stops": [
                {"order_id": "S1", "status": "TRIGGER_PENDING"},
                {"order_id": "S2", "status": "CANCELLED"},
            ],
        }
        self.assertIs(state, PositionStateCodec.encode(state))
        self.assertEqual(["E1"], state["entry_order_ids"])
        self.assertEqual(["S1"], state["stop_order_ids"])
        self.assertEqual("E1", state["trade_id"])
        self.assertEqual(2, state["schema_version"])


class GatewayJournalBoundaryTests(unittest.TestCase):
    def test_correlation_records_are_defensive_copies(self):
        from trading.adapters.gateways.journal import GatewayJournal

        with tempfile.TemporaryDirectory(prefix=".journal-boundary-", dir=ROOT) as directory:
            journal = GatewayJournal(Path(directory) / "intents.json", "kite")
            journal.bind("ACCOUNT")
            record = journal.put("REQUEST-1", kind="ENTRY", phase="UNKNOWN")
            record["phase"] = "REJECTED"
            snapshot = journal.records
            snapshot["REQUEST-1"]["phase"] = "REJECTED"
            self.assertEqual("UNKNOWN", journal.records["REQUEST-1"]["phase"])
            found = journal.match(tag=journal.records["REQUEST-1"]["tag"])
            self.assertEqual("UNKNOWN", found["phase"])

    def test_identity_fields_cannot_be_reassigned_by_updates(self):
        from trading.adapters.gateways.journal import GatewayJournal

        with tempfile.TemporaryDirectory(prefix=".journal-boundary-", dir=ROOT) as directory:
            journal = GatewayJournal(Path(directory) / "intents.json", "kite")
            journal.bind("ACCOUNT")
            with self.assertRaisesRegex(ReconciliationError, "immutable"):
                journal.put("REQUEST-1", tag="different-tag")
            with self.assertRaisesRegex(ReconciliationError, "identity"):
                journal.put("", phase="UNKNOWN")
            self.assertFalse(journal.records)
            self.assertFalse(journal.path.exists())

    def test_corrupt_and_ambiguous_journals_fail_closed(self):
        from trading.adapters.gateways.journal import GatewayJournal, broker_tag

        with tempfile.TemporaryDirectory(prefix=".journal-boundary-", dir=ROOT) as directory:
            path = Path(directory) / "intents.json"
            for content in (
                "{ invalid json",
                json.dumps({"schema_version": 1, "accounts": {"kite:A": ["bad"]}}),
                json.dumps(
                    {
                        "schema_version": 1,
                        "accounts": {
                            "kite:A": {
                                "A": {"request_id": "A", "tag": broker_tag("A"), "order_id": "E1"},
                                "B": {"request_id": "B", "tag": broker_tag("B"), "order_id": "E1"},
                            }
                        },
                    }
                ),
            ):
                with self.subTest(content=content[:40]):
                    path.write_text(content, encoding="utf-8")
                    journal = GatewayJournal(path, "kite")
                    with self.assertRaises(ReconciliationError):
                        journal.bind("A")
                    self.assertEqual(content, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
