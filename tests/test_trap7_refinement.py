import unittest
from ai_context_dossier import MarketDossier
from ai_consultant import AIConsultant


class TestTrap7Refinement(unittest.TestCase):
    def setUp(self):
        self.ai = AIConsultant(mode="playbook")

    def _create_mock_dossier(self, **kwargs):
        defaults = dict(
            date="2026-10-27",
            time_utc="05:30:00",
            time_ist="11:00:00",
            direction="CE",
            symbol="NIFTY_22700_CE",
            strike=22700,
            option_entry_price=50.0,
            spot_price=22700.0,
            session_phase="MORNING_TREND",
            minutes_from_open=105,
            minutes_to_close=270,
            is_expiry_0dte=False,
            days_to_expiry=2.0,
            gamma_hazard_flag=False,
            session_vwap=22750.0,
            vwap_distance_pts=50.0,
            vwap_slope_15m=-0.35,  # Counter-trend slope for CE
            vwap_cross_count_60m=1,
            vwap_blender_warning=False,
            box_range_15m=30.0,
            box_range_30m=45.0,
            box_position_pct=50.0,
            compression_hazard=False,
            ceiling_floor_hazard=False,
            ema9_5m=22705.0,
            ema20_5m=22715.0,
            ema_spread_5m=-10.0,
            ribbon_compression_hazard=False,
            pullback_distance_pts=5.0,
            rsi_1m=48.0,
            day_high=22800.0,
            day_low=22650.0,
            day_range_pts=150.0,
            distance_to_day_extreme=100.0,
            last_trade_direction=None,
            last_trade_pnl=None,
            minutes_since_last_exit=None,
            consecutive_losses_today=0,
            is_directional_shift=False,
            realized_pnl_today=0.0,
            trades_taken_today=0,
            capital_preservation_active=False,
            is_counter_trend_slope=True,
            is_climax_extended=False,
            is_candle_aligned=True,
            is_reversal_inflection=True,
        )
        defaults.update(kwargs)
        return MarketDossier(**defaults)

    def test_trap7_vetoes_extreme_slope_avalanche(self):
        """Extreme slope > 0.85 pts/min is an avalanche and MUST be vetoed."""
        d = self._create_mock_dossier(
            vwap_slope_15m=-1.20,
            is_reversal_inflection=False,  # Fails inflection due to extreme slope
        )
        verdict = self.ai.evaluate(d)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.action, "VETOED")
        self.assertIn("Trap 7", verdict.trap_detected)

    def test_trap7_vetoes_opposing_candle(self):
        """Counter-trend trade with opposing candle must be vetoed."""
        d = self._create_mock_dossier(
            is_candle_aligned=False,
            is_reversal_inflection=False,  # Fails inflection due to candle against trade
        )
        verdict = self.ai.evaluate(d)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.action, "VETOED")
        self.assertIn("Trap 7", verdict.trap_detected)

    def test_trap7_approves_valid_reversal_inflection(self):
        """Moderate slope, aligned candle, and runway allows reversal inflection."""
        d = self._create_mock_dossier(
            vwap_slope_15m=-0.35, vwap_distance_pts=60.0, is_candle_aligned=True, is_reversal_inflection=True
        )
        verdict = self.ai.evaluate(d)
        self.assertTrue(verdict.is_approved)
        self.assertEqual(verdict.action, "APPROVED")
        self.assertIsNone(verdict.trap_detected)

    def test_trap8_vetoes_chasing_away_from_vwap(self):
        """Buying CE when spot is >= 75 pts ABOVE VWAP is chasing and must be vetoed."""
        d = self._create_mock_dossier(
            direction="CE",
            spot_price=22850.0,
            session_vwap=22750.0,
            vwap_distance_pts=100.0,
            is_counter_trend_slope=False,
            vwap_slope_15m=+0.25,
            is_reversal_inflection=False,
        )
        verdict = self.ai.evaluate(d)
        self.assertFalse(verdict.is_approved)
        self.assertEqual(verdict.action, "VETOED")
        self.assertIn("Trap 8", verdict.trap_detected)


if __name__ == "__main__":
    unittest.main()
