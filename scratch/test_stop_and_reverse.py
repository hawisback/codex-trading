import os
import sys

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import math
from backtest_engine import BacktestEngine, StrategyConfig, Trade

dates_w1_3 = [
    ("2026-08-31", "Mon Aug 31"),
    ("2026-09-01", "Tue Sep 01 (0DTE)"),
    ("2026-09-02", "Wed Sep 02"),
    ("2026-09-03", "Thu Sep 03"),
    ("2026-09-04", "Fri Sep 04"),
    ("2026-09-07", "Mon Sep 07"),
    ("2026-09-08", "Tue Sep 08 (0DTE)"),
    ("2026-09-09", "Wed Sep 09"),
    ("2026-09-10", "Thu Sep 10"),
    ("2026-09-11", "Fri Sep 11"),
    ("2026-09-15", "Tue Sep 15 (0DTE)"),
    ("2026-09-16", "Wed Sep 16"),
    ("2026-09-17", "Thu Sep 17"),
    ("2026-09-18", "Fri Sep 18"),
]

s3_cfg = StrategyConfig.load_from_config("institutional_pullback")

class StopAndReverseEngine(BacktestEngine):
    def run_simulation(self, cfg: StrategyConfig, enable_reverse: bool = True):
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

            recent_15m = self.spot_candles[max(0, idx - 14): idx + 1]
            box_high = max(c["high"] for c in recent_15m)
            box_low = min(c["low"] for c in recent_15m)
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
                    exit_reason = "INITIAL_STOP"
                    exit_price = round(current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0), 2)
                # B. Profit Target Cap
                elif opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                    exit_reason = "PROFIT_TARGET"
                    exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)
                # C. Active Incremental Runner Trailing Check
                elif cfg.enable_runner_trailing and current_trade.peak_gain_pct >= cfg.runner_activation_pct:
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

                # D. Structural Stops if Trailing Not Yet Activated
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

                # E. EOD Square-Off
                if idx >= 360 and not exit_reason:
                    exit_reason = "EOD_SQUAREOFF"
                    exit_price = opt_close

                if exit_reason:
                    current_trade.close(idx, time_str, exit_price, exit_reason)
                    trades.append(current_trade)
                    prev_dir = current_trade.direction
                    prev_reason = exit_reason
                    current_trade = None
                    last_exit_bar = idx

                    # STOP & REVERSE LOGIC:
                    # If stopped out by STRUCTURAL_VWAP_STOP, market just had a major regime breach across VWAP.
                    # Immediately flip position to the opposite direction!
                    if enable_reverse and "STRUCTURAL_VWAP_STOP" in prev_reason and idx < 330:
                        rev_dir = "PE" if prev_dir == "CE" else "CE"
                        rev_sym, rev_strike = self.select_contract(close, rev_dir, cfg.strike_selection)
                        _, _, rev_entry_price = self.get_option_bar(rev_sym, rev_strike, rev_dir, idx, bar)
                        current_trade = Trade(
                            trade_id=len(trades) + 1,
                            symbol=rev_sym,
                            direction=rev_dir,
                            strike=rev_strike,
                            entry_bar=idx,
                            entry_time=time_str,
                            entry_price=rev_entry_price,
                            peak_price=rev_entry_price,
                            quantity=cfg.quantity if hasattr(cfg, "quantity") else 65
                        )
                    continue

            # Standard Entry Evaluation
            if idx < 10 or idx > 330:
                continue
            if len(trades) >= cfg.max_daily_entries:
                continue
            if (idx - last_exit_bar) < cfg.min_spacing_bars:
                continue

            # Pullback condition
            if cfg.require_pullback:
                ce_pullback = (low <= ema9 + cfg.pullback_ema_tolerance_pts)
                pe_pullback = (high >= ema9 - cfg.pullback_ema_tolerance_pts)
            else:
                ce_pullback = True
                pe_pullback = True

            # Momentum / V-Reversal Sanity
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
                sym, strike = self.select_contract(close, direction, cfg.strike_selection)
                _, _, entry_price = self.get_option_bar(sym, strike, direction, idx, bar)
                current_trade = Trade(
                    trade_id=len(trades) + 1,
                    symbol=sym,
                    direction=direction,
                    strike=strike,
                    entry_bar=idx,
                    entry_time=time_str,
                    entry_price=entry_price,
                    peak_price=entry_price,
                    quantity=65
                )

        return trades

def calc_stats(tr):
    n = len(tr)
    w = len([t for t in tr if t.pnl > 0])
    gross = sum(t.pnl for t in tr)
    fee = n * 40.0
    net = gross - fee
    wr = (w / n * 100) if n else 0.0
    return {"n": n, "w": w, "wr": wr, "gross": gross, "fee": fee, "net": net}

print("=" * 115)
print("TESTING STOP & REVERSE ON STRUCTURAL VWAP STOPS: WEEKS 1 - 3 (AUG 31 - SEP 18)")
print("=" * 115)
print(f"{'Date':<15} | {'Base Trades':<12} {'Base Net':<12} | {'Reverse Trades':<15} {'Reverse Net':<14} | {'Difference'}")
print("-" * 115)

all_base = []
all_rev = []

for d, label in dates_w1_3:
    eng = StopAndReverseEngine(d)
    if not eng.spot_candles:
        continue
    tr_base = eng.run_simulation(s3_cfg, enable_reverse=False)
    tr_rev = eng.run_simulation(s3_cfg, enable_reverse=True)
    all_base.extend(tr_base)
    all_rev.extend(tr_rev)
    
    st_b = calc_stats(tr_base)
    st_r = calc_stats(tr_rev)
    diff = st_r['net'] - st_b['net']
    print(f"{label:<15} | {st_b['n']:>4} tr  Rs {st_b['net']:>8.2f} | {st_r['n']:>5} tr  Rs {st_r['net']:>9.2f} | Rs {diff:>+9.2f}")

tot_b = calc_stats(all_base)
tot_r = calc_stats(all_rev)

print("=" * 115)
print(f"CONSOLIDATED BASELINE (NO REVERSE): Trades={tot_b['n']} WinRate={tot_b['wr']:.1f}% Net PnL = Rs {tot_b['net']:>10.2f}")
print(f"CONSOLIDATED WITH STOP & REVERSE:   Trades={tot_r['n']} WinRate={tot_r['wr']:.1f}% Net PnL = Rs {tot_r['net']:>10.2f}")
print(f"NET PROFIT IMPROVEMENT (ALPHA):     Rs {tot_r['net'] - tot_b['net']:>+10.2f}")
print("=" * 115)
