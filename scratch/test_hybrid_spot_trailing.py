import json
import sys
import copy
import sqlite3
from datetime import datetime, timedelta

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")

from backtest_engine import BacktestEngine, StrategyConfig, Trade, calculate_metrics, print_trades_table, print_scorecard
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

consultant = AIConsultant(mode="playbook")

class HybridSpotTrailingEngine(BacktestEngine):
    def __init__(self, target_date="2026-10-15", spot_trail_mode="ema20", spot_buffer=4.0):
        super().__init__(target_date)
        self.spot_trail_mode = spot_trail_mode # "ema20", "ema9_buffer", "spot_peak_pts", "session_vwap"
        self.spot_buffer = spot_buffer

    def run_simulation(self, cfg: StrategyConfig):
        trades = []
        current_trade = None
        last_exit_bar = -999
        spot_closes = []
        spot_typicals = []
        spot_highs = []
        spot_lows = []

        for idx, bar in enumerate(self.spot_candles):
            close = bar["close"]
            high = bar["high"]
            low = bar["low"]
            spot_closes.append(close)
            spot_highs.append(high)
            spot_lows.append(low)
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

                # Track spot peak during the trade
                if not hasattr(current_trade, "spot_peak"):
                    current_trade.spot_peak = high if is_ce else low
                else:
                    if is_ce:
                        current_trade.spot_peak = max(current_trade.spot_peak, high)
                    else:
                        current_trade.spot_peak = min(current_trade.spot_peak, low)

                hold_duration = idx - current_trade.entry_bar
                exit_reason = None
                exit_price = opt_close

                # A. Initial Hard Stop on Option Premium (-30%)
                if opt_low <= current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0):
                    exit_reason = f"INITIAL_OPTION_STOP (-{cfg.initial_stop_pct:.0f}%)"
                    exit_price = round(current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0), 2)

                # B. Profit Target Cap (+50%)
                elif opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                    exit_reason = f"PROFIT_TARGET (+{cfg.target_pct:.0f}%)"
                    exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)

                # C. Max Hold Duration
                elif hold_duration >= cfg.max_hold_minutes:
                    exit_reason = f"MAX_HOLD_TIME ({cfg.max_hold_minutes}m)"
                    exit_price = opt_close

                # D. HYBRID SPOT-BASED TRAILING (Activates when Option Gain >= runner_activation_pct)
                elif current_trade.peak_gain_pct >= cfg.runner_activation_pct:
                    current_trade.runner_active = True

                    # Breakeven safety floor: Never let runner go into a loss (Floor @ +2%)
                    be_floor = current_trade.entry_price * 1.02
                    if opt_close <= be_floor:
                        exit_reason = f"HYBRID_BREAKEVEN_FLOOR (+2.0%)"
                        exit_price = round(be_floor, 2)

                    # Spot-Based Trailing Conditions (Does NOT stop out on option premium noise!)
                    elif self.spot_trail_mode == "ema20":
                        # Exit when Spot closes on wrong side of 5m EMA20
                        if is_ce and close < ema20:
                            exit_reason = f"SPOT_5M_EMA20_CROSS ({close:.1f} < {ema20:.1f})"
                            exit_price = opt_close
                        elif not is_ce and close > ema20:
                            exit_reason = f"SPOT_5M_EMA20_CROSS ({close:.1f} > {ema20:.1f})"
                            exit_price = opt_close

                    elif self.spot_trail_mode == "ema9_buffer":
                        # Exit when Spot breaks 5m EMA9 by buffer
                        if is_ce and close < (ema9 - self.spot_buffer):
                            exit_reason = f"SPOT_5M_EMA9_BUFFER ({close:.1f} < {ema9 - self.spot_buffer:.1f})"
                            exit_price = opt_close
                        elif not is_ce and close > (ema9 + self.spot_buffer):
                            exit_reason = f"SPOT_5M_EMA9_BUFFER ({close:.1f} > {ema9 + self.spot_buffer:.1f})"
                            exit_price = opt_close

                    elif self.spot_trail_mode == "spot_peak_pts":
                        # Exit when Spot drops X points from its high
                        spot_drop = current_trade.spot_peak - close if is_ce else close - current_trade.spot_peak
                        if spot_drop >= self.spot_buffer: # e.g. 25 points
                            exit_reason = f"SPOT_PEAK_PULLBACK (-{spot_drop:.1f} pts from {current_trade.spot_peak:.1f})"
                            exit_price = opt_close

                    elif self.spot_trail_mode == "session_vwap":
                        if is_ce and close < (session_vwap - 5.0):
                            exit_reason = f"SPOT_VWAP_BREAK ({close:.1f} < {session_vwap:.1f})"
                            exit_price = opt_close
                        elif not is_ce and close > (session_vwap + 5.0):
                            exit_reason = f"SPOT_VWAP_BREAK ({close:.1f} > {session_vwap:.1f})"
                            exit_price = opt_close

                # D2. Late-Day Micro-Trail (After 14:00 IST / bar 285+)
                elif cfg.late_day_micro_trail_enabled and idx >= cfg.late_day_micro_trail_bar and current_trade.peak_gain_pct >= cfg.late_day_micro_trail_activation_pct:
                    floor_price = current_trade.entry_price * (1.0 + cfg.late_day_micro_trail_floor_pct / 100.0)
                    if opt_close <= floor_price:
                        exit_reason = f"AI_LATE_DAY_MICRO_TRAIL (Floor={floor_price:.2f})"
                        exit_price = round(floor_price, 2)

                # E. Pre-Activation Structural Stops
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

            # Signal Entry Logic
            if idx < 10 or idx > 330:
                continue
            if (idx - last_exit_bar) < cfg.min_spacing_bars:
                continue

            if cfg.require_pullback:
                ce_pullback = (low <= (ema9 + cfg.pullback_ema_tolerance_pts))
                pe_pullback = (high >= (ema9 - cfg.pullback_ema_tolerance_pts))
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
                sym, strike = self.select_contract(close, direction, mode=cfg.strike_selection)
                opt_h, opt_l, opt_entry = self.get_option_bar(sym, strike, direction, idx, bar)
                trade_id = len(trades) + 1
                current_trade = Trade(
                    trade_id=trade_id, symbol=sym, direction=direction, strike=strike,
                    entry_bar=idx, entry_time=time_str, entry_price=opt_entry,
                    peak_price=opt_entry, peak_gain_pct=0.0
                )
                current_trade.spot_peak = high if direction == "CE" else low

        if current_trade is not None:
            last_bar = self.spot_candles[-1]
            _, _, last_opt = self.get_option_bar(
                current_trade.symbol, current_trade.strike, current_trade.direction,
                len(self.spot_candles) - 1, last_bar
            )
            current_trade.close(len(self.spot_candles) - 1, last_bar["start_time"][11:19], last_opt, "EOD_SQUAREOFF")
            trades.append(current_trade)

        return trades

