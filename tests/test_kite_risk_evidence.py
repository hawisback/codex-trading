"""Offline account-day reconciliation and official contract-source contracts."""

import copy
from datetime import datetime, timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from market_clock import IST_TZ, MarketClock
from trading.adapters.gateways.kite import KiteExecutionGateway
from trading.adapters.kite_contract_evidence import (
    KiteContractEvidence,
    KITE_MASTER_URL,
    NSE_FREEZE_URL,
    NSE_CALENDAR_URL,
)
from trading.domain.broker_contracts import BrokerContractError
from trading.domain.kite_daily_pnl import kite_daily_pnl

NOW = datetime(2026, 10, 30, 11, 0, tzinfo=IST_TZ)
SYMBOL = "NIFTY26NOV24000CE"
INSTRUMENT = "INST-NIFTY-2026-11-17-24000-CE"
MASTER = (
    "instrument_token,tradingsymbol,name,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange\n"
    f"12345,{SYMBOL},NIFTY,2026-11-17,24000,0.05,65,CE,NFO-OPT,NFO\n"
)
FREEZE = '"S.No.","SYMBOL    ","VOL_FRZ_QTY    "\n1,NIFTY,3510\n2,BANKNIFTY,900\n'
CALENDAR = json.dumps({"FO": [{"tradingDate": day} for day in ("26-Jan-2026", "24-Nov-2026", "25-Dec-2026")]})


def row(**changes):
    return dict(
        exchange="NFO",
        tradingsymbol=SYMBOL,
        product="NRML",
        quantity=65,
        overnight_quantity=0,
        day_buy_quantity=130,
        day_sell_quantity=65,
        day_buy_value=13000,
        day_sell_value=5850,
        realised=-650,
        unrealised=-325,
        pnl=-975,
        **changes,
    )


def fills():
    return [
        dict(
            exchange="NFO",
            tradingsymbol=SYMBOL,
            product="NRML",
            trade_id="1",
            order_id="B1",
            transaction_type="BUY",
            quantity=130,
            average_price=100,
            fill_timestamp="2026-10-30 10:00:00",
        ),
        dict(
            exchange="NFO",
            tradingsymbol=SYMBOL,
            product="NRML",
            trade_id="2",
            order_id="S1",
            transaction_type="SELL",
            quantity=65,
            average_price=90,
            fill_timestamp="2026-10-30 10:30:00",
        ),
    ]


class KiteDailyPnlTests(unittest.TestCase):
    def setUp(self):
        self.positions = {"net": [row()], "day": [row()]}
        self.trades = fills()

    def normalize(self):
        return kite_daily_pnl(self.positions, self.trades, account_id="OFFLINE-TEST", observed_at=NOW)

    def test_partial_sell_retains_realized_and_unrealized_loss(self):
        result = self.normalize()
        self.assertEqual("-650", result["realized_pnl_today"])
        self.assertEqual("-325", result["unrealized_pnl_today"])
        self.assertEqual("2026-10-30", result["pnl_session_date"])

    def test_closed_positions_remain_in_daily_loss(self):
        for name in ("net", "day"):
            self.positions[name][0].update(
                quantity=0,
                day_sell_quantity=130,
                day_sell_value=11700,
                realised=-1300,
                unrealised=0,
                pnl=-1300,
            )
        self.trades[1]["quantity"] = 130
        self.assertEqual("-1300", self.normalize()["realized_pnl_today"])

    def test_authenticated_complete_empty_books_are_zero(self):
        self.positions, self.trades = {"net": [], "day": []}, []
        self.assertEqual("0", self.normalize()["realized_pnl_today"])

    def test_missing_or_partial_positions_are_not_zero(self):
        for positions in (
            {},
            {"net": []},
            {"net": [], "day": None},
            {"error": True, "net": [], "day": []},
            {"truncated": True, "net": [], "day": []},
            {"has_more": True, "net": [], "day": []},
            {"next_cursor": "more", "net": [], "day": []},
        ):
            self.positions = positions
            with self.subTest(positions=positions), self.assertRaises(BrokerContractError):
                self.normalize()

    def test_missing_position_fields_or_overnight_basis_fail_closed(self):
        original = copy.deepcopy(self.positions)
        for field in original["net"][0]:
            self.positions = copy.deepcopy(original)
            del self.positions["net"][0][field]
            with self.subTest(field=field), self.assertRaises(BrokerContractError):
                self.normalize()
        self.positions = original
        self.positions["net"][0]["overnight_quantity"] = 65
        with self.assertRaisesRegex(BrokerContractError, "CARRY_POSITION"):
            self.normalize()

    def test_missing_duplicate_stale_and_wrong_value_fills_fail_closed(self):
        original = copy.deepcopy(self.trades)
        for trades in (
            original[:1],
            original + original[:1],
            [],
            None,
            [{**original[0], "fill_timestamp": "2026-10-29 10:00:00"}, original[1]],
            [{**original[0], "quantity": 65}, original[1]],
            [{**original[0], "average_price": 90}, original[1]],
            [{**original[0], "transaction_type": "UNKNOWN"}, original[1]],
            [{**original[0], "fill_timestamp": "2026-10-30 12:00:00"}, original[1]],
        ):
            self.trades = trades
            with self.subTest(trades=trades), self.assertRaises(BrokerContractError):
                self.normalize()

    def test_duplicate_rows_or_nonfinite_pnl_are_rejected(self):
        for broken in (dict(realised="NaN"), dict(unrealised=None), dict(pnl=-999), dict(quantity=True)):
            self.positions = {"net": [{**row(), **broken}], "day": [row()]}
            with self.subTest(broken=broken), self.assertRaises(BrokerContractError):
                self.normalize()
        self.positions = {"net": [row(), row()], "day": [row()]}
        with self.assertRaises(BrokerContractError):
            self.normalize()


class KiteContractEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.clock = patch.object(MarketClock, "now_ist", return_value=NOW)
        self.clock_mock = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.master, self.freeze, self.calendar, self.urls = MASTER, FREEZE, CALENDAR, []
        self.evidence = KiteContractEvidence(opener=self.open)

    def open(self, request, timeout):
        self.urls.append(request.full_url)
        self.assertGreater(timeout, 0)
        self.assertFalse(request.get_header("Authorization"))
        sources = {KITE_MASTER_URL: self.master, NSE_FREEZE_URL: self.freeze, NSE_CALENDAR_URL: self.calendar}
        return io.BytesIO(sources[request.full_url].encode())

    def read(self, **kwargs):
        return self.evidence.for_entry(INSTRUMENT, SYMBOL, lot_size=65, tick_size="0.05", **kwargs)

    def test_exact_contract_uses_exchange_limit_and_provenance(self):
        result = self.read()
        self.assertEqual(3510, result["max_single_order_quantity"])
        self.assertEqual(INSTRUMENT, result["contract_evidence"]["instrument_id"])
        self.assertEqual(64, len(result["contract_evidence"]["master_sha256"]))
        self.assertEqual([KITE_MASTER_URL, NSE_FREEZE_URL, NSE_CALENDAR_URL], self.urls)
        self.read()
        self.assertEqual(3, len(self.urls))

    def test_wrong_instrument_lot_tick_and_duplicate_contract_are_rejected(self):
        for master in (
            MASTER.replace(",65,", ",75,"),
            MASTER.replace("0.05", "0.1"),
            MASTER + MASTER.splitlines()[1] + "\n",
        ):
            self.master = master
            self.evidence = KiteContractEvidence(opener=self.open)
            with self.subTest(master=master), self.assertRaises(BrokerContractError):
                self.read()
        self.master = MASTER
        self.evidence = KiteContractEvidence(opener=self.open)
        with self.assertRaisesRegex(BrokerContractError, "IDENTITY_MISMATCH"):
            self.evidence.for_entry(
                INSTRUMENT.replace("24000", "24100"), SYMBOL, lot_size=65, tick_size="0.05"
            )

    def test_missing_invalid_or_ambiguous_freeze_is_not_guessed(self):
        for freeze in (
            "error",
            FREEZE.replace("NIFTY,3510", "OTHER,3510"),
            FREEZE.replace("3510", "0"),
            FREEZE.replace("3510", "NaN"),
            FREEZE + "3,NIFTY,3510\n",
        ):
            self.freeze = freeze
            self.evidence = KiteContractEvidence(opener=self.open)
            with self.subTest(freeze=freeze), self.assertRaises(BrokerContractError):
                self.read()

    def test_new_session_requires_new_download(self):
        self.read()
        self.clock_mock.return_value = NOW + timedelta(days=3)
        self.read()
        self.assertEqual(6, len(self.urls))

    def test_stale_missing_and_incomplete_calendars_are_rejected(self):
        for calendar in (
            "{}",
            CALENDAR.replace("2026", "2025"),
            json.dumps({"FO": [{"tradingDate": "26-Jan-2026"}]}),
        ):
            self.calendar = calendar
            self.evidence = KiteContractEvidence(opener=self.open)
            with (
                self.subTest(calendar=calendar),
                self.assertRaisesRegex(BrokerContractError, "CALENDAR_UNVERIFIED"),
            ):
                self.read()

    def test_holiday_expiry_and_weekend_session_are_rejected(self):
        self.master = MASTER.replace("2026-11-17", "2026-11-24")
        with self.assertRaisesRegex(BrokerContractError, "NO_VERIFIED_TRADABLE_EXPIRY"):
            self.evidence.for_entry(
                INSTRUMENT.replace("11-17", "11-24"), SYMBOL, lot_size=65, tick_size="0.05"
            )
        self.clock_mock.return_value = NOW + timedelta(days=1)
        self.master = MASTER
        with self.assertRaisesRegex(BrokerContractError, "NOT_AN_EXCHANGE_SESSION"):
            self.read()


class KiteGatewayEvidenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".tools/tmp")
        self.addCleanup(temp.cleanup)
        self.gateway = KiteExecutionGateway(
            api_key="offline",
            access_token="offline",
            account_id="OFFLINE-TEST",
            journal_path=Path(temp.name) / "journal.json",
        )
        self.clock = patch.object(MarketClock, "now_ist", return_value=NOW)
        self.clock_mock = self.clock.start()
        self.addCleanup(self.clock.stop)
        self.calls = []
        self.payloads = {
            "/user/profile": {"user_id": "OFFLINE-TEST"},
            "/portfolio/positions": {"net": [], "day": []},
            "/trades": [],
            "/user/margins": {
                "equity": {"available": {"live_balance": 15000, "cash": 15000}, "utilised": {"debits": 0}}
            },
        }
        self.request = patch.object(self.gateway, "_request", side_effect=self.respond)
        self.request_mock = self.request.start()
        self.addCleanup(self.request.stop)

    def respond(self, method, endpoint, *args, **kwargs):
        self.assertEqual("GET", method)
        self.calls.append(endpoint)
        return copy.deepcopy(self.payloads[endpoint])

    def test_readonly_daily_pnl_does_not_arm_gateway_or_claim_unknown_zero(self):
        result = self.gateway.get_daily_pnl()
        self.assertEqual("0", result["realized_pnl_today"])
        self.assertFalse(self.gateway._live_authorized)
        self.payloads["/trades"] = {"error": True}
        self.assertTrue(self.gateway.get_daily_pnl()["error"])

    def test_entry_evidence_merges_independent_sources_and_preserves_real_margin(self):
        contract = {"max_single_order_quantity": 3510, "contract_evidence": {"symbol": SYMBOL}}
        self.gateway.register_contract(INSTRUMENT, SYMBOL)
        with patch.object(self.gateway._contract_evidence, "for_entry", return_value=contract):
            result = self.gateway.get_entry_funds(INSTRUMENT)
        self.assertEqual(15000, result["available_margin"])
        self.assertEqual(3510, result["max_single_order_quantity"])
        self.assertEqual("0", result["realized_pnl_today"])
        self.assertFalse(self.gateway._live_authorized)

    def test_session_or_credential_change_during_reads_invalidates_pnl(self):
        original = self.respond

        def changed(method, endpoint, *args, **kwargs):
            result = original(method, endpoint, *args, **kwargs)
            if endpoint == "/trades":
                self.clock_mock.return_value = NOW + timedelta(days=1)
            return result

        self.request_mock.side_effect = changed
        self.assertTrue(self.gateway.get_daily_pnl()["error"])


if __name__ == "__main__":
    unittest.main()
