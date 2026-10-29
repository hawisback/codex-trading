"""Offline failure cases for the real batch/Antigravity protocol and exits."""

import copy
from datetime import timedelta
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ai_consultant as ac
from entry_policy import EntryBlocked, EntryPolicy
from market_clock import MarketClock
from test_self_healing_exit import entry_dossier
from tests.scenarios import ROOT, NOW, INTELLIGENCE, market_responses, make_trader
from trading.application.entry import EntryWorkflow
from trading.application.dossier import DossierService
from trading.application.market_context import MarketContextService
from trading.application.position_monitor import PositionMonitor
from trading.application.scheduler import run_scheduler
from trading.domain.order_book import order_book_snapshot


class EntryHandoffTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix=".path-a-handoff-", dir=ROOT)
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        for key, name in (("PENDING_FILE_JSON", "pending.json"), ("PENDING_FILE_MD", "pending.md"),
                          ("VERDICT_FILE", "verdict.json")):
            p = patch.object(ac, key, self.root / name)
            p.start(); self.addCleanup(p.stop)
        self.elapsed = 0.0
        self.now = MarketClock.parse_to_ist(NOW)
        p = patch.object(MarketClock, "now_ist", side_effect=lambda: self.now + timedelta(seconds=self.elapsed))
        p.start(); self.addCleanup(p.stop)
        p = patch.object(ac.time, "monotonic", side_effect=lambda: self.elapsed)
        p.start(); self.addCleanup(p.stop)

    def pending(self):
        return json.loads(ac.PENDING_FILE_JSON.read_text())

    def response(self, **changes):
        pending = self.pending()
        data = dict(request_id=pending["request_id"], candidate_id=pending["candidate_id"],
                    submitted_at=MarketClock.now_ist().isoformat(), action="APPROVED", reason="Current candidate")
        data.update(changes)
        ac.VERDICT_FILE.write_text(json.dumps(data), encoding="utf-8")

    def evaluate(self, respond=None, timeout=2):
        def tick(duration):
            self.elapsed += max(.1, duration)
            if respond:
                respond()
        with patch.object(ac.time, "sleep", side_effect=tick):
            return ac.AIConsultant(mode="chat", timeout_seconds=timeout).evaluate(entry_dossier(67))

    def test_actual_consultation_accepts_current_identity_and_cleans_request(self):
        verdict = self.evaluate(lambda: ac.submit_entry_verdict(self.pending()["request_id"], "APPROVED"))
        self.assertEqual("APPROVED", verdict.action)
        self.assertTrue(verdict.request_id)
        self.assertTrue(verdict.candidate_id)
        self.assertEqual("TEST", verdict.entry_instrument_id)
        self.assertFalse(ac.PENDING_FILE_JSON.exists())
        self.assertFalse(ac.VERDICT_FILE.exists())

    def test_wrong_missing_identity_and_bad_timestamps_never_approve(self):
        cases = [dict(request_id="previous"), dict(candidate_id="other-contract"), dict(request_id=None),
                 dict(submitted_at=(self.now - timedelta(seconds=1)).isoformat()),
                 dict(submitted_at=(self.now + timedelta(days=1)).isoformat()),
                 dict(submitted_at=self.now.replace(tzinfo=None).isoformat()), dict(confidence=float("nan")),
                 dict(max_entry_price=float("inf"))]
        for changes in cases:
            with self.subTest(changes=changes):
                self.elapsed = 0
                verdict = self.evaluate(lambda: self.response(**changes))
                self.assertEqual("TIMEOUT_EXPIRED", verdict.action)
                self.assertIsNone(verdict.max_entry_price)

    def test_late_response_to_a_cannot_approve_b(self):
        old = []
        self.evaluate(lambda: old.append(self.pending()))
        ticks = []
        def respond():
            ticks.append(True)
            if len(ticks) == 1:
                ac.atomic_save(ac.VERDICT_FILE, dict(request_id=old[0]["request_id"],
                    candidate_id=old[0]["candidate_id"], submitted_at=MarketClock.now_ist().isoformat(),
                    action="APPROVED", reason="Old A"))
            else:
                self.response(reason="Current B")
        verdict = self.evaluate(respond)
        self.assertEqual("Current B", verdict.reasoning)
        self.assertNotEqual(old[0]["request_id"], verdict.request_id)
        self.assertGreaterEqual(len(ticks), 2)

    def test_veto_and_trap_dominate_conflicting_approval_aliases(self):
        for changes in (dict(action="VETOED", approved=True), dict(verdict="VETOED"),
                        dict(approved=False), dict(trap="Trap 7")):
            with self.subTest(changes=changes):
                self.elapsed = 0
                verdict = self.evaluate(lambda: self.response(**changes))
                self.assertEqual("VETOED", verdict.action)
                self.assertIsNone(verdict.max_entry_price)

    def test_cli_rejects_unbound_response(self):
        def submit():
            for identity in (None, "old"):
                with self.assertRaises(ValueError):
                    ac.submit_entry_verdict(identity, "APPROVED")
        self.assertEqual("TIMEOUT_EXPIRED", self.evaluate(submit).action)
        self.assertFalse(ac.VERDICT_FILE.exists())

    def test_missing_response_times_out_and_keeps_cash(self):
        self.assertEqual("TIMEOUT_EXPIRED", self.evaluate().action)
        self.assertFalse(ac.PENDING_FILE_JSON.exists())

    def test_chat_publishes_confluence_rubric_in_json_and_markdown(self):
        observed = []
        def inspect():
            payload = self.pending()
            rubric = payload["evaluation_rubric"]
            self.assertIn("high-conviction BUY_CE", rubric)
            self.assertIn("15-20%", rubric)
            self.assertIn("Confluence never auto-approves", rubric)
            self.assertIn(rubric, ac.PENDING_FILE_MD.read_text(encoding="utf-8"))
            observed.append(payload)
        self.assertEqual("TIMEOUT_EXPIRED", self.evaluate(inspect).action)
        self.assertTrue(observed)

    def test_partial_response_is_retried_until_a_bound_verdict_arrives(self):
        ticks = []
        def respond():
            ticks.append(True)
            if len(ticks) == 1:
                ac.VERDICT_FILE.write_text('{"action":')
            else:
                self.response()
        self.assertEqual("APPROVED", self.evaluate(respond).action)
        self.assertEqual(2, len(ticks))

    def test_submission_time_limits_approval_lifetime_even_when_poll_is_delayed(self):
        def respond():
            self.response()
            self.elapsed += 6  # Default approval TTL is 5 seconds, consultation is 10.
        verdict = self.evaluate(respond, timeout=10)
        self.assertEqual("VETOED", verdict.action)
        self.assertIn("APPROVAL_EXPIRED", verdict.reasoning)
        self.assertIsNone(verdict.max_entry_price)

    def test_cli_rejects_matching_request_after_deadline(self):
        def respond():
            identity = self.pending()["request_id"]
            self.elapsed += 3
            with self.assertRaises(ValueError):
                ac.submit_entry_verdict(identity, "APPROVED")
        self.assertEqual("TIMEOUT_EXPIRED", self.evaluate(respond).action)
        self.assertFalse(ac.VERDICT_FILE.exists())

    def test_missing_chat_depth_preserves_cash_before_consultation(self):
        trader = make_trader(self.root / "active.json", "macd_momentum")
        trader.ai_consultant = ac.AIConsultant(mode="chat", trading_config=trader.trading_cfg)
        trader.client.quote_error = {"error": True}
        context = MarketContextService(lambda p, **kw: market_responses()[p], lambda: {}).fetch()
        decision = dict(signal="BUY_CE", instrument_id="TEST", symbol="NIFTY-CE", ltp=67)
        result = EntryWorkflow().run(trader, context, decision, [], 0, INTELLIGENCE)
        self.assertEqual("CONSULTATION_CONTEXT_UNAVAILABLE", result["blocked"])
        self.assertFalse(any(call[0] == "POST" for call in trader.client.calls))
        self.assertFalse(ac.PENDING_FILE_JSON.exists())

    def test_real_entry_workflow_executes_only_current_companion_approval(self):
        for approve_current in (True, False):
            with self.subTest(approve_current=approve_current):
                self.elapsed = 0
                trader = make_trader(self.root / str(approve_current) / "active.json", "macd_momentum")
                trader.client.quote_ask = trader.client.fill_price = 67
                trader.ai_consultant = ac.AIConsultant(mode="chat", timeout_seconds=2,
                                                      trading_config=trader.trading_cfg)
                context = MarketContextService(lambda p, **kw: market_responses()[p],
                                               trader.client.get_funds).fetch()
                decision = dict(signal="BUY_CE", instrument_id="TEST", symbol="NIFTY-TEST-CE", ltp=67,
                                setup_type="MACD_2M_MOMENTUM", invalidation_level=22950)
                def respond(duration):
                    self.elapsed += max(.1, duration)
                    if approve_current:
                        ac.submit_entry_verdict(self.pending()["request_id"], "APPROVED")
                    else:
                        self.response(request_id="previous-candidate")
                with patch.object(ac.time, "sleep", side_effect=respond):
                    EntryWorkflow().run(trader, context, decision, [], 0, INTELLIGENCE)
                posts = [call for call in trader.client.calls if call[:2] == ("POST", "/execution/orders")]
                self.assertEqual(1 if approve_current else 0, len(posts))
                if approve_current:
                    state = trader.load_active_position()
                    self.assertTrue(state["protection_confirmed"])
                    self.assertTrue(state["entry_execution"]["ai_verdict"]["request_id"])
                else:
                    self.assertFalse(trader.position_store.exists())


