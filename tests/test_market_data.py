"""Offline broker wire fixtures and local market-context integration; AI stays real."""

from contextlib import contextmanager, nullcontext
import copy
import csv
from datetime import timedelta
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from market_clock import MarketClock
from trading.adapters.market_data import BrokerMarketData, create_market_data
from trading.adapters.market_sources import (
    BreezeMarketSource,
    HEAVYWEIGHTS,
    InstrumentMaster,
    KiteSessionSource,
    MarketDataError,
    ReadBudget,
    SPOT,
)
from trading.application.market_context import MarketContextService
from trading.application.scheduler import run_scheduler
from trading.application.workflows import CycleWorkflow
from trading.domain.market_data import completed_spot_bars, resample_five_minutes, technical_metrics
from tools.market_data import inspect_market_data

NOW = MarketClock.parse_to_ist("2026-10-22T10:00:00+05:30")
EXPIRY = "2026-10-27"
ROOT = Path(__file__).resolve().parents[1]


def contract_rows():
    return [
        dict(
            expiry=expiry,
            strike=strike,
            right=right,
            symbol=f"EXACT-{expiry}-{strike}-{right}",
            token=strike + (right == "PE"),
        )
        for expiry in (EXPIRY, "2026-11-03")
        for strike in range(22150, 23200, 50)
        for right in ("CE", "PE")
    ]


def candle_rows():
    rows = []
    for day, count in ((NOW - timedelta(days=1), 375), (NOW, 46)):
        opening = day.replace(hour=9, minute=15)
        for index in range(count):
            rows.append(
                [
                    (opening + timedelta(minutes=index)).isoformat(),
                    22600 + index / 10,
                    22602 + index / 10,
                    22598 + index / 10,
                    22601 + index / 10,
                    0,
                ]
            )
    return rows


class FixtureSource:
    broker_name = "fixture"

    def __init__(self):
        self.timestamp = NOW.isoformat()
        self.rows = candle_rows()
        self.calls = []
        self.missing_oi = False
        self.failed_heavyweights = False

    def quotes(self, symbols, budget):
        self.calls.append(("quotes", tuple(symbols)))
        if self.failed_heavyweights and SPOT not in symbols:
            raise TimeoutError("unavailable")
        return {
            s: dict(
                last_price=22649, open=22750, high=22785, low=22564, close=22810, timestamp=self.timestamp
            )
            for s in symbols
        }

    def history(self, start, end, budget):
        self.calls.append(("history",))
        return copy.deepcopy(self.rows)

    def option_quotes(self, contracts, expiry, budget):
        self.calls.append(("options", expiry))
        result = {
            c["symbol"]: dict(
                ltp=80,
                open_interest=100 if c["right"] == "CE" else 200,
                oi_change=-10,
                volume=20,
                timestamp=self.timestamp,
                bid=79,
                ask=81,
            )
            for c in contracts
        }
        if self.missing_oi:
            del result[contracts[0]["symbol"]]["oi_change"]
        return result

    def depth(self, contract, budget):
        return dict(
            timestamp=self.timestamp,
            last_price=80,
            depth=dict(buy=[dict(price=79, quantity=650)], sell=[dict(price=81, quantity=650)]),
        )


class MarketDataTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(MarketClock, "now_ist", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.source = FixtureSource()
        self.provider = BrokerMarketData(
            self.source, master=SimpleNamespace(options=lambda budget: contract_rows())
        )

    def test_six_capabilities_and_context_run_without_local_server(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("No HTTP expected")):
            health = self.provider.get_data_quality()
            self.assertTrue(health["quote_ready"])
            self.assertEqual("LIVE", health["market_feed"]["status"])
            self.assertEqual("NIFTY 50", self.provider.get_snapshot()["underlying"]["symbol"])
            self.assertEqual(45, len(self.provider.get_candles()["candles"]))
            self.assertEqual(50, len(self.provider.get_candles("5m", 50)["candles"]))
            self.assertEqual(8, len(self.provider.get_technicals()["metrics"]))
            chain = self.provider.get_options()
            self.assertEqual(21, len(chain["strikes"]))
            self.assertEqual(22650, chain["atm_strike"])
            self.assertEqual(EXPIRY, chain["expiry"])
            self.assertEqual(2, chain["summary"]["pcr_oi"])
            self.assertEqual(-10, chain["strikes"][0]["call"]["oi_change"])
            self.assertEqual("EXACT-2026-10-27-22150-CE", chain["strikes"][0]["call"]["symbol"])
            self.assertEqual(
                list(HEAVYWEIGHTS), [s["symbol"] for s in self.provider.get_heavyweights()["stocks"]]
            )
            context = MarketContextService(self.provider, lambda: {"available_margin": 10000}).fetch()
            self.assertEqual("NIFTY_SPOT_INTRADAY", context["session_vwap_basis"])
            self.assertEqual(10000, context["available_margin"])
            expected = round(sum((r[2] + r[3] + r[4]) / 3 for r in candle_rows()[-46:-1]) / 45, 2)
            self.assertEqual(expected, context["session_vwap"])
        self.assertEqual(1, sum(c[0] == "history" for c in self.source.calls))

    def test_stale_future_missing_and_invalid_quotes_fail_closed(self):
        for timestamp in (
            (NOW - timedelta(seconds=20)).isoformat(),
            (NOW + timedelta(seconds=3)).isoformat(),
            (NOW - timedelta(days=1)).isoformat(),
            None,
        ):
            with self.subTest(timestamp=timestamp):
                self.source.timestamp = timestamp
                self.assertFalse(self.provider.get_data_quality()["quote_ready"])
                self.assertFalse(MarketContextService(self.provider, lambda: {}).health()["healthy"])
                with self.assertRaises((MarketDataError, ValueError)):
                    self.provider.get_snapshot()

    def test_incomplete_candle_excluded_and_session_gap_blocks_vwap(self):
        bars = self.provider.get_candles()["candles"]
        self.assertTrue(bars[-1]["start_time"].startswith("2026-10-22T09:59"))
        self.source.rows.pop(-3)
        self.provider._history_minute = None
        with self.assertRaisesRegex(MarketDataError, "gaps"):
            self.provider.get_candles()

    def test_five_minute_resampling_uses_only_five_complete_constituents(self):
        rows = completed_spot_bars(candle_rows(), NOW)
        bars = resample_five_minutes(rows)
        self.assertEqual(84, len(bars))
        self.assertEqual(22600, bars[0]["open"])
        self.assertEqual(22602.4, bars[0]["high"])
        self.assertEqual(22601.4, bars[0]["close"])
        rows.pop(2)
        self.assertEqual(83, len(resample_five_minutes(rows)))

    def test_indicator_known_flat_series_and_warmup(self):
        metrics = technical_metrics([{"close": 100}] * 50)
        self.assertEqual(100, metrics["ema_50"])
        self.assertEqual(0, metrics["macd_histogram"])
        self.assertFalse(metrics["macd_histogram_expanding_positive"])
        self.assertFalse(metrics["macd_histogram_expanding_negative"])
        with self.assertRaises(ValueError):
            technical_metrics([{"close": 100}] * 49)

    def test_explicit_expiry_missing_leg_and_missing_oi(self):
        self.assertEqual("2026-11-03", self.provider.get_options(0, "2026-11-03")["expiry"])
        with self.assertRaises(MarketDataError):
            self.provider.get_options(expiry="2026-11-04")
        self.source.missing_oi = True
        with self.assertRaises(KeyError):
            self.provider.get_options()
        self.provider.master = SimpleNamespace(options=lambda budget: contract_rows()[1:])
        with self.assertRaisesRegex(MarketDataError, "incomplete"):
            self.provider.get_options()

    def test_heavyweight_failure_blocks_entry_context(self):
        self.source.failed_heavyweights = True
        with self.assertRaises(TimeoutError):
            MarketContextService(self.provider, lambda: {}).fetch()
        # Exposure management retains its existing bounded optional breadth read.
        context = MarketContextService(self.provider, lambda: {}).fetch(monitor_only=True)
        self.assertEqual([], context["heavyweights"]["stocks"])

    def test_selection_is_explicit_and_independent_of_execution(self):
        with patch.dict(os.environ, {"MARKET_DATA_BROKER": "breeze"}):
            provider = create_market_data(gateway=SimpleNamespace(broker_name="kite"))
            self.assertIsInstance(provider.source, BreezeMarketSource)
            self.assertIsInstance(create_market_data("kite").source, KiteSessionSource)
        gateway = SimpleNamespace(broker_name="breeze")
        self.assertIs(gateway, create_market_data("breeze", gateway=gateway).source.gateway)
        with self.assertRaises(ValueError):
            create_market_data("proxy")

    def test_diagnostic_checks_all_contracts_and_returns_failure(self):
        self.assertTrue(inspect_market_data(self.provider)["ready"])
        self.source.timestamp = (NOW - timedelta(minutes=1)).isoformat()
        report = inspect_market_data(self.provider)
        self.assertFalse(report["ready"])
        self.assertEqual(10, len(report["capabilities"]))

    def test_unhealthy_direct_provider_blocks_entries_even_with_ignore_flag(self):
        from tests.scenarios import make_trader

        with tempfile.TemporaryDirectory(prefix=".market-gate-", dir=ROOT) as directory:
            trader = make_trader(Path(directory) / "active.json")
            trader.market_data = self.provider
            self.source.timestamp = (NOW - timedelta(minutes=1)).isoformat()
            result = CycleWorkflow(Path(directory), 10).run(trader, ignore_feed_health=True)
            self.assertFalse(result["has_open_trades"])
            self.assertFalse(any(call[0] in ("POST", "PATCH", "DELETE") for call in trader.client.calls))
            self.assertEqual([], self.source.calls[1:])

    def test_cli_market_selection_takes_precedence_without_changing_execution_selection(self):
        calls = []

        def factory(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                client=SimpleNamespace(get_status=lambda: {"mode": "PAPER"}),
                intelligence=SimpleNamespace(stop_worker=lambda: True),
                run_cycle=lambda **kwargs: {},
            )

        with (
            patch.dict(os.environ, {"MARKET_DATA_BROKER": "kite"}),
            patch("sys.argv", ["scheduler", "--once", "--broker", "proxy", "--market-data-broker", "breeze"]),
        ):
            run_scheduler(factory)
        self.assertEqual("proxy", calls[0]["broker"])
        self.assertEqual("breeze", calls[0]["market_data_broker"])


class JsonResponse(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class SourceContractTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(MarketClock, "now_ist", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_kite_session_wire_and_previous_close_oi_are_preserved(self):
        calls = []

        def opener(request, **kwargs):
            calls.append(request)
            parsed = urlsplit(request.full_url)
            self.assertEqual("kite.zerodha.com", parsed.hostname)
            self.assertEqual("enctoken test-session", request.get_header("Authorization"))
            if "historical" in parsed.path:
                return JsonResponse(
                    {
                        "status": "success",
                        "data": {"candles": [["2026-10-21T00:00:00+05:30", 10, 11, 9, 10, 500, 300]]},
                    }
                )
            keys = parse_qs(parsed.query)["i"]
            return JsonResponse(
                {
                    "status": "success",
                    "data": {
                        key: dict(
                            instrument_token=256265,
                            last_price=20,
                            ohlc=dict(open=19, high=21, low=18, close=19),
                            oi=400,
                            volume=800,
                            timestamp=NOW.isoformat(),
                        )
                        for key in keys
                    },
                }
            )

        source = KiteSessionSource("test-session", "test-user", opener=opener)
        source.quote_limiter.acquire = lambda **kwargs: True
        source.history_limiter.acquire = lambda **kwargs: True
        self.assertEqual(20, source.quotes([SPOT], ReadBudget(5))[SPOT]["last_price"])
        contract = dict(symbol="REAL-KITE-SYMBOL", token=123, strike=22650, right="CE")
        quote = source.option_quotes([contract], EXPIRY, ReadBudget(5))[contract["symbol"]]
        self.assertEqual(100, quote["oi_change"])
        source.option_quotes([contract], EXPIRY, ReadBudget(5))
        self.assertEqual(1, sum("historical" in r.full_url for r in calls))
        self.assertTrue(all(r.get_method() == "GET" for r in calls))

    def test_missing_kite_session_never_falls_back_to_paid_api_or_local_server(self):
        source = KiteSessionSource(opener=lambda *args, **kwargs: self.fail("Unexpected HTTP"))
        source.enctoken = source.user_id = ""
        self.assertFalse(BrokerMarketData(source).get_data_quality()["quote_ready"])

    def test_breeze_wire_normalization_and_contract_identity(self):
        calls = []

        class Gateway:
            _lock = nullcontext()

            @contextmanager
            def read_budget(self, seconds):
                yield

            def _ensure_verified(self):
                pass

            def _request(self, method, path, data, **kwargs):
                calls.append((method, path, data))
                return [
                    dict(
                        stock_code=data["stock_code"],
                        exchange_code="NSE",
                        ltp="22649",
                        open="22750",
                        high="22785",
                        low="22564",
                        previous_close="22810",
                        ltt="22-Oct-2026 10:00:00",
                    )
                ]

            def get_historical_candles(self, instrument_id, start, end, **kwargs):
                calls.append(("history", instrument_id))
                return {"candles": []}

            def get_option_chain(self, expiry, right):
                return {
                    "contracts": [
                        dict(
                            stock_code="NIFTY",
                            exchange_code="NFO",
                            expiry_date="27-Oct-2026",
                            right=right.title(),
                            strike_price=22650,
                            ltp="80",
                            open_interest="500",
                            chnge_oi="-50",
                            total_quantity_traded="200",
                            ltt="22-Oct-2026 10:00:00",
                        )
                    ]
                }

        source = BreezeMarketSource(Gateway())
        provider = BrokerMarketData(source, master=SimpleNamespace(options=lambda b: contract_rows()))
        self.assertEqual("NIFTY 50", provider.get_snapshot()["underlying"]["symbol"])
        self.assertEqual(5, len(provider.get_heavyweights()["stocks"]))
        self.assertIn("HDFBAN", [call[2]["stock_code"] for call in calls if call[0] == "GET"])
        chain = provider.get_options(0)
        self.assertEqual(-50, chain["strikes"][0]["call"]["oi_change"])
        source.history(NOW, NOW, ReadBudget(5))
        self.assertEqual(("history", "INST-NIFTY-INDEX"), calls[-1])
        source.stock_codes[SPOT] = "WRONG"
        with patch.object(
            source.gateway, "_request", return_value=[{"stock_code": "NIFTY", "exchange_code": "NFO"}]
        ):
            with self.assertRaises(MarketDataError):
                provider.get_snapshot()

    def test_instrument_master_reads_exact_symbols_filters_futures_and_rolls_expiry(self):
        buffer = io.StringIO()
        fields = [
            "instrument_token",
            "tradingsymbol",
            "name",
            "expiry",
            "strike",
            "instrument_type",
            "segment",
            "exchange",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fields)
        writer.writeheader()
        for right, expiry, segment in (
            ("CE", EXPIRY, "NFO-OPT"),
            ("PE", EXPIRY, "NFO-OPT"),
            ("FUT", EXPIRY, "NFO-FUT"),
            ("CE", "2026-10-21", "NFO-OPT"),
        ):
            writer.writerow(
                dict(
                    instrument_token=123,
                    tradingsymbol="NIFTY-EXACT-" + right,
                    name="NIFTY",
                    expiry=expiry,
                    strike=22650,
                    instrument_type=right,
                    segment=segment,
                    exchange="NFO",
                )
            )
        calls = []

        def opener(request, **kwargs):
            calls.append(request.full_url)
            return io.BytesIO(buffer.getvalue().encode())

        master = InstrumentMaster(opener=opener)
        self.assertEqual(2, len(master.options(ReadBudget(5))))
        self.assertEqual("NIFTY-EXACT-CE", master.options(ReadBudget(5))[0]["symbol"])
        self.assertEqual(1, len(calls))
        with self.assertRaises(ValueError):
            InstrumentMaster("../outside.csv")


if __name__ == "__main__":
    unittest.main()
