"""VIX, sector AI context, native depth and deterministic stream failure scenarios."""

import copy
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from ai_consultant import AIConsultant
from market_clock import MarketClock
from test_self_healing_exit import entry_dossier, approved_decision, Broker, Trader
from tests.test_market_data import NOW, EXPIRY, ROOT, FixtureSource, contract_rows, candle_rows, JsonResponse
from trading.adapters.kite_stream import KiteTickStream, TickStore
from trading.adapters.market_data import BrokerMarketData
from trading.adapters.market_sources import (
    BreezeMarketSource,
    KiteSessionSource,
    MarketDataError,
    ReadBudget,
    SPOT,
    VIX,
)
from trading.adapters.gateways.breeze import BreezeExecutionGateway
from trading.application.dossier import DossierService
from trading.application.market_context import MarketContextService
from trading.application.position_monitor import PositionMonitor
from trading.domain.volatility import vix_exit_settings, validate_vix_policy


class EnhancementTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(MarketClock, "now_ist", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.source = FixtureSource()
        self.provider = BrokerMarketData(
            self.source, master=SimpleNamespace(options=lambda budget: contract_rows())
        )

    def test_vix_sector_payloads_and_dossier_preserve_values_and_timestamps(self):
        original = self.source.quotes

        def quotes(symbols, budget):
            result = original(symbols, budget)
            for symbol, (price, close) in {
                VIX: (14.25, 13.73),
                "NIFTY BANK": (51200, 51675),
                "NIFTY IT": (42150, 41795),
            }.items():
                if symbol in result:
                    result[symbol].update(last_price=price, close=close)
            return result

        self.source.quotes = quotes
        snapshot = self.provider.get_snapshot()
        self.assertEqual(14.25, snapshot["vix"]["last_price"])
        self.assertEqual(3.7873, snapshot["vix"]["change_pct"])
        self.assertEqual({"BANKNIFTY", "NIFTYIT"}, set(self.provider.get_sectors()))
        self.assertEqual(snapshot["vix"], self.provider("/vix"))
        ctx = MarketContextService(self.provider, lambda: {"available_margin": 10000}).fetch()
        dossier = DossierService({}).build_dossier(ctx, {"signal": "BUY_CE", "ltp": 80}, [], 0)
        self.assertEqual(14.25, dossier.vix["last_price"])
        self.assertTrue(dossier.sector_divergence)
        self.assertIn("BANKNIFTY", dossier.to_markdown())
        self.assertIn("India VIX", dossier.to_markdown())
        dossier.sectors["BANKNIFTY"]["last_price"] = 1
        self.assertEqual(51200, ctx["sectors"]["BANKNIFTY"]["last_price"])

    def test_actual_ai_vetoes_divergence_and_still_enforces_existing_traps(self):
        dossier = entry_dossier(67)
        self.assertEqual("APPROVED", AIConsultant().evaluate(dossier).action)
        dossier.sector_divergence = True
        verdict = AIConsultant().evaluate(dossier)
        self.assertEqual("VETOED", verdict.action)
        self.assertIn("Sector Divergence", verdict.trap_detected)
        self.assertEqual(
            "APPROVED",
            AIConsultant(trading_config={"ai_context": {"sector_divergence_veto": False}})
            .evaluate(dossier)
            .action,
        )
        dossier.option_entry_price = 8.0
        dossier.is_expiry_0dte = True
        self.assertIn("Trap 2", AIConsultant().evaluate(dossier).trap_detected)

    def test_depth_resolves_exact_contract_and_retains_real_levels(self):
        def depth(contract, budget):
            return dict(
                timestamp=NOW.isoformat(),
                depth=dict(
                    buy=[dict(price=141.45 - i * 0.05, quantity=650 + i * 65) for i in range(5)],
                    sell=[dict(price=141.50 + i * 0.05, quantity=650 + i * 65) for i in range(5)],
                ),
            )

        self.source.depth = depth
        identity = f"INST-NIFTY-{EXPIRY}-22650-PE"
        quote = self.provider.get_contract_quote(identity)
        self.assertEqual("LIVE", quote["status"])
        self.assertEqual(identity, quote["instrument_id"])
        self.assertEqual(141.45, quote["best_bid"])
        self.assertEqual(650, quote["best_ask_qty"])
        self.assertEqual(5, len(quote["depth"]["buy"]))
        symbol = quote["symbol"]
        self.assertEqual(symbol, self.provider.get_contract_quote(symbol)["instrument_id"])
        bundle = self.provider.get_entry_quotes(identity, include_index=True)
        self.assertEqual("LIVE", bundle["quote"]["status"])
        self.assertEqual("INST-NIFTY-INDEX", bundle["spot_quote"]["instrument_id"])
        self.assertTrue(self.provider.get_contract_quote("UNVERIFIED")["error"])

    def test_stale_future_crossed_empty_fractional_or_off_tick_depth_fails_closed(self):
        original = self.source.depth
        variants = [
            dict(timestamp=(NOW - timedelta(seconds=3)).isoformat()),
            dict(timestamp=(NOW + timedelta(seconds=1)).isoformat()),
            dict(depth=dict(buy=[], sell=[])),
            dict(depth=dict(buy=[dict(price=82, quantity=65)], sell=[dict(price=81, quantity=65)])),
            dict(depth=dict(buy=[dict(price=79, quantity=1.5)], sell=[dict(price=81, quantity=65)])),
            dict(depth=dict(buy=[dict(price=79.01, quantity=65)], sell=[dict(price=81, quantity=65)])),
            dict(depth=dict(buy=[dict(price=79, quantity=0)], sell=[dict(price=81, quantity=65)])),
        ]
        for changes in variants:
            with self.subTest(changes=changes):
                self.source.depth = lambda c, b: dict(original(c, b), **changes)
                self.assertEqual(
                    "UNAVAILABLE", self.provider.get_contract_quote(f"INST-NIFTY-{EXPIRY}-22650-PE")["status"]
                )

    def test_optional_vix_policy_tightens_without_mutation_and_ignores_stale_inputs(self):
        cfg = dict(
            target_pct=50, initial_stop_pct=30, trail_pullback_pct=10, vix_adaptation=dict(enabled=True)
        )
        baseline = copy.deepcopy(cfg)
        vix = dict(last_price=12, change_pct=0, timestamp=NOW.isoformat())
        adjusted = vix_exit_settings(cfg, vix, NOW)
        self.assertEqual(40, adjusted["target_pct"])
        self.assertEqual(7.5, adjusted["trail_pullback_pct"])
        self.assertEqual(30, adjusted["initial_stop_pct"])
        self.assertEqual(baseline, cfg)
        self.assertEqual(
            cfg, vix_exit_settings(cfg, dict(vix, timestamp=(NOW - timedelta(seconds=20)).isoformat()), NOW)
        )
        self.assertEqual(cfg, vix_exit_settings(cfg, dict(vix, last_price=18, change_pct=2), NOW))
        self.assertEqual(
            40, vix_exit_settings(cfg, dict(vix, last_price=18, change_pct=-4), NOW)["target_pct"]
        )
        with self.assertRaises(ValueError):
            validate_vix_policy(dict(vix_adaptation=dict(enabled=True, target_factor=1.1)))

    def test_monitor_uses_vix_target_and_never_lowers_a_persisted_trailing_floor(self):
        cfg = dict(
            exit=dict(
                target_pct=50,
                profit_target_enabled=True,
                runner_activation_pct=15,
                vix_adaptation=dict(enabled=True),
            )
        )
        exits, ratchets = [], []
        monitor = PositionMonitor(
            cfg,
            True,
            lambda *args, **kwargs: exits.append(args) or {"status": "CLOSED"},
            lambda trade, trigger: ratchets.append(trigger),
        )
        trade = dict(
            trade_id="E1",
            status="OPEN",
            symbol="NIFTY-CE",
            entry_price=100,
            last_bid=145,
            peak_bid=145,
            quote_verified=True,
        )
        vix = dict(last_price=12, change_pct=0, timestamp=NOW.isoformat())
        monitor.manage([trade], {"vix": vix}, {})
        self.assertIn("40.0%", exits[0][1])
        cfg["exit"]["profit_target_enabled"] = False
        trade.update(last_bid=150, peak_bid=150, desired_stop_trigger=140)
        monitor.manage([trade], {"vix": vix}, {})
        monitor.manage([trade], {"vix": dict(vix, last_price=22)}, {})
        self.assertTrue(all(trigger >= 140 for trigger in ratchets))

    def test_native_quote_reader_drives_real_ai_approved_entry_and_stale_book_blocks_submit(self):
        self.provider.master = SimpleNamespace(
            options=lambda b: [dict(expiry=EXPIRY, strike=22650, right="CE", symbol="TEST", token=123)]
        )
        calls = []

        def depth(contract, budget):
            calls.append(contract["symbol"])
            return dict(
                timestamp=self.source.timestamp,
                depth=dict(buy=[dict(price=66.95, quantity=650)], sell=[dict(price=67, quantity=650)]),
            )

        self.source.depth = depth
        for stale in (False, True):
            with (
                self.subTest(stale=stale),
                tempfile.TemporaryDirectory(prefix=".native-book-", dir=ROOT) as directory,
            ):
                broker = Broker()
                broker.quote_ask = broker.fill_price = 67
                trader = Trader(Path(directory) / "active.json", broker)
                trader.quote_reader = self.provider
                decision = approved_decision(trader.trading_cfg, 67)
                self.source.timestamp = (NOW - timedelta(seconds=2)).isoformat() if stale else NOW.isoformat()
                result = trader.execute_trade(decision)
                if stale:
                    self.assertTrue(result["error"])
                    self.assertFalse(any(call[:2] == ("POST", "/execution/orders") for call in broker.calls))
                else:
                    self.assertEqual("SUCCESS", result["status"])
                    self.assertTrue(any(call[:2] == ("POST", "/execution/orders") for call in broker.calls))
                self.assertFalse(any(call[:2] == ("GET", "/market/quote/TEST") for call in broker.calls))
        self.assertTrue(calls)

    def test_breeze_native_depth_preserves_bid_ask_quantities_and_contract_identity(self):
        wire = []

        def request(method, endpoint, body, **kwargs):
            wire.append((method, endpoint, body))
            return [
                dict(
                    stock_code="NIFTY",
                    exchange_code="NFO",
                    product_type="options",
                    expiry_date=EXPIRY,
                    strike_price="22650",
                    right="put",
                    ltp="141.5",
                    ltt=NOW.isoformat(),
                    best_bid_price="141.45",
                    best_offer_price="141.50",
                    best_bid_quantity="650",
                    best_offer_quantity="780",
                )
            ]

        gateway = SimpleNamespace(
            _lock=nullcontext(),
            read_budget=lambda seconds: nullcontext(),
            _ensure_verified=lambda: None,
            _request=request,
            _contracts={},
            journal=SimpleNamespace(records={}),
        )
        gateway._raw_identity = lambda raw: BreezeExecutionGateway._raw_identity(gateway, raw)
        provider = BrokerMarketData(BreezeMarketSource(gateway), master=self.provider.master)
        quote = provider.get_contract_quote(f"INST-NIFTY-{EXPIRY}-22650-PE")
        self.assertEqual(650, quote["best_bid_qty"])
        self.assertEqual(780, quote["best_ask_qty"])
        self.assertEqual("put", wire[0][2]["right"])
        self.assertEqual("NFO", wire[0][2]["exchange_code"])
        self.assertTrue(all(call[0] == "GET" for call in wire))


class TickStoreTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW.replace(hour=9, minute=15, second=10)
        self.elapsed = 100.0
        self.clock = patch.object(MarketClock, "now_ist", side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.store = TickStore(monotonic=lambda: self.elapsed)
        self.store.spot_token = 256265
        self.store.connection(True)

    def tick(self, price=100, *, token=256265):
        self.store.put(
            dict(
                instrument_token=token,
                last_price=price,
                timestamp=self.now.isoformat(),
                ohlc=dict(open=100, high=105, low=95, close=99),
            )
        )

    def test_receive_age_exchange_age_and_reconnect_require_new_ticks(self):
        self.tick()
        self.assertEqual(100, self.store.quote(256265)["last_price"])
        self.elapsed += 1
        with self.assertRaises(MarketDataError):
            self.store.quote(256265, max_age=1)
        self.store.connection(False)
        with self.assertRaises(MarketDataError):
            self.store.quote(256265)
        self.store.connection(True)
        with self.assertRaises(MarketDataError):
            self.store.quote(256265)
        self.tick(101)
        self.assertEqual(101, self.store.quote(256265)["last_price"])
        self.now += timedelta(seconds=20)
        with self.assertRaises(MarketDataError):
            self.store.quote(256265)

    def test_out_of_order_and_previous_session_ticks_do_not_replace_current_quote(self):
        self.tick(101)
        self.store.put(
            dict(
                instrument_token=256265,
                last_price=99,
                timestamp=(self.now - timedelta(seconds=1)).isoformat(),
            )
        )
        self.assertEqual(101, self.store.quote(256265)["last_price"])
        self.store.put(
            dict(instrument_token=256265, last_price=99, timestamp=(self.now - timedelta(days=1)).isoformat())
        )
        with self.assertRaises(MarketDataError):
            self.store.quote(256265)

    def test_partial_startup_minute_requires_backfill_then_complete_minutes_use_ticks(self):
        self.store.seed([])
        for second in (10, 25, 40, 55):
            self.now = self.now.replace(minute=15, second=second)
            self.tick(100)
        for second, price in ((5, 101), (20, 104), (35, 98), (50, 102)):
            self.now = self.now.replace(minute=16, second=second)
            self.tick(price)
        self.now = self.now.replace(minute=17, second=5)
        self.tick(103)
        with self.assertRaisesRegex(MarketDataError, "backfill"):
            self.store.history()
        self.store.seed([[self.now.replace(minute=15, second=0).isoformat(), 100, 100, 100, 100, 0]])
        bars = self.store.history()
        self.assertEqual(2, len(bars))
        self.assertEqual(
            dict(open=101, high=104, low=98, close=102),
            {k: bars[-1][k] for k in ("open", "high", "low", "close")},
        )
        self.assertEqual(0, bars[-1]["volume"])

    def test_disconnect_gap_and_daily_rollover_invalidate_candles(self):
        self.now = NOW
        self.store.connection(True)
        self.tick()
        self.store.seed(candle_rows())
        self.assertEqual(45 + 375, len(self.store.history()))
        self.store.connection(False)
        self.now += timedelta(minutes=2)
        self.store.connection(True)
        self.tick()
        with self.assertRaisesRegex(MarketDataError, "backfill"):
            self.store.history()
        self.now += timedelta(days=1)
        self.tick()
        with self.assertRaisesRegex(MarketDataError, "backfill"):
            self.store.history()


class FakeTicker:
    MODE_FULL = "full"

    def __init__(self, api_key, access_token, **kwargs):
        self.credentials = (api_key, access_token)
        self.socket_url = "wss://ws.kite.trade"
        self.commands = []
        self.closed = False

    def connect(self, threaded=False):
        self.commands.append(("connect", threaded))
        self.on_connect(self, {})

    def subscribe(self, tokens):
        self.commands.append(("subscribe", tokens))

    def set_mode(self, mode, tokens):
        self.commands.append(("mode", mode, tokens))
        self.on_ticks(
            self,
            [
                dict(
                    instrument_token=token,
                    last_price=22649,
                    exchange_timestamp=NOW,
                    ohlc=dict(open=22750, high=22785, low=22564, close=22810),
                    volume_traded=100,
                    oi=200,
                    depth=dict(
                        buy=[dict(price=141.45, quantity=650)], sell=[dict(price=141.50, quantity=650)]
                    ),
                )
                for token in tokens
            ],
        )

    def close(self):
        self.closed = True
        self.on_close(self, 1000, "closed")


class StreamLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(MarketClock, "now_ist", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def test_web_and_connect_configuration_full_subscriptions_and_shutdown(self):
        for transport in ("web", "connect"):
            with self.subTest(transport=transport):
                stream = KiteTickStream(
                    transport=transport,
                    enctoken="test-session",
                    user_id="user",
                    api_key="key",
                    access_token="access",
                    ticker_factory=FakeTicker,
                )
                stream.subscribe([256265], spot_token=256265)
                stream.start()
                self.assertEqual(22649, stream.store.quote(256265)["last_price"])
                self.assertIn(("mode", "full", [256265]), stream._ticker.commands)
                if transport == "web":
                    self.assertEqual("ws.zerodha.com", urlsplit(stream._ticker.socket_url).hostname)
                    self.assertEqual(
                        ["test-session"], parse_qs(urlsplit(stream._ticker.socket_url).query)["enctoken"]
                    )
                else:
                    self.assertEqual(("key", "access"), stream._ticker.credentials)
                stream._on_disconnect()
                with self.assertRaises(MarketDataError):
                    stream.store.quote(256265)
                stream._on_connect(stream._ticker, {})
                self.assertEqual(22649, stream.store.quote(256265)["last_price"])
                stream.close()
                self.assertTrue(stream._ticker.closed)
                with self.assertRaises(MarketDataError):
                    stream.start()

    def test_cached_quotes_do_not_poll_rest_and_history_only_bootstraps_once(self):
        calls = []

        def opener(request, **kwargs):
            calls.append(request.full_url)
            if "historical" in request.full_url:
                return JsonResponse(dict(status="success", data={"candles": candle_rows()}))
            keys = parse_qs(urlsplit(request.full_url).query)["i"]
            return JsonResponse(
                dict(status="success", data={key: dict(instrument_token=256265) for key in keys})
            )

        stream = KiteTickStream(enctoken="session", user_id="user", ticker_factory=FakeTicker)
        source = KiteSessionSource("session", "user", opener=opener, stream=stream)
        source.quote_limiter.acquire = lambda **kwargs: True
        source.history_limiter.acquire = lambda **kwargs: True
        for _ in range(3):
            self.assertEqual(22649, source.quotes([SPOT], ReadBudget(5))[SPOT]["last_price"])
        for _ in range(2):
            self.assertEqual(420, len(source.history(NOW - timedelta(days=10), NOW, ReadBudget(5))))
        self.assertEqual(2, len(calls))  # Token discovery + one history seed.
        source.close()

    def test_missing_credentials_and_subscription_overflow_never_connect(self):
        with self.assertRaises(MarketDataError):
            KiteTickStream(ticker_factory=lambda *args: self.fail("Unexpected connection")).start()
        with self.assertRaises(MarketDataError):
            KiteTickStream().subscribe(range(3001))

    def test_executable_stream_depth_checks_monotonic_receive_age_below_one_second(self):
        elapsed = [100.0]
        store = TickStore(monotonic=lambda: elapsed[0])
        stream = KiteTickStream(enctoken="session", user_id="user", ticker_factory=FakeTicker, store=store)
        source = KiteSessionSource(
            "session",
            "user",
            stream=stream,
            opener=lambda *args, **kwargs: self.fail("Unexpected REST quote"),
        )
        contract = dict(symbol="NIFTY-EXACT", token=123, expiry=EXPIRY, strike=22650, right="PE")
        self.assertIn("depth", source.depth(contract, ReadBudget(1)))
        elapsed[0] += 1.1
        # Wall-clock/exchange timestamp is unchanged; monotonic age still rejects the book.
        with self.assertRaises(TimeoutError):
            source.depth(contract, ReadBudget(0.01))
        source.close()

    def test_sdk_host_naive_timestamps_convert_to_ist_and_timestamp_less_packets_are_rejected(self):
        stream = KiteTickStream(enctoken="session", user_id="user", ticker_factory=FakeTicker)
        stream.start()
        stream._on_ticks(
            None,
            [
                dict(
                    instrument_token=123,
                    last_price=100,
                    exchange_timestamp=datetime.fromtimestamp(NOW.timestamp()),
                )
            ],
        )
        self.assertEqual(NOW.isoformat(), stream.store.quote(123)["timestamp"])
        stream._on_ticks(None, [dict(instrument_token=123, last_price=101)])
        with self.assertRaises(MarketDataError):
            stream.store.quote(123)
        stream.close()


if __name__ == "__main__":
    unittest.main()
