import json

with open("config/strategies.json", "r", encoding="utf-8") as f:
    cfg = json.load(f)

cfg["active_strategy"] = "macd_momentum"

cfg["strategies"]["macd_momentum"] = {
    "display_name": "Strategy 5: 2m MACD Momentum & AI Companion (Path A)",
    "description": "High-Velocity 2-Minute MACD Crossover Momentum Engine with Step-Ladder Milestone Compounding, Refined Institutional Traps, and Antigravity AI Code Companion real-time pair-trading verification.",
    "entry": {
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "strike_selection": "ATM_ROUNDED",
        "min_spacing_bars": 1
    },
    "exit": {
        "max_hold_seconds": 21600,
        "initial_stop_pct": 20.0,
        "target_pct": 50.0,
        "profit_target_enabled": False,
        "aggressive_trail_enabled": True,
        "aggressive_trail_activation_pct": 50.0,
        "aggressive_trail_pullback_pct": 5.0,
        "stop_min_improvement_points": 0.5,
        "stop_confirmation_timeout_sec": 10.0,
        "monitor_quote_max_age_sec": 5.0,
        "monitor_quote_timeout_sec": 3.0,
        "structural_stops_enabled": True,
        "enable_structural_wick_stop": True,
        "runner_trailing_enabled": True,
        "runner_activation_pct": 15.0,
        "continuous_ratchet_enabled": True,
        "trail_pullback_pct": 10.0,
        "progressive_floor_tiers": [
            {
                "gain_pct": 15.0,
                "floor_pct": 0.0
            },
            {
                "gain_pct": 20.0,
                "floor_pct": 10.0
            },
            {
                "gain_pct": 30.0,
                "floor_pct": 20.0
            },
            {
                "gain_pct": 40.0,
                "floor_pct": 30.0
            }
        ],
        "lock_breakeven_on_runner": True
    },
    "compounding": {
        "enabled": True,
        "mode": "step_ladder",
        "baseline_capital": 10000.0,
        "max_lots_cap": 10,
        "max_order_quantity": 650,
        "milestones": [
            {
                "min_capital": 0.0,
                "lots": 2
            },
            {
                "min_capital": 20000.0,
                "lots": 4
            },
            {
                "min_capital": 40000.0,
                "lots": 6
            },
            {
                "min_capital": 70000.0,
                "lots": 8
            },
            {
                "min_capital": 100000.0,
                "lots": 10
            }
        ]
    }
}

with open("config/strategies.json", "w", encoding="utf-8") as f:
    json.dump(cfg, f, indent=2)

print("SUCCESSFULLY REGISTERED macd_momentum IN config/strategies.json")
