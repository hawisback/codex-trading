"""Strict required-field/type mutations and actual broker request builders, offline."""

import copy
from email.message import Message
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from market_clock import MarketClock
from tests.test_market_data import NOW, ROOT, FixtureSource, contract_rows, JsonResponse
from tests.test_breeze_gateway import Server
from trading.adapters.market_data import BrokerMarketData
from trading.adapters.market_sources import KiteSessionSource, BreezeMarketSource, ReadBudget
from trading.adapters.gateways.breeze import BreezeExecutionGateway
from trading.application.market_context import MarketContextService
from trading.domain.market_contracts import ContractError, SCHEMAS, validate_market_contract
from tools.verify_market_data import BrokerHeaderObserver, verify_live
from tools.after_hours_market import verify_after_hours


def schema_nodes(schema, path=()):
    if isinstance(schema, dict):
        for key, child in schema.items():
            yield path + (key,), child
            yield from schema_nodes(child, path + (key,))
    elif isinstance(schema, list):
        yield from schema_nodes(schema[0], path + (0,))


def response_metadata(response, content_type="application/json", status=200):
    response.headers = Message()
    response.headers["Content-Type"] = content_type
    response.status = status
    return response


class SchemaContractTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(MarketClock, "now_ist", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.provider = BrokerMarketData(
            FixtureSource(), master=SimpleNamespace(options=lambda budget: contract_rows())
        )
        self.payloads = dict(
            data_quality=self.provider.get_data_quality(),
            snapshot=self.provider.get_snapshot(),
            candles_1m=self.provider.get_candles("1m", 375),
            candles_5m=self.provider.get_candles("5m", 50),
            technicals_5m=self.provider.get_technicals(),
            options=self.provider.get_options(),
            heavyweights=self.provider.get_heavyweights(),
            vix=self.provider.get_vix(),
            sectors=self.provider.get_sectors(),
            option_depth=self.provider.get_contract_quote("INST-NIFTY-2026-10-27-22650-PE"),
        )

    def test_all_ten_payload_variants_match_the_engine_contracts(self):
        self.assertEqual(set(SCHEMAS), set(self.payloads))
        for name, payload in self.payloads.items():
            with self.subTest(name=name):
                self.assertTrue(validate_market_contract(name, payload))

    def test_every_required_field_is_enforced_at_every_schema_node(self):
        for name, schema in SCHEMAS.items():
            for path, _ in schema_nodes(schema):
                broken = copy.deepcopy(self.payloads[name])
                parent = broken
                for key in path[:-1]:
                    parent = parent[key]
                del parent[path[-1]]
                with self.subTest(name=name, path=path), self.assertRaises(ContractError):
                    validate_market_contract(name, broken)

    def test_every_declared_field_rejects_incompatible_json_types(self):
        for name, schema in SCHEMAS.items():
            for path, child in schema_nodes(schema):
                broken = copy.deepcopy(self.payloads[name])
                parent = broken
                for key in path[:-1]:
                    parent = parent[key]
                wrong = (
                    []
                    if isinstance(child, dict)
                    else {}
                    if isinstance(child, list) or child in ("string", "timestamp", "date")
                    else "not-the-required-type"
                )
                parent[path[-1]] = wrong
                with self.subTest(name=name, path=path), self.assertRaises(ContractError):
                    validate_market_contract(name, broken)

    def test_booleans_numeric_strings_nan_and_infinite_values_are_not_numbers(self):
        for value in (True, False, "22649", float("nan"), float("inf"), None):
            broken = copy.deepcopy(self.payloads["snapshot"])
            broken["underlying"]["last_price"] = value
            with self.subTest(value=value), self.assertRaises(ContractError):
                validate_market_contract("snapshot", broken)

    def test_contract_identity_quantities_and_required_ist_timestamps_are_enforced(self):
        for stamp in ("2026-10-22T10:00:00", "2026-10-22T04:30:00Z", None):
            broken = copy.deepcopy(self.payloads["vix"])
            broken["timestamp"] = stamp
            with self.assertRaises(ContractError):
                validate_market_contract("vix", broken)
        broken = copy.deepcopy(self.payloads["options"])
        broken["strikes"][0]["call"]["open_interest"] = 1.5
        with self.assertRaises(ContractError):
            validate_market_contract("options", broken)
        broken = copy.deepcopy(self.payloads["option_depth"])
        broken["depth"]["buy"][0]["quantity"] += 65
        with self.assertRaises(ContractError):
            validate_market_contract("option_depth", broken)

    def test_real_engine_consumer_accepts_the_complete_payloads_and_uses_spot_vwap(self):
        context = MarketContextService(self.provider, lambda: {}).fetch()
        bars = self.payloads["candles_1m"]["candles"]
        expected = round(sum((b["high"] + b["low"] + b["close"]) / 3 for b in bars) / len(bars), 2)
        self.assertEqual(expected, context["session_vwap"])
        self.assertEqual("NIFTY_SPOT_INTRADAY", context["session_vwap_basis"])
        self.assertEqual(21, len(context["strikes"]))
        self.assertEqual(5, len(context["heavyweights"]["stocks"]))
        self.assertEqual(self.payloads["technicals_5m"]["metrics"]["ema_9"], context["ema_9"])

    def test_closed_book_requires_explicit_diagnostic_validation(self):
        book = copy.deepcopy(self.payloads["option_depth"])
        book["status"] = "CLOSED"
        with self.assertRaises(ContractError):
            validate_market_contract("option_depth", book)
        self.assertTrue(validate_market_contract("option_depth", book, require_live=False))

    def test_after_hours_checks_preserve_live_freshness_rejection(self):
        from datetime import timedelta

        source = self.provider.source
        source.broker_name, source.stream, source.user_id = "kite", None, "dummy-account"
        source._get = lambda *args: {"user_id": "dummy-account"}
        previous = copy.deepcopy(source.rows[:375])
        today = copy.deepcopy(previous)
        for bar in today:
            bar[0] = (MarketClock.parse_to_ist(bar[0]) + timedelta(days=1)).isoformat()
        source.rows = previous + today
        observer = SimpleNamespace(verified=1, failures=[])
        with patch.object(MarketClock, "now_ist", return_value=NOW.replace(hour=18)):
            result = verify_after_hours(self.provider, observer, 2)
            self.assertTrue(result["passed"], result["checks"])
            self.assertFalse(result["live_verified"])
            self.assertFalse(self.provider.get_data_quality()["quote_ready"])
            with self.assertRaises(Exception):
                self.provider.get_snapshot()
        with self.assertRaisesRegex(ValueError, "only available"):
            verify_after_hours(self.provider, observer, 2)


class BrokerHeaderContractTests(unittest.TestCase):
    def test_actual_kite_web_and_connect_request_builders_supply_required_headers(self):
        for mode in ("web", "connect_stream", "connect_rest"):
            source = KiteSessionSource(
                "dummy-session",
                "dummy-account",
                transport="connect" if mode == "connect_rest" else "web",
                api_key="dummy-key",
                access_token="dummy-access",
            )
            if mode == "connect_stream":
                source.stream = SimpleNamespace(
                    transport="connect", api_key="dummy-key", access_token="dummy-access"
                )
            observer = BrokerHeaderObserver(
                lambda request, **kw: response_metadata(JsonResponse(dict(status="success", data={})))
            )
            observer.provider = SimpleNamespace(source=source)
            source.opener = observer
            source.quote_limiter.acquire = lambda **kw: True
            self.assertEqual({}, source._get("/quote", {"i": ["NSE:NIFTY 50"]}, ReadBudget(2)))
            self.assertEqual(1, observer.verified)
            self.assertEqual([], observer.failures)

    def test_actual_breeze_session_and_signed_get_headers_and_checksum(self):
        with tempfile.TemporaryDirectory(prefix=".header-contract-", dir=ROOT) as directory:
            server = Server()
            observer = BrokerHeaderObserver(lambda request, **kw: response_metadata(server(request, **kw)))
            gateway = BreezeExecutionGateway(
                api_key="test-key",
                api_secret="test-secret",
                api_session="login-session",
                account_id="BREEZE_TEST",
                journal_path=Path(directory) / "intents.json",
            )
            gateway.rate_limiter.acquire = lambda **kw: True
            observer.provider = SimpleNamespace(source=BreezeMarketSource(gateway))
            with patch("urllib.request.urlopen", side_effect=observer):
                self.assertEqual(20000, gateway.get_funds()["available_margin"])
            self.assertGreaterEqual(observer.verified, 2)
            self.assertEqual([], observer.failures)
            self.assertTrue(all(call[0] == "GET" for call in server.calls))
            self.assertFalse(gateway.get_status()["live_authorized"])

    def test_missing_request_header_or_wrong_response_content_type_is_a_failure(self):
        source = KiteSessionSource("dummy-session", "dummy-account")
        observer = BrokerHeaderObserver(lambda request, **kw: response_metadata(JsonResponse({})))
        observer.provider = SimpleNamespace(source=source)
        import urllib.request

        with self.assertRaises(ContractError):
            observer(urllib.request.Request("https://kite.zerodha.com/oms/quote"))
        observer.opener = lambda request, **kw: response_metadata(JsonResponse({}), "text/html")
        source.opener = observer
        source.quote_limiter.acquire = lambda **kw: True
        with self.assertRaises(Exception):
            source._get("/quote", {}, ReadBudget(2))
        self.assertEqual(2, len(observer.failures))

    def test_missing_live_credentials_are_blocked_without_attempting_network(self):
        provider = BrokerMarketData(KiteSessionSource("unused", "unused"))
        provider.source.enctoken = ""
        with patch("tools.verify_market_data.create_market_data", return_value=provider):
            result = verify_live("kite", 1)
        self.assertFalse(result["passed"])
        self.assertEqual(["KITE_ENCTOKEN"], result["missing_configuration"])
        self.assertTrue(all(row["status"] == "BLOCKED" for row in result["checks"]))
