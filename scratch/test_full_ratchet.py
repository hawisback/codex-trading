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

class PerfectRatchetEngine(BacktestEngine):
    def run_simulation(self, initial_stop_pct: float = 12.0):
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

                # Calculate Current Stop Trigger based on Dynamic Incremental Ratchet
                # Initial: -initial_stop_pct
                # Gain >= 10%: Breakeven (+0%)
                # Gain >= 20%: +10% floor, or 10% from peak
                # Gain >= 30%: +20% floor, or 10% from peak
                # Gain >= 40%: +30% floor, or 10% from peak
                ratchet_stop = current_trade.entry_price * (1.0 - initial_stop_pct / 100.0)
                if current_trade.peak_gain_pct >= 40.0:
                    floor = current_trade.entry_price * 1.30
                    ratchet_stop = max(floor, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 30.0:
                    floor = current_trade.entry_price * 1.20
                    ratchet_stop = max(floor, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 20.0:
                    floor = current_trade.entry_price * 1.10
                    ratchet_stop = max(floor, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 10.0:
                    floor = current_trade.entry_price * 1.00 # Breakeven
                    ratchet_stop = max(floor, current_trade.peak_price * 0.90)

                # 1. Profit Target Cap
                if opt_high >= current_trade.entry_price * 1.50:
                    exit_reason = "PROFIT_TARGET (+50%)"
                    exit_price = round(current_trade.entry_price * 1.50, 2)

                # 2. Dynamic Trailing Ratchet Breach (checked first with Trailing Priority!)
                elif opt_low <= ratchet_stop:
                    exit_price = round(ratchet_stop, 2)
                    if current_trade.peak_gain_pct >= 10.0:
                        exit_reason = f"DYNAMIC_RATCHET_STOP (Stop={exit_price:.2f}, Peak=+{current_trade.peak_gain_pct:.1f}%)"
                    else:
                        exit_reason = f"INITIAL_PROTECTIVE_STOP (-{initial_stop_pct:.0f}%)"

                # 3. Structural Stops ONLY if not yet profitable (or if spot breaks structural benchmark)
                elif current_trade.peak_gain_pct < 10.0:
                    if is_ce:
                        if close < (session_vwap - 15.0):
                            exit_reason = "STRUCTURAL_VWAP_STOP"
                            exit_price = opt_close
                        elif close < ema20 and ema9 < ema20:
                            exit_reason = "STRUCTURAL_EMA20_STOP"
                            exit_price = opt_close
                    else:
                        if close > (session_vwap + 15.0):
                            exit_reason = "STRUCTURAL_VWAP_STOP"
                            exit_price = opt_close
                        elif close > ema20 and ema9 > ema20:
                            exit_reason = "STRUCTURAL_EMA20_STOP"
                            exit_price = opt_close

                # 4. EOD Square-Off
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
            if len(trades) >= 6:
                continue
            if (idx - last_exit_bar) < 10:
                continue

            ce_pullback = (low <= ema9 + 12.0)
            pe_pullback = (high >= ema9 - 12.0)
            pe_reversal_veto = (rsi > 50.0) or (close > ema9)

            ce_signal = (close > ema9) and (ema9 > ema20) and (close > session_vwap) and ce_pullback
            pe_signal = (close < ema9) and (ema9 < ema20) and (close < session_vwap) and pe_pullback and not pe_reversal_veto

            direction = None
            if ce_signal:
                if box_spread < 28.0 and close >= (box_high - 3.0):
                    ce_signal = False
                if (close - ema9) > 24.0 or rsi > 78.0:
                    ce_signal = False
                if ce_signal:
                    direction = "CE"

            elif pe_signal:
                if box_spread < 28.0 and close <= (box_low + 3.0):
                    pe_signal = False
                if (ema9 - close) > 24.0 or rsi < 22.0:
                    pe_signal = False
                if pe_signal:
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
print("TESTING FULL INCREMENTAL RATCHET (+10% -> Breakeven, +20% -> +10%, etc.)")
print("=" * 115)

for stop_pct in [8.0, 10.0, 12.0, 15.0]:
    all_tr = []
    for d, label in dates_w1_3:
        eng = PerfectRatchetEngine(d)
        if not eng.spot_candles:
            continue
        tr = eng.run_simulation(initial_stop_pct=stop_pct)
        all_tr.extend(tr)
    st = calc_stats(all_tr)
    print(f"Stop: -{stop_pct:>4.1f}% | Trades: {st['n']:>2} | Wins: {st['w']:>2} | WinRate: {st['wr']:>5.1f}% | Net(1 Lot): Rs {st['net']:>9.2f} | Net(2 Lots): Rs {st['net']*2:>9.2f}")
