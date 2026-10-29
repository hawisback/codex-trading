import os
import sys
import json
import math
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, ".")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

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

class AICopilotBacktestEngine:
    def __init__(self, target_date: str = "2026-10-14", max_capital: float = 9749.0):
        self.target_date = target_date
        self.max_capital = max_capital
        self.spot_candles = []
        self.options_data = {}
        self.load_data()
        self.ai_consultant = AIConsultant(mode="playbook")

    def load_data(self):
        spot_file = f"data/spot_candles_{self.target_date.replace('-', '')}.json"
        opt_file = f"data/option_candles_{self.target_date.replace('-', '')}.json"
        
        with open(spot_file, "r", encoding="utf-8") as f:
            self.spot_candles = json.load(f)
            
        with open(opt_file, "r", encoding="utf-8") as f:
            self.options_data = json.load(f)

    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> float:
        if len(prices) < period:
            return prices[-1] if prices else 0.0
        k = 2.0 / (period + 1)
        ema = prices[0]
        for p in prices[1:]:
            ema = p * k + ema * (1 - k)
        return round(ema, 2)

    def get_option_bar(self, sym: str, bar_idx: int) -> Tuple[float, float, float]:
        candles = self.options_data.get(sym, [])
        if bar_idx < len(candles):
            c = candles[bar_idx]
            return float(c["high"]), float(c["low"]), float(c["close"])
        return 0.0, 0.0, 0.0

    def select_affordable_strike(self, spot: float, direction: str, bar_idx: int) -> Tuple[str, int, float]:
        """Select best strike (ITM if affordable, otherwise ATM) where entry_price * 65 <= max_capital."""
        max_premium = self.max_capital / 65.0  # ~149.98
        atm_strike = int(round(spot / 50.0)) * 50
        
        if direction == "PE":
            itm_strike = atm_strike + 50
            # Test ITM first
            itm_sym = f"NIFTY_{self.target_date}_{itm_strike}_PE"
            if itm_sym in self.options_data and bar_idx < len(self.options_data[itm_sym]):
                p = self.options_data[itm_sym][bar_idx]["open"]
                if p <= max_premium:
                    return itm_sym, itm_strike, p
            # Fallback to ATM
            atm_sym = f"NIFTY_{self.target_date}_{atm_strike}_PE"
            atm_p = self.options_data[atm_sym][bar_idx]["open"] if atm_sym in self.options_data else 130.0
            return atm_sym, atm_strike, atm_p
        else:
            itm_strike = atm_strike - 50
            itm_sym = f"NIFTY_{self.target_date}_{itm_strike}_CE"
            if itm_sym in self.options_data and bar_idx < len(self.options_data[itm_sym]):
                p = self.options_data[itm_sym][bar_idx]["open"]
                if p <= max_premium:
                    return itm_sym, itm_strike, p
            atm_sym = f"NIFTY_{self.target_date}_{atm_strike}_CE"
            atm_p = self.options_data[atm_sym][bar_idx]["open"] if atm_sym in self.options_data else 130.0
            return atm_sym, atm_strike, atm_p

    def run_simulation(self, enable_waterfall_override: bool = True, enable_micro_trail: bool = True):
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
            ema9 = self.calculate_ema(bars_5m, 9)
            ema20 = self.calculate_ema(bars_5m, 20)

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
            # 1. MANAGE CURRENT OPEN TRADE (IF ANY)
            # ---------------------------------------------------------
            if current_trade is not None:
                opt_high, opt_low, opt_close = self.get_option_bar(current_trade.symbol, idx)
                if opt_high > current_trade.peak_price:
                    current_trade.peak_price = opt_high
                    current_trade.peak_gain_pct = round(((opt_high - current_trade.entry_price) / current_trade.entry_price) * 100, 2)

                hold_duration = idx - current_trade.entry_bar
                exit_reason = None
                exit_price = opt_close

                # A. Stop Loss (-30%)
                if opt_low <= current_trade.entry_price * 0.70:
                    exit_reason = "INITIAL_STOP"
                    exit_price = round(current_trade.entry_price * 0.70, 2)

                # B. Profit Target (+50%)
                elif opt_high >= current_trade.entry_price * 1.50:
                    exit_reason = "PROFIT_TARGET"
                    exit_price = round(current_trade.entry_price * 1.50, 2)

                # C. AI Late-Session Micro-Trail (After 14:00 IST = bar 285+)
                elif enable_micro_trail and idx >= 285 and current_trade.peak_gain_pct >= 4.0:
                    # If gain reached +4.0% late in day, protect capital with Breakeven + 1% floor
                    floor_price = round(current_trade.entry_price * 1.01, 2)
                    if opt_low <= floor_price:
                        exit_reason = "AI_LATE_DAY_MICRO_TRAIL"
                        exit_price = floor_price

                # D. Standard Runner Trailing (>= 15% peak gain)
                elif current_trade.peak_gain_pct >= 15.0:
                    # 10% pullback from peak
                    trail_stop = current_trade.peak_price * 0.90
                    breakeven_floor = current_trade.entry_price * 1.02
                    effective_stop = max(trail_stop, breakeven_floor)
                    if opt_low <= effective_stop:
                        exit_reason = "RUNNER_PEAK_TRAIL"
                        exit_price = round(effective_stop, 2)

                # E. EOD Square-Off (15:20 IST = Bar 365)
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

            # Check VWAP blender condition (to prevent chop)
            # VWAP crosses in past 60m
            vwap_window = 60
            past_spots = spot_closes[max(0, idx - vwap_window): idx + 1]
            past_typicals = spot_typicals[max(0, idx - vwap_window): idx + 1]
            vwap_crosses = 0
            for i in range(1, len(past_spots)):
                if (past_spots[i] >= past_typicals[i] and past_spots[i-1] < past_typicals[i-1]) or \
                   (past_spots[i] <= past_typicals[i] and past_spots[i-1] > past_typicals[i-1]):
                    vwap_crosses += 1
            is_vwap_blender = (vwap_crosses >= 5 and abs(close - session_vwap) < 15.0)

            # Signal Candidate Detection
            is_bear_trend = (close < ema9 < ema20 < session_vwap)
            is_bull_trend = (close > ema9 > ema20 > session_vwap)

            setup_found = None
            direction = None

            # Path 1: High-Velocity Waterfall Breakdown Override
            if enable_waterfall_override and not is_vwap_blender:
                # Range box spread >= 24 pts and close broke below 15m box low
                # AND spot is at least 10 pts below VWAP with EMA9 sloping down
                if close < box_low and (session_vwap - close) >= 12.0 and box_spread >= 24.0:
                    setup_found = "WATERFALL_BREAKDOWN"
                    direction = "PE"

            # Path 2: Strategy 3 Standard Pullback to 5m EMA9 (Requires 15m Range Box Spread >= 28.0)
            if not setup_found and not is_vwap_blender and box_spread >= 28.0:
                if is_bear_trend:
                    # 1m high pulled back within 4.0 pts of 5m EMA9
                    if abs(high - ema9) <= 4.0 and (session_vwap - close) < 80.0:  # No climax trap
                        setup_found = "PULLBACK_VALUE"
                        direction = "PE"
                elif is_bull_trend:
                    if abs(low - ema9) <= 4.0 and (close - session_vwap) < 80.0:
                        setup_found = "PULLBACK_VALUE"
                        direction = "CE"

            # If setup found, validate with AI Playbook logic
            if setup_found and direction:
                # Check Climax Trap (>80 pts from VWAP)
                if abs(close - session_vwap) >= 80.0:
                    # Climax veto!
                    continue

                sym, strike, entry_p = self.select_affordable_strike(close, direction, idx)
                
                # Verify AI Dossier approval
                dossier = generate_market_dossier(
                    target_date=self.target_date,
                    candles=self.spot_candles[:idx + 1],
                    current_bar_idx=idx,
                    direction=direction,
                    symbol=sym,
                    strike=strike,
                    option_entry_price=entry_p,
                    trade_history=trades,
                    days_to_expiry=5.0,
                    is_expiry_0dte=False
                )
                
                # Check AI playbook verdict
                verdict = self.ai_consultant.evaluate(dossier)
                
                # In waterfall mode, AI recognizes directional shift/expansion breakdown
                if setup_found == "WATERFALL_BREAKDOWN":
                    # Bypass blender veto if directional momentum is active
                    if verdict.trap_detected == "Trap 1: The VWAP Blender" and abs(close - session_vwap) >= 14.0:
                        verdict.is_approved = True
                        verdict.confidence_score = 90
                        verdict.reasoning = "Waterfall Breakdown: 15m Range Box breakdown below VWAP with high velocity."

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

