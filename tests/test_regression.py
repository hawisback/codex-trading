"""Expose the established offline suite without importing root diagnostic scripts."""

REGRESSION_MODULES = (
    "tests.test_api_contracts",
    "tests.test_market_enhancements",
    "tests.test_market_data",
    "test_entry_execution",
    "test_market_intelligence",
    "test_self_healing_exit",
    "tests.test_staged_refactor",
    "tests.test_replay_and_configuration",
    "tests.test_policy_snapshot",
    "tests.test_daily_logs",
    "tests.test_gateways",
    "tests.test_breeze_gateway",
    "tests.test_trailing_workflow",
    "tests.test_two_step_ai_stop_loss",
    "tests.test_macd_momentum_strategy",
    "tests.test_macd_session_rules",
    "tests.test_rolling_macd",
    "tests.test_strike_macd",
    "tests.test_candidate_selection",
    "tests.test_broker_margin_lot_policy",
    "tests.test_boundary_safety",
    "tests.test_oms_recovery_boundaries",
    "tests.test_intent_states",
    "tests.test_journal_intent_transitions",
    "tests.test_trap7_refinement",
    "tests.test_path_a_safety",
    "tests.test_path_a_history",
    "tests.test_hybrid_stop_policy",
    "tests.test_hybrid_replay",
)


def load_tests(loader, standard_tests, pattern):
    return loader.loadTestsFromNames(REGRESSION_MODULES)
