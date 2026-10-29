#!/usr/bin/env python3
"""
Test Trailing Stop Loss Variations on Native BacktestEngine
"""

import copy
from backtest_engine import BacktestEngine, StrategyConfig, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

consultant = AIConsultant(mode="playbook")
base_cfg = StrategyConfig.load_from_config("institutional_pullback")

class SteppedLadderEngine(BacktestEngine):
    """
    Extends BacktestEngine to support Systematic Stepped Ladder Trailing:
    - Peak >= 20% -> Lock floor at +10%
    - Peak >= 30% -> Lock floor at +20%
    - Peak >= 40% -> Lock floor at +30%
    - Target: +50%
    """
    def run_simulation(self, cfg: StrategyConfig):
        trades = []
        current_trade = None
        last_exit_bar = -999
        spot_closes = []
        spot_typicals = []

        for idx, bar in enumerate(self.spot_candles):
            close = bar["close"]
            high = bar["high"]
            low = bar["low"]
            spot_closes.append(close)
            spot_typicals.append((high + low + close) / 3.0)

            session_vwap = sum(spot_typicals) / len(spot_typicals)
            bars_5m = [spot_closes[i] for i in range(4, len(spot_closes), 5)] or [close]
            ema9 = self.calculate_ema(bars_5m, 9)
            ema20 = self.calculate_ema(bars_5m, 20)
            rsi = self.calculate_rsi(spot_closes, 14)

            # Box calculation
            lookback_box = max(0, len(spot_closes) - 15)
            box_slice = spot_closes[lookback_box:]
            box_high = max(box_slice)
            box_low = min(box_slice)
            box_spread = box_high - box_low

            raw_time = bar["start_time"]
            time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

            # Position Management
            if current_trade is not None:
                is_ce = (current_trade.direction == "CE")
                opt_high, opt_low, opt_close = self.get_option_bar(
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

                # A. Initial Stop
                if opt_low <= current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0):
                    exit_reason = f"INITIAL_STOP (-{cfg.initial_stop_pct:.0f}%)"
                    exit_price = round(current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0), 2)
                    
                # B. Profit Target Cap (+50%)
                elif opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                    exit_reason = "PROFIT_TARGET (+50%)"
                    exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)

                # C. Systematic Stepped Ladder Trailing
                else:
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
                        
                        # Stop out if price violates locked floor
                        if opt_close <= floor_price:
                            exit_reason = f"LADDER_TRAIL_FLOOR (+{floor_pct:.0f}%)"
                            exit_price = round(floor_price, 2)
                        # EMA9 trailing runner
                        elif is_ce and close < (ema9 - cfg.ema9_trailing_buffer):
                            exit_reason = f"TRAILING_EMA9 ({close:.1f} < {ema9:.1f})"
                            exit_price = opt_close
                        elif not is_ce and close > (ema9 + cfg.ema9_trailing_buffer):
                            exit_reason = f"TRAILING_EMA9 ({close:.1f} > {ema9:.1f})"
                            exit_price = opt_close
                        # Peak pullback
                        elif opt_close <= current_trade.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0):
                            exit_reason = f"TRAILING_PEAK_PULLBACK (-{cfg.peak_pullback_pct:.0f}%)"
                            exit_price = opt_close

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

                # EOD Square-off
                if idx >= 360 and not exit_reason:
                    exit_reason = "EOD_SQUAREOFF"
                    exit_price = opt_close

                if exit_reason:
                    current_trade.close(idx, time_str, exit_price, exit_reason)
                    trades.append(current_trade)
                    current_trade = None
                    last_exit_bar = idx
                continue

            # Standard Entry Evaluation
            if idx < 10 or idx > 330:
                continue
            if len(trades) >= cfg.max_daily_entries:
                continue
            if (idx - last_exit_bar) < cfg.min_spacing_bars:
                continue

            ce_pullback = (low <= ema9 + cfg.pullback_ema_tolerance_pts)
            pe_pullback = (high >= ema9 - cfg.pullback_ema_tolerance_pts)

            if cfg.prevent_v_reversal_counter_trades:
                pe_reversal_veto = (rsi > 50.0) or (close > ema9)
            else:
                pe_reversal_veto = False

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
                sym, strike = self.select_contract(close, direction, mode=cfg.strike_selection)
                opt_h, opt_l, opt_entry = self.get_option_bar(sym, strike, direction, idx, bar)
                trade_id = len(trades) + 1
                current_trade = Trade(
                    trade_id=trade_id, symbol=sym, direction=direction, strike=strike,
                    entry_bar=idx, entry_time=time_str, entry_price=opt_entry,
                    peak_price=opt_entry, peak_gain_pct=0.0
                )

        if current_trade is not None:
            last_bar = self.spot_candles[-1]
            _, _, last_opt = self.get_option_bar(
                current_trade.symbol, current_trade.strike, current_trade.direction,
                len(self.spot_candles) - 1, last_bar
            )
            current_trade.close(len(self.spot_candles) - 1, last_bar["start_time"][11:19], last_opt, "EOD_SQUAREOFF")
            trades.append(current_trade)

        return trades


