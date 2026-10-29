import os
import sys
sys.path.insert(0, os.path.abspath("."))
import sqlite3
import math
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from trading.domain.indicators import exponential_average, simple_rsi

HISTORICAL_DB_PATH = r"C:\Users\hawis\OneDrive\Desktop\icici-breeze-api-trading\data\market\historical.db"

@dataclass
class Trade:
    trade_id: int
    date: str
    symbol: str
    direction: str
    strike: int
    entry_bar: int
    entry_time: str
    entry_price: float
    quantity: int = 40  # 2 lots = 40 contracts for SENSEX
    exit_bar: Optional[int] = None
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    pnl: Optional[float] = None
    pnl_pct: Optional[float] = None
    peak_price: float = 0.0
    peak_gain_pct: float = 0.0
    runner_active: bool = False

    def close(self, exit_bar: int, exit_time: str, exit_price: float, reason: str):
        self.exit_bar = exit_bar
        self.exit_time = exit_time
        self.exit_price = round(exit_price, 2)
        self.exit_reason = reason
        self.pnl = round((self.exit_price - self.entry_price) * self.quantity, 2)
        self.pnl_pct = round(((self.exit_price - self.entry_price) / self.entry_price) * 100, 2)

    @property
    def hold_minutes(self) -> int:
        if self.exit_bar is not None:
            return self.exit_bar - self.entry_bar
        return 0

