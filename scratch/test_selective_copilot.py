import os
import sys
import json
import math
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Optional, Tuple

sys.path.insert(0, ".")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from backtest_engine import BacktestEngine, bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

@dataclass
class TradeResult:
    trade_id: int
    date: str
    symbol: str
    direction: str
    strike: int
    entry_bar: int
    entry_time: str
    entry_price: float
    setup_type: str
    quantity: int = 65
    exit_bar: Optional[int] = None
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: float = 0.0
    pnl_pct: float = 0.0
    peak_gain_pct: float = 0.0

class SelectiveCopilotEngine:
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
        return max(0.1, float((expiry_d - target_d).days))

    def get_option_bar(self, sym: str, strike: int, direction: str, bar_idx: int, spot_bar: dict) -> Tuple[float, float, float]:
        if not self.is_synthetic_options and sym in self.options_data and bar_idx < len(self.options_data[sym]):
            c = self.options_data[sym][bar_idx]
            return float(c["high"]), float(c["low"]), float(c["close"])
        
        days_base = self.get_expiry_days()
        days_remaining = max(0.001, days_base - (bar_idx / 375.0) * 0.25)
        is_call = (direction == "CE")
        c_close = bsm_price(spot_bar["close"], strike, days_remaining, is_call=is_call)
        c_high = bsm_price(spot_bar["high"] if is_call else spot_bar["low"], strike, days_remaining, is_call=is_call)
        c_low = bsm_price(spot_bar["low"] if is_call else spot_bar["high"], strike, days_remaining, is_call=is_call)
        return max(c_close, c_high), min(c_close, c_low), c_close

    def select_affordable_strike(self, spot: float, direction: str, bar_idx: int, spot_bar: dict) -> Tuple[str, int, float]:
        max_premium = self.max_capital / 65.0
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

    def run_simulation(self, mode: str = "baseline") -> List[TradeResult]:
        trades: List[TradeResult] = []
        current_trade: Optional[TradeResult] = None
        last_exit_bar = -999
        spot_closes: List[float] = []
        spot_typicals: List[float] = []

        day_open = self.spot_candles[0]["open"]

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
                if opt_high > current_trade.entry_price:
                    gain = round(((opt_high - current_trade.entry_price) / current_trade.entry_price) * 100, 2)
                    if gain > current_trade.peak_gain_pct:
                        current_trade.peak_gain_pct = gain

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

                # Late-Day Micro-Trail (ONLY for trades entered after 14:00 IST = Bar 285+)
                elif mode == "selective_copilot" and current_trade.entry_bar >= 285 and idx >= 285 and current_trade.peak_gain_pct >= 4.0:
                    floor_price = round(current_trade.entry_price * 1.01, 2)
                    if opt_low <= floor_price:
                        exit_reason = "AI_LATE_DAY_MICRO_TRAIL"
                        exit_price = floor_price

                # Runner Peak Trailing (>= 15% peak gain)
                elif current_trade.peak_gain_pct >= 15.0:
                    trail_stop = current_trade.entry_price * (1.0 + (current_trade.peak_gain_pct * 0.01) - 0.10)
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

            # Mode: Selective AI Co-Pilot
            # 1. Waterfall Exception: ONLY allowed in the afternoon (after 12:30 IST = Bar 195)
            # when market has dropped significantly (>0.4% from open) with strong EMA spread (>= 4.0 pts)
            if mode == "selective_copilot" and idx >= 195 and not is_vwap_blender:
                drop_from_open_pct = ((close - day_open) / day_open) * 100
                if drop_from_open_pct < -0.40 and close < box_low and (session_vwap - close) >= 18.0 and (ema20 - ema9) >= 4.0:
                    setup_found = "WATERFALL_BREAKDOWN"
                    direction = "PE"

            # 2. Strategy 3 Standard Pullback (Active in both modes)
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
                if abs(close - session_vwap) >= 80.0:
                    continue

                sym, strike, entry_p = self.select_affordable_strike(close, direction, idx, bar)

                dossier = generate_market_dossier(
                    target_date=self.target_date,
                    candles=self.spot_candles[:idx + 1],
                    current_bar_idx=idx,
                    direction=direction,
                    symbol=sym,
                    strike=strike,
                    option_entry_price=entry_p,
                    trade_history=[],
                    days_to_expiry=self.get_expiry_days(),
                    is_expiry_0dte=(self.get_expiry_days() <= 0.2)
                )

                verdict = self.ai_consultant.evaluate(dossier)
                if setup_found == "WATERFALL_BREAKDOWN":
                    if verdict.trap_detected == "Trap 1: The VWAP Blender" and abs(close - session_vwap) >= 15.0:
                        verdict.is_approved = True

                if verdict.is_approved:
                    current_trade = TradeResult(
                        trade_id=len(trades) + 1,
                        date=self.target_date,
                        symbol=sym,
                        direction=direction,
                        strike=strike,
                        entry_bar=idx,
                        entry_time=time_str,
                        entry_price=entry_p,
                        setup_type=setup_found
                    )

        return trades