class PathAExitTests(unittest.TestCase):
    def setUp(self):
        self.cfg = json.loads((ROOT / "config/strategies.json").read_text())["strategies"]["macd_momentum"]

    def trade(self, direction):
        return dict(trade_id="E1", symbol="NIFTY-" + direction, status="OPEN", entry_price=100,
                    last_bid=100, peak_bid=100, quote_verified=True, entry_time=NOW,
                    setup_type="MACD_2M_MOMENTUM", invalidation_level=22680 if direction == "CE" else 22840)

    def manage(self, trade, ctx, now=NOW):
        self.exits, self.saves = [], []
        def exit_trade(identity, reason, **kwargs):
            self.exits.append(reason); return {"status": "CLOSED"}
        with MarketClock.at(now):
            return PositionMonitor(self.cfg, True, exit_trade, lambda *a: None,
                save_position=lambda t: self.saves.append(copy.deepcopy(t))).manage([trade], ctx, {})

    def test_reversal_keeps_swing_and_option_stops(self):
        for direction, spot in (("CE", 22700), ("PE", 22820)):
            with self.subTest(direction=direction):
                trade = self.trade(direction)
                ctx = dict(spot=spot, session_vwap=22760, ema_9=22760, ema_20=22760)
                self.assertEqual([trade], self.manage(trade, ctx))
                self.assertFalse(self.exits)
                trade["last_bid"] = 69
                self.manage(trade, ctx)
                self.assertIn("INITIAL STOP", self.exits[0])
                trade["last_bid"] = 100
                ctx["spot"] = trade["invalidation_level"]
                self.manage(trade, ctx)
                self.assertIn("INVALIDATION", self.exits[0])

    def test_reclaim_is_persisted_and_later_break_exits_after_restart(self):
        for direction in ("CE", "PE"):
            with self.subTest(direction=direction):
                trade = self.trade(direction)
                self.manage(trade, dict(spot=22760, session_vwap=22760, ema_9=22760, ema_20=22760))
                self.assertTrue(self.saves[-1]["structural_reclaims"]["vwap"])
                restarted = json.loads(json.dumps(self.saves[-1]))
                self.manage(restarted, dict(spot=22740 if direction == "CE" else 22780,
                                           session_vwap=22760, ema_9=22760, ema_20=22760))
                self.assertIn("STRUCTURAL STOP", self.exits[0])

    def test_hard_squareoff_remains_unconditional(self):
        self.manage(self.trade("CE"), {}, now="2026-10-19T15:15:00+05:30")
        self.assertIn("SQUARE-OFF", self.exits[0])


