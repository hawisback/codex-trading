import os
import sys
import json
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, ".")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from backtest_engine import BacktestEngine, StrategyConfig, bsm_price, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict

@dataclass
class SimulatedTrade:
    trade_id: int
    symbol: str
    direction: str
    strike: int
    entry_bar: int
    entry_time: str
    entry_price: float
    setup_type: str  # "PULLBACK_VALUE" or "WATERFALL_BREAKDOWN"
    quantity: int = 65
    exit_bar: Optional[int] = None
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    peak_price: float = 0.0
    peak_gain_pct: float = 0.0
    ai_verdict: Optional[AIVerdict] = None

class RobustAICopilotEngine:
    def __init__(self, target_date: str, max_capital: float = 9749.0):
        self.target_date = target_date
        self.max_capital = max_capital
        self.engine = BacktestEngine(target_date=target_date)
        self.spot_candles = self.engine.spot_candles
        self.options_data = self.engine.options_data
        self.is_synthetic_options = self.engine.is_synthetic_options
        self.ai_consultant = AIConsultant(mode="playbook")

    def get_expiry_days(self) -> float:
        target_d = datetime.strptime(self.target_date, "%Y-%m-%d").date()
        if target_d.weekday() <= 1:
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
        else:
            expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
        delta_days = (expiry_d - target_d).days
        return max(0.1, float(delta_days))

    def get_option_bar(self, sym: str, strike: int, direction: str, bar_idx: int, spot_bar: dict) -> Tuple[float, float, float]:
        if not self.is_synthetic_options and sym in self.options_data and bar_idx < len(self.options_data[sym]):
            c = self.options_data[sym][bar_idx]
            return float(c["high"]), float(c["low"]), float(c["close"])
        
        # Fallback to calibrated BSM
        days_base = self.get_expiry_days()
        days_remaining = max(0.001, days_base - (bar_idx / 375.0) * 0.25)
        is_call = (direction == "CE")
        c_close = bsm_price(spot_bar["close"], strike, days_remaining, is_call=is_call)
        c_high = bsm_price(spot_bar["high"] if is_call else spot_bar["low"], strike, days_remaining, is_call=is_call)
        c_low = bsm_price(spot_bar["low"] if is_call else spot_bar["high"], strike, days_remaining, is_call=is_call)
        return max(c_close, c_high), min(c_close, c_low), c_close

    def select_affordable_strike(self, spot: float, direction: str, bar_idx: int, spot_bar: dict) -> Tuple[str, int, float]:
        max_premium = self.max_capital / 65.0  # ~₹149.98
        atm_strike = int(round(spot / 50.0)) * 50
        
        if direction == "PE":
            itm_strike = atm_strike + 50
            itm_sym = f"NIFTY_{self.target_date}_{itm_strike}_PE"
            _, _, itm_close = self.get_option_bar(itm_sym, itm_strike, direction, bar_idx, spot_bar)
            if itm_close <= max_premium:
                return itm_sym, itm_strike, itm_close
            atm_sym = f"NIFTY_{self.target_date}_{atm_strike}_PE"
            _, _, atm_close = self.get_option_bar(atm_sym, atm_strike, direction, bar_idx, spot_bar)
            return atm_sym, atm_strike, atm_close
        else:
            itm_strike = atm_strike - 50
            itm_sym = f"NIFTY_{self.target_date}_{itm_strike}_CE"
            _, _, itm_close = self.get_option_bar(itm_sym, itm_strike, direction, bar_idx, spot_bar)
            if itm_close <= max_premium:
                return itm_sym, itm_strike, itm_close
            atm_sym = f"NIFTY_{self.target_date}_{atm_strike}_CE"
            _, _, atm_close = self.get_option_bar(atm_sym, atm_strike, direction, bar_idx, spot_bar)
            return atm_sym, atm_strike, atm_close

    def run_simulation(self, enable_waterfall_override: bool = True, enable_micro_trail: bool = True) -> List[SimulatedTrade]:
        trades: List[SimulatedTrade] = []
        current_trade: Optional[SimulatedTrade] = None
        last_exit_bar = -999
        spot_closes: List[float] = []
        spot_typicals: List[float] = []

        for idx, bar in enumerate(self.spot_candles):
            close = bar["close"]
            high = bar["high"]
            low = bar["low"]
            spot_closes.append(close)
            spot_typicals.append((high + low + close) / 3.0)

            session_vwap = round(sum(spot_typicals) / len(spot_typicals), 2)
            bars_5m = [spot_closes[i] for i in range(4, len(spot_closes), 5)] or [close]
            ema9 = BacktestEngine.calculate_ema(bars_5m, 9)
            ema20 = BacktestEngine.calculate_ema(bars_5m, 20)

            # Prior 15-minute range box (prior bars)
            recent_15m = self.spot_candles[max(0, idx - 15): idx]
            if recent_15m:
                box_high = max(c["high"] for c in recent_15m)
                box_low = min(c["low"] for c in recent_15m)
                box_spread = box_high - box_low
            else:
                box_high = close
                box_low = close
                box_spread = 0.0

            raw_time = bar["start_time"]
            time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

            # ---------------------------------------------------------
            # 1. MANAGE OPEN TRADE
            # ---------------------------------------------------------
            if current_trade is not None:
                opt_high, opt_low, opt_close = self.get_option_bar(
                    current_trade.symbol, current_trade.strike, current_trade.direction, idx, bar
                )
                if opt_high > current_trade.peak_price:
                    current_trade.peak_price = opt_high
                    current_trade.peak_gain_pct = round(((opt_high - current_trade.entry_price) / current_trade.entry_price) * 100, 2)

                exit_reason = None
                exit_price = opt_close

                # Stop Loss (-30%)
                if opt_low <= current_trade.entry_price * 0.70:
                    exit_reason = "INITIAL_STOP"
                    exit_price = round(current_trade.entry_price * 0.70, 2)
                # Profit Target (+50%)
                elif opt_high >= current_trade.entry_price * 1.50:
                    exit_reason = "PROFIT_TARGET"
                    exit_price = round(current_trade.entry_price * 1.50, 2)
                # Late-Day Micro-Trail: ONLY applies to trades ENTERED late in the day (after 14:00 IST = Bar 285+)
                elif enable_micro_trail and current_trade.entry_bar >= 285 and idx >= 285 and current_trade.peak_gain_pct >= 4.0:
                    floor_price = round(current_trade.entry_price * 1.01, 2)
                    if opt_low <= floor_price:
                        exit_reason = "AI_LATE_DAY_MICRO_TRAIL"
                        exit_price = floor_price
                # Runner Peak Trailing (>= 15% peak gain)
                elif current_trade.peak_gain_pct >= 15.0:
                    trail_stop = current_trade.peak_price * 0.90
                    breakeven_floor = current_trade.entry_price * 1.02
                    effective_stop = max(trail_stop, breakeven_floor)
                    if opt_low <= effective_stop:
                        exit_reason = "RUNNER_PEAK_TRAIL"
                        exit_price = round(effective_stop, 2)
                # EOD Square-Off (15:20 IST = Bar 365)
                elif idx >= 365:
                    exit_reason = "EOD_SQUAREOFF"
                    exit_price = opt_close

                if exit_reason:
                    current_trade.exit_bar = idx
                    current_trade.exit_time = time_str
                    current_trade.exit_price = exit_price
                    current_trade.exit_reason = exit_reason
                    current_trade.pnl = round((exit_price - current_trade.entry_price) * current_trade.quantity, 2)
                    current_trade.pnl_pct = round(((exit_price - current_trade.entry_price) / current_trade.entry_price) * 100, 2)
                    trades.append(current_trade)
                    current_trade = None
                    last_exit_bar = idx
                continue

            # ---------------------------------------------------------
            # 2. EVALUATE ENTRY OPPORTUNITIES
            # ---------------------------------------------------------
            if idx - last_exit_bar < 5 or idx < 15 or idx >= 360:
                continue

            # VWAP blender check
            vwap_window = 60
            past_spots = spot_closes[max(0, idx - vwap_window): idx + 1]
            past_typicals = spot_typicals[max(0, idx - vwap_window): idx + 1]
            vwap_crosses = 0
            for i in range(1, len(past_spots)):
                if (past_spots[i] >= past_typicals[i] and past_spots[i-1] < past_typicals[i-1]) or \
                   (past_spots[i] <= past_typicals[i] and past_spots[i-1] > past_typicals[i-1]):
                    vwap_crosses += 1
            is_vwap_blender = (vwap_crosses >= 5 and abs(close - session_vwap) < 15.0)

            is_bear_trend = (close < ema9 < ema20 < session_vwap)
            is_bull_trend = (close > ema9 > ema20 > session_vwap)

            setup_found = None
            direction = None

            # Path 1: Qualified High-Velocity Waterfall Breakdown Override
            # Only active after morning discovery (Bar 75 = 10:30 IST) to prevent morning opening traps
            # Requires genuine structural breakdown: 15m Box broken, > 18 pts from VWAP, and EMA separation
            if enable_waterfall_override and idx >= 75 and not is_vwap_blender:
                ema_spread = abs(ema9 - ema20)
                # Breakdown
                if close < box_low and (session_vwap - close) >= 18.0 and box_spread >= 24.0 and ema_spread >= 4.0:
                    setup_found = "WATERFALL_BREAKDOWN"
                    direction = "PE"
                # Breakout
                elif close > box_high and (close - session_vwap) >= 18.0 and box_spread >= 24.0 and ema_spread >= 4.0:
                    setup_found = "WATERFALL_BREAKDOWN"
                    direction = "CE"

            # Path 2: Standard Strategy 3 Pullback to 5m EMA9
            if not setup_found and not is_vwap_blender and box_spread >= 28.0:
                if is_bear_trend:
                    if abs(high - ema9) <= 4.0 and (session_vwap - close) < 80.0:
                        setup_found = "PULLBACK_VALUE"
                        direction = "PE"
                elif is_bull_trend:
                    if abs(low - ema9) <= 4.0 and (close - session_vwap) < 80.0:
                        setup_found = "PULLBACK_VALUE"
                        direction = "CE"

            if setup_found and direction:
                # Climax veto check (>80 pts from VWAP)
                if abs(close - session_vwap) >= 80.0:
                    continue

                sym, strike, entry_p = self.select_affordable_strike(close, direction, idx, bar)

                # Dossier validation
                dossier = generate_market_dossier(
                    target_date=self.target_date,
                    candles=self.spot_candles[:idx + 1],
                    current_bar_idx=idx,
                    direction=direction,
                    symbol=sym,
                    strike=strike,
                    option_entry_price=entry_p,
                    trade_history=trades,
                    days_to_expiry=self.get_expiry_days(),
                    is_expiry_0dte=(self.get_expiry_days() <= 0.2)
                )

                verdict = self.ai_consultant.evaluate(dossier)
                if setup_found == "WATERFALL_BREAKDOWN":
                    if verdict.trap_detected == "Trap 1: The VWAP Blender" and abs(close - session_vwap) >= 14.0:
                        verdict.is_approved = True
                        verdict.confidence_score = 90
                        verdict.reasoning = "Waterfall Breakdown: 15m Range Box breakdown with high velocity."

                if verdict.is_approved:
                    current_trade = SimulatedTrade(
                        trade_id=len(trades) + 1,
                        symbol=sym,
                        direction=direction,
                        strike=strike,
                        entry_bar=idx,
                        entry_time=time_str,
                        entry_price=entry_p,
                        setup_type=setup_found,
                        peak_price=entry_p,
                        ai_verdict=verdict
                    )

        return trades

