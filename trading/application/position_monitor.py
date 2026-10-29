"""Position exit and trailing decisions, separate from scheduler cadence."""

from trading.domain.limits import HARD_SQUARE_OFF
from trading.domain.states import is_exiting
from trading.domain.trailing import runner_trigger, session_trigger
from trading.domain.volatility import vix_exit_settings
import logging
from market_clock import MarketClock
from trading.domain.prices import round_tick

logger = logging.getLogger("NiftyAI")


class PositionMonitor:
    def __init__(self, strategy_cfg, state_verified, exit_trade, ratchet_stops, save_position=None):
        self.strategy_cfg = strategy_cfg
        self.state_verified = state_verified
        self.exit_trade = exit_trade
        self.ratchet_stops = ratchet_stops
        self.save_position = save_position

    def manage(self, open_trades: list, ctx: dict, intel: dict) -> list:
        """
        Actively manage open trades based on configured strategy rules:
        - Strategy 1 (Legacy Scalper): Reinstated 6-minute (360s) stopwatch timer exit, tight % stops (6%), and % targets (7%).
        - Strategy 2 & 3 (Structural / Pullback): Structural invalidation via Session VWAP & 5m EMA20, plus dynamic 5m EMA9 trailing runners & breakeven floor locks.
        """
        if not self.state_verified:
            return open_trades
        remaining_open = []
        spot = ctx.get("spot")
        vwap = ctx.get("session_vwap")
        ema9 = ctx.get("ema_9")
        ema20 = ctx.get("ema_20")
        hw = ctx.get("heavyweights", {})
        dec = hw.get("declining", 0)
        adv = hw.get("advancing", 0)

        exit_cfg = vix_exit_settings(
            self.strategy_cfg.get("exit", {}), ctx.get("vix", {}), MarketClock.now_ist()
        )
        max_hold_seconds = exit_cfg.get("max_hold_seconds", 21600)
        initial_stop_pct = min(float(exit_cfg.get("initial_stop_pct", 30.0)), 20.0)
        target_pct = exit_cfg.get("target_pct", 50.0)
        target_enabled = exit_cfg.get("profit_target_enabled", True)
        enable_structural_stops = exit_cfg.get("structural_stops_enabled", True)
        enable_structural_wick_stop = exit_cfg.get("enable_structural_wick_stop", True)
        vwap_stop_buffer = exit_cfg.get("vwap_stop_buffer", 15.0)
        ema20_stop = exit_cfg.get("ema20_stop", True)
        enable_runner_trailing = exit_cfg.get("runner_trailing_enabled", True)
        runner_activation_pct = exit_cfg.get("runner_activation_pct", 15.0)
        ema9_trailing_buffer = exit_cfg.get("ema9_trailing_buffer", 4.0)
        lock_breakeven_on_runner = exit_cfg.get("lock_breakeven_on_runner", True)
        enable_micro_trail = exit_cfg.get("late_day_micro_trail_enabled", True)
        micro_trail_time = exit_cfg.get("late_day_micro_trail_time", "14:00")
        micro_activation_pct = exit_cfg.get("late_day_micro_trail_activation_pct", 4.0)
        micro_floor_pct = exit_cfg.get("late_day_micro_trail_floor_pct", 1.0)
        enable_morning_trail = exit_cfg.get("morning_micro_trail_enabled", True)
        morning_trail_start = exit_cfg.get("morning_micro_trail_start", "09:15")
        morning_trail_end = exit_cfg.get("morning_micro_trail_end", "09:45")
        morning_activation_pct = exit_cfg.get("morning_micro_trail_activation_pct", 10.0)
        morning_floor_pct = exit_cfg.get("morning_micro_trail_floor_pct", 1.0)
        morning_first_trade_only = exit_cfg.get("morning_micro_trail_first_trade_only", True)

        for t in open_trades:
            if is_exiting(t) or t.get("risk_exit_required"):
                result = self.exit_trade(
                    t.get("trade_id"),
                    t.get("risk_exit_required") or t.get("exit_reason", "Resume pending exit"),
                )
                if result.get("status") != "CLOSED":
                    remaining_open.append(t)
                continue
            trade_id = t.get("trade_id")
            if t.get("quote_verified") is False and MarketClock.now_ist().strftime("%H:%M") < HARD_SQUARE_OFF:
                remaining_open.append(t)
                continue
            symbol = t.get("symbol", "")
            entry_price = float(t.get("entry_price") or 0)
            last_bid = float(t.get("last_bid") or entry_price)
            peak_bid = max(float(t.get("peak_bid") or entry_price), last_bid)
            entry_time_str = t.get("entry_time")
            is_ce = symbol.endswith("CE") or "-CE" in t.get("instrument_id", "")
            is_pe = symbol.endswith("PE") or "-PE" in t.get("instrument_id", "")
            require_reclaim = (
                exit_cfg.get("structural_reference_reclaim_required", False)
                and t.get("setup_type") == "MACD_2M_MOMENTUM"
                and float(t.get("invalidation_level") or 0) > 0
            )
            reclaims = t.get("structural_reclaims", {})
            if require_reclaim and spot:
                reclaims = dict(reclaims)
                for name, reference in (("vwap", vwap), ("ema20", ema20), ("ema9", ema9)):
                    if reference and ((is_ce and spot >= reference) or (is_pe and spot <= reference)):
                        reclaims[name] = True
                if reclaims != t.get("structural_reclaims", {}):
                    t["structural_reclaims"] = reclaims
                    if self.save_position is not None:
                        self.save_position(t)
            vwap_armed = not require_reclaim or reclaims.get("vwap", False)
            ema20_armed = not require_reclaim or reclaims.get("ema20", False)
            ema9_armed = not require_reclaim or reclaims.get("ema9", False)

            gain_pct = ((last_bid - entry_price) / entry_price) * 100 if entry_price > 0 else 0.0
            loss_pct = ((entry_price - last_bid) / entry_price) * 100 if entry_price > 0 else 0.0
            peak_gain_pct = ((peak_bid - entry_price) / entry_price) * 100 if entry_price > 0 else 0.0

            hold_sec = 0.0
            entry_hm = None
            if entry_time_str:
                try:
                    entry_dt = MarketClock.parse_to_ist(entry_time_str)
                    now_dt = MarketClock.now_ist()
                    if entry_dt is not None:
                        hold_sec = max(0.0, (now_dt - entry_dt).total_seconds())
                        entry_hm = entry_dt.strftime("%H:%M")
                except Exception:
                    pass

            vwap_disp = f"{vwap:.1f}" if vwap is not None else "N/A"
            ema9_disp = f"{ema9:.1f}" if ema9 is not None else "N/A"
            spot_disp = f"{spot:.1f}" if spot is not None else "N/A"

            logger.info(
                f"  [ACTIVE POSITION] {symbol} | Entry: {entry_price:.2f} | Bid: {last_bid:.2f} ({gain_pct:+.1f}%) | "
                f"Peak: {peak_bid:.2f} ({peak_gain_pct:+.1f}%) | Held: {int(hold_sec)}s | Spot: {spot_disp} | VWAP: {vwap_disp} | 5m EMA9: {ema9_disp}"
            )

            exit_reason = None
            known_floor = max(
                float(t.get("desired_stop_trigger") or 0),
                float(t.get("current_stop_trigger") or 0),
                float(t.get("ai_stop_price") or 0),
            )

            # 0. Session Hard Square-off (Strictly flat book overnight by 15:15 IST)
            now_ist = MarketClock.now_ist()
            now_time = now_ist.strftime("%H:%M")
            session_window, session_stop, session_label = session_trigger(entry_price, peak_bid, exit_cfg, now_time)
            trade_hm = entry_hm or now_time
            is_first_trade = t.get("today_entry_number") == 1
            is_morning_eligible = (
                enable_morning_trail
                and (morning_trail_start <= trade_hm <= morning_trail_end)
                and (not morning_first_trade_only or is_first_trade)
            )
            if now_time >= HARD_SQUARE_OFF:
                exit_reason = f"SESSION HARD SQUARE-OFF: Current time {now_time} IST >= 15:15 cutoff. Enforcing flat book overnight."

            # 0b. Structural Invalidation (Spot breached technical invalidation level)
            elif (
                t.get("invalidation_level") is not None
                and (
                    (is_ce and spot and spot <= float(t["invalidation_level"]))
                    or (is_pe and spot and spot >= float(t["invalidation_level"]))
                )
            ):
                inval_level = float(t["invalidation_level"])
                exit_reason = f"STRUCTURAL INVALIDATION: Spot ({spot:.1f}) breached invalidation level ({inval_level:.1f}). Cutting trade early to protect capital."

            elif known_floor > 0 and last_bid <= known_floor:
                ai_sl = float(t.get("ai_stop_price") or 0)
                if ai_sl > 0 and last_bid <= ai_sl:
                    exit_reason = (
                        f"AI STOP LOSS: Option bid ({last_bid:.2f}) breached AI stop level ({ai_sl:.2f})"
                    )
                else:
                    exit_reason = (
                        f"PERSISTED TRAILING FLOOR: Bid ({last_bid:.2f}) breached floor ({known_floor:.2f})"
                    )

            # 1. Stop Loss Safeguard
            elif loss_pct >= initial_stop_pct:
                exit_reason = (
                    f"INITIAL STOP: Option fell {loss_pct:.1f}% (hit configured {initial_stop_pct}% stop)"
                )

            # 2. Profit Target Cap
            elif target_enabled and gain_pct >= target_pct:
                exit_reason = (
                    f"PROFIT TARGET: Option gained {gain_pct:.1f}% (hit configured {target_pct}% target)"
                )

            # 3. Stopwatch Timer Exit (Reinstated 6-minute / 360s timer for Legacy Scalper)
            elif max_hold_seconds and hold_sec >= max_hold_seconds:
                exit_reason = f"MAX HOLD TIME: Position held for {int(hold_sec)}s (exceeded {max_hold_seconds}s stopwatch timer)"

            # Session policy takes precedence over the generic +15% runner.
            elif session_stop is not None:
                trigger = max(known_floor, session_stop)
                if last_bid <= trigger:
                    exit_reason = f"{session_label}: Bid ({last_bid:.2f}) hit stop ({trigger:.2f}) at +{peak_gain_pct:.1f}% peak"
                else:
                    self.ratchet_stops(t, trigger)

            # 4. Dynamic Trailing Runner outside session-specific windows.
            elif not session_window and enable_runner_trailing and peak_gain_pct + 1e-9 >= runner_activation_pct:
                trail_stop = max(known_floor, runner_trigger(entry_price, peak_bid, exit_cfg))

                if last_bid <= trail_stop:
                    exit_reason = f"DYNAMIC TRAILING RATCHET: Bid ({last_bid:.2f}) hit ratchet stop ({trail_stop:.2f}), locked +{gain_pct:.1f}% profit"
                elif ema9_armed and is_ce and spot and ema9 and spot < (ema9 - ema9_trailing_buffer):
                    exit_reason = f"TRAILING STOP (5m EMA9): Spot ({spot:.1f}) broke below 5m EMA9 ({ema9:.1f}), locking in +{gain_pct:.1f}% gain"
                elif ema9_armed and is_pe and spot and ema9 and spot > (ema9 + ema9_trailing_buffer):
                    exit_reason = f"TRAILING STOP (5m EMA9): Spot ({spot:.1f}) crossed above 5m EMA9 ({ema9:.1f}), locking in +{gain_pct:.1f}% gain"
                else:
                    self.ratchet_stops(t, trail_stop)

            # 4b. AI Morning Micro-Trailing (Protects morning first trade in 09:15-09:45 window once peak reaches +10%)
            elif not session_window and is_morning_eligible and peak_gain_pct + 1e-9 >= morning_activation_pct:
                pullback_pct = exit_cfg.get("trail_pullback_pct", exit_cfg.get("peak_pullback_pct", 10.0))
                morning_floor = entry_price * (1.0 + morning_floor_pct / 100.0)
                morning_trailing = peak_bid * (1.0 - pullback_pct / 100.0)
                morning_trigger = round_tick(max(known_floor, morning_floor, morning_trailing))
                if last_bid <= morning_trigger:
                    exit_reason = (
                        f"AI MORNING MICRO-TRAIL: Bid ({last_bid:.2f}) hit trailing stop ({morning_trigger:.2f}), "
                        f"locked +{gain_pct:.1f}% profit (activated at +{peak_gain_pct:.1f}% peak gain in {morning_trail_start}-{morning_trail_end})"
                    )
                else:
                    self.ratchet_stops(t, morning_trigger)

            # 4c. AI Late-Day Micro-Trailing (Protects +4% gains after 14:00 against afternoon theta decay)
            elif (
                not session_window and enable_micro_trail and now_time >= micro_trail_time and peak_gain_pct >= micro_activation_pct
            ):
                micro_floor_trigger = round_tick(entry_price * (1.0 + micro_floor_pct / 100.0))
                micro_floor_limit = round_tick(micro_floor_trigger * 0.98)
                if last_bid <= micro_floor_trigger:
                    exit_reason = (
                        f"AI LATE-DAY MICRO-TRAIL: Bid ({last_bid:.2f}) hit floor ({micro_floor_trigger:.2f})"
                    )
                else:
                    self.ratchet_stops(t, micro_floor_trigger)

            # 5. Structural Stops (Only active if runner trailing is not active and structural stops enabled)
            # Session ratchets never suppress the configured structural safety checks.
            if exit_reason is None and enable_structural_stops and (
                session_window or not (
                    (enable_runner_trailing and peak_gain_pct + 1e-9 >= runner_activation_pct)
                    or (is_morning_eligible and peak_gain_pct + 1e-9 >= morning_activation_pct)
                    or (enable_micro_trail and now_time >= micro_trail_time and peak_gain_pct >= micro_activation_pct)
                )
            ):
                if is_ce:
                    if vwap_armed and vwap and spot and spot < (vwap - vwap_stop_buffer):
                        exit_reason = f"STRUCTURAL STOP: Spot ({spot:.1f}) broke below Session VWAP ({vwap:.1f}) by >{vwap_stop_buffer:.1f} pts"
                    elif ema20_armed and ema20_stop and spot and ema20 and ema9 and (spot < ema20) and (ema9 < ema20):
                        exit_reason = (
                            f"TREND STOP: Spot ({spot:.1f}) below 5m EMA20 ({ema20:.1f}) & EMA9 bear cross"
                        )
                elif is_pe:
                    if vwap_armed and vwap and spot and spot > (vwap + vwap_stop_buffer):
                        exit_reason = f"STRUCTURAL STOP: Spot ({spot:.1f}) rallied above Session VWAP ({vwap:.1f}) by >{vwap_stop_buffer:.1f} pts"
                    elif ema20_armed and ema20_stop and spot and ema20 and ema9 and (spot > ema20) and (ema9 > ema20):
                        exit_reason = (
                            f"TREND STOP: Spot ({spot:.1f}) above 5m EMA20 ({ema20:.1f}) & EMA9 bull cross"
                        )

            if exit_reason:
                exit_res = self.exit_trade(trade_id, exit_reason, limit_price=last_bid)
                if exit_res.get("status") != "CLOSED":
                    logger.warning(
                        f"⚠️ Trade {trade_id} exit remains pending; retaining position for reconciliation."
                    )
                    remaining_open.append(t)
            else:
                remaining_open.append(t)

        return remaining_open
