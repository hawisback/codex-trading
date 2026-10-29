"""Conservative OHLC execution estimates, never broker-fill or AI evidence."""

from datetime import timedelta
from trading.domain.market_data import exchange_time
from trading.domain.trailing import runner_trigger


def simulate_option_path(signal_index, direction, spot_bars, options, strike, exit_config):
    """Enter at next minute's open. Existing stops are tested before new highs.

    A ratchet derived from this minute's high is effective next minute. A gap
    through the old stop exits at the worse open. These are OHLC estimates;
    bid/ask slippage and resting stop-limit fill probability remain unknown.
    Missing option candles invalidate the whole estimate instead of repricing it.
    """
    first = signal_index + 1
    if direction not in ("CE", "PE") or signal_index < 0 or first >= len(spot_bars):
        return None
    entry_bar = options.bar(strike, direction, spot_bars[first]["start_time"])
    if entry_bar is None:
        return None
    entry = entry_bar["open"]
    recent = spot_bars[max(0, signal_index - 4):signal_index + 1]
    invalidation = (min(b["low"] for b in recent) - 2 if direction == "CE"
                    else max(b["high"] for b in recent) + 2)
    stop = entry * (1 - exit_config.get("initial_stop_pct", 20) / 100)
    peak = entry
    last = None
    previous = exchange_time(spot_bars[signal_index]["start_time"])
    for index in range(first, len(spot_bars)):
        spot = spot_bars[index]
        stamp = exchange_time(spot["start_time"])
        if stamp != previous + timedelta(minutes=1):
            return None
        previous = stamp
        bar = options.bar(strike, direction, stamp)
        if bar is None:
            return None
        if stamp.strftime("%H:%M") >= "15:15":
            last = (index, bar["open"], "15:15_SQUARE_OFF")
            break
        if bar["low"] <= stop:
            last = (index, min(stop, bar["open"]), "EXISTING_STOP_OR_GAP")
            break
        if ((direction == "CE" and spot["low"] <= invalidation)
                or (direction == "PE" and spot["high"] >= invalidation)):
            # Spot/option wick ordering is unavailable: use the adverse option low.
            last = (index, bar["low"], "STRUCTURAL_INVALIDATION_OHLC_ESTIMATE")
            break
        peak = max(peak, bar["high"])
        if (peak / entry - 1) * 100 + 1e-9 >= exit_config.get("runner_activation_pct", 15):
            stop = max(stop, runner_trigger(entry, peak, exit_config))
    if last is None:
        # An open position at the end of a partial history is not realized PnL.
        return None
    exit_index, exit_price, reason = last
    return dict(entry_idx=first, exit_idx=exit_index, signal_idx=signal_index, direction=direction,
                strike=strike, entry_price=entry, exit_price=exit_price, peak_price=peak,
                peak_gain_pct=(peak / entry - 1) * 100, invalidation_spot=invalidation,
                pnl_pts=exit_price - entry, pnl_inr=(exit_price - entry) * 65,
                ret_pct=(exit_price / entry - 1) * 100, exit_reason=reason,
                pricing_source="EXACT_CONTRACT_OHLC_ESTIMATE", ai_used=False)
