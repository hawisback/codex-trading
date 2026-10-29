#!/usr/bin/env python3
"""
Test Trailing Stop Loss Systematic Ladder Models
"""

import math
from typing import List, Optional
from backtest_engine import BacktestEngine, StrategyConfig, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

def simulate_custom_exits(
    engine: BacktestEngine,
    cfg: StrategyConfig,
    initial_stop_pct: float = 30.0,
    trailing_type: str = "current", # "current" or "stepped_ladder"
    ladder_start_pct: float = 20.0,
    ladder_step_pct: float = 10.0,
    ladder_lock_pct: float = 10.0
) -> List[Trade]:
    """
    Simulate Strategy 3 with customizable systematic trailing ladder.
    """
    trades: List[Trade] = []
    current_trade: Optional[Trade] = None
    last_exit_bar = -999
    spot_closes: List[float] = []
    spot_typicals: List[float] = []

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

        raw_time = bar["start_time"]
        time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

        # Position Management
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

            # A. Initial Stop Loss
            if opt_low <= current_trade.entry_price * (1.0 - initial_stop_pct / 100.0):
                exit_reason = f"INITIAL_STOP (-{initial_stop_pct}%)"
                exit_price = round(current_trade.entry_price * (1.0 - initial_stop_pct / 100.0), 2)
                
            # B. Profit Target (+50%)
            elif opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                exit_reason = "PROFIT_TARGET (+50%)"
                exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)

            # C. Trailing Stop Logic
            elif trailing_type == "stepped_ladder":
                # Systematic Ladder:
                # e.g., Peak >= 40% -> floor = +30%
                #       Peak >= 30% -> floor = +20%
                #       Peak >= 20% -> floor = +10%
                #       Peak >= 15% -> floor = +2% (breakeven)
                floor_pct = None
                if current_trade.peak_gain_pct >= 40.0:
                    floor_pct = 30.0
                elif current_trade.peak_gain_pct >= 30.0:
                    floor_pct = 20.0
                elif current_trade.peak_gain_pct >= 20.0:
                    floor_pct = 10.0
                elif current_trade.peak_gain_pct >= 15.0:
                    floor_pct = 2.0

                if floor_pct is not None:
                    current_trade.runner_active = True
                    floor_price = current_trade.entry_price * (1.0 + floor_pct / 100.0)
                    if opt_close <= floor_price:
                        exit_reason = f"TRAILING_LADDER (+{floor_pct}%)"
                        exit_price = round(floor_price, 2)
                    elif is_ce and close < (ema9 - cfg.ema9_trailing_buffer):
                        exit_reason = f"TRAILING_EMA9 ({close:.1f} < {ema9:.1f})"
                        exit_price = opt_close
                    elif not is_ce and close > (ema9 + cfg.ema9_trailing_buffer):
                        exit_reason = f"TRAILING_EMA9 ({close:.1f} > {ema9:.1f})"
                        exit_price = opt_close
                    elif opt_close <= current_trade.peak_price * 0.90:
                        exit_reason = "TRAILING_PEAK_PULLBACK (-10%)"
                        exit_price = opt_close

                # Structural stop if trailing not yet activated
                elif cfg.enable_structural_stops:
                    if is_ce:
                        if close < (session_vwap - cfg.vwap_stop_buffer):
                            exit_reason = "STRUCTURAL_VWAP_STOP"
                            exit_price = opt_close
                        elif cfg.ema20_stop and (close < ema20) and (ema9 < ema20):
                            exit_reason = "STRUCTURAL_EMA20_STOP"
                            exit_price = opt_close
                    else:
                        if close > (session_vwap + cfg.vwap_stop_buffer):
                            exit_reason = "STRUCTURAL_VWAP_STOP"
                            exit_price = opt_close
                        elif cfg.ema20_stop and (close > ema20) and (ema9 > ema20):
                            exit_reason = "STRUCTURAL_EMA20_STOP"
                            exit_price = opt_close

            elif trailing_type == "current":
                # Current Strategy 3 Logic
                if cfg.enable_structural_stops:
                    if is_ce:
                        if close < (session_vwap - cfg.vwap_stop_buffer):
                            exit_reason = "STRUCTURAL_VWAP_STOP"
                            exit_price = opt_close
                        elif cfg.ema20_stop and (close < ema20) and (ema9 < ema20):
                            exit_reason = "STRUCTURAL_EMA20_STOP"
                            exit_price = opt_close
                        elif cfg.enable_runner_trailing and current_trade.peak_gain_pct >= cfg.runner_activation_pct:
                            current_trade.runner_active = True
                            if cfg.lock_breakeven_on_runner and opt_close <= current_trade.entry_price * 1.02:
                                exit_reason = "TRAILING_BREAKEVEN_FLOOR (+2%)"
                                exit_price = opt_close
                            elif close < (ema9 - cfg.ema9_trailing_buffer):
                                exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} < {ema9:.1f})"
                                exit_price = opt_close
                            elif opt_close <= current_trade.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0):
                                exit_reason = f"TRAILING_PEAK_PULLBACK (-{cfg.peak_pullback_pct}%)"
                                exit_price = opt_close
                    else:
                        if close > (session_vwap + cfg.vwap_stop_buffer):
                            exit_reason = "STRUCTURAL_VWAP_STOP"
                            exit_price = opt_close
                        elif cfg.ema20_stop and (close > ema20) and (ema9 > ema20):
                            exit_reason = "STRUCTURAL_EMA20_STOP"
                            exit_price = opt_close
                        elif cfg.enable_runner_trailing and current_trade.peak_gain_pct >= cfg.runner_activation_pct:
                            current_trade.runner_active = True
                            if cfg.lock_breakeven_on_runner and opt_close <= current_trade.entry_price * 1.02:
                                exit_reason = "TRAILING_BREAKEVEN_FLOOR (+2%)"
                                exit_price = opt_close
                            elif close > (ema9 + cfg.ema9_trailing_buffer):
                                exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} > {ema9:.1f})"
                                exit_price = opt_close
                            elif opt_close <= current_trade.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0):
                                exit_reason = f"TRAILING_PEAK_PULLBACK (-{cfg.peak_pullback_pct}%)"
                                exit_price = opt_close

            # EOD Square-Off
            if idx >= 360 and not exit_reason:
                exit_reason = "EOD_SQUAREOFF"
                exit_price = opt_close

            if exit_reason:
                current_trade.close(idx, time_str, exit_price, exit_reason)
                trades.append(current_trade)
                current_trade = None
                last_exit_bar = idx

        # Entry Evaluation
        else:
            if idx < 15 or idx < (last_exit_bar + cfg.min_spacing_bars):
                continue

            # Standard Pullback rules
            bars_15m = spot_closes[max(0, len(spot_closes) - 15):]
            range_15m = max(bars_15m) - min(bars_15m)
            if cfg.enable_range_box_filter and range_15m < cfg.range_box_spread_min:
                continue

            call_pullback = abs(close - ema9) <= cfg.pullback_ema_tolerance_pts
            call_signal = (close > session_vwap) and (ema9 > ema20) and (rsi > 50) and call_pullback
            if call_signal:
                sym, strike = engine.select_contract(close, "CE", cfg.strike_selection)
                _, _, opt_price = engine.get_option_bar(sym, strike, "CE", idx, bar)
                current_trade = Trade(
                    trade_id=len(trades) + 1, symbol=sym, direction="CE", strike=strike,
                    entry_bar=idx, entry_time=time_str, entry_price=opt_price,
                    peak_price=opt_price, peak_gain_pct=0.0
                )
                continue

            put_pullback = abs(close - ema9) <= cfg.pullback_ema_tolerance_pts
            put_signal = (close < session_vwap) and (ema9 < ema20) and (rsi < 50) and put_pullback
            if cfg.prevent_v_reversal_counter_trades and rsi > 46:
                put_signal = False

            if put_signal:
                sym, strike = engine.select_contract(close, "PE", cfg.strike_selection)
                _, _, opt_price = engine.get_option_bar(sym, strike, "PE", idx, bar)
                current_trade = Trade(
                    trade_id=len(trades) + 1, symbol=sym, direction="PE", strike=strike,
                    entry_bar=idx, entry_time=time_str, entry_price=opt_price,
                    peak_price=opt_price, peak_gain_pct=0.0
                )
                continue

    return trades

