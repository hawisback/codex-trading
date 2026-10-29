"""Existing rule-based signal evaluation, independent of broker execution."""

from typing import cast


class LegacyRuleEvaluator:
    def __init__(self, strategy_cfg):
        self.strategy_cfg = strategy_cfg

    def evaluate(self, ctx: dict, intel: dict | None = None) -> tuple[str, list[str]]:
        """
        Legacy Strategy 3 / 2 / 1 Rule-Based Evaluation (Steps 1 to 5):
        Preserved 100% intact as a validated backup engine.
        """
        spot = ctx["spot"]
        last_1m_high = ctx.get("last_1m_high", spot)
        last_1m_low = ctx.get("last_1m_low", spot)
        ema9 = ctx["ema_9"]
        ema20 = ctx["ema_20"]
        rsi = ctx["rsi_14"]
        session_vwap = ctx.get("session_vwap")
        box_high = cast(float, ctx.get("box_high_15m"))
        box_low = cast(float, ctx.get("box_low_15m"))
        box_spread = ctx.get("box_spread_15m", 999.0)
        is_box = ctx.get("is_consolidation_box", False)
        hw = ctx.get("heavyweights", {})
        flow = ctx.get("order_flow", {})
        atm_strike = ctx.get("atm_strike") or (int(round(spot / 50.0)) * 50 if spot else 0)

        entry_cfg = self.strategy_cfg.get("entry", {})
        require_pullback = entry_cfg.get("require_pullback", False)
        pullback_tol = entry_cfg.get("pullback_ema_tolerance_pts", 4.0)
        require_range_box = entry_cfg.get("require_range_box_filter", True)
        range_box_spread_min = entry_cfg.get("range_box_spread_min", 28.0)
        value_proximity_pts = entry_cfg.get("value_proximity_pts", 24.0)
        prevent_v_reversal = entry_cfg.get("prevent_v_reversal_counter_trades", False)

        reasons = []
        signal = "NEUTRAL"

        # -------------------------------------------------------------
        # STEP 1: TREND ALIGNMENT & PULLBACK VALIDATION
        # -------------------------------------------------------------
        if spot and ema9 and ema20 and session_vwap:
            if spot > ema9 and ema9 > ema20 and spot > session_vwap:
                if require_pullback:
                    if last_1m_low <= (ema9 + pullback_tol):
                        signal = "BUY_CE"
                        reasons.append(
                            f"Trend Aligned Bull & Pullback Confirmed: Spot ({spot:.1f}) > 5m EMA9 ({ema9:.1f}) > EMA20 ({ema20:.1f}) & > VWAP ({session_vwap:.1f}); "
                            f"1m low ({last_1m_low:.1f}) retested within {pullback_tol:.1f} pts of 5m EMA9."
                        )
                    else:
                        signal = "NEUTRAL"
                        reasons.append(
                            f"PULLBACK BLOCKED: Spot is in bull trend, but 1m low ({last_1m_low:.1f}) did not retest 5m EMA9 ({ema9:.1f} + {pullback_tol:.1f} pts). "
                            f"Chasing in mid-air prevented!"
                        )
                else:
                    signal = "BUY_CE"
                    reasons.append(
                        f"Trend Aligned Bull: Spot ({spot:.1f}) > 5m EMA9 ({ema9:.1f}) > EMA20 ({ema20:.1f}) & > VWAP ({session_vwap:.1f})"
                    )

            elif spot < ema9 and ema9 < ema20 and spot < session_vwap:
                if prevent_v_reversal and ((rsi and rsi > 50.0) or (spot > ema9)):
                    signal = "NEUTRAL"
                    reasons.append(
                        f"V-REVERSAL BLOCKED: Counter-trend Put vetoed because RSI ({rsi:.1f} > 50) or spot price bouncing above 5m EMA9."
                    )
                elif require_pullback:
                    if last_1m_high >= (ema9 - pullback_tol):
                        signal = "BUY_PE"
                        reasons.append(
                            f"Trend Aligned Bear & Pullback Confirmed: Spot ({spot:.1f}) < 5m EMA9 ({ema9:.1f}) < EMA20 ({ema20:.1f}) & < VWAP ({session_vwap:.1f}); "
                            f"1m high ({last_1m_high:.1f}) retested within {pullback_tol:.1f} pts of 5m EMA9."
                        )
                    else:
                        signal = "NEUTRAL"
                        reasons.append(
                            f"PULLBACK BLOCKED: Spot is in bear trend, but 1m high ({last_1m_high:.1f}) did not retest 5m EMA9 ({ema9:.1f} - {pullback_tol:.1f} pts). "
                            f"Chasing in mid-air prevented!"
                        )
                else:
                    signal = "BUY_PE"
                    reasons.append(
                        f"Trend Aligned Bear: Spot ({spot:.1f}) < 5m EMA9 ({ema9:.1f}) < EMA20 ({ema20:.1f}) & < VWAP ({session_vwap:.1f})"
                    )
            else:
                signal = "NEUTRAL"
                reasons.append("Trend Mixed: Price not cleanly aligned with 5m EMA and Session VWAP.")
        else:
            signal = "NEUTRAL"
            reasons.append("Incomplete indicators for trend classification.")

        # -------------------------------------------------------------
        # STEP 2: MARKET REGIME (Consolidation Ceiling vs. Expansion)
        # -------------------------------------------------------------
        if require_range_box and is_box and box_spread < range_box_spread_min:
            if signal == "BUY_CE":
                if spot < (box_high + 2.0) and spot >= (box_high - 6.0):
                    signal = "NEUTRAL"
                    reasons.append(
                        f"REGIME BLOCKED: Spot ({spot:.1f}) is at CEILING of 15m box ({box_low:.1f} - {box_high:.1f}, spread {box_spread:.1f} pts). Awaiting breakout or pullback."
                    )
                elif spot < (box_low + 5.0):
                    reasons.append(
                        f"REGIME: Spot at value floor of 15m box ({box_low:.1f}); favorable risk-reward."
                    )
            elif signal == "BUY_PE":
                if spot > (box_low - 2.0) and spot <= (box_low + 6.0):
                    signal = "NEUTRAL"
                    reasons.append(
                        f"REGIME BLOCKED: Spot ({spot:.1f}) is at FLOOR of 15m box ({box_low:.1f} - {box_high:.1f}). Awaiting breakdown or rally."
                    )

        # Value Proximity Check: Do not buy if overextended (parabolic exhaustion)
        if signal == "BUY_CE":
            distance_from_ema9 = spot - ema9
            if distance_from_ema9 > value_proximity_pts or (rsi and rsi > 78.0):
                signal = "NEUTRAL"
                reasons.append(
                    f"VALUE BLOCKED: Spot is overextended (+{distance_from_ema9:.1f} pts above 5m EMA9, RSI {rsi:.1f}). Awaiting pullback to value."
                )
            elif distance_from_ema9 <= 16.0:
                reasons.append(
                    f"VALUE CONFIRMED: Spot near 5m EMA9 (+{distance_from_ema9:.1f} pts); optimal risk/reward entry."
                )
        elif signal == "BUY_PE":
            distance_from_ema9 = ema9 - spot
            if distance_from_ema9 > value_proximity_pts or (rsi and rsi < 22.0):
                signal = "NEUTRAL"
                reasons.append(
                    f"VALUE BLOCKED: Spot is overextended (-{distance_from_ema9:.1f} pts below 5m EMA9, RSI {rsi:.1f}). Awaiting rally to value."
                )
            elif distance_from_ema9 <= 16.0:
                reasons.append(
                    f"VALUE CONFIRMED: Spot near 5m EMA9 (-{distance_from_ema9:.1f} pts); optimal risk/reward entry."
                )

        # -------------------------------------------------------------
        # STEP 3: INSTITUTIONAL ORDER FLOW & RUNWAY VALIDATION
        # -------------------------------------------------------------
        next_call_stk = flow.get("next_call_strike", 0)
        next_call_oi = flow.get("next_call_oi", 0)
        next_call_oi_chg = flow.get("next_call_oi_chg", 0)
        atm_put_oi_chg = flow.get("atm_put_oi_chg", 0)
        next_put_stk = flow.get("next_put_strike", 0)
        next_put_oi = flow.get("next_put_oi", 0)
        next_put_oi_chg = flow.get("next_put_oi_chg", 0)

        if signal == "BUY_CE":
            # If institutions are aggressively writing calls on the next overhead strike, ceiling is blocked
            runway = next_call_stk - spot
            if 0 < runway < 38.0 and next_call_oi >= 4000000 and next_call_oi_chg > 1000000:
                signal = "NEUTRAL"
                reasons.append(
                    f"ORDER FLOW BLOCKED: Heavy Call Writing (+{next_call_oi_chg / 1e6:.1f}M OI) defending {next_call_stk:.0f} (runway only {runway:.1f} pts)."
                )
            elif next_call_oi_chg <= 0:
                reasons.append(
                    f"ORDER FLOW CONFIRMED: Overhead Call writers unwinding at {next_call_stk:.0f} ({next_call_oi_chg / 1e6:.1f}M OI). Runway clear!"
                )

            # Check if Put writers are establishing support
            if atm_put_oi_chg > 1000000:
                reasons.append(
                    f"ORDER FLOW CONFIRMED: Strong Put writing support at ATM {atm_strike:.0f} (+{atm_put_oi_chg / 1e6:.1f}M OI)."
                )
            elif atm_put_oi_chg < -500000:
                signal = "NEUTRAL"
                reasons.append(
                    f"ORDER FLOW WARNING: Put writers unwinding at ATM {atm_strike:.0f} ({atm_put_oi_chg / 1e6:.1f}M OI). Support fragile."
                )

        elif signal == "BUY_PE":
            runway = spot - next_put_stk
            if 0 < runway < 38.0 and next_put_oi >= 4000000 and next_put_oi_chg > 1000000:
                signal = "NEUTRAL"
                reasons.append(
                    f"ORDER FLOW BLOCKED: Heavy Put Writing (+{next_put_oi_chg / 1e6:.1f}M OI) defending {next_put_stk:.0f} (runway only {runway:.1f} pts)."
                )

        # -------------------------------------------------------------
        # STEP 4: HEAVYWEIGHT CONSTITUENT LEADERSHIP & TRAP CHECK
        # -------------------------------------------------------------
        hw_adv = hw.get("advancing", 0)
        hw_dec = hw.get("declining", 0)  # noqa: F841 - preserve extracted lookup behavior
        hdfc_chg = hw.get("hdfc_chg", 0.0)
        rel_chg = hw.get("reliance_chg", 0.0)
        icici_chg = hw.get("icici_chg", 0.0)

        if signal == "BUY_CE":
            # If 4/5 heavyweights advancing and HDFC is strong, allow rally even if Reliance is mildly lagging
            if hw_adv >= 4 and hdfc_chg >= 0.70:
                reasons.append(f"HEAVYWEIGHTS STRONG: 4/5 advancing led by HDFCBANK (+{hdfc_chg:.2f}%).")
                if rel_chg < -1.30:
                    signal = "NEUTRAL"
                    reasons.append(
                        f"HEAVYWEIGHTS BLOCKED: Reliance collapsing ({rel_chg:.2f}%) dragging broader index."
                    )
            else:
                if rel_chg < -0.55:
                    signal = "NEUTRAL"
                    reasons.append(f"HEAVYWEIGHTS BLOCKED: Reliance dragging market down ({rel_chg:.2f}%).")
                top3_non_neg = sum(1 for c in [hdfc_chg, rel_chg, icici_chg] if c >= -0.10)
                if top3_non_neg < 2:
                    signal = "NEUTRAL"
                    reasons.append(
                        f"HEAVYWEIGHTS BLOCKED: Lack of consensus among HDFC/Reliance/ICICI ({top3_non_neg}/3 holding)."
                    )

        elif signal == "BUY_PE":
            if hw_adv >= 4 or (hdfc_chg > 0.60 and rel_chg > 0.60):
                signal = "NEUTRAL"
                reasons.append("HEAVYWEIGHTS BLOCKED: Top heavyweights too strong for Put buying.")

        # -------------------------------------------------------------
        # STEP 5: MACRO & FINANCIAL NEWS SENTIMENT
        # -------------------------------------------------------------
        if intel:
            trap_advisories = intel.get("trap_advisories", [])
            if signal == "BUY_CE" and "POTENTIAL_BULL_TRAP" in trap_advisories:
                signal = "NEUTRAL"
                reasons.append(
                    "MACRO TRAP BLOCKED: Active Bull Trap advisory (External cues/news divergent)."
                )
            elif signal == "BUY_PE" and "POTENTIAL_BEAR_TRAP" in trap_advisories:
                signal = "NEUTRAL"
                reasons.append("MACRO TRAP BLOCKED: Active Bear Trap advisory.")

        return signal, reasons
