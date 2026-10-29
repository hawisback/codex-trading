"""Offline news-worker tests: no live providers, broker calls or AI replacements."""

import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.parse
from types import SimpleNamespace
from unittest.mock import patch

from market_intelligence import MarketIntelligence


ROOT = Path(__file__).resolve().parent
RSS = b"<rss><channel><item><title>Nifty rally as HDFC beats estimates</title><link>https://example.invalid/news</link></item></channel></rss>"


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix=".news-test-", dir=ROOT)
        self.directory = Path(directory.name)
        self.assertTrue(self.directory.resolve().is_relative_to(ROOT))
        self.addCleanup(directory.cleanup)
        # A failed test must never fall back to an actual provider connection.
        network = patch("market_intelligence.urllib.request.urlopen", side_effect=AssertionError("Unexpected network request"))
        network.start()
        self.addCleanup(network.stop)
        self.instances = []
        self.addCleanup(self.stop_all)
        self.calls = []

    def stop_all(self):
        for instance in self.instances:
            instance.stop_worker(timeout=2)

    def make(self, **kwargs):
        instance = MarketIntelligence(start_worker=False, snapshot_dir=self.directory, **kwargs)
        instance._read_payload = self.payload
        self.instances.append(instance)
        return instance

    def payload(self, url):
        self.calls.append((url, threading.get_ident()))
        if "finance.yahoo.com" in url:
            return json.dumps({"chart": {"result": [{"meta": {
                "regularMarketPrice": 100, "previousClose": 100}}]}}).encode()
        if "scanner.tradingview.com" in url:
            return json.dumps({"totalCount": 1, "data": [{"s": "NSEIX:NIFTY1!", "d": [100.0, 0.0, "GIFT NIFTY", 100.0, 100.0, 100.0, 1000]}]}).encode()
        return RSS

    def seed(self, instance, now=100):
        with patch("market_intelligence.time.monotonic", return_value=now):
            instance._refresh_once()

    def snapshot(self, instance, now=100, spot=0):
        with patch("market_intelligence.time.monotonic", return_value=now):
            return instance.get_market_intelligence(spot)

    def test_initial_cache_is_complete_but_not_ready(self):
        instance = self.make()
        snapshot = instance.get_market_intelligence()
        self.assertFalse(snapshot["ready"])
        self.assertEqual("INITIALIZING", snapshot["status"])
        self.assertEqual("NEUTRAL", snapshot["global_cues"]["global_bias"])
        self.assertEqual([], snapshot["news"]["headlines"])
        self.assertIn("INTELLIGENCE_UNAVAILABLE", snapshot["trap_advisories"][0])
        self.assertFalse(self.calls)

    def test_expired_getter_never_fetches_or_persists(self):
        instance = self.make()
        self.seed(instance)
        calls = len(self.calls)
        with patch.object(instance, "fetch_global_cues") as quotes, patch.object(instance, "fetch_news_feed") as rss, patch.object(instance, "save_snapshot") as disk:
            self.assertFalse(self.snapshot(instance, 221)["ready"])
        quotes.assert_not_called()
        rss.assert_not_called()
        disk.assert_not_called()
        self.assertEqual(calls, len(self.calls))

    def test_returned_nested_data_cannot_mutate_cache(self):
        instance = self.make()
        self.seed(instance)
        first = self.snapshot(instance)
        first["global_cues"]["items"]["Dow Jones"]["price"] = -1
        first["news"]["headlines"][0]["title"] = "mutated"
        first["sources"]["Dow Jones"]["fresh"] = False
        second = self.snapshot(instance)
        self.assertEqual(100, second["global_cues"]["items"]["Dow Jones"]["price"])
        self.assertNotEqual("mutated", second["news"]["headlines"][0]["title"])
        self.assertTrue(second["sources"]["Dow Jones"]["fresh"])

    def test_spot_advisories_are_independent_per_reader(self):
        instance = self.make()
        self.seed(instance)
        first = self.snapshot(instance, spot=-1)
        saved = list(first["trap_advisories"])
        second = self.snapshot(instance, spot=0)
        self.assertIn("POTENTIAL_BEAR_TRAP", saved[0])
        self.assertEqual(saved, first["trap_advisories"])
        self.assertEqual([], second["trap_advisories"])

    def test_stale_snapshot_retains_data_and_blocks_entries(self):
        instance = self.make()
        self.seed(instance)
        snapshot = self.snapshot(instance, 221)
        self.assertEqual("STALE", snapshot["status"])
        self.assertFalse(snapshot["ready"])
        self.assertEqual(121, snapshot["sources"]["Dow Jones"]["age_seconds"])
        self.assertEqual(100, snapshot["global_cues"]["items"]["Dow Jones"]["price"])

    def test_quote_timeout_preserves_last_success_until_its_original_expiry(self):
        instance = self.make()
        self.seed(instance)
        original = instance._read_payload

        def fail_one(url):
            if "^DJI" in urllib.parse.unquote(url):
                raise TimeoutError()
            return original(url)

        instance._read_payload = fail_one
        self.seed(instance, 161)
        snapshot = self.snapshot(instance, 161)
        self.assertTrue(snapshot["ready"])
        self.assertEqual("PARTIAL", snapshot["status"])
        self.assertEqual("TimeoutError", snapshot["sources"]["Dow Jones"]["error"])
        self.assertEqual(61, snapshot["sources"]["Dow Jones"]["age_seconds"])
        self.assertFalse(self.snapshot(instance, 221)["ready"])

    def test_total_outage_is_unavailable_not_fresh_neutral(self):
        instance = self.make()
        instance._read_payload = lambda url: (_ for _ in ()).throw(TimeoutError())
        self.seed(instance)
        snapshot = self.snapshot(instance)
        self.assertFalse(snapshot["ready"])
        self.assertEqual("UNAVAILABLE", snapshot["status"])
        self.assertTrue(all(s["error"] for s in snapshot["sources"].values()))

    def test_one_healthy_rss_feed_is_sufficient_and_partial_is_visible(self):
        instance = self.make()
        original = instance._read_payload

        def fail_one(url):
            if "moneycontrol" in url:
                raise TimeoutError("feed unavailable")
            return original(url)

        instance._read_payload = fail_one
        self.seed(instance)
        snapshot = self.snapshot(instance)
        self.assertTrue(snapshot["ready"])
        self.assertEqual("PARTIAL", snapshot["status"])
        self.assertEqual(1, snapshot["news"]["total_headlines"])
        self.assertIn("INTELLIGENCE_PARTIAL", snapshot["trap_advisories"][0])

    def test_expired_feed_is_excluded_when_another_feed_remains_fresh(self):
        instance = self.make()
        self.seed(instance)
        original = instance._read_payload

        def later(url):
            if "moneycontrol" in url:
                raise TimeoutError("feed unavailable")
            if "economictimes" in url:
                return b"<rss><channel><item><title>Nifty plunge</title></item></channel></rss>"
            return original(url)

        instance._read_payload = later
        self.seed(instance, 200)
        snapshot = self.snapshot(instance, 230)
        self.assertTrue(snapshot["ready"])
        self.assertEqual(-1, snapshot["news"]["sentiment_score"])
        self.assertEqual(1, snapshot["news"]["total_headlines"])

    def test_worker_fetches_six_sources_off_caller_thread_and_persists(self):
        instance = self.make()
        persisted = threading.Event()
        save = instance.save_snapshot

        def save_and_signal(*args):
            save(*args)
            persisted.set()

        instance.save_snapshot = save_and_signal
        caller = threading.get_ident()
        instance.start_worker()
        instance.start_worker()
        self.assertTrue(instance.wait_until_ready(timeout=1))
        self.assertTrue(persisted.wait(1))
        self.assertTrue(instance._worker.daemon)
        self.assertEqual(7, len(self.calls))
        self.assertTrue(all(thread != caller for _, thread in self.calls))
        saved = json.loads((self.directory / "latest_intelligence.json").read_text())
        self.assertTrue(saved["ready"])
        self.assertNotIn("success_monotonic", saved["sources"]["Dow Jones"])
        self.assertTrue((self.directory / "latest_intelligence.md").exists())

    def test_blocked_provider_does_not_hold_reader_lock(self):
        instance = self.make()
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()
        original = instance._read_payload

        def blocked(url):
            entered.set()
            release.wait(2)
            return original(url)

        instance._read_payload = blocked
        instance.start_worker()
        self.assertTrue(entered.wait(1))
        results = []

        def read():
            results.extend(instance.get_market_intelligence() for _ in range(50))
            returned.set()

        reader = threading.Thread(target=read)
        reader.start()
        try:
            self.assertTrue(returned.wait(.5), "Getter blocked behind network work")
            self.assertTrue(all(not value["ready"] for value in results))
            self.assertTrue(instance._worker.is_alive())
        finally:
            release.set()
            reader.join(1)

    def test_blocked_snapshot_writer_does_not_hold_reader_lock_or_shutdown(self):
        instance = self.make()
        entered, release, returned = threading.Event(), threading.Event(), threading.Event()

        def blocked_save(*args):
            entered.set()
            release.wait(2)

        instance.save_snapshot = blocked_save
        instance.start_worker()
        self.assertTrue(entered.wait(1))
        reader = threading.Thread(target=lambda: (instance.get_market_intelligence(), returned.set()))
        reader.start()
        try:
            self.assertTrue(returned.wait(.5), "Getter blocked behind disk work")
            self.assertFalse(instance.stop_worker(timeout=0))
            self.assertEqual("STOPPED", instance.get_market_intelligence()["status"])
        finally:
            release.set()
            reader.join(1)

    def test_stop_wakes_idle_worker_and_is_idempotent(self):
        instance = self.make()
        instance.start_worker()
        self.assertTrue(instance.wait_until_ready(timeout=1))
        self.assertTrue(instance.stop_worker(timeout=1))
        self.assertTrue(instance.stop_worker(timeout=0))
        self.assertFalse(instance._worker.is_alive())
        with self.assertRaises(RuntimeError):
            instance.start_worker()

    def test_explicit_readiness_wait_has_a_timeout(self):
        instance = self.make()
        self.assertFalse(instance.wait_until_ready(timeout=0))
        self.assertFalse(self.calls)

    def test_persistence_failure_does_not_discard_published_data(self):
        instance = self.make()
        with patch.object(instance, "save_snapshot", side_effect=OSError("disk unavailable")):
            instance.start_worker()
            self.assertTrue(instance.wait_until_ready(timeout=1))
            deadline = time.monotonic() + 1
            while instance.get_market_intelligence()["worker"]["refreshing"] and time.monotonic() < deadline:
                threading.Event().wait(.005)
            snapshot = instance.get_market_intelligence()
            self.assertTrue(snapshot["ready"])
            self.assertEqual("disk unavailable", snapshot["worker"]["last_error"])

    def test_unexpected_cycle_exception_does_not_kill_worker(self):
        instance = self.make(refresh_interval_seconds=.01)
        refresh = instance._refresh_once
        calls = []

        def once():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("transient")
            return refresh()

        with patch.object(instance, "_refresh_once", side_effect=once):
            instance.start_worker()
            self.assertTrue(instance.wait_until_ready(timeout=1))
            self.assertTrue(instance._worker.is_alive())
            instance.stop_worker()

    def test_oversized_response_is_rejected(self):
        instance = self.make()
        with patch("market_intelligence.urllib.request.urlopen", return_value=io.BytesIO(b"x" * (instance.MAX_RESPONSE_BYTES + 1))):
            with self.assertRaises(ValueError):
                MarketIntelligence._read_payload(instance, "https://example.invalid")

    def test_chart_previous_close_and_invalid_quote_are_handled(self):
        instance = self.make()
        instance._read_payload = lambda url: json.dumps({"chart": {"result": [{"meta": {
            "regularMarketPrice": 101, "chartPreviousClose": 100}}]}}).encode() if "finance.yahoo" in url else (
                json.dumps({"totalCount": 1, "data": [{"s": "NSEIX:NIFTY1!", "d": [101.0, 0.0, "GIFT NIFTY", 100.0, 100.0, 100.0, 1000]}]}).encode()
                if "scanner.tradingview" in url else RSS
            )
        self.seed(instance)
        self.assertTrue(self.snapshot(instance)["ready"])
        self.assertEqual(1, self.snapshot(instance)["global_cues"]["items"]["Dow Jones"]["change_pct"])

    def test_invalid_prices_and_malformed_rss_do_not_become_fresh(self):
        instance = self.make()
        instance._read_payload = lambda url: b'{"chart":{"result":[{"meta":{"regularMarketPrice":null,"previousClose":100}}]}}' if "finance.yahoo" in url else b"not RSS"
        self.seed(instance)
        snapshot = self.snapshot(instance)
        self.assertFalse(snapshot["ready"])
        self.assertTrue(all(s["error"] for s in snapshot["sources"].values()))

    def test_parallel_readers_see_complete_generations_during_refreshes(self):
        instance = self.make(refresh_interval_seconds=.005)
        generation = [0]

        def payload(url):
            if "CL=F" in urllib.parse.unquote(url):
                generation[0] += 1
            if "finance.yahoo" in url:
                return json.dumps({"chart": {"result": [{"meta": {
                    "regularMarketPrice": 100 + generation[0], "previousClose": 100}}]}}).encode()
            if "scanner.tradingview" in url:
                return json.dumps({
                    "totalCount": 1,
                    "data": [{"s": "NSEIX:NIFTY1!", "d": [100.0 + generation[0], 0.0, "GIFT NIFTY", 100.0, 100.0, 100.0, 1000]}],
                }).encode()
            return RSS

        instance._read_payload = payload
        instance.start_worker()
        self.assertTrue(instance.wait_until_ready(timeout=1))
        failures = []

        def read():
            try:
                for _ in range(150):
                    snapshot = instance.get_market_intelligence()
                    prices = {item["price"] for item in snapshot["global_cues"]["items"].values()}
                    if len(prices) != 1 or not snapshot["ready"]:
                        raise AssertionError("Torn or incomplete published snapshot")
            except BaseException as exc:
                failures.append(exc)

        readers = [threading.Thread(target=read) for _ in range(6)]
        for reader in readers:
            reader.start()
        for reader in readers:
            reader.join(2)
        self.assertTrue(all(not r.is_alive() for r in readers))
        self.assertEqual([], failures)

    def test_reporting_command_times_out_and_stops_worker(self):
        import market_intelligence
        instance = self.make()
        with patch.object(market_intelligence, "MarketIntelligence", return_value=instance), patch.object(instance, "wait_until_ready", return_value=False), patch("market_intelligence.logging.basicConfig"), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(1, market_intelligence.main())
        self.assertTrue(instance._stop_event.is_set())

    def test_reporting_read_does_not_overwrite_latest_trading_spot(self):
        instance = self.make()
        self.seed(instance)
        self.snapshot(instance, spot=-1)
        with patch("market_intelligence.time.monotonic", return_value=100):
            self.assertTrue(instance.wait_until_ready(timeout=0))
            instance.save_snapshot(self.directory)
        self.assertEqual(-1, instance._latest_spot_change)
        persisted = json.loads((self.directory / "latest_intelligence.json").read_text())
        self.assertIn("POTENTIAL_BEAR_TRAP", persisted["trap_advisories"][0])

    def test_market_context_reporting_times_out_and_stops_worker(self):
        import run_market_context
        instance = self.make()
        client = SimpleNamespace(get_snapshot=lambda: {"underlying": {"change_pct": 0}}, close=lambda: None)
        with patch.object(run_market_context, "MarketIntelligence", return_value=instance), patch.object(run_market_context, "create_market_data", return_value=client), patch.object(instance, "wait_until_ready", return_value=False), patch("sys.stdout", new=io.StringIO()):
            self.assertEqual(1, run_market_context.fetch_full_market_context())
        self.assertTrue(instance._stop_event.is_set())

    def test_scheduler_once_and_exception_paths_stop_worker(self):
        import nifty_trader_scheduler as scheduler
        for failure in (None, RuntimeError("test failure"), KeyboardInterrupt()):
            instance = self.make()

            def run_cycle(**kwargs):
                if failure:
                    raise failure
                return {"has_open_trades": False}

            trader = SimpleNamespace(client=SimpleNamespace(get_status=lambda: {"mode": "PAPER"}),
                                     intelligence=instance, run_cycle=run_cycle)
            with patch.object(scheduler, "NiftyOptionsTrader", return_value=trader), patch("sys.argv", ["scheduler", "--once"]):
                if failure:
                    with self.assertRaises(type(failure)):
                        scheduler._main()
                else:
                    scheduler._main()
            self.assertTrue(instance._stop_event.is_set())

    def test_work_duration_is_subtracted_from_monitor_sleep(self):
        from nifty_trader_scheduler import cycle_sleep_delay
        with patch("nifty_trader_scheduler.time.monotonic", return_value=102):
            self.assertEqual(3, cycle_sleep_delay(100, 5))
        with patch("nifty_trader_scheduler.time.monotonic", return_value=140):
            self.assertEqual(0, cycle_sleep_delay(100, 5))


if __name__ == "__main__":
    unittest.main()