def run_benchmark(dates_list, cfg, engine_cls=BacktestEngine):
    all_trades = []
    for d in dates_list:
        eng = engine_cls(d)
        if not eng.spot_candles:
            continue
        trades = eng.run_simulation(cfg)
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
                all_trades.append(t)
    n = len(all_trades)
    w = len([t for t in all_trades if t.pnl > 0])
    gross = sum(t.pnl for t in all_trades)
    fee = n * 40.0
    net = gross - fee
    wr = (w / n * 100) if n else 0.0
    return {"n": n, "w": w, "wr": wr, "gross": gross, "fee": fee, "net": net, "trades": all_trades}



def run_comparative_audit():
    c_base = copy.deepcopy(base_cfg)

    c_act20 = copy.deepcopy(base_cfg)
    c_act20.runner_activation_pct = 20.0

    c_stop20 = copy.deepcopy(base_cfg)
    c_stop20.initial_stop_pct = 20.0

    c_stop20_act20 = copy.deepcopy(base_cfg)
    c_stop20_act20.initial_stop_pct = 20.0
    c_stop20_act20.runner_activation_pct = 20.0

    c_ladder30 = copy.deepcopy(base_cfg)
    c_ladder30.initial_stop_pct = 30.0

    c_ladder20 = copy.deepcopy(base_cfg)
    c_ladder20.initial_stop_pct = 20.0

    test_configs = [
        ("Config 1: Current Baseline (InitStop 30%, RunnerAct 15%, TrailPeak 10%)", c_base, BacktestEngine),
        ("Config 2: Runner Activation at 20% (InitStop 30%, RunnerAct 20%, TrailPeak 10%)", c_act20, BacktestEngine),
        ("Config 3: Tight Initial Stop at 20% (InitStop 20%, RunnerAct 15%, TrailPeak 10%)", c_stop20, BacktestEngine),
        ("Config 4: Tight Stop 20% + RunnerAct 20%", c_stop20_act20, BacktestEngine),
        ("Config 5: Systematic Stepped Ladder (+10%/+20%/+30% floors, InitStop 30%)", c_ladder30, SteppedLadderEngine),
        ("Config 6: Systematic Stepped Ladder (+10%/+20%/+30% floors, InitStop 20%)", c_ladder20, SteppedLadderEngine),
    ]

    # --- Test 1: Monday, October 5, 2026 ---
    print("=" * 105)
    print(" 🔎 COMPARATIVE AUDIT ON MONDAY, OCTOBER 5, 2026")
    print("=" * 105)
    for label, cfg, eng_cls in test_configs:
        res = run_benchmark(["2026-10-05"], cfg, eng_cls)
        print(f"{label:<72} | Net: Rs {res['net']:>8.2f} (WR: {res['wr']:4.1f}%, {res['n']} trds)")
        if "Config 1" in label or "Config 5" in label:
            for t in res["trades"]:
                print(f"    * {t.direction} {t.entry_time[:5]} -> {t.exit_time[:5]} | PnL: Rs {t.pnl:>8.2f} | Peak: {t.peak_gain_pct:>5.1f}% | Exit: {t.exit_reason}")

    # --- Test 2: Full Week 10 (October 5 - 9, 2026) ---
    print("\n" + "=" * 105)
    print(" 🔎 COMPARATIVE AUDIT ON WEEK 10 (OCTOBER 05 - 09, 2026 - 5 SESSIONS)")
    print("=" * 105)
    week10_dates = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]
    for label, cfg, eng_cls in test_configs:
        res = run_benchmark(week10_dates, cfg, eng_cls)
        print(f"{label:<72} | Net: Rs {res['net']:>8.2f} (WR: {res['wr']:4.1f}%, {res['n']} trds)")

    # --- Test 3: June 2026 (15 Sessions) ---
    print("\n" + "=" * 105)
    print(" 🔎 COMPARATIVE AUDIT ON JUNE 2026 (15 SESSIONS)")
    print("=" * 105)
    june_dates = [
        "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
        "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12",
        "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"
    ]
    for label, cfg, eng_cls in test_configs:
        res = run_benchmark(june_dates, cfg, eng_cls)
        print(f"{label:<72} | Net: Rs {res['net']:>8.2f} (WR: {res['wr']:4.1f}%, {res['n']} trds)")

    # --- Test 4: Full 50-Session Benchmark (July - October 2026) ---
    print("\n" + "=" * 105)
    print(" 🔎 COMPARATIVE AUDIT ON 50-SESSION BENCHMARK (JULY - OCTOBER 2026)")
    print("=" * 105)
    from audit_grand_10weeks import jul_aug_weeks, sep_oct_weeks
    all_50_dates = [d for w, dl in (jul_aug_weeks + sep_oct_weeks) for d in dl]
    for label, cfg, eng_cls in test_configs:
        res = run_benchmark(all_50_dates, cfg, eng_cls)
        print(f"{label:<72} | Net: Rs {res['net']:>8.2f} (WR: {res['wr']:4.1f}%, {res['n']} trds)")

if __name__ == "__main__":
    run_comparative_audit()
