#!/usr/bin/env python3
"""
30-Session Empirical Audit: Materializing Market Swings with AI Gatekeeper
Compares:
1. Baseline: Validated Strategy 3 + AI Playbook Gate (The benchmark)
2. Variant A: Strategy 3 + AI Climax Spring Protocol (Mean-Reversion with Structural Wick Stop)
3. Variant B: Strategy 3 + AI Failure-Flip Protocol (Trapped Liquidity Reversal on stop-out)
4. Variant C: Complete Institutional Suite (Strategy 3 + Climax Spring + Failure Flip)
"""

import math
import sqlite3
from typing import List, Dict, Tuple, Optional
from backtest_engine import BacktestEngine, StrategyConfig, HISTORICAL_DB_PATH, Trade, bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

def get_session_dates(count: int = 30) -> List[str]:
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT substr(start_time, 1, 10) "
        "FROM historical_candles "
        "WHERE instrument_id = 'INST-NIFTY-INDEX' AND start_time LIKE '%+00:00' "
        "ORDER BY 1"
    )
    dates = [r[0] for r in c.fetchall()]
    conn.close()
    return dates[-count:]

def run_simulation_with_swings(
    engine: BacktestEngine,
    cfg: StrategyConfig,
    consultant: AIConsultant,
    enable_climax_spring: bool = False,
    enable_failure_flip: bool = False
) -> List[Trade]:
    trades: List[Trade] = []
    current_trade: Optional[Trade] = None
    last_exit_bar = -999
    last_stopped_trade: Optional[Trade] = None
    last_stopped_bar = -999
    spot_closes: List[float] = []
    spot_typicals: List[float] = []
    rsi_history: List[float] = []
    dte = engine.get_expiry_days()
    day_open = engine.spot_candles[0]["open"]
    climax_wick_stop_spot: Optional[float] = None

    for idx, bar in enumerate(engine.spot_candles):
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]
        open_p = bar["open"]
        spot_closes.append(close)
        spot_typicals.append((high + low + close) / 3.0)

        session_vwap = sum(spot_typicals) / len(spot_typicals)
        bars_5m = [spot_closes[i] for i in range(4, len(spot_closes), 5)] or [close]
        ema9 = engine.calculate_ema(bars_5m, 9)
        ema20 = engine.calculate_ema(bars_5m, 20)
        rsi = engine.calculate_rsi(spot_closes, 14)
        rsi_history.append(rsi)

        recent_15m = engine.spot_candles[max(0, idx - 14): idx + 1]
        box_high = max(c["high"] for c in recent_15m)
        box_low = min(c["low"] for c in recent_15m)
        box_spread = box_high - box_low

        raw_time = bar["start_time"]
        time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

        # -------------------------------------------------------------
        # 1. Active Position Management
        # -------------------------------------------------------------
        if current_trade is not None:
            is_ce = (current_trade.direction == "CE")
            opt_high, opt_low, opt_close = engine.get_option_bar(
                current_trade.symbol, current_trade.strike, current_trade.direction, idx, bar
            )

            if opt_high > current_trade.peak_price:
                current_trade.peak_price = opt_high
                current_trade.peak_gain_pct = round(
                    ((opt_high - current_trade.entry_price) / current_trade.entry_price) * 100, 2
                )

            exit_reason = None
            exit_price = opt_close

            # A. Structural Wick Invalidation for Climax Spring trades
            if climax_wick_stop_spot is not None:
                if is_ce and low <= climax_wick_stop_spot:
                    exit_reason = f"CLIMAX_WICK_INVALIDATION ({low:.1f} <= {climax_wick_stop_spot:.1f})"
                    exit_price = opt_close
                elif not is_ce and high >= climax_wick_stop_spot:
                    exit_reason = f"CLIMAX_WICK_INVALIDATION ({high:.1f} >= {climax_wick_stop_spot:.1f})"
                    exit_price = opt_close

            # B. Initial Stop (-30%)
            if not exit_reason and opt_low <= current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0):
                exit_reason = "INITIAL_STOP"
                exit_price = round(current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0), 2)
            # C. Profit Target Cap (+50%)
            elif not exit_reason and opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                exit_reason = "PROFIT_TARGET"
                exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)
            # D. Dynamic Runner Trailing (+20% activation)
            elif not exit_reason and cfg.enable_runner_trailing and current_trade.peak_gain_pct >= cfg.runner_activation_pct:
                current_trade.runner_active = True
                floor_pct = 10.0
                if current_trade.peak_gain_pct >= 40.0:
                    floor_pct = 30.0
                elif current_trade.peak_gain_pct >= 30.0:
                    floor_pct = 20.0
                floor_price = current_trade.entry_price * (1.0 + floor_pct / 100.0)
                trail_stop = max(floor_price, current_trade.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0))

                if opt_close <= trail_stop:
                    exit_reason = f"TRAILING_DYNAMIC_RATCHET (Stop={trail_stop:.2f})"
                    exit_price = round(trail_stop, 2)
                elif is_ce and close < (ema9 - cfg.ema9_trailing_buffer):
                    exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} < {ema9:.1f})"
                    exit_price = opt_close
                elif not is_ce and close > (ema9 + cfg.ema9_trailing_buffer):
                    exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} > {ema9:.1f})"
                    exit_price = opt_close

            # E. Late-Day Micro-Trail (post 14:00)
            elif not exit_reason and cfg.late_day_micro_trail_enabled and idx >= cfg.late_day_micro_trail_bar and current_trade.peak_gain_pct >= cfg.late_day_micro_trail_activation_pct:
                floor_price = current_trade.entry_price * (1.0 + cfg.late_day_micro_trail_floor_pct / 100.0)
                if opt_close <= floor_price:
                    exit_reason = f"AI_LATE_DAY_MICRO_TRAIL (Floor={floor_price:.2f})"
                    exit_price = round(floor_price, 2)

            # F. EOD Square-off
            if idx >= 360 and not exit_reason:
                exit_reason = "EOD_SQUAREOFF"
                exit_price = opt_close

            if exit_reason:
                current_trade.close(idx, time_str, exit_price, exit_reason)
                trades.append(current_trade)
                last_exit_bar = idx
                if "INITIAL_STOP" in exit_reason or "CLIMAX_WICK" in exit_reason or "STRUCTURAL" in exit_reason:
                    last_stopped_trade = current_trade
                    last_stopped_bar = idx
                current_trade = None
                climax_wick_stop_spot = None

            continue

        # -------------------------------------------------------------
        # 2. Entry Signal Discovery
        # -------------------------------------------------------------
        if idx < 10 or idx > 330:
            continue
        if len(trades) >= cfg.max_daily_entries:
            continue

        direction = None
        setup_type = "STANDARD_PULLBACK"
        potential_wick_stop = None

        # -------------------------------------------------------------
        # 2A. TRIGGER #1: CLIMAX SPRING REVERSAL (Wyckoff Exhaustion Reversal)
        # -------------------------------------------------------------
        if enable_climax_spring and idx <= 120:  # Morning discovery window (09:25 - 11:15 IST)
            recent_low = min(c['low'] for c in engine.spot_candles[max(0, idx - 2): idx + 1])
            recent_high = max(c['high'] for c in engine.spot_candles[max(0, idx - 2): idx + 1])
            recent_min_rsi = min(rsi_history[max(0, idx - 2): idx + 1])
            recent_max_rsi = max(rsi_history[max(0, idx - 2): idx + 1])
            delta_1m = close - open_p

            dist_open_ext = recent_low - day_open
            dist_vwap_ext = recent_low - session_vwap

            # Bullish Climax Spring (CE)
            if (dist_open_ext <= -75.0 or dist_vwap_ext <= -40.0) and recent_min_rsi <= 32.0 and delta_1m >= 18.0:
                direction = "CE"
                setup_type = "CLIMAX_SPRING_BOTTOM"
                potential_wick_stop = recent_low - 2.0

            # Bearish Climax Upthrust (PE)
            elif (recent_high - day_open >= 75.0 or recent_high - session_vwap >= 40.0) and recent_max_rsi >= 68.0 and delta_1m <= -18.0:
                direction = "PE"
                setup_type = "CLIMAX_SPRING_TOP"
                potential_wick_stop = recent_high + 2.0

        # -------------------------------------------------------------
        # 2B. TRIGGER #2: THE FAILURE FLIP (Trapped Liquidity Reversal)
        # -------------------------------------------------------------
        if not direction and enable_failure_flip and last_stopped_trade and (idx - last_stopped_bar) <= 12:
            is_dead_zone = (135 <= idx <= 240)
            if not is_dead_zone:
                if last_stopped_trade.direction == "PE" and close > (ema9 + 5.0) and rsi > 54.0 and (close > session_vwap):
                    direction = "CE"
                    setup_type = "FAILURE_FLIP_SHORT_SQUEEZE"
                    last_stopped_trade = None
                elif last_stopped_trade.direction == "CE" and close < (ema9 - 5.0) and rsi < 46.0 and (close < session_vwap):
                    direction = "PE"
                    setup_type = "FAILURE_FLIP_LONG_LIQUIDATION"
                    last_stopped_trade = None

        # -------------------------------------------------------------
        # 2C. STANDARD STRATEGY 3 PULLBACK SIGNAL
        # -------------------------------------------------------------
        if not direction and (idx - last_exit_bar) >= cfg.min_spacing_bars:
            ce_pullback = (low <= ema9 + cfg.pullback_ema_tolerance_pts)
            pe_pullback = (high >= ema9 - cfg.pullback_ema_tolerance_pts)
            ce_signal = (close > ema9) and (ema9 > ema20) and (close > session_vwap) and ce_pullback
            pe_signal = (close < ema9) and (ema9 < ema20) and (close < session_vwap) and pe_pullback

            if ce_signal:
                if cfg.enable_range_box_filter and box_spread < cfg.range_box_spread_min and close >= (box_high - 3.0):
                    ce_signal = False
                if (close - ema9) > cfg.value_proximity_pts or rsi > 78.0:
                    ce_signal = False
                if ce_signal:
                    direction = "CE"
                    setup_type = "INSTITUTIONAL_PULLBACK"
            elif pe_signal:
                if cfg.enable_range_box_filter and box_spread < cfg.range_box_spread_min and close <= (box_low + 3.0):
                    pe_signal = False
                if (ema9 - close) > cfg.value_proximity_pts or rsi < 22.0:
                    pe_signal = False
                if pe_signal:
                    direction = "PE"
                    setup_type = "INSTITUTIONAL_PULLBACK"

        # -------------------------------------------------------------
        # 2D. MANDATORY RULE #1: AI CONSULTANT EVALUATION
        # -------------------------------------------------------------
        if direction:
            sym, strike = engine.select_contract(close, direction, mode=cfg.strike_selection)
            _, _, opt_entry = engine.get_option_bar(sym, strike, direction, idx, bar)

            dossier = generate_market_dossier(
                target_date=engine.target_date,
                candles=engine.spot_candles,
                current_bar_idx=idx,
                direction=direction,
                symbol=sym,
                strike=strike,
                option_entry_price=opt_entry,
                trade_history=trades,
                days_to_expiry=dte,
                is_expiry_0dte=(dte <= 0.2)
            )

            # Special bypass for approved Climax Springs / Failure Flips
            if setup_type in ["CLIMAX_SPRING_BOTTOM", "CLIMAX_SPRING_TOP", "FAILURE_FLIP_SHORT_SQUEEZE", "FAILURE_FLIP_LONG_LIQUIDATION"]:
                dossier.is_directional_shift = True  # Recognized institutional reversal

            verdict = consultant.evaluate(dossier)
            if not verdict.is_approved:
                continue

            current_trade = Trade(
                trade_id=len(trades) + 1,
                symbol=sym,
                direction=direction,
                strike=strike,
                entry_bar=idx,
                entry_time=time_str,
                entry_price=opt_entry,
                peak_price=opt_entry,
                peak_gain_pct=0.0
            )
            current_trade.setup_type = setup_type
            climax_wick_stop_spot = potential_wick_stop

    if current_trade is not None:
        last_bar = engine.spot_candles[-1]
        _, _, last_opt = engine.get_option_bar(
            current_trade.symbol, current_trade.strike, current_trade.direction,
            len(engine.spot_candles) - 1, last_bar
        )
        current_trade.close(len(engine.spot_candles) - 1, last_bar["start_time"][11:19], last_opt, "EOD_SQUAREOFF")
        trades.append(current_trade)

    return trades