if __name__ == "__main__":
    pass

from inspect_oct05 import Oct5RefinedConsultant

def run_ladder_matrix():
    consultant = Oct5RefinedConsultant(mode="playbook")
    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")

    models = [
        ("Model 1: Baseline (InitStop 30%, PeakPullback 10%, Act 15%)", 30.0, "current"),
        ("Model 2: Tight Initial Stop (InitStop 20%, PeakPullback 10%, Act 15%)", 20.0, "current"),
        ("Model 3: Systematic Ladder (InitStop 30%, StepLock +10%/+20%/+30%)", 30.0, "stepped_ladder"),
        ("Model 4: Tight Stop + Ladder (InitStop 20%, StepLock +10%/+20%/+30%)", 20.0, "stepped_ladder"),
    ]

    def evaluate_dates(dates_list, stop_val, trail_type):
        approved_trades = []
        for d in dates_list:
            eng = BacktestEngine(d)
            if not eng.spot_candles:
                continue
            trades = simulate_custom_exits(eng, s3_cfg, initial_stop_pct=stop_val, trailing_type=trail_type)
            dte = eng.get_expiry_days()
            for i, t in enumerate(trades, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(
                    target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
                    direction=t.direction, symbol=t.symbol, strike=t.strike,
                    option_entry_price=t.entry_price, trade_history=trades[:i-1],
                    days_to_expiry=dte, is_expiry_0dte=(dte <= 0.2)
                )
                if consultant.evaluate(dos).is_approved:
                    approved_trades.append(t)
        n = len(approved_trades)
        w = len([t for t in approved_trades if t.pnl > 0])
        gross = sum(t.pnl for t in approved_trades)
        fee = n * 40.0
        net = gross - fee
        wr = (w / n * 100) if n else 0.0
        return {"n": n, "w": w, "wr": wr, "gross": gross, "fee": fee, "net": net}

    # 1. October 5, 2026
    print("=" * 95)
    print(" 🔬 MODEL EVALUATION ON OCTOBER 5, 2026")
    print("=" * 95)
    for name, s_val, t_type in models:
        res = evaluate_dates(["2026-10-05"], s_val, t_type)
        print(f"{name:<60} | Net: Rs {res['net']:>8.2f} (WR: {res['wr']:4.1f}%, {res['n']} trds)")

    # 2. Week 10 (Oct 05 - 09, 2026)
    print("\n" + "=" * 95)
    print(" 🔬 MODEL EVALUATION ON WEEK 10 (OCT 05 - 09, 2026 - 5 SESSIONS)")
    print("=" * 95)
    week10_dates = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    for name, s_val, t_type in models:
        res = evaluate_dates(week10_dates, s_val, t_type)
        print(f"{name:<60} | Net: Rs {res['net']:>8.2f} (WR: {res['wr']:4.1f}%, {res['n']} trds)")

    # 3. June 2026 (15 Sessions)
    print("\n" + "=" * 95)
    print(" 🔬 MODEL EVALUATION ON JUNE 2026 (15 SESSIONS)")
    print("=" * 95)
    june_dates = [
        "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
        "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12",
        "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"
    ]
    for name, s_val, t_type in models:
        res = evaluate_dates(june_dates, s_val, t_type)
        print(f"{name:<60} | Net: Rs {res['net']:>8.2f} (WR: {res['wr']:4.1f}%, {res['n']} trds)")

if __name__ == "__main__":
    run_ladder_matrix()
