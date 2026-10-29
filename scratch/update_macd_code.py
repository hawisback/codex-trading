import re

path = "trading/strategies/macd_momentum.py"
with open(path, "r", encoding="utf-8") as fp:
    content = fp.read()

new_class = '''class MacdMomentumStrategy:
    """
    Path A: 2-Minute MACD Momentum Strategy with 5m EMA Value Confirmation.
    Detects 2m MACD line crossovers with signal line, confirmed by 5m EMA9 value proximity
    and 5m EMA20 trend alignment.
    """
    def __init__(self, strategy_cfg: Optional[Dict] = None):
        self.cfg = strategy_cfg or {}
        entry_cfg = self.cfg.get("entry", {})
        self.fast_period = int(entry_cfg.get("macd_fast", 12))
        self.slow_period = int(entry_cfg.get("macd_slow", 26))
        self.signal_period = int(entry_cfg.get("macd_signal", 9))
        self.require_ema_confirmation = bool(entry_cfg.get("require_ema_confirmation", False))
        self.ema_proximity_pts = float(entry_cfg.get("ema_proximity_pts", 10.0))
        self.require_ema20_trend_alignment = bool(entry_cfg.get("require_ema20_trend_alignment", False))
        self.min_invalidation_buffer_pts = float(entry_cfg.get("min_invalidation_buffer_pts", 15.0))

    def evaluate(self, ctx: Dict, intel: Optional[Dict] = None) -> CandidateSignal:
        candles_1m = ctx.get("candles_1m") or []

        if len(candles_1m) < 30:
            return CandidateSignal(
                signal="NEUTRAL",
                reasons=[f"Insufficient 1m candles ({len(candles_1m)} < 30) for 2m MACD calculation."],
                setup_type="NONE"
            )

        now = MarketClock.now_ist()
        try:
            resampled_2m = resample_1m_to_2m(candles_1m, as_of=now)
        except (ValueError, TypeError, KeyError):
            return CandidateSignal("NEUTRAL", ["Invalid or incomplete timestamped candle history."], "NONE")
        if len(resampled_2m) < max(2, self.slow_period + 1):
            return CandidateSignal(
                signal="NEUTRAL",
                reasons=[f"Insufficient 2m candles ({len(resampled_2m)} < {self.slow_period}) for MACD."],
                setup_type="NONE"
            )

        latest = resampled_2m[-1]
        if latest["minute_idx"] != len(candles_1m) - 1:
            return CandidateSignal("NEUTRAL", ["Waiting for the current two-minute candle to close."], "NONE")
        if now - exchange_time(latest["start_time"]) >= timedelta(minutes=3):
            return CandidateSignal("NEUTRAL", ["Latest completed two-minute candle is stale."], "NONE")
        closes = [float(b["close"]) for b in resampled_2m]
        macd_line, signal_line, hist = calculate_macd(
            closes,
            fast_period=self.fast_period,
            slow_period=self.slow_period,
            signal_period=self.signal_period
        )

        n = len(resampled_2m) - 1

        pe_cross = (macd_line[n] < signal_line[n]) and (macd_line[n - 1] >= signal_line[n - 1])
        ce_cross = (macd_line[n] > signal_line[n]) and (macd_line[n - 1] <= signal_line[n - 1])

        recent_1m = candles_1m[-5:] if len(candles_1m) >= 5 else candles_1m
        spot = float(ctx.get("spot") or latest["close"])
        ema9 = float(ctx.get("ema_9") or spot)
        ema20 = float(ctx.get("ema_20") or spot)

        if ce_cross:
            if self.require_ema_confirmation:
                ema_dist = abs(spot - ema9)
                if ema_dist > self.ema_proximity_pts:
                    return CandidateSignal(
                        signal="NEUTRAL",
                        reasons=[
                            f"2m MACD Bullish cross rejected: Spot ({spot:.1f}) is extended {ema_dist:.1f} pts "
                            f"from 5m EMA9 ({ema9:.1f}) > {self.ema_proximity_pts:.1f} pts tolerance."
                        ],
                        setup_type="NONE"
                    )
                if self.require_ema20_trend_alignment and spot < ema20:
                    return CandidateSignal(
                        signal="NEUTRAL",
                        reasons=[
                            f"2m MACD Bullish cross rejected: Spot ({spot:.1f}) is below 5m EMA20 ({ema20:.1f}). "
                            f"Counter-trend entries blocked."
                        ],
                        setup_type="NONE"
                    )

            raw_inval = min(float(b.get("low", b.get("close"))) for b in recent_1m) - 2.0
            invalidation = min(raw_inval, spot - self.min_invalidation_buffer_pts)
            reasons = [
                f"2m MACD Bullish Crossover: MACD ({macd_line[n]:.2f}) crossed above Signal ({signal_line[n]:.2f}), "
                f"Histogram: {hist[n]:+.2f} (prev: {hist[n-1]:+.2f}). "
                f"EMA Value Confirmation: Spot ({spot:.1f}) near 5m EMA9 ({ema9:.1f}, dist {abs(spot - ema9):.1f} pts) & above EMA20 ({ema20:.1f})."
            ]
            return CandidateSignal(
                signal="BUY_CE",
                reasons=reasons,
                setup_type="MACD_2M_MOMENTUM",
                invalidation_level=invalidation
            )

        if pe_cross:
            if self.require_ema_confirmation:
                ema_dist = abs(spot - ema9)
                if ema_dist > self.ema_proximity_pts:
                    return CandidateSignal(
                        signal="NEUTRAL",
                        reasons=[
                            f"2m MACD Bearish cross rejected: Spot ({spot:.1f}) is extended {ema_dist:.1f} pts "
                            f"from 5m EMA9 ({ema9:.1f}) > {self.ema_proximity_pts:.1f} pts tolerance."
                        ],
                        setup_type="NONE"
                    )
                if self.require_ema20_trend_alignment and spot > ema20:
                    return CandidateSignal(
                        signal="NEUTRAL",
                        reasons=[
                            f"2m MACD Bearish cross rejected: Spot ({spot:.1f}) is above 5m EMA20 ({ema20:.1f}). "
                            f"Counter-trend entries blocked."
                        ],
                        setup_type="NONE"
                    )

            raw_inval = max(float(b.get("high", b.get("close"))) for b in recent_1m) + 2.0
            invalidation = max(raw_inval, spot + self.min_invalidation_buffer_pts)
            reasons = [
                f"2m MACD Bearish Crossover: MACD ({macd_line[n]:.2f}) crossed below Signal ({signal_line[n]:.2f}), "
                f"Histogram: {hist[n]:+.2f} (prev: {hist[n-1]:+.2f}). "
                f"EMA Value Confirmation: Spot ({spot:.1f}) near 5m EMA9 ({ema9:.1f}, dist {abs(spot - ema9):.1f} pts) & below EMA20 ({ema20:.1f})."
            ]
            return CandidateSignal(
                signal="BUY_PE",
                reasons=reasons,
                setup_type="MACD_2M_MOMENTUM",
                invalidation_level=invalidation
            )

        return CandidateSignal(
            signal="NEUTRAL",
            reasons=[
                f"2m MACD in-range: MACD={macd_line[n]:.2f}, Signal={signal_line[n]:.2f}, "
                f"Hist={hist[n]:+.2f} (No fresh crossover on latest bar)."
            ],
            setup_type="NONE",
            invalidation_level=None
        )
'''

# Replace from class MacdMomentumStrategy to the end
idx = content.find("class MacdMomentumStrategy:")
if idx != -1:
    updated = content[:idx] + new_class
    with open(path, "w", encoding="utf-8") as fp:
        fp.write(updated)
    print("Updated trading/strategies/macd_momentum.py successfully")
else:
    print("Class not found")
