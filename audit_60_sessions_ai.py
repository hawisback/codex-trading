#!/usr/bin/env python3
"""
Comprehensive 60-Session Empirical Backtest Audit
Testing 3 Models across the last 60 live trading sessions (2026-07-23 to 2026-10-16):
Model 1: Production Baseline (Strategy 3 + AI Playbook Entry Gatekeeper)
Model 2: Strategy 3 + AI Playbook + Tier-1 Breakeven Shield (+12% Gain -> Lock Breakeven Floor)
Model 3: Strategy 3 + AI Playbook + Tier-1 Breakeven Shield + In-Flight AI Co-Pilot (Climax & V-Reversal)
"""

import sys
import os
import json
import sqlite3
from typing import List, Dict, Tuple
from dataclasses import dataclass
from backtest_engine import BacktestEngine, StrategyConfig, Trade, HISTORICAL_DB_PATH
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

def get_last_60_sessions() -> List[str]:
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
    return dates[-60:]

def run_custom_simulation(
    engine: BacktestEngine,
    cfg: StrategyConfig,
    consultant: AIConsultant,
    enable_tier1_shield: bool = False,
    enable_inflight_ai: bool = False
) -> List[Trade]:
    trades: List[Trade] = []
    current_trade = None
    last_exit_bar = -999
    spot_closes: List[float] = []
    spot_typicals: List[float] = []
    dte = engine.get_expiry_days()

    for idx, bar in enumerate(engine.spot_candles):
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]
        spot_closes.append(close)
        spot_typicals.append((high + low + close) / 3.0)

        session_vwap = sum(spot_typicals) / len(spot_typicals)
        bars_5m = [spot_closes[i] for i in range(4, len(spot_closes), 5)] or [close]
        ema9 = engine.calculate_ema(bars_5m, 9)
        ema20 = engine.calculate_ema(bars_5m, 20)
        rsi = engine.calculate_rsi(spot_closes, 14)

        recent_15m = engine.spot_candles[max(0, idx - 14): idx + 1]
        box_high = max(c["high"] for c in recent_15m)
        box_low = min(c["low"] for c in recent_15m)
        box_spread = box_high - box_low

        raw_time = bar["start_time"]
        time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

        # -------------------------------------------------------------
        # 1. Position Management
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

            hold_duration = idx - current_trade.entry_bar
            exit_reason = None
            exit_price = opt_close

            # A. Initial Hard Stop
            if opt_low <= current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0):
                exit_reason = "INITIAL_STOP"
                exit_price = round(current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0), 2)
            
            # B. Profit Target Cap
            elif opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                exit_reason = "PROFIT_TARGET"
                exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)

            # C. In-Flight AI Co-Pilot Checks (Fix #1)
            elif enable_inflight_ai and (
                # Climax Trap 8: Spot extended >= 75 pts from VWAP while in profit
                (abs(close - session_vwap) >= 75.0 and current_trade.peak_gain_pct >= 8.0)
            ):
                climax_floor = round(current_trade.entry_price * 1.01, 2)
                if opt_close <= climax_floor:
                    exit_reason = f"AI_INFLIGHT_CLIMAX_LOCK (Floor={climax_floor:.2f})"
                    exit_price = climax_floor

            elif enable_inflight_ai and (
                # V-Reversal Momentum Flips: Spot breaking counter-trend through 5m EMA9
                (not is_ce and close > (ema9 + 4.0) and rsi > 55.0) or
                (is_ce and close < (ema9 - 4.0) and rsi < 45.0)
            ):
                exit_reason = f"AI_INFLIGHT_V_REVERSAL_EXIT (Spot={close:.1f} vs EMA9={ema9:.1f})"
                exit_price = opt_close

            # D. Dynamic Runner Trailing & Progressive Floor Tiers (Fix #2: Tier-1 Breakeven Shield at 12%)
            elif cfg.enable_runner_trailing:
                activation_pct = 12.0 if enable_tier1_shield else cfg.runner_activation_pct
                if current_trade.peak_gain_pct >= activation_pct:
                    current_trade.runner_active = True
                    if current_trade.peak_gain_pct >= 40.0:
                        floor_pct = 30.0
                    elif current_trade.peak_gain_pct >= 30.0:
                        floor_pct = 20.0
                    elif current_trade.peak_gain_pct >= 20.0:
                        floor_pct = 10.0
                    elif enable_tier1_shield and current_trade.peak_gain_pct >= 12.0:
                        floor_pct = 1.0  # Tier-1 Breakeven Shield (+1% profit lock)
                    else:
                        floor_pct = 10.0

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

            # E. Late-Day Micro-Trail (post-14:00 IST = bar 285+)
            elif cfg.late_day_micro_trail_enabled and idx >= cfg.late_day_micro_trail_bar and current_trade.peak_gain_pct >= cfg.late_day_micro_trail_activation_pct:
                floor_price = current_trade.entry_price * (1.0 + cfg.late_day_micro_trail_floor_pct / 100.0)
                if opt_close <= floor_price:
                    exit_reason = f"AI_LATE_DAY_MICRO_TRAIL (Floor={floor_price:.2f})"
                    exit_price = round(floor_price, 2)

            # F. Structural Stops
            elif cfg.enable_structural_stops:
                if is_ce:
                    if close < (session_vwap - cfg.vwap_stop_buffer):
                        exit_reason = f"STRUCTURAL_VWAP_STOP ({close:.1f} < {session_vwap - cfg.vwap_stop_buffer:.1f})"
                        exit_price = opt_close
                    elif cfg.ema20_stop and (close < ema20) and (ema9 < ema20):
                        exit_reason = f"STRUCTURAL_EMA20_STOP ({close:.1f} < {ema20:.1f})"
                        exit_price = opt_close
                else:
                    if close > (session_vwap + cfg.vwap_stop_buffer):
                        exit_reason = f"STRUCTURAL_VWAP_STOP ({close:.1f} > {session_vwap + cfg.vwap_stop_buffer:.1f})"
                        exit_price = opt_close
                    elif cfg.ema20_stop and (close > ema20) and (ema9 > ema20):
                        exit_reason = f"STRUCTURAL_EMA20_STOP ({close:.1f} > {ema20:.1f})"
                        exit_price = opt_close

            # G. EOD Square-Off at 15:15 (bar 360)
            if idx >= 360 and not exit_reason:
                exit_reason = "EOD_SQUAREOFF"
                exit_price = opt_close

            if exit_reason:
                current_trade.close(idx, time_str, exit_price, exit_reason)
                trades.append(current_trade)
                current_trade = None
                last_exit_bar = idx

            continue

        # -------------------------------------------------------------
        # 2. Entry Evaluation with Mandatory AI Gatekeeper Consultation
        # -------------------------------------------------------------
        if idx < 10 or idx > 330:
            continue
        if len(trades) >= cfg.max_daily_entries:
            continue
        if (idx - last_exit_bar) < cfg.min_spacing_bars:
            continue

        if cfg.require_pullback:
            ce_pullback = (low <= ema9 + cfg.pullback_ema_tolerance_pts)
            pe_pullback = (high >= ema9 - cfg.pullback_ema_tolerance_pts)
        else:
            ce_pullback = True
            pe_pullback = True

        pe_reversal_veto = (rsi > 50.0) or (close > ema9) if cfg.prevent_v_reversal_counter_trades else False

        ce_signal = (close > ema9) and (ema9 > ema20) and (close > session_vwap) and ce_pullback
        pe_signal = (close < ema9) and (ema9 < ema20) and (close < session_vwap) and pe_pullback and not pe_reversal_veto

        direction = None
        if ce_signal:
            if cfg.enable_range_box_filter and box_spread < cfg.range_box_spread_min and close >= (box_high - 3.0):
                ce_signal = False
            if (close - ema9) > cfg.value_proximity_pts or rsi > 78.0:
                ce_signal = False
            if ce_signal:
                direction = "CE"

        elif pe_signal:
            if cfg.enable_range_box_filter and box_spread < cfg.range_box_spread_min and close <= (box_low + 3.0):
                pe_signal = False
            if (ema9 - close) > cfg.value_proximity_pts or rsi < 22.0:
                pe_signal = False
            if pe_signal:
                direction = "PE"

        if direction:
            sym, strike = engine.select_contract(close, direction, mode=cfg.strike_selection)
            _, _, opt_entry = engine.get_option_bar(sym, strike, direction, idx, bar)

            # MANDATORY RULE #1: Call AI Consultant with full 6-dimensional dossier
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
            verdict = consultant.evaluate(dossier)
            if not verdict.is_approved:
                # SUPREME AI VETO ENFORCED: Stand aside in cash
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
        return {"n": 0, "w": 0, "l": 0, "wr": 0.0, "gross": 0.0, "fee": 0.0, "net": 0.0, "pf": 0.0, "avg": 0.0}
    w = len([t for t in trades if t.pnl > 0])
    l = len([t for t in trades if t.pnl <= 0])
    gross = sum(t.pnl for t in trades)
    fee = n * 40.0
    net = gross - fee
    w_sum = sum(t.pnl for t in trades if t.pnl > 0)
    l_sum = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = (w_sum / l_sum) if l_sum > 0 else 999.0
    wr = (w / n * 100.0) if n else 0.0
    avg = net / n if n else 0.0
    return {
        "n": n, "w": w, "l": l, "wr": wr,
        "gross": gross, "fee": fee, "net": net,
        "pf": pf, "avg": avg
    }