def compute_metrics(trades: List[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "w": 0, "l": 0, "wr": 0.0, "net_1l": 0.0, "net_2l": 0.0, "roi_2l": 0.0, "pf": 0.0}
    w = len([t for t in trades if t.pnl > 0])
    l = len([t for t in trades if t.pnl <= 0])
    wr = (w / n * 100.0) if n else 0.0
    fee_1l = n * 40.0
    fee_2l = n * 40.0
    net_1l = sum(t.pnl for t in trades) - fee_1l
    net_2l = sum(t.pnl * 2 for t in trades) - fee_2l
    roi_2l = (net_2l / 10000.0) * 100.0
    w_sum = sum(t.pnl for t in trades if t.pnl > 0)
    l_sum = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = (w_sum / l_sum) if l_sum > 0 else 999.0
    return {
        "n": n, "w": w, "l": l, "wr": wr,
        "net_1l": net_1l, "net_2l": net_2l, "roi_2l": roi_2l, "pf": pf
    }

def main():
    dates = get_session_dates(30)
    print("=" * 115)
    print(f" 🏛️ 30-SESSION FORENSIC AUDIT: AI SWING CAPTURE ({dates[0]} to {dates[-1]})")
    print("=" * 115)

    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
    consultant = AIConsultant(mode="playbook")

    m_base, m_climax, m_flip, m_suite = [], [], [], []

    for d in dates:
        eng = BacktestEngine(d)
        if not eng.spot_candles:
            continue

        # 1. Baseline Strategy 3
        t_base = run_simulation_with_swings(eng, s3_cfg, consultant, False, False)
        m_base.extend(t_base)

        # 2. Strategy 3 + Climax Spring
        t_climax = run_simulation_with_swings(eng, s3_cfg, consultant, True, False)
        m_climax.extend(t_climax)

        # 3. Strategy 3 + Failure Flip
        t_flip = run_simulation_with_swings(eng, s3_cfg, consultant, False, True)
        m_flip.extend(t_flip)

        # 4. Complete Suite (Both Enabled)
        t_suite = run_simulation_with_swings(eng, s3_cfg, consultant, True, True)
        m_suite.extend(t_suite)

    st_base = compute_metrics(m_base)
    st_climax = compute_metrics(m_climax)
    st_flip = compute_metrics(m_flip)
    st_suite = compute_metrics(m_suite)

    print(f"{'Performance Metric':<32} | {'Model 1 (Baseline)':<18} | {'+ Climax Spring':<18} | {'+ Failure Flip':<18} | {'Combined Suite':<18}")
    print("-" * 115)
    print(f"{'Total Trades Taken':<32} | {st_base['n']:<18} | {st_climax['n']:<18} | {st_flip['n']:<18} | {st_suite['n']:<18}")
    print(f"{'Winning Trades':<32} | {st_base['w']:<18} | {st_climax['w']:<18} | {st_flip['w']:<18} | {st_suite['w']:<18}")
    print(f"{'Losing Trades':<32} | {st_base['l']:<18} | {st_climax['l']:<18} | {st_flip['l']:<18} | {st_suite['l']:<18}")
    print(f"{'Win Rate %':<32} | {st_base['wr']:<17.1f}% | {st_climax['wr']:<17.1f}% | {st_flip['wr']:<17.1f}% | {st_suite['wr']:<17.1f}%")
    print(f"{'Net PnL (1 Lot / 65 Qty)':<32} | ₹{st_base['net_1l']:<17,.2f} | ₹{st_climax['net_1l']:<17,.2f} | ₹{st_flip['net_1l']:<17,.2f} | ₹{st_suite['net_1l']:<17,.2f}")
    print(f"{'Net PnL (2 Lots / ₹10k Margin)':<32} | ₹{st_base['net_2l']:<17,.2f} | ₹{st_climax['net_2l']:<17,.2f} | ₹{st_flip['net_2l']:<17,.2f} | ₹{st_suite['net_2l']:<17,.2f}")
    print(f"{'Net ROI % (₹10,000 Margin)':<32} | {st_base['roi_2l']:>+16.1f}% | {st_climax['roi_2l']:>+16.1f}% | {st_flip['roi_2l']:>+16.1f}% | {st_suite['roi_2l']:>+16.1f}%")
    print(f"{'Profit Factor':<32} | {st_base['pf']:<18.2f} | {st_climax['pf']:<18.2f} | {st_flip['pf']:<18.2f} | {st_suite['pf']:<18.2f}")
    print("=" * 115)

    print("\n🔍 Specific Climax Spring Trades Executed across 30 Sessions:")
    climax_trades = [t for t in m_climax if getattr(t, "setup_type", "") in ["CLIMAX_SPRING_BOTTOM", "CLIMAX_SPRING_TOP"]]
    print(f"  Total Climax Spring Trades: {len(climax_trades)}")
    for t in climax_trades:
        print(f"    - {t.symbol} {t.direction} ({getattr(t, 'setup_type', '')}) @ {t.entry_time} | Entry: ₹{t.entry_price:.2f} Exit: ₹{t.exit_price:.2f} | PnL (1L): ₹{t.pnl:+.2f} | PnL (2L): ₹{t.pnl*2:+.2f} | Reason: {t.exit_reason}")

    print("\n🔍 Specific Analysis for Today's Session (2026-10-16):")
    t_today_base = [t for t in m_base if t.entry_time and '2026-10-16' in str(t.symbol)]
    t_today_climax = [t for t in m_climax if t.entry_time and '2026-10-16' in str(t.symbol)]
    print(f"  Baseline Trades Today: {len(t_today_base)}")
    for t in t_today_base:
        print(f"    - {t.symbol} {t.direction} @ {t.entry_time} | Entry: ₹{t.entry_price:.2f} Exit: ₹{t.exit_price:.2f} | PnL (2L): ₹{t.pnl*2:+.2f} | Reason: {t.exit_reason}")
    print(f"  Climax Spring Trades Today: {len(t_today_climax)}")
    for t in t_today_climax:
        print(f"    - {t.symbol} {t.direction} @ {t.entry_time} | Entry: ₹{t.entry_price:.2f} Exit: ₹{t.exit_price:.2f} | PnL (2L): ₹{t.pnl*2:+.2f} | Reason: {t.exit_reason}")

if __name__ == "__main__":
    main()