def run_comprehensive_audit():
    all_dates = [
        # August Final Full Week
        "2026-08-24", "2026-08-25", "2026-08-26", "2026-08-27", "2026-08-28",
        # August/September Bridge Week
        "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
        # September First Full Week
        "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
        # Today (October 14, 2026)
        "2026-10-14"
    ]

    print("=" * 105)
    print(" 16-DAY FORENSIC AUDIT: BASELINE STRATEGY 3 vs. SELECTIVE AI CO-PILOT")
    print(" August Last Week + September First Week + Today (October 14, 2026)")
    print("=" * 105)

    base_results = []
    copilot_results = []

    print(f"{'Date':<12} | {'Day Focus':<18} | {'Base Tr':<8} | {'Base Net':<12} | {'Co-Pilot Tr':<12} | {'Co-Pilot Net':<14} | {'Delta':<10}")
    print("-" * 100)

    for d in all_dates:
        engine = SelectiveCopilotEngine(target_date=d, max_capital=9749.0)
        base = engine.run_simulation(mode="baseline")
        copilot = engine.run_simulation(mode="selective_copilot")

        b_net = sum(t.pnl for t in base) - len(base) * 40.0
        c_net = sum(t.pnl for t in copilot) - len(copilot) * 40.0
        delta = c_net - b_net

        base_results.extend(base)
        copilot_results.extend(copilot)

        tag = "Today (Oct 14)" if d == "2026-10-14" else ("Aug/Sep Bridge" if "08-31" <= d <= "09-04" else ("Aug Final Week" if d <= "08-28" else "Sep First Week"))
        print(f"{d:<12} | {tag:<18} | {len(base):<8} | Rs {b_net:+9,.2f} | {len(copilot):<12} | Rs {c_net:+11,.2f} | Rs {delta:+8,.2f}")

    print("=" * 100)
    print("\n" + "=" * 105)
    print(" 16-DAY AGGREGATE SUMMARY (1 LOT / ~Rs 10,000 CAPITAL)")
    print("=" * 105)

    b_cnt = len(base_results)
    b_wins = sum(1 for t in base_results if t.pnl > 0)
    b_win_pct = (b_wins / b_cnt * 100) if b_cnt > 0 else 0.0
    b_gross = sum(t.pnl for t in base_results)
    b_net = b_gross - b_cnt * 40.0

    c_cnt = len(copilot_results)
    c_wins = sum(1 for t in copilot_results if t.pnl > 0)
    c_win_pct = (c_wins / c_cnt * 100) if c_cnt > 0 else 0.0
    c_gross = sum(t.pnl for t in copilot_results)
    c_net = c_gross - c_cnt * 40.0

    print(f"{'Configuration':<45} | {'Trades':<8} | {'Win Rate':<10} | {'Gross PnL':<14} | {'Net PnL (1 Lot)':<16}")
    print("-" * 105)
    print(f"{'1. Baseline Strategy 3 (Pullback Only)':<45} | {b_cnt:<8} | {b_win_pct:<9.1f}% | Rs {b_gross:+11,.2f} | Rs {b_net:+13,.2f}")
    print(f"{'2. Selective AI Co-Pilot (Waterfall + Micro-Trail)':<45} | {c_cnt:<8} | {c_win_pct:<9.1f}% | Rs {c_gross:+11,.2f} | Rs {c_net:+13,.2f}")
    print("=" * 105)
    print(f"NET PROFIT INCREASE OVER BASELINE: Rs {c_net - b_net:+,.2f} on 1 Lot!")

if __name__ == "__main__":
    run_comprehensive_audit()