def main():
    dates = get_last_60_sessions()
    print("=" * 105)
    print(f" 🏛️ AUDIT: 60 TRADING SESSIONS EMPIRICAL AI BACKTEST ({dates[0]} to {dates[-1]})")
    print("=" * 105)

    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
    consultant = AIConsultant(mode="playbook")

    m1_all_trades: List[Trade] = []
    m2_all_trades: List[Trade] = []
    m3_all_trades: List[Trade] = []

    print(f"{'Session Date':<12} | {'M1 Net PnL (Baseline)':<24} | {'M2 Net PnL (+12% Shield)':<26} | {'M3 Net PnL (InFlight AI)':<26} | {'Alpha M3 vs M1'}")
    print("-" * 105)

    for i, d in enumerate(dates, 1):
        eng = BacktestEngine(d)
        if not eng.spot_candles:
            continue

        # Model 1: Production Baseline
        t1 = run_custom_simulation(eng, s3_cfg, consultant, enable_tier1_shield=False, enable_inflight_ai=False)
        m1_all_trades.extend(t1)

        # Model 2: Tier-1 Breakeven Shield (+12%)
        t2 = run_custom_simulation(eng, s3_cfg, consultant, enable_tier1_shield=True, enable_inflight_ai=False)
        m2_all_trades.extend(t2)

        # Model 3: Tier-1 Breakeven Shield + In-Flight AI Co-Pilot
        t3 = run_custom_simulation(eng, s3_cfg, consultant, enable_tier1_shield=True, enable_inflight_ai=True)
        m3_all_trades.extend(t3)

        s1 = compute_metrics(t1)
        s2 = compute_metrics(t2)
        s3 = compute_metrics(t3)
        diff = s3["net"] - s1["net"]
        diff_str = f"₹{diff:+8.2f}" if diff != 0 else "    ₹0.00"

        if i % 5 == 0 or diff != 0 or d == "2026-10-16":
            print(f"{d:<12} | Tr={s1['n']} Net=₹{s1['net']:>8.2f} ({s1['wr']:4.0f}%) | Tr={s2['n']} Net=₹{s2['net']:>8.2f} ({s2['wr']:4.0f}%) | Tr={s3['n']} Net=₹{s3['net']:>8.2f} ({s3['wr']:4.0f}%) | {diff_str}")

    print("=" * 105)
    print(" 📊 FINAL 60-SESSION PERFORMANCE SCORECARD (Real Capital Model / 1 Lot / Friction Deducted)")
    print("=" * 105)

    st1 = compute_metrics(m1_all_trades)
    st2 = compute_metrics(m2_all_trades)
    st3 = compute_metrics(m3_all_trades)

    print(f"{'Performance Metric':<30} | {'Model 1 (Current Baseline)':<22} | {'Model 2 (Tier-1 Shield)':<22} | {'Model 3 (Shield + InFlight AI)':<24}")
    print("-" * 105)
    print(f"{'Total Trades Taken':<30} | {st1['n']:<22} | {st2['n']:<22} | {st3['n']:<24}")
    print(f"{'Winning Trades':<30} | {st1['w']:<22} | {st2['w']:<22} | {st3['w']:<24}")
    print(f"{'Losing Trades':<30} | {st1['l']:<22} | {st2['l']:<22} | {st3['l']:<24}")
    print(f"{'Win Rate %':<30} | {st1['wr']:<21.1f}% | {st2['wr']:<21.1f}% | {st3['wr']:<23.1f}%")
    print(f"{'Gross Profit':<30} | ₹{st1['gross']:<21,.2f} | ₹{st2['gross']:<21,.2f} | ₹{st3['gross']:<23,.2f}")
    print(f"{'Brokerage & Friction Fees':<30} | ₹{st1['fee']:<21,.2f} | ₹{st2['fee']:<21,.2f} | ₹{st3['fee']:<23,.2f}")
    print(f"{'REAL NET P&L':<30} | ₹{st1['net']:<21,.2f} | ₹{st2['net']:<21,.2f} | ₹{st3['net']:<23,.2f}")
    print(f"{'Profit Factor':<30} | {st1['pf']:<22.2f} | {st2['pf']:<22.2f} | {st3['pf']:<24.2f}")
    print(f"{'Average Net PnL per Trade':<30} | ₹{st1['avg']:<21,.2f} | ₹{st2['avg']:<21,.2f} | ₹{st3['avg']:<23,.2f}")
    print("-" * 105)
    print(f"NET PROFIT ENHANCEMENT (M3 vs M1): ₹{st3['net'] - st1['net']:>+12,.2f} ({(st3['net'] - st1['net'])/st1['net']*100:+.1f}%)")
    print(f"WIN RATE DELTA (M3 vs M1):         {st3['wr'] - st1['wr']:>+12.1f}%")
    print("=" * 105)

if __name__ == "__main__":
    main()
