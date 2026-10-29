"""Offline boundary and recovery checks for the production MACD session profile."""

import copy
from datetime import timedelta
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from market_clock import MarketClock
from position_lifecycle import PositionLifecycle
from trading.application.position_monitor import PositionMonitor
from trading.application.selection import CandidateSelectionService
from trading.configuration import validate_trailing_configuration
from trading.domain.trailing import session_trigger
from trading.models import CandidateSignal
from trading.strategies.macd_momentum import MacdMomentumStrategy

ROOT = Path(__file__).resolve().parents[1]


def profile():
    return json.loads((ROOT / "config/strategies.json").read_text())["strategies"]["macd_momentum"]


class SessionEntryTests(unittest.TestCase):
    def setUp(self):
        self.start = MarketClock.parse_to_ist("2026-10-27T09:15:00+05:30")
        self.cfg = profile()
        # Preserve coverage of the previous stepped sampling path; rolling/warmup
        # activation and the active profile are exercised in test_rolling_macd.
        self.cfg["entry"].update(
            use_rolling_2m=False,
            prior_session_warmup_enabled=False,
            early_orb_required=False,
            vwap_climax_pts=50,
        )
        self.cfg["entry"]["midday_dead_zone_filter"]["min_15m_range_pts"] = 24

    def evaluate(self, direction="CE", count=64, histogram=0.2, changes=None, bars_change=None):
        candles = [
            dict(
                start_time=(self.start + timedelta(minutes=i)).isoformat(),
                open=23000,
                close=23000,
                high=23001,
                low=22999,
                volume=100,
            )
            for i in range(count)
        ]
        for bar in candles[:15]:
            bar.update(high=23020, low=22980)
        if bars_change:
            bars_change(candles)
        ctx = dict(candles_1m=candles, spot=23000, session_vwap=23000)
        ctx.update(changes or {})
        signed = histogram if direction == "CE" else -histogram
        with (
            MarketClock.at(self.start + timedelta(minutes=count)),
            patch(
                "trading.strategies.macd_momentum.calculate_macd",
                return_value=([0, signed], [0, 0], [0, signed]),
            ),
        ):
            return MacdMomentumStrategy(self.cfg).evaluate(ctx)

    def test_histogram_threshold_and_minimum_invalidation_for_both_directions(self):
        for direction in ("CE", "PE"):
            self.assertEqual("NEUTRAL", self.evaluate(direction, histogram=0.19999).signal)
            candidate = self.evaluate(direction)
            self.assertEqual("BUY_" + direction, candidate.signal)
            self.assertGreaterEqual(abs(candidate.invalidation_level - 23000), 25)

    def test_counter_candle_rejected_and_doji_allowed(self):
        for direction, opening in (("CE", 23001), ("PE", 22999)):
            candidate = self.evaluate(direction, bars_change=lambda b: b[-2].update(open=opening))
            self.assertIn("opposes", candidate.reasons[0])
            self.assertEqual("BUY_" + direction, self.evaluate(direction).signal)

    def test_vwap_tolerance_and_climax_boundaries(self):
        for direction, sign in (("CE", 1), ("PE", -1)):
            self.assertEqual(
                "BUY_" + direction,
                self.evaluate(direction, changes={"session_vwap": 23000 + sign * 12}).signal,
            )
            self.assertIn(
                "fighting",
                self.evaluate(direction, changes={"session_vwap": 23000 + sign * 12.01}).reasons[0],
            )
            self.assertEqual(
                "BUY_" + direction,
                self.evaluate(direction, changes={"session_vwap": 23000 - sign * 49.99}).signal,
            )
            self.assertIn(
                "climax", self.evaluate(direction, changes={"session_vwap": 23000 - sign * 50}).reasons[0]
            )

    def test_opening_range_buffer_inclusive_and_breakout_allowed(self):
        for direction, key, value in (("CE", "high", 23008), ("PE", "low", 22992)):

            def change(bars):
                for bar in bars[:15]:
                    bar[key] = value

            self.assertIn("Opening Range", self.evaluate(direction, bars_change=change).reasons[0])
            spot = value + (0.05 if direction == "CE" else -0.05)
            self.assertEqual(
                "BUY_" + direction,
                self.evaluate(
                    direction, bars_change=change, changes=dict(spot=spot, session_vwap=spot)
                ).signal,
            )

    def test_missing_invalid_market_inputs_fail_closed(self):
        for key in ("spot", "session_vwap"):
            for value in (None, 0, -1, True, float("nan"), float("inf"), "bad"):
                self.assertEqual("NEUTRAL", self.evaluate(changes={key: value}).signal)

    def test_midday_uses_timestamp_and_completed_range_without_permissive_default(self):
        self.assertEqual("BUY_CE", self.evaluate(count=134).signal)  # 11:29
        self.assertIn("Midday flatline", self.evaluate(count=136).reasons[0])  # 11:31
        self.assertEqual("BUY_CE", self.evaluate(count=240).signal)  # 13:15

        def wide(bars):
            for bar in bars[-15:]:
                bar.update(high=23012, low=22988)

        self.assertEqual("BUY_CE", self.evaluate(count=136, bars_change=wide).signal)
        # A caller cannot override the actual narrow candle range with a fake spread.
        self.assertEqual("NEUTRAL", self.evaluate(count=136, changes=dict(box_spread_15m=100)).signal)

    def test_late_entry_cutoff_and_missing_opening_history(self):
        self.assertIn("14:15", self.evaluate(count=300).reasons[0])
        self.assertEqual("NEUTRAL", self.evaluate(bars_change=lambda b: b.pop(0)).signal)

    def test_invalid_filter_configuration_is_rejected_before_startup(self):
        for changes in (
            dict(min_hist_threshold=-1),
            dict(vwap_climax_pts=0),
            dict(require_vwap_alignment="false"),
            dict(opening_range_filter_enabled=1),
            dict(midday_dead_zone_filter=[]),
            dict(midday_dead_zone_filter=dict(end_minute=100)),
            dict(max_daily_entries=2.5),
            dict(min_spacing_bars=True),
        ):
            cfg = copy.deepcopy(self.cfg)
            cfg["entry"].update(changes)
            with self.subTest(changes=changes), self.assertRaises((ValueError, TypeError)):
                MacdMomentumStrategy(cfg)


