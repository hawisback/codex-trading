"""Offline R03-R05 contract coverage. Tests NOT executed per owner request."""

import unittest
from datetime import date, datetime

from market_clock import IST_TZ
from trading.domain.broker_contracts import BrokerContractError, BrokerFundsView, BrokerOrderView
from trading.domain.expiry_evidence import (
    ExpiryEvidence,
    ExpiryEvidenceError,
    listed_expiry_contracts,
)


class BrokerEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 29, 11, 30, tzinfo=IST_TZ)
        self.funds = dict(
            account_id="sandbox-account",
            available_margin="50000",
            funds_asof=self.now.isoformat(),
            max_single_order_quantity=65,
            source="authenticated-broker-fixture",
        )

    def test_funds_require_same_account_freshness_and_order_limit(self):
        accepted = BrokerFundsView.validated(self.funds, account_id="sandbox-account", now=self.now)
        self.assertEqual(65, accepted.max_single_order_quantity)
        for invalid in (
            {"account_id": "wrong"},
            {"max_single_order_quantity": None},
            {"available_margin": "NaN"},
            {"funds_asof": "2026-10-29T09:00:00+05:30"},
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaises(BrokerContractError):
                    BrokerFundsView.validated(
                        {**self.funds, **invalid}, account_id="sandbox-account", now=self.now
                    )

    def test_unknown_broker_state_not_erased_and_fills_strict(self):
        order = dict(
            order_id="TEST-1",
            account_id="sandbox-account",
            symbol="NIFTY-TEST",
            status="UNKNOWN",
            quantity=65,
            filled_quantity=25,
            pending_quantity=40,
        )
        view = BrokerOrderView.validated(order, account_id="sandbox-account")
        self.assertEqual("UNKNOWN", view.status)
        with self.assertRaises(BrokerContractError):
            BrokerOrderView.validated({**order, "status": "magic_state"}, account_id="sandbox-account")
        with self.assertRaises(BrokerContractError):
            BrokerOrderView.validated({**order, "filled_quantity": 70}, account_id="sandbox-account")


class ExpiryEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.today = date(2026, 10, 29)
        self.expiry = date(2026, 11, 3)
        self.evidence = ExpiryEvidence.from_records(
            exchange_source="exchange-recorded-schedule",
            exchange_asof=self.today,
            sessions=[self.today, date(2026, 10, 30), self.expiry],
            broker_source="verified-broker-instrument-master",
            master_asof=self.today,
            contracts=[
                dict(
                    instrument_id="INST-NIFTY-2026-11-03-24000-CE",
                    symbol="NIFTY-TEST-CE",
                    strike=24000,
                    right="CE",
                    expiry=self.expiry,
                )
            ],
        )

    def test_requires_matching_current_session_and_listed_master(self):
        quote_asof = datetime(2026, 10, 29, 10, 0, tzinfo=IST_TZ)
        listed = listed_expiry_contracts(self.evidence, trade_date=self.today, quote_asof=quote_asof)
        self.assertEqual(1, len(listed))
        self.assertEqual(self.expiry, listed[0].expiry)
        with self.assertRaises(ExpiryEvidenceError):
            listed_expiry_contracts(
                self.evidence,
                trade_date=date(2026, 10, 30),
                quote_asof=datetime(2026, 10, 30, 10, 0, tzinfo=IST_TZ),
            )

    def test_conflicting_broker_contract_alias_rejected(self):
        with self.assertRaises(ExpiryEvidenceError):
            ExpiryEvidence.from_records(
                exchange_source="exchange",
                exchange_asof=self.today,
                sessions=[self.today, self.expiry],
                broker_source="broker",
                master_asof=self.today,
                contracts=[
                    dict(instrument_id="a", symbol="duplicate", strike=24000, right="CE", expiry=self.expiry),
                    dict(instrument_id="b", symbol="duplicate", strike=24100, right="CE", expiry=self.expiry),
                ],
            )


if __name__ == "__main__":
    unittest.main()
