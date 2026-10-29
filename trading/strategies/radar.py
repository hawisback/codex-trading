"""Live opportunity-radar signal adapter. No order placement or AI gate bypass."""

from market_clock import MarketClock
from trading.models import CandidateSignal


class RadarStrategy:
    def __init__(self, radar):
        self.radar = radar

    def evaluate(self, ctx, intel=None):
        spot = ctx.get("spot")
        candles = ctx.get("candles_1m") or []
        bar_idx = len(candles) - 1 if candles else 0
        bar = (
            candles[-1]
            if candles
            else {
                "open": ctx.get("day_open", spot),
                "high": ctx.get("day_high", spot),
                "low": ctx.get("day_low", spot),
                "close": spot,
                "start_time": MarketClock.now_ist().isoformat(),
            }
        )
        bar_ts = bar.get("start_time") or bar.get("date")
        dt_bar = MarketClock.parse_to_ist(bar_ts) or MarketClock.now_ist()
        current_session_min = MarketClock.get_session_minutes(dt_bar)[0]

        all_bars = candles if candles else [bar]
        spot_closes = [float(c.get("close", spot)) for c in all_bars]
        session_vwap = float(ctx.get("session_vwap") or spot)
        ema9 = float(ctx.get("ema_9") or spot)
        ema20 = float(ctx.get("ema_20") or spot)
        rsi = float(ctx.get("rsi_14") or 50.0)
        day_open = float(ctx.get("day_open") or (all_bars[0].get("open", spot) if all_bars else spot))
        box_high = float(ctx.get("box_high_15m") or spot)
        box_low = float(ctx.get("box_low_15m") or spot)

        # Rolling RSI history for climax extreme detection
        if len(spot_closes) > 15:

            def _calc_rsi_sub(prices: list, period: int = 14) -> float:
                if len(prices) <= period:
                    return 50.0
                deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
                gains = [max(0.0, d) for d in deltas]
                losses = [max(0.0, -d) for d in deltas]
                avg_gain = sum(gains[:period]) / period
                avg_loss = sum(losses[:period]) / period
                for i in range(period, len(deltas)):
                    avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                    avg_loss = (avg_loss * (period - 1) + losses[i]) / period
                if avg_loss == 0.0:
                    return 100.0
                rs = avg_gain / avg_loss
                return round(100.0 - (100.0 / (1.0 + rs)), 1)

            rsi_history = [_calc_rsi_sub(spot_closes[: i + 1]) for i in range(len(spot_closes))]
        else:
            rsi_history = [rsi] * len(all_bars)

        opp = self.radar.evaluate(
            bar_idx=bar_idx,
            bar=bar,
            all_bars=all_bars,
            spot_closes=spot_closes,
            session_vwap=session_vwap,
            ema9=ema9,
            ema20=ema20,
            rsi=rsi,
            rsi_history=rsi_history,
            day_open=day_open,
            box_high=box_high,
            box_low=box_low,
            session_minute=current_session_min,
        )

        if opp.action in ["BUY_CE", "BUY_PE"] and opp.conviction >= 80:
            signal = opp.action
            reasons = [f"AI RADAR [{opp.regime} | Conviction: {opp.conviction}%]: {opp.thesis}"]
            setup_type = opp.regime
            invalidation_level = opp.invalidation_level
        else:
            signal = "NEUTRAL"
            reasons = [f"AI RADAR STAND ASIDE: {opp.thesis}"]
            setup_type = "NONE"
            invalidation_level = None

        return CandidateSignal(signal, reasons, setup_type, invalidation_level)