def load_sensex_day(target_date: str, expiry: str):
    conn = sqlite3.connect(f"file:{HISTORICAL_DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    
    query_spot = """
        SELECT start_time, open, high, low, close, volume
        FROM historical_candles
        WHERE instrument_id = 'INST-SENSEX-INDEX' AND interval = '1m'
          AND start_time >= ? AND start_time <= ?
        ORDER BY start_time ASC
    """
    start_utc = f"{target_date}T03:45:00+00:00"
    end_utc = f"{target_date}T10:00:00+00:00"
    spot_rows = [dict(r) for r in conn.execute(query_spot, (start_utc, end_utc)).fetchall()]
    
    query_opt = """
        SELECT instrument_id, start_time, open, high, low, close, volume
        FROM historical_candles
        WHERE instrument_id LIKE ? AND interval = '1m'
          AND start_time >= ? AND start_time <= ?
        ORDER BY start_time ASC
    """
    opt_pattern = f"INST-SENSEX-{expiry}%"
    opt_rows = conn.execute(query_opt, (opt_pattern, start_utc, end_utc)).fetchall()
    
    options_by_inst = {}
    for r in opt_rows:
        inst = r["instrument_id"]
        if inst not in options_by_inst:
            options_by_inst[inst] = {}
        options_by_inst[inst][r["start_time"]] = dict(r)
        
    conn.close()
    return spot_rows, options_by_inst

def select_sensex_strike(spot: float, direction: str, mode: str = "STRICT_ITM") -> int:
    if mode == "STRICT_ITM":
        if direction == "CE":
            return int(spot // 100) * 100
        return int(math.ceil(spot / 100.0)) * 100
    return int(round(spot / 100.0) * 100)

def run_sensex_simulation(dates_and_expiries, use_ai_playbook: bool = False):
    all_trades: List[Trade] = []
    trade_id_counter = 1

    # Scaled parameters for SENSEX (~72k-75k level, approx 3.2x NIFTY)
    PULLBACK_TOLERANCE_PTS = 14.0       # 4.0 on NIFTY * 3.3
    VALUE_PROXIMITY_PTS = 75.0         # 24.0 on NIFTY * 3.1
    RANGE_BOX_SPREAD_MIN = 85.0        # 28.0 on NIFTY * 3.0
    CLIMAX_OPEN_DIST_MIN = 230.0       # 75.0 on NIFTY * 3.1
    CLIMAX_VWAP_DIST_MIN = 130.0       # 40.0 on NIFTY * 3.2
    CLIMAX_IMPULSE_DELTA_MIN = 55.0    # 18.0 on NIFTY * 3.1
    BOX_RESISTANCE_BUFFER = 12.0       # 4.0 on NIFTY * 3.0

    mode_label = "WITH AI PLAYBOOK GATEKEEPER" if use_ai_playbook else "WITHOUT AI (MECHANICAL ONLY)"
    print("\n" + "=" * 90)
    print(f"BSE SENSEX HISTORICAL AUDIT [{mode_label}] (Oct 12 - Oct 16, 2026)")
    print(f"Contract Sizing: 2 Lots (40 contracts) | Strike Step: 100 pts")
    print("=" * 90)

    for target_date, expiry in dates_and_expiries:
        spot_candles, options_data = load_sensex_day(target_date, expiry)
        if not spot_candles:
            continue

        current_trade: Optional[Trade] = None
        last_exit_bar = -999
        spot_closes: List[float] = []
        spot_typicals: List[float] = []
        vwap_history: List[float] = []
        day_open = spot_candles[0]["open"]

        for idx, bar in enumerate(spot_candles):
            close = bar["close"]
            high = bar["high"]
            low = bar["low"]
            open_p = bar["open"]
            start_time = bar["start_time"]
            spot_closes.append(close)

            # Cumulative session VWAP
            typical_price = (high + low + close) / 3.0
            spot_typicals.append(typical_price)
            session_vwap = sum(spot_typicals) / len(spot_typicals)
            vwap_history.append(session_vwap)

            # Resample 5m bars for EMA9 / EMA20
            bars_5m = []
            for i in range(0, idx + 1, 5):
                chunk = spot_candles[i:min(i + 5, idx + 1)]
                if chunk:
                    bars_5m.append({
                        "open": chunk[0]["open"],
                        "high": max(c["high"] for c in chunk),
                        "low": min(c["low"] for c in chunk),
                        "close": chunk[-1]["close"],
                    })

            closes_5m = [b["close"] for b in bars_5m]
            ema9 = exponential_average(closes_5m, 9, last_during_warmup=True)
            ema20 = exponential_average(closes_5m, 20, last_during_warmup=True)
            rsi = simple_rsi(spot_closes, 14)

            # 15m Range Box
            window_15m = spot_candles[max(0, idx - 14): idx + 1]
            box_high = max(c["high"] for c in window_15m)
            box_low = min(c["low"] for c in window_15m)
            box_spread = box_high - box_low

            # -------------------------------------------------------------
            # POSITION MONITORING / EXIT LOGIC
            # -------------------------------------------------------------
            if current_trade is not None:
                inst_id = current_trade.symbol
                opt_candle = options_data.get(inst_id, {}).get(start_time)
                
                if opt_candle:
                    o_high = opt_candle["high"]
                    o_low = opt_candle["low"]
                    o_close = opt_candle["close"]
                else:
                    o_high = o_low = o_close = current_trade.entry_price

                if o_high > current_trade.peak_price:
                    current_trade.peak_price = o_high
                    current_trade.peak_gain_pct = ((o_high - current_trade.entry_price) / current_trade.entry_price) * 100

                if current_trade.peak_gain_pct >= 20.0:
                    current_trade.runner_active = True

                exit_signal = None
                exit_price = o_close

                # Hard Stop (-30%)
                if o_low <= current_trade.entry_price * 0.70:
                    exit_signal = "STOP_LOSS_INITIAL_30%"
                    exit_price = current_trade.entry_price * 0.70
                # Target (+50%)
                elif o_high >= current_trade.entry_price * 1.50 and not current_trade.runner_active:
                    exit_signal = "TARGET_50%"
                    exit_price = current_trade.entry_price * 1.50
                # Trailing Ratchet on Runner
                elif current_trade.runner_active:
                    peak = current_trade.peak_price
                    trail_level = peak * 0.90
                    trail_level = max(trail_level, current_trade.entry_price * 1.01)
                    if o_low <= trail_level:
                        exit_signal = "RUNNER_PEAK_TRAIL_EXIT"
                        exit_price = min(o_close, trail_level)
                # Structural Stop (VWAP cross)
                elif current_trade.direction == "CE" and close < session_vwap:
                    exit_signal = "STRUCTURAL_VWAP_STOP"
                    exit_price = o_close
                elif current_trade.direction == "PE" and close > session_vwap:
                    exit_signal = "STRUCTURAL_VWAP_STOP"
                    exit_price = o_close
                # EOD Square-Off
                elif idx >= 360:
                    exit_signal = "EOD_SQUAREOFF"
                    exit_price = o_close

                if exit_signal:
                    current_trade.close(idx, start_time, exit_price, exit_signal)
                    all_trades.append(current_trade)
                    current_trade = None
                    last_exit_bar = idx
                    continue

            # -------------------------------------------------------------
            # ENTRY SIGNALS & AI PLAYBOOK AUDIT
            # -------------------------------------------------------------
            if current_trade is None and (idx - last_exit_bar) >= 10 and idx < 300:
                signal = None
                setup = None

                # Climax Spring setup
                if idx <= 120:
                    recent_low = min(c["low"] for c in spot_candles[max(0, idx - 2): idx + 1])
                    recent_high = max(c["high"] for c in spot_candles[max(0, idx - 2): idx + 1])
                    delta = close - open_p
                    dist_open_ext = recent_low - day_open
                    dist_vwap_ext = recent_low - session_vwap

                    if (dist_open_ext <= -CLIMAX_OPEN_DIST_MIN or dist_vwap_ext <= -CLIMAX_VWAP_DIST_MIN) and delta >= CLIMAX_IMPULSE_DELTA_MIN and rsi <= 35.0:
                        signal = "CE"
                        setup = "CLIMAX_SPRING"
                    elif (recent_high - day_open >= CLIMAX_OPEN_DIST_MIN or recent_high - session_vwap >= CLIMAX_VWAP_DIST_MIN) and delta <= -CLIMAX_IMPULSE_DELTA_MIN and rsi >= 65.0:
                        signal = "PE"
                        setup = "CLIMAX_SPRING"

                # Trend Pullback setup
                if signal is None:
                    ce_trend = (close > ema9) and (ema9 > ema20) and (close > session_vwap)
                    ce_pullback = (low <= ema9 + PULLBACK_TOLERANCE_PTS)
                    ce_value = (close - ema9 <= VALUE_PROXIMITY_PTS) and (rsi < 78.0)
                    ce_box_ok = not (box_spread < RANGE_BOX_SPREAD_MIN and close >= (box_high - BOX_RESISTANCE_BUFFER))

                    if ce_trend and ce_pullback and ce_value and ce_box_ok:
                        signal = "CE"
                        setup = "TREND_PULLBACK"

                    pe_trend = (close < ema9) and (ema9 < ema20) and (close < session_vwap)
                    pe_pullback = (high >= ema9 - PULLBACK_TOLERANCE_PTS)
                    pe_value = (ema9 - close <= VALUE_PROXIMITY_PTS) and (rsi > 22.0)
                    pe_box_ok = not (box_spread < RANGE_BOX_SPREAD_MIN and close <= (box_low + BOX_RESISTANCE_BUFFER))

                    if pe_trend and pe_pullback and pe_value and pe_box_ok:
                        signal = "PE"
                        setup = "TREND_PULLBACK"

                if signal:
                    # AI PLAYBOOK GATEKEEPER VETOES
                    if use_ai_playbook:
                        # Trap 1: Chronic VWAP Crosses (>= 4 crosses in last 60 bars)
                        lookback_60 = min(60, len(spot_closes))
                        vwap_crosses = 0
                        for k in range(len(spot_closes) - lookback_60 + 1, len(spot_closes)):
                            p_prev = spot_closes[k - 1] - vwap_history[k - 1]
                            p_curr = spot_closes[k] - vwap_history[k]
                            if (p_prev > 0 and p_curr < 0) or (p_prev < 0 and p_curr > 0):
                                vwap_crosses += 1
                        if vwap_crosses >= 4:
                            continue  # VETOED by Trap 1 (VWAP Meat Grinder)

                        # Trap 1: Midday Dead Zone (11:30 - 13:15 IST => bar 135 to 240)
                        if 135 <= idx <= 240 and setup != "CLIMAX_SPRING":
                            # Veto if VWAP is flat (|VWAP - VWAP_30| < 15 pts)
                            vwap_slope_30 = abs(session_vwap - vwap_history[max(0, idx - 30)])
                            if vwap_slope_30 < 20.0:
                                continue  # VETOED by Trap 1 (Midday Flat VWAP)

                        # Trap 7: Counter-Trend VWAP Slope
                        if len(vwap_history) >= 15:
                            slope_15 = session_vwap - vwap_history[idx - 15]
                            if signal == "CE" and slope_15 < -5.0:
                                continue  # VETOED: Buying CE while VWAP is declining
                            if signal == "PE" and slope_15 > 5.0:
                                continue  # VETOED: Buying PE while VWAP is rising

                        # Trap 6: Compressed Ribbon Drift (|EMA9 - EMA20| < 12.0)
                        if abs(ema9 - ema20) < 12.0 and setup != "CLIMAX_SPRING":
                            continue  # VETOED: Compressed ribbon theta bleed

                    strike = select_sensex_strike(close, signal, mode="STRICT_ITM")
                    inst_id = f"INST-SENSEX-{expiry}-{strike}-{signal}"
                    
                    if inst_id in options_data and start_time in options_data[inst_id]:
                        entry_candle = options_data[inst_id][start_time]
                        entry_p = entry_candle["close"]
                        
                        # Trap 2: Penny option veto (< INR 30)
                        if entry_p < 30.0:
                            continue
                            
                        current_trade = Trade(
                            trade_id=trade_id_counter,
                            date=target_date,
                            symbol=inst_id,
                            direction=signal,
                            strike=strike,
                            entry_bar=idx,
                            entry_time=start_time,
                            entry_price=entry_p,
                            peak_price=entry_p,
                            quantity=40
                        )
                        trade_id_counter += 1

    # Print Results
    print(f"{'ID':<3} | {'Date':<10} | {'Contract':<30} | {'Entry':<8} | {'Exit':<8} | {'PnL %':<8} | {'PnL (INR)':<10} | {'Exit Reason'}")
    print("-" * 90)
    total_pnl = 0.0
    wins = 0
    losses = 0

    for t in all_trades:
        total_pnl += t.pnl
        if t.pnl > 0:
            wins += 1
        elif t.pnl < 0:
            losses += 1
        print(f"{t.trade_id:<3} | {t.date:<10} | {t.symbol:<30} | {t.entry_price:<8.2f} | {t.exit_price:<8.2f} | {t.pnl_pct:>6.2f}% | {t.pnl:>10.2f} | {t.exit_reason}")

    total_trades = len(all_trades)
    win_rate = (wins / total_trades * 100) if total_trades else 0
    print("-" * 90)
    print(f"Total Trades: {total_trades} | Wins: {wins} | Losses: {losses} | Win Rate: {win_rate:.1f}%")
    print(f"Net Realized PnL: INR {total_pnl:,.2f} on 2 Lots (40 contracts)")
    print("=" * 90)

if __name__ == "__main__":
    dates = [
        ("2026-10-12", "2026-10-15"),
        ("2026-10-13", "2026-10-15"),
        ("2026-10-14", "2026-10-15"),
        ("2026-10-15", "2026-10-15"),
        ("2026-10-16", "2026-10-22"),
    ]
    # 1. Run Mechanical (Without AI Gatekeeper)
    run_sensex_simulation(dates, use_ai_playbook=False)
    # 2. Run With AI Playbook Gatekeeper
    run_sensex_simulation(dates, use_ai_playbook=True)