def evaluate_models_today():
    date = "2026-10-15"
    cfg3 = StrategyConfig.load_from_config("institutional_pullback")
    cfg2 = StrategyConfig.load_from_config("structural_runner")

    models = [
        ("Current Strategy 3 Baseline (10% Option Ratchet)", BacktestEngine(date), cfg3),
        ("Hybrid Model A: Spot 5m EMA20 Cross (Breakeven Floor + Spot EMA20)", HybridSpotTrailingEngine(date, "ema20"), cfg3),
        ("Hybrid Model B: Spot 5m EMA9 Buffer (Spot < EMA9 - 6.0 pts)", HybridSpotTrailingEngine(date, "ema9_buffer", 6.0), cfg3),
        ("Hybrid Model C: Spot Peak Pullback (Spot drops 28 pts from peak)", HybridSpotTrailingEngine(date, "spot_peak_pts", 28.0), cfg3),
        ("Hybrid Model D: Strategy 2 Structural Runner with Hybrid Spot EMA20", HybridSpotTrailingEngine(date, "ema20"), cfg2),
    ]

    print("=" * 115)
    print(f" HYBRID SPOT-BASED TRAILING BACKTEST REPLAY: {date}")
    print("=" * 115)

    for name, eng, cfg in models:
        trades = eng.run_simulation(cfg)
        
        # Filter with AI Playbook
        approved = []
        for t in trades:
            idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
            dossier = generate_market_dossier(
                target_date=date, candles=eng.spot_candles, current_bar_idx=idx,
                direction=t.direction, symbol=t.symbol, strike=t.strike,
                option_entry_price=t.entry_price, trade_history=approved,
                days_to_expiry=eng.get_expiry_days(), is_expiry_0dte=False
            )
            v = consultant.evaluate(dossier)
            if v.is_approved:
                approved.append(t)
        
        m = calculate_metrics(approved)
        print(f"\n>>> {name}")
        print_trades_table(approved)
        print(f"Total Trades: {m['total_trades']} | Win Rate: {m['win_rate']:.1f}% | Gross P&L: ₹{m['net_pnl']:+,.2f} | Net (Post-Fee): ₹{m['net_pnl'] - m['total_trades']*40:+,.2f} | Max Win: ₹{m['max_win']:+,.2f}")

if __name__ == "__main__":
    evaluate_models_today()