def run_multi_day_audit():
    print("=" * 105)
    print(" MULTI-WEEK AUDIT: AUGUST LAST WEEK & SEPTEMBER FIRST WEEK")
    print(" Comparing Baseline Strategy 3 vs. Full AI Co-Pilot Across 15 Trading Days")
    print("=" * 105)

    week_groups = {
        "Week 1: August Final Full Week (Aug 24 - Aug 28, 2026)": [
            "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28"
        ],
        "Week 2: August/September Transition Week (Aug 31 - Sep 04, 2026)": [
            "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"
        ],
        "Week 3: September First Full Week (Sep 07 - Sep 11, 2026)": [
            "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"
        ],
    }

    grand_base_trades = []
    grand_copilot_trades = []

    for week_title, dates in week_groups.items():
        print(f"\n>>> {week_title}")
        print(f"{'Date':<12} | {'Base Tr':<8} | {'Base Net':<12} | {'Co-Pilot Tr':<12} | {'Co-Pilot Net':<14} | {'Alpha Delta':<12}")
        print("-" * 80)
        
        w_base_trades = []
        w_copilot_trades = []

        for d in dates:
            try:
                engine = RobustAICopilotEngine(target_date=d, max_capital=9749.0)
                base = engine.run_simulation(enable_waterfall_override=False, enable_micro_trail=False)
                copilot = engine.run_simulation(enable_waterfall_override=True, enable_micro_trail=True)

                base_net = sum(t.pnl for t in base) - (len(base) * 40.0)
                copilot_net = sum(t.pnl for t in copilot) - (len(copilot) * 40.0)
                delta = copilot_net - base_net

                w_base_trades.extend(base)
                w_copilot_trades.extend(copilot)
                grand_base_trades.extend(base)
                grand_copilot_trades.extend(copilot)

                print(f"{d:<12} | {len(base):<8} | Rs {base_net:+9,.2f} | {len(copilot):<12} | Rs {copilot_net:+11,.2f} | Rs {delta:+9,.2f}")
            except Exception as e:
                print(f"{d:<12} | ERROR: {e}")

        w_b_net = sum(t.pnl for t in w_base_trades) - len(w_base_trades)*40.0
        w_c_net = sum(t.pnl for t in w_copilot_trades) - len(w_copilot_trades)*40.0
        print("-" * 80)
        print(f"WEEK TOTAL   | {len(w_base_trades):<8} | Rs {w_b_net:+9,.2f} | {len(w_copilot_trades):<12} | Rs {w_c_net:+11,.2f} | Rs {w_c_net - w_b_net:+9,.2f}")

    # Grand Summary
    print("\n" + "=" * 105)
    print(" GRAND 15-DAY AUDIT COMPARISON SUMMARY (AUG 24 - SEP 11, 2026)")
    print("=" * 105)
    
    b_count = len(grand_base_trades)
    b_wins = sum(1 for t in grand_base_trades if t.pnl > 0)
    b_win_pct = (b_wins / b_count * 100) if b_count > 0 else 0.0
    b_gross = sum(t.pnl for t in grand_base_trades)
    b_net = b_gross - (b_count * 40.0)

    c_count = len(grand_copilot_trades)
    c_wins = sum(1 for t in grand_copilot_trades if t.pnl > 0)
    c_win_pct = (c_wins / c_count * 100) if c_count > 0 else 0.0
    c_gross = sum(t.pnl for t in grand_copilot_trades)
    c_net = c_gross - (c_count * 40.0)

    print(f"{'Strategy Configuration':<45} | {'Trades':<8} | {'Win Rate':<10} | {'Gross PnL':<14} | {'Net PnL (1 Lot)':<16}")
    print("-" * 105)
    print(f"{'1. Baseline Strategy 3 (Standard Pullback Only)':<45} | {b_count:<8} | {b_win_pct:<9.1f}% | Rs {b_gross:+11,.2f} | Rs {b_net:+13,.2f}")
    print(f"{'2. Full AI Co-Pilot (Waterfall + Micro-Trail)':<45} | {c_count:<8} | {c_win_pct:<9.1f}% | Rs {c_gross:+11,.2f} | Rs {c_net:+13,.2f}")
    print("=" * 105)
    print(f"NET ALPHA GENERATED BY AI CO-PILOT OVER BASELINE: Rs {c_net - b_net:+,.2f} on 1 Lot (~Rs 10,000 Capital)!")

if __name__ == "__main__":
    run_multi_day_audit()
