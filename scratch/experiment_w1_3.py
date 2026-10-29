import os
import sys

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import math
from backtest_engine import BacktestEngine, StrategyConfig, bsm_price, Trade

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

class AdaptiveEngine(BacktestEngine):
    def select_contract(self, spot: float, direction: str, is_0dte: bool = False) -> tuple[str, int]:
        # On 0DTE, pick deeper ITM to ensure premium >= Rs 45 and delta >= 0.70
        if is_0dte:
            if direction == "CE":
                strike = int((spot - 30) // 50) * 50
            else:
                strike = int(math.ceil((spot + 30) / 50.0)) * 50
        else:
            if direction == "CE":
                strike = int(spot // 50) * 50
            else:
                strike = int(math.ceil(spot / 50.0)) * 50
        sym = f"NIFTY_{self.target_date}_{strike}_{direction}"
        return sym, strike

    def run_simulation(self, initial_stop_pct: float = 12.0, max_vwap_dist: float = 55.0, allow_fresh_breakout: bool = True):
        trades = []
        current_trade = None
        last_exit_bar = -999
        spot_closes = []
        spot_typicals = []
        dte = self.get_expiry_days()
        is_0dte = (dte <= 0.2)

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

                exit_reason = None
                exit_price = opt_close

                # A. Strict 10-12% Protective Stop
                if opt_low <= current_trade.entry_price * (1.0 - initial_stop_pct / 100.0):
                    exit_reason = f"PROTECTIVE_STOP (-{initial_stop_pct:.0f}%)"
                    exit_price = round(current_trade.entry_price * (1.0 - initial_stop_pct / 100.0), 2)
                # B. Profit Target Cap
                elif opt_high >= current_trade.entry_price * 1.50:
                    exit_reason = "PROFIT_TARGET (+50%)"
                    exit_price = round(current_trade.entry_price * 1.50, 2)
                # C. Dynamic Incremental Trailing Ratchet (+10% -> Breakeven, +20% -> +10%, +30% -> +20%)
                elif current_trade.peak_gain_pct >= 20.0:
                    current_trade.runner_active = True
                    floor_pct = 10.0
                    if current_trade.peak_gain_pct >= 40.0:
                        floor_pct = 30.0
                    elif current_trade.peak_gain_pct >= 30.0:
                        floor_pct = 20.0
                    floor_price = current_trade.entry_price * (1.0 + floor_pct / 100.0)
                    trail_stop = max(floor_price, current_trade.peak_price * 0.90)

                    if opt_close <= trail_stop:
                        exit_reason = f"TRAILING_DYNAMIC_RATCHET (Stop={trail_stop:.2f})"
                        exit_price = round(trail_stop, 2)
                    elif is_ce and close < (ema9 - 4.0):
                        exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} < {ema9:.1f})"
                        exit_price = opt_close
                    elif not is_ce and close > (ema9 + 4.0):
                        exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} > {ema9:.1f})"
                        exit_price = opt_close

                # D. Structural Exits (VWAP invalidation)
                elif is_ce and close < (session_vwap - 15.0):
                    exit_reason = "STRUCTURAL_VWAP_STOP"
                    exit_price = opt_close
                elif not is_ce and close > (session_vwap + 15.0):
                    exit_reason = "STRUCTURAL_VWAP_STOP"
                    exit_price = opt_close
                elif is_ce and close < ema20 and ema9 < ema20:
                    exit_reason = "STRUCTURAL_EMA20_STOP"
                    exit_price = opt_close
                elif not is_ce and close > ema20 and ema9 > ema20:
                    exit_reason = "STRUCTURAL_EMA20_STOP"
                    exit_price = opt_close

                # E. EOD Square-Off
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
            if idx < 10 or idx > 330:
                continue
            if len(trades) >= 6:
                continue
            if (idx - last_exit_bar) < 10:
                continue

            vwap_dist = abs(close - session_vwap)
            # Filter: Do NOT enter if spot is overextended from VWAP (> max_vwap_dist)
            if vwap_dist > max_vwap_dist:
                continue

            # Momentum alignment
            bull_aligned = (close > ema9) and (ema9 > ema20) and (close > session_vwap)
            bear_aligned = (close < ema9) and (ema9 < ema20) and (close < session_vwap)

            # Pullback qualification
            ce_pullback = (low <= ema9 + 12.0)
            pe_pullback = (high >= ema9 - 12.0)

            # Fresh breakout qualification (if allow_fresh_breakout and box_spread >= 28)
            ce_breakout = allow_fresh_breakout and (box_spread >= 28.0) and (close > box_high - 1.0) and (high >= box_high)
            pe_breakout = allow_fresh_breakout and (box_spread >= 28.0) and (close < box_low + 1.0) and (low <= box_low)

            direction = None
            if bull_aligned and (ce_pullback or ce_breakout):
                if box_spread < 28.0 and close >= (box_high - 3.0):
                    pass # consolidation ceiling
                elif (close - ema9) <= 24.0 and rsi <= 74.0:
                    direction = "CE"

            elif bear_aligned and (pe_pullback or pe_breakout):
                # V-reversal veto
                if rsi <= 50.0 and close <= ema9:
                    if box_spread < 28.0 and close <= (box_low + 3.0):
                        pass # consolidation floor
                    elif (ema9 - close) <= 24.0 and rsi >= 26.0:
                        direction = "PE"

            if direction:
                sym, strike = self.select_contract(close, direction, is_0dte=is_0dte)
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
print("EXPERIMENT: ADAPTIVE ENTRY & PROTECTIVE STOP (WEEKS 1 - 3: AUG 31 - SEP 18)")
print("=" * 115)

for stop_pct in [10.0, 12.0, 15.0]:
    for max_dist in [45.0, 55.0, 65.0]:
        all_tr = []
        for d, label in dates_w1_3:
            eng = AdaptiveEngine(d)
            if not eng.spot_candles:
                continue
            tr = eng.run_simulation(initial_stop_pct=stop_pct, max_vwap_dist=max_dist, allow_fresh_breakout=True)
            all_tr.extend(tr)
        st = calc_stats(all_tr)
        print(f"Stop: {stop_pct:>4.1f}% | MaxVWAPDist: {max_dist:>4.1f} pts | Trades: {st['n']:>2} | WinRate: {st['wr']:>5.1f}% | Net(1 Lot): Rs {st['net']:>9.2f} | Net(2 Lots): Rs {st['net']*2:>9.2f}")