class SessionTrailingTests(unittest.TestCase):
    def setUp(self):
        self.cfg = profile()
        self.updates, self.exits = [], []
        self.trade = dict(
            trade_id="TEST",
            symbol="TEST-CE",
            entry_price=100,
            last_bid=100,
            peak_bid=100,
            quote_verified=True,
        )
        self.monitor = PositionMonitor(
            self.cfg, True, lambda *a, **kw: self.exits.append(a[1]) or dict(status="CLOSED"), self.ratchet
        )

    def ratchet(self, state, trigger):
        self.updates.append(trigger)
        state["desired_stop_trigger"] = max(state.get("desired_stop_trigger", 0), trigger)

    def tick(self, hm, bid, peak=None, ctx=None):
        self.trade.update(last_bid=bid, peak_bid=max(self.trade["peak_bid"], bid, peak or 0))
        with MarketClock.at("2026-10-27T" + hm + ":00+05:30"):
            return self.monitor.manage([self.trade], ctx or {}, {})

    def test_morning_exact_stages_and_generic_runner_does_not_override(self):
        for bid, floor in (
            (104.99, None),
            (105, 92),
            (110, 101),
            (115, 110),
            (118, 110),
            (125, 115),
            (150, 144.75),
        ):
            self.tick("10:30", bid)
            self.assertEqual(floor, self.updates[-1] if self.updates else None)
            self.assertFalse(self.exits)

    def test_midday_trailing_precedes_generic_runner_even_above_fifteen_percent(self):
        for bid, floor in ((104.99, None), (105, 103.4), (120, 118.2)):
            self.tick("12:00", bid)
            self.assertEqual(floor, self.updates[-1] if self.updates else None)
        self.tick("12:01", 118.2)
        self.assertTrue(self.exits)

    def test_floors_survive_session_boundary_and_restart(self):
        self.tick("11:29", 120)
        self.assertEqual(110.4, self.updates[-1])
        self.tick("11:30", 120)
        self.assertEqual(118.2, self.updates[-1])
        self.trade = json.loads(json.dumps(self.trade))
        self.tick("13:15", 119)
        self.assertEqual(118.2, self.updates[-1])
        self.tick("13:16", 118.2)
        self.assertIn("PERSISTED", self.exits[-1])

    def test_session_window_boundaries_and_opt_in_only(self):
        cfg = self.cfg["exit"]
        self.assertEqual("MORNING PROGRESSIVE TRAIL", session_trigger(100, 108, cfg, "11:29")[2])
        self.assertEqual("MIDDAY MICRO-TRAIL", session_trigger(100, 108, cfg, "11:30")[2])
        self.assertFalse(session_trigger(100, 108, cfg, "13:15")[0])
        self.assertFalse(session_trigger(100, 108, {}, "10:00")[0])

    def test_afternoon_pullback_and_large_runner_never_loosen(self):
        self.tick("13:15", 115)
        self.assertEqual(110.95, self.updates[-1])
        self.tick("13:16", 150)
        self.assertEqual(144.75, self.updates[-1])
        self.tick("13:17", 144.75)
        self.assertIn("PERSISTED", self.exits[-1])

    def test_session_trailing_retains_structural_and_hard_exit_guards(self):
        self.tick("10:00", 108, ctx=dict(spot=22900, session_vwap=23000))
        self.assertIn("STRUCTURAL STOP", self.exits[-1])
        self.exits.clear()
        self.trade["quote_verified"] = False
        self.tick("12:00", 200)
        self.assertFalse(self.exits)
        self.tick("15:15", 200)
        self.assertIn("SQUARE-OFF", self.exits[-1])

    def test_invalid_session_settings_are_rejected(self):
        for changes in (
            dict(morning_progressive_trail_enabled="true"),
            dict(morning_progressive_trail_end="12:00"),
            dict(morning_be_activation_pct=4),
            dict(morning_soft_sl_floor_pct=-100),
            dict(midday_micro_trail_pullback_pct=100),
            dict(midday_micro_trail_start="11:3"),
            dict(midday_micro_trail_floor_pct=float("nan")),
            dict(morning_be_activation_pct="12"),
        ):
            cfg = copy.deepcopy(self.cfg)
            cfg["exit"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_trailing_configuration(cfg)


class StrictItmTests(unittest.TestCase):
    def select(self, direction, *, price=100, margin=10000, missing=False):
        cfg = profile()
        strategy = SimpleNamespace(
            evaluate=lambda *a, **kw: CandidateSignal(
                "BUY_" + direction, ["fixture"], "MACD_2M_MOMENTUM", 22900
            )
        )
        itm = 22950 if direction == "CE" else 23050
        leg = "call" if direction == "CE" else "put"
        strikes = [dict(strike=23000, **{leg: dict(ltp=50, instrument_id="ATM", symbol="ATM")})]
        if not missing:
            strikes.append(dict(strike=itm, **{leg: dict(ltp=price, instrument_id="ITM", symbol="ITM")}))
        return CandidateSelectionService(
            "macd_momentum",
            cfg,
            65,
            lambda funds, premium: 65 if premium * 65 <= funds - 150 else 0,
            strategy,
            dict(option_selection=dict(max_option_premium=135)),
        ).analyze(dict(spot=23000, atm_strike=23000, available_margin=margin, strikes=strikes))

    def test_exact_atm_boundary_selects_intrinsic_itm_in_both_directions(self):
        for direction in ("CE", "PE"):
            decision = self.select(direction)
            self.assertEqual("BUY_" + direction, decision["signal"])
            self.assertEqual("ITM", decision["instrument_id"])

    def test_missing_expensive_unaffordable_and_invalid_itm_never_fall_back(self):
        for direction in ("CE", "PE"):
            for changes in (
                dict(missing=True),
                dict(price=136),
                dict(margin=6600),
                dict(price=None),
                dict(price=float("nan")),
                dict(price=True),
                dict(price=-1),
            ):
                decision = self.select(direction, **changes)
                self.assertEqual("NEUTRAL", decision["signal"])
                self.assertIsNone(decision["instrument_id"])
                self.assertEqual(0, decision["quantity"])


class EntryLimitRecoveryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix=".session-limits-", dir=ROOT)
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "active.json"
        self.trader = self.restart()
        self.journal = [
            dict(order_id="ENTRY1", kind="ENTRY", filled_quantity=65, created_at="2026-10-27T10:00:00+05:30")
        ]

    def restart(self):
        trader = PositionLifecycle()
        trader.initialize_safety(self.path)
        trader.strategy_mode = "macd_momentum"
        trader.strategy_cfg = profile()
        trader.execution_scope = dict(mode="PAPER", account_id="TEST")
        return trader

    def test_daily_cap_is_checked_before_any_order_side_effect(self):
        self.assertEqual("DAILY_ENTRY_CAP", self.trader._submit_entry({"invalidation_level": 23000}, today_entries=10)["detail"])
        with MarketClock.at("2026-10-27T09:29:59+05:30"):
            self.assertEqual("ENTRY_ACTIVATION_PENDING", self.trader._submit_entry({"invalidation_level": 23000})["detail"])

    def test_cooldown_persists_across_restart_without_resetting_on_reconciliation(self):
        with MarketClock.at("2026-10-27T10:05:30+05:30"):
            self.trader._record_flat_entry_limits(self.journal, 1)
        self.trader = self.restart()
        with MarketClock.at("2026-10-27T10:15:59+05:30"):
            self.trader._record_flat_entry_limits(self.journal, 1)
            self.assertEqual("ENTRY_SPACING_COOLDOWN", self.trader._entry_limit_block(1))
        with MarketClock.at("2026-10-27T10:16:00+05:30"):
            self.assertIsNone(self.trader._entry_limit_block(1))

    def test_missing_or_corrupt_spacing_evidence_blocks_entries(self):
        with MarketClock.at("2026-10-27T11:00:00+05:30"):
            self.assertEqual("ENTRY_SPACING_UNVERIFIED", self.trader._entry_limit_block(1))
            self.path.with_name("active_entry_limits.json").write_text("corrupt")
            self.assertEqual("ENTRY_SPACING_UNVERIFIED", self.trader._entry_limit_block(1))

    def test_actual_reconciliation_records_flatness_and_submission_rechecks_limits(self):
        from tests.scenarios import make_trader

        with MarketClock.at("2026-10-27T10:05:00+05:30"):
            trader = make_trader(self.path, "macd_momentum")
            broker = trader.client
            broker.add("ENTRY", "E1", 65, "FILLED", average_price=100)
            broker.add("EXIT", "X1", 65, "FILLED", "E1")
            self.assertEqual(([], 1), trader.get_trades_state())
            self.assertTrue(trader.state_verified)
            self.assertEqual("ENTRY_SPACING_COOLDOWN", trader.execute_trade({})["detail"])
            self.assertFalse(any(call[:2] == ("POST", "/execution/orders") for call in broker.calls))
        with MarketClock.at("2026-10-27T10:15:00+05:30"):
            restarted = make_trader(self.path, "macd_momentum")
            restarted.client = broker
            self.assertEqual(([], 1), restarted.get_trades_state())
            self.assertIsNone(restarted._entry_limit_block(1))
            broker.add("ENTRY", "E2", 65, "FILLED", average_price=100)
            broker.add("EXIT", "X2", 65, "FILLED", "E2")
            self.assertEqual("ENTRY_SPACING_COOLDOWN", restarted.execute_trade({})["detail"])
