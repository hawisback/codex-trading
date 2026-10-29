import json

path = "config/strategies.json"
with open(path, "r", encoding="utf-8") as fp:
    cfg = json.load(fp)

strat = cfg["strategies"]["macd_momentum"]
strat["display_name"] = "Strategy 5: 2m MACD Momentum & EMA Value Confirmation"
strat["description"] = "High-Velocity 2-Minute MACD Crossover Momentum Engine confirmed by 5m EMA9 Value Proximity and EMA20 Trend Alignment, featuring 30% Initial Stop Loss, 5% Aggressive Trailing, Step-Ladder Milestone Compounding, and AI Companion verification."

strat["entry"]["require_ema_confirmation"] = True
strat["entry"]["ema_proximity_pts"] = 10.0
strat["entry"]["require_ema20_trend_alignment"] = True
strat["entry"]["min_invalidation_buffer_pts"] = 15.0

strat["exit"]["initial_stop_pct"] = 30.0
strat["exit"]["aggressive_trail_enabled"] = True
strat["exit"]["aggressive_trail_activation_pct"] = 50.0
strat["exit"]["aggressive_trail_pullback_pct"] = 5.0

with open(path, "w", encoding="utf-8") as fp:
    json.dump(cfg, fp, indent=2)

print("Updated config/strategies.json successfully")