class PathAContextTests(unittest.TestCase):
    def test_documented_cli_accepts_path_a_without_constructing_trader(self):
        with patch("sys.argv", ["scheduler", "--strategy", "macd_momentum", "--list-strategies"]), \
                patch("sys.stdout", new_callable=io.StringIO):
            run_scheduler(lambda **kw: self.fail("List mode must not construct a trader"))

    def test_real_depth_and_oi_are_detached_and_rendered_in_dossier(self):
        with MarketClock.at(NOW):
            responses = market_responses()
            ctx = MarketContextService(lambda p, **kw: responses[p], lambda: {}).fetch()
            quote = dict(instrument_id="TEST", timestamp=NOW, request_started_monotonic=ac.time.monotonic(),
                         best_bid=66.95, best_ask=67, best_bid_qty=130, best_ask_qty=65,
                         depth=dict(buy=[dict(price=66.95, quantity=130)], sell=[dict(price=67, quantity=65)]))
            ctx.update(option_quote=quote)
            decision = dict(signal="BUY_CE", instrument_id="TEST", symbol="NIFTY-CE", target_strike=23000, ltp=67)
            dossier = DossierService({}).build_dossier(ctx, decision, [], 0, INTELLIGENCE)
            quote["depth"]["buy"][0]["quantity"] = 999
            self.assertEqual(130, dossier.order_book["bid_quantity"])
            self.assertAlmostEqual(1 / 3, dossier.order_book["quantity_imbalance"], places=6)
            self.assertEqual(ctx["order_flow"], dossier.order_flow)
            self.assertIn("Selected Contract Order Book", dossier.to_markdown())
            for changes in (dict(timestamp="2026-10-19T09:00:00+05:30"), dict(instrument_id="OTHER"),
                            dict(depth={"buy": [], "sell": []})):
                with self.subTest(changes=changes), self.assertRaises(EntryBlocked):
                    order_book_snapshot(dict(quote, **changes), "TEST", EntryPolicy())
