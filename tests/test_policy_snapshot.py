"""Read-only inspection contract. Tests are provided but NOT executed in this change."""

import unittest

from trading.policy_snapshot import build_policy_snapshot


class PolicyInventoryTests(unittest.TestCase):
    def setUp(self):
        self.trading = {
            "risk": {"max_order_quantity": 65, "max_trades_per_day": 5, "account_equity": 500000},
            "session": {
                "no_new_trade_before": "09:20",
                "no_new_trade_after": "14:45",
                "force_exit_time": "15:20",
            },
            "option_selection": {"max_option_premium": 135, "exchange_holidays": ["2026-10-20"]},
            "mode": "LIVE",
        }
        self.strategies = {
            "active_strategy": "macd_momentum",
            "ai_consultation": {"default_mode": "chat"},
            "strategies": {
                "macd_momentum": {
                    "compounding": {"enabled": True, "max_lots_cap": 10, "max_order_quantity": 650},
                    "entry": {"max_daily_entries": 2},
                }
            },
        }

    def test_observations_preserve_conflicting_values_without_enforcing_them(self):
        snapshot = build_policy_snapshot(self.trading, self.strategies, environ={})
        fields = {row.key: row for row in snapshot.observations}
        self.assertEqual(65, fields["risk.max_order_quantity"].configured)
        self.assertEqual(650, fields["selected_strategy.compounding.max_order_quantity"].configured)
        self.assertEqual("14:45", fields["session.no_new_trade_after"].configured)
        self.assertIn("14:15", fields["session.no_new_trade_after"].runtime_rule)
        self.assertEqual("chat", snapshot.ai_mode)
        self.assertEqual(64, len(snapshot.inventory_sha256))
        self.assertEqual((), snapshot.diagnostics)

    def test_precedence_reports_source_without_mutating_inputs(self):
        before = repr(self.trading), repr(self.strategies)
        snapshot = build_policy_snapshot(
            self.trading,
            self.strategies,
            strategy="macd_momentum",
            ai_mode="rules",
            execution_broker="kite",
            environ={"AI_CONSULTATION_MODE": "chat", "EXECUTION_BROKER": "breeze"},
        )
        self.assertEqual("rules", snapshot.ai_mode)
        self.assertEqual("--ai-mode", snapshot.ai_mode_source)
        self.assertEqual("kite", snapshot.execution_broker)
        self.assertEqual("--broker", snapshot.execution_broker_source)
        self.assertEqual(before, (repr(self.trading), repr(self.strategies)))

    def test_malformed_known_values_emit_diagnostics(self):
        self.trading["session"]["no_new_trade_after"] = "99:99"
        self.trading["risk"]["max_order_quantity"] = True
        snapshot = build_policy_snapshot(self.trading, self.strategies)
        self.assertEqual(2, len(snapshot.diagnostics))
        self.assertIn("risk.max_order_quantity", snapshot.diagnostics[0])
        self.assertIn("session.no_new_trade_after", snapshot.diagnostics[1])

    def test_snapshot_does_not_retain_mutable_json_collection(self):
        snapshot = build_policy_snapshot(self.trading, self.strategies)
        fields = {row.key: row for row in snapshot.observations}
        self.trading["option_selection"]["exchange_holidays"].append("2026-11-01")
        self.assertEqual(("2026-10-20",), fields["option_selection.exchange_holidays"].configured)

    def test_digest_is_deterministic_for_identical_allowlisted_policy(self):
        first = build_policy_snapshot(self.trading, self.strategies)
        second = build_policy_snapshot(self.trading, self.strategies)
        self.assertEqual(first.inventory_sha256, second.inventory_sha256)


if __name__ == "__main__":
    unittest.main()
