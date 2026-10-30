"""Contract selection and purchasing-power policy shared by strategy workflows."""

from trading.domain.indicators import select_strike
from trading.models import Decision
from typing import cast
from trading.domain.limits import FEE_RESERVE, LOT_SIZE
from trading.domain.market_data import number


class CandidateSelectionService:
    def __init__(
        self, strategy_mode, strategy_cfg, quantity, quantity_calculator, strategy, trading_cfg=None
    ):
        self.strategy_mode = strategy_mode
        self.strategy_cfg = strategy_cfg
        self.quantity = quantity
        self.quantity_calculator = quantity_calculator
        self.strategy = strategy
        self.trading_cfg = trading_cfg or {}

    def analyze(self, ctx: dict, intel: dict | None = None, today_entries: int = 0) -> Decision:
        """
        Synthesize multi-factor market state and determine trade signal:
        - If strategy_mode == 'ai_opportunity_radar': Evaluates both Dynamic Trend Pullbacks & Climax Capitulation Springs.
        - Otherwise: Evaluates legacy rule-based strategies (Strategy 3 Institutional Pullback, Strategy 2, etc.)
        - Enforces strict ITM/ATM strike selection and zero-shortfall margin budget.
        """
        spot = ctx.get("spot")
        candles = ctx.get("candles_1m") or []
        entry_cfg = self.strategy_cfg.get("entry", {})
        strike_selection_mode = entry_cfg.get("strike_selection", "STRICT_ITM")
        strict_contract = self.strategy_mode == "macd_momentum" and strike_selection_mode == "STRICT_ITM"

        setup_type = "NONE"
        invalidation_level = None

        candidate = self.strategy.evaluate(ctx, intel=intel)
        signal, reasons = candidate.signal, candidate.reasons
        setup_type, invalidation_level = candidate.setup_type, candidate.invalidation_level

        # -------------------------------------------------------------
        # INSTRUMENT SELECTION (If signal survives all contextual filters)
        # -------------------------------------------------------------
        atm_strike = ctx.get("atm_strike")
        target_instrument = None
        target_symbol = None
        target_ltp = None
        target_strike = None
        order_qty = self.quantity

        if signal in ["BUY_CE", "BUY_PE"]:
            if strike_selection_mode == "STRICT_ITM" and spot:
                target_strike = select_strike(spot, "CE" if signal == "BUY_CE" else "PE", "STRICT_ITM")
                # At exact strike boundaries, strict ITM must still have intrinsic value.
                if strict_contract and target_strike == spot:
                    target_strike += -50 if signal == "BUY_CE" else 50
                reasons.append(
                    f"STRIKE SELECTION: Strict ITM strike {target_strike} selected (resilient to theta decay)."
                )
            else:
                target_strike = (
                    select_strike(spot, "CE" if signal == "BUY_CE" else "PE", "ATM") if spot else atm_strike
                )
                reasons.append(f"STRIKE SELECTION: ATM strike {target_strike} selected.")

            matched_strike_obj = None
            for s in ctx.get("strikes", []):
                if target_strike is not None and abs(s.get("strike", 0) - target_strike) < 1.0:
                    matched_strike_obj = s
                    break

            if not matched_strike_obj and atm_strike and not strict_contract:
                for s in ctx.get("strikes", []):
                    if abs(s.get("strike", 0) - atm_strike) < 1.0:
                        matched_strike_obj = s
                        reasons.append(
                            f"STRIKE FALLBACK: Target strike {target_strike} not in window; defaulted to ATM {atm_strike}."
                        )
                        break

            if matched_strike_obj:
                leg = (
                    matched_strike_obj.get("call") if signal == "BUY_CE" else matched_strike_obj.get("put")
                ) or {}
                target_instrument = leg.get("instrument_id")
                target_symbol = leg.get("symbol")
                target_ltp = leg.get("ltp")
                if strict_contract:
                    try:
                        target_ltp = number(target_ltp, minimum=0.01)
                    except (ValueError, TypeError, OverflowError):
                        target_ltp = None

                # -------------------------------------------------------------
                # ZERO-SHORTFALL MARGIN BUDGET GATEKEEPER & MAX PREMIUM ENFORCEMENT
                # -------------------------------------------------------------
                try:
                    avail_margin = (
                        number(ctx.get("available_margin"), minimum=0)
                        if strict_contract
                        else float(ctx.get("available_margin") or 0.0)
                    )
                except (ValueError, TypeError, OverflowError):
                    avail_margin = 0.0
                order_qty = self.quantity_calculator(avail_margin, target_ltp or 100.0)
                # Keep a ₹150 buffer for exchange turnover, STT, and statutory taxes
                safe_budget = max(0.0, avail_margin - FEE_RESERVE)
                required_cost = (target_ltp or 0.0) * order_qty
                max_premium = (
                    float(self.trading_cfg.get("option_selection", {}).get("max_option_premium", 185.0))
                    if self.trading_cfg
                    else 185.0
                )

                r01 = self.trading_cfg.get("r01_policy", {})
                if r01.get("enabled") is True and r01.get("price_only_veto_disabled") is True:
                    # Buying-power and quote-quality vetoes remain independent.
                    max_premium = float("inf")

                # 1. If ITM exceeds safe budget or max premium policy, step down to ATM
                if (
                    not strict_contract
                    and target_ltp
                    and (required_cost > safe_budget or order_qty == 0 or target_ltp > max_premium)
                ):
                    reasons.append(
                        f"MARGIN BUDGET OPTIMIZATION: ITM strike {target_strike} (₹{target_ltp:.1f} x {order_qty} = ₹{required_cost:.0f}) "
                        f"exceeds safe policy (Budget: ₹{safe_budget:.0f}, Max Premium: ₹{max_premium:.1f}). Falling back to ATM {atm_strike}."
                    )
                    atm_obj = next(
                        (
                            s
                            for s in ctx.get("strikes", [])
                            if abs(s.get("strike", 0) - (atm_strike or 0)) < 1.0
                        ),
                        None,
                    )
                    if atm_obj:
                        matched_strike_obj = atm_obj
                        target_strike = int(cast(float, atm_strike))
                        leg = (
                            matched_strike_obj.get("call")
                            if signal == "BUY_CE"
                            else matched_strike_obj.get("put")
                        ) or {}
                        target_instrument = leg.get("instrument_id")
                        target_symbol = leg.get("symbol")
                        target_ltp = leg.get("ltp")
                        order_qty = self.quantity_calculator(avail_margin, target_ltp or 100.0)
                        required_cost = (target_ltp or 0.0) * order_qty

                # 2. Search the configured OTM window, nearest strike first.
                if (
                    not strict_contract
                    and target_ltp
                    and (required_cost > safe_budget or order_qty == 0 or target_ltp > max_premium)
                    and atm_strike
                ):
                    max_otm_strikes = int(
                        self.trading_cfg.get("option_selection", {}).get("max_otm_strikes", 4)
                    )
                    for step in range(1, max_otm_strikes + 1):
                        otm_strike = atm_strike + (step * 50 if signal == "BUY_CE" else -step * 50)
                        otm_obj = next(
                            (s for s in ctx.get("strikes", []) if abs(s.get("strike", 0) - otm_strike) < 1.0),
                            None,
                        )
                        if otm_obj is None:
                            continue
                        leg = (otm_obj.get("call") if signal == "BUY_CE" else otm_obj.get("put")) or {}
                        try:
                            otm_ltp = number(leg.get("ltp"), minimum=0.01)
                        except (ValueError, TypeError):
                            continue
                        if (
                            not leg.get("instrument_id")
                            or not leg.get("symbol")
                            or otm_ltp > max_premium
                            or otm_ltp * LOT_SIZE > safe_budget
                        ):
                            continue
                        otm_qty = self.quantity_calculator(avail_margin, otm_ltp)
                        if otm_qty > 0 and (otm_ltp * otm_qty) <= safe_budget:
                            reasons.append(
                                f"MARGIN BUDGET OPTIMIZATION: ATM strike exceeded policy; selected {step}-strike OTM {otm_strike} "
                                f"(₹{otm_ltp:.1f} x {otm_qty} = ₹{otm_ltp * otm_qty:.0f} <= ₹{safe_budget:.0f})."
                            )
                            matched_strike_obj = otm_obj
                            target_strike = int(otm_strike)
                            target_instrument = leg.get("instrument_id")
                            target_symbol = leg.get("symbol")
                            target_ltp = otm_ltp
                            order_qty = otm_qty
                            required_cost = otm_ltp * order_qty
                            break

                # 3. FINAL SHORTFALL VETO: If candidate STILL exceeds safe margin budget or max premium or capital is 0
                if (
                    target_ltp is None
                    or target_instrument is None
                    or (
                        strict_contract
                        and (
                            not target_symbol
                            or not isinstance(target_ltp, (int, float))
                            or isinstance(target_ltp, bool)
                        )
                    )
                    or order_qty <= 0
                    or required_cost > safe_budget
                    or target_ltp > max_premium
                    or safe_budget <= 0
                ):
                    shortfall_amt = max(0.0, required_cost - safe_budget)
                    signal = "NEUTRAL"
                    reasons.append(
                        f"INSUFFICIENT FUNDS VETO: Contract ({target_symbol or target_strike}) requires ₹{required_cost:.2f} "
                        f"(₹{target_ltp or 0:.2f} x {order_qty} qty), exceeding safe margin ₹{safe_budget:.2f} "
                        f"(Shortfall: ₹{shortfall_amt:.2f}, Broker Avail: ₹{avail_margin:.2f}). "
                        f"Zero-shortfall rule enforced: Order blocked from submission!"
                    )
                    target_instrument = None
                    target_symbol = None
                    target_ltp = None

            if strict_contract and (not target_instrument or not target_symbol or not target_ltp):
                signal = "NEUTRAL"
                reasons.append(
                    "STRICT ITM VETO: Required ITM contract unavailable or outside purchasing-power/premium policy; preserving cash."
                )
                target_instrument = target_symbol = target_ltp = None
                order_qty = 0

        return {
            "signal": signal,
            "strategy": self.strategy_mode,
            "setup_type": setup_type,
            "invalidation_level": invalidation_level,
            "bull_score": 1 if signal == "BUY_CE" else 0,
            "bear_score": 1 if signal == "BUY_PE" else 0,
            "instrument_id": target_instrument,
            "symbol": target_symbol,
            "ltp": target_ltp,
            "target_strike": target_strike,
            "quantity": order_qty,
            "order_qty": order_qty,
            "reasons": reasons,
        }
