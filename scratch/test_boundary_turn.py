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

class RegimeTurningPointEngine(BacktestEngine):
    def run_simulation(self, cfg: StrategyConfig, enable_boundary_reversal: bool = True):
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

            prior_bars = self.spot_candles[:idx+1]
            dh = max(b["high"] for b in prior_bars)
            dl = min(b["low"] for b in prior_bars)
            drange = dh - dl
            range_pos_pct = ((close - dl) / drange * 100.0) if drange > 0 else 50.0

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

                exit_reason = None
                exit_price = opt_close

                # Dynamic Trailing Ratchet
                ratchet_stop = current_trade.entry_price * 0.85 # -15% protective stop
                if current_trade.peak_gain_pct >= 40.0:
                    ratchet_stop = max(current_trade.entry_price * 1.30, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 30.0:
                    ratchet_stop = max(current_trade.entry_price * 1.20, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 20.0:
                    ratchet_stop = max(current_trade.entry_price * 1.10, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 10.0:
                    ratchet_stop = max(current_trade.entry_price * 1.00, current_trade.peak_price * 0.90)

                if opt_high >= current_trade.entry_price * 1.50:
                    exit_reason = "PROFIT_TARGET (+50%)"
                    exit_price = round(current_trade.entry_price * 1.50, 2)
                elif opt_low <= ratchet_stop:
                    exit_price = round(ratchet_stop, 2)
                    exit_reason = "RATCHET_STOP"
                elif current_trade.peak_gain_pct < 10.0:
                    if is_ce and close < (session_vwap - 15.0):
                        exit_reason = "STRUCTURAL_VWAP_STOP"
                    elif not is_ce and close > (session_vwap + 15.0):
                        exit_reason = "STRUCTURAL_VWAP_STOP"
                    elif is_ce and close < ema20 and ema9 < ema20:
                        exit_reason = "STRUCTURAL_EMA20_STOP"
                    elif not is_ce and close > ema20 and ema9 > ema20:
                        exit_reason = "STRUCTURAL_EMA20_STOP"

                if idx >= 360 and not exit_reason:
                    exit_reason = "EOD_SQUAREOFF"
                    exit_price = opt_close

                if exit_reason:
                    current_trade.close(idx, time_str, exit_price, exit_reason)
                    trades.append(current_trade)
                    current_trade = None
                    last_exit_bar = idx
                continue

            # Entry Evaluation
            if idx < 15 or idx > 330:
                continue
            if len(trades) >= 6:
                continue
            if (idx - last_exit_bar) < 10:
                continue

            direction = None

            # -------------------------------------------------------------
            # CASE 1: BOUNDARY TURNING POINT (Mean Reversion at Extremes)
            # -------------------------------------------------------------
            if enable_boundary_reversal and drange >= 80.0:
                # Top Boundary Reversal: Spot at Day High (Range Pos >= 75%), RSI >= 65, rejecting down
                if range_pos_pct >= 75.0 and (close - session_vwap) >= 25.0:
                    # Check if 1m candle closed below previous candle's low (turning down)
                    if close < self.spot_candles[idx-1]["low"] and rsi >= 60.0:
                        direction = "PE" # Turn the top into a Put win!

                # Bottom Boundary Reversal: Spot at Day Low (Range Pos <= 25%), RSI <= 35, bouncing up
                elif range_pos_pct <= 25.0 and (session_vwap - close) >= 25.0:
                    # Check if 1m candle closed above previous candle's high (turning up)
                    if close > self.spot_candles[idx-1]["high"] and rsi <= 40.0:
                        direction = "CE" # Turn the bottom into a Call win!

            # -------------------------------------------------------------
            # CASE 2: TREND CONTINUATION (Only in the Meat of the Move: 25% to 75% Range)
            # -------------------------------------------------------------
            if not direction:
                ce_pullback = (low <= ema9 + 12.0)
                pe_pullback = (high >= ema9 - 12.0)

                ce_trend = (close > ema9) and (ema9 > ema20) and (close > session_vwap) and ce_pullback
                pe_trend = (close < ema9) and (ema9 < ema20) and (close < session_vwap) and pe_pullback

                # Only allow trend if NOT at extreme boundary!
                if ce_trend and range_pos_pct < 75.0 and (close - ema9) <= 24.0 and rsi <= 70.0:
                    direction = "CE"
                elif pe_trend and range_pos_pct > 25.0 and (ema9 - close) <= 24.0 and rsi >= 30.0 and (rsi <= 50.0 or close <= ema9):
                    direction = "PE"

            if direction:
                sym, strike = self.select_contract(close, direction, "STRICT_ITM")
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
print("TESTING BOUNDARY TURNING POINT (MEAN REVERSION) STRATEGY: WEEKS 1 - 3")
print("=" * 115)

all_base = []
all_turn = []

for d, label in dates_w1_3:
    eng = RegimeTurningPointEngine(d)
    if not eng.spot_candles:
        continue
    tr_base = eng.run_simulation(s3_cfg, enable_boundary_reversal=False)
    tr_turn = eng.run_simulation(s3_cfg, enable_boundary_reversal=True)
    all_base.extend(tr_base)
    all_turn.extend(tr_turn)
    
    st_b = calc_stats(tr_base)
    st_t = calc_stats(tr_turn)
    diff = st_t['net'] - st_b['net']
    print(f"{label:<18} | Base: {st_b['n']:>2} tr  Rs {st_b['net']:>8.2f} ({st_b['wr']:4.1f}%) | Turn: {st_t['n']:>2} tr  Rs {st_t['net']:>8.2f} ({st_t['wr']:4.1f}%) | Alpha: Rs {diff:>+8.2f}")

tot_b = calc_stats(all_base)
tot_t = calc_stats(all_turn)

print("=" * 115)
print(f"BASE STRATEGY (NO BOUNDARY TURNS): Trades={tot_b['n']} WinRate={tot_b['wr']:.1f}% Net = Rs {tot_b['net']:>10.2f}")
print(f"WITH BOUNDARY TURNS TRADED:       Trades={tot_t['n']} WinRate={tot_t['wr']:.1f}% Net = Rs {tot_t['net']:>10.2f}")
print(f"TOTAL NET IMPROVEMENT (ALPHA):    Rs {tot_t['net'] - tot_b['net']:>+10.2f}")
print("=" * 115)