def main():
    print("=" * 95)
    print(" BACKTEST VERIFICATION: AI CO-PILOT UPGRADE ON TODAY'S TAPE (2026-10-14)")
    print(" Evaluating: 1) Waterfall Breakdown Override + 2) Late-Day Micro-Trail Protection")
    print(" Real Kite 1-Minute Option Candles Across All Strikes")
    print("=" * 95)

    engine = AICopilotBacktestEngine(target_date="2026-10-14", max_capital=9749.0)

    # 1. Baseline Strategy 3 (What we ran live today)
    baseline_trades = engine.run_simulation(enable_waterfall_override=False, enable_micro_trail=False)
    
    # 2. AI Co-Pilot with Waterfall Override Only
    waterfall_trades = engine.run_simulation(enable_waterfall_override=True, enable_micro_trail=False)

    # 3. Full AI Co-Pilot (Waterfall Override + Late-Day Micro-Trail)
    copilot_trades = engine.run_simulation(enable_waterfall_override=True, enable_micro_trail=True)

    print("\n" + "=" * 95)
    print(" COMPARISON SUMMARY TABLE")
    print("=" * 95)
    print(f"{'Strategy Configuration':<45} | {'Trades':<7} | {'Win%':<7} | {'Gross PnL':<12} | {'Net (1 Lot)':<14}")
    print("-" * 95)

    runs = [
        ("1. Baseline Strategy 3 (Live Mode Today)", baseline_trades),
        ("2. AI Waterfall Override Only", waterfall_trades),
        ("3. Full AI Co-Pilot (Waterfall + Micro-Trail)", copilot_trades),
    ]

    for label, tr_list in runs:
        t_count = len(tr_list)
        wins = sum(1 for t in tr_list if t.pnl > 0)
        win_pct = f"{(wins / t_count) * 100:.1f}%" if t_count > 0 else "0.0%"
        gross = sum(t.pnl for t in tr_list)
        friction = t_count * 40.0
        net = gross - friction
        print(f"{label:<45} | {t_count:<7} | {win_pct:<7} | Rs {gross:+9,.2f} | Rs {net:+11,.2f}")

    print("\n" + "=" * 95)
    print(" DETAILED TRADE LOG FOR FULL AI CO-PILOT CONFIGURATION:")
    print("=" * 95)
    for t in copilot_trades:
        print(f"Trade #{t.trade_id} [{t.setup_type}]:")
        print(f"  Entry: Bar {t.entry_bar} ({t.entry_time} IST) -> {t.symbol} @ Rs {t.entry_price:.2f}")
        print(f"  Exit:  Bar {t.exit_bar} ({t.exit_time} IST) -> Rs {t.exit_price:.2f} ({t.exit_reason})")
        print(f"  Peak Price: Rs {t.peak_price:.2f} (+{t.peak_gain_pct:.1f}%)")
        print(f"  Realized PnL: Rs {t.pnl:+,.2f} ({t.pnl_pct:+.1f}%) [Margin Deployed: Rs {t.entry_price * 65:,.2f}]")
        print(f"  AI Verdict: {t.ai_verdict.reasoning[:100]}...\n")

if __name__ == "__main__":
    main()
