"""Optional, tightening-only VIX exit policy. Existing OMS floors stay authoritative."""

from trading.domain.market_data import exchange_time, number


def validate_vix_policy(config):
    policy = config.get("vix_adaptation", {})
    if not policy.get("enabled", False):
        return
    number(policy.get("low_vix_below", 13), minimum=0.01)
    if number(policy.get("crush_change_pct", -3)) >= 0:
        raise ValueError("VIX crush threshold must be negative")
    for key, default in (("target_factor", 0.8), ("pullback_factor", 0.75)):
        if not 0 < number(policy.get(key, default)) <= 1:
            raise ValueError("VIX exit factors must tighten within (0, 1]")


def vix_exit_settings(config, vix, now):
    result = dict(config)
    policy = config.get("vix_adaptation", {})
    if not policy.get("enabled", False):
        return result
    validate_vix_policy(config)
    try:
        stamp = exchange_time(vix["timestamp"])
        if stamp.date() != now.date() or not 0 <= (now - stamp).total_seconds() < 20:
            return result
        level = number(vix["last_price"], minimum=0.01)
        change = number(vix["change_pct"])
    except (KeyError, ValueError, TypeError):
        return result
    if level < number(policy.get("low_vix_below", 13)) or change <= number(
        policy.get("crush_change_pct", -3)
    ):
        target_factor = number(policy.get("target_factor", 0.8))
        pullback_factor = number(policy.get("pullback_factor", 0.75))
        result["target_pct"] = config.get("target_pct", 50) * target_factor
        normal = config.get("trail_pullback_pct", config.get("peak_pullback_pct", 10))
        result["trail_pullback_pct"] = normal * pullback_factor
        if config.get("aggressive_trail_enabled", False):
            result["aggressive_trail_pullback_pct"] = min(
                config.get("aggressive_trail_pullback_pct", 5), result["trail_pullback_pct"]
            )
    return result
