import os
import sys

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import math
from typing import List, Tuple
from backtest_engine import BacktestEngine, StrategyConfig, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

weeks = [
    ("Week 1 (Aug 31 - Sep 04)", ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]),
    ("Week 2 (Sep 07 - Sep 11)", ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]),
    ("Week 3 (Sep 14 - Sep 18)", ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]),
    ("Week 4 (Sep 21 - Sep 25)", ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]),
    ("Week 5 (Sep 28 - Oct 02)", ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]),
    ("Week 6 (Oct 05 - Oct 09)", ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]),
    ("Current (Oct 12 - Oct 13)", ["2026-10-12", "2026-10-13"])
]

consultant = AIConsultant(mode="playbook")
all_dates = [d for _, dl in weeks for d in dl]

class AblationEngine(BacktestEngine):
    def run_simulation_ablation(
        self,
        cfg: StrategyConfig,
        initial_stop_pct: float = 30.0,
        enable_10pct_breakeven: bool = False
    ) -> List[Trade]:
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

                # Ratchet Calculation
                ratchet_stop = current_trade.entry_price * (1.0 - initial_stop_pct / 100.0)
                if current_trade.peak_gain_pct >= 40.0:
                    ratchet_stop = max(current_trade.entry_price * 1.30, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 30.0:
                    ratchet_stop = max(current_trade.entry_price * 1.20, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 20.0:
                    ratchet_stop = max(current_trade.entry_price * 1.10, current_trade.peak_price * 0.90)
                elif enable_10pct_breakeven and current_trade.peak_gain_pct >= 10.0:
                    ratchet_stop = max(current_trade.entry_price * 1.00, current_trade.peak_price * 0.90)

                # 1. Target Cap
                if opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                    exit_reason = "PROFIT_TARGET"
                    exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)
                # 2. Ratchet / Protective Stop Hit
                elif opt_low <= ratchet_stop:
                    exit_price = round(ratchet_stop, 2)
                    exit_reason = "RATCHET_STOP"
                # 3. Structural Stops (if not profitable)
                elif current_trade.peak_gain_pct < 10.0 and cfg.enable_structural_stops:
                    if is_ce:
                        if close < (session_vwap - cfg.vwap_stop_buffer):
                            exit_reason = "STRUCTURAL_VWAP_STOP"
                            exit_price = opt_close
                        elif cfg.ema20_stop and close < ema20 and ema9 < ema20:
                            exit_reason = "STRUCTURAL_EMA20_STOP"
                            exit_price = opt_close
                    else:
                        if close > (session_vwap + cfg.vwap_stop_buffer):
                            exit_reason = "STRUCTURAL_VWAP_STOP"
                            exit_price = opt_close
                        elif cfg.ema20_stop and close > ema20 and ema9 > ema20:
                            exit_reason = "STRUCTURAL_EMA20_STOP"
                            exit_price = opt_close

                if idx >= 360 and not exit_reason:
                    exit_reason = "EOD_SQUAREOFF"
                    exit_price = opt_close

                if exit_reason:
                    current_trade.close(idx, time_str, exit_price, exit_reason)
                    trades.append(current_trade)
                    current_trade = None
                    last_exit_bar = idx
                continue

            # Entry
            if idx < 10 or idx > 330:
                continue
            if len(trades) >= cfg.max_daily_entries:
                continue
            if (idx - last_exit_bar) < cfg.min_spacing_bars:
                continue

            ce_pullback = (low <= ema9 + cfg.pullback_ema_tolerance_pts)
            pe_pullback = (high >= ema9 - cfg.pullback_ema_tolerance_pts)
            pe_reversal_veto = (rsi > 50.0) or (close > ema9)

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
    w_sum = sum(t.pnl for t in tr if t.pnl > 0)
    l_sum = abs(sum(t.pnl for t in tr if t.pnl <= 0))
    pf = (w_sum / l_sum) if l_sum > 0 else (999.0 if w_sum > 0 else 0.0)
    wr = (w / n * 100) if n else 0.0
    return {"n": n, "w": w, "wr": wr, "gross": gross, "fee": fee, "net": net, "pf": pf}

def evaluate_suite(name: str, stop_pct: float, be_10: bool):
    s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
    all_ai_trades = []
    w1_3_trades = []
    w4_7_trades = []

    for idx, (w_name, dates) in enumerate(weeks):
        for d in dates:
            eng = AblationEngine(d)
            if not eng.spot_candles:
                continue
            dte = eng.get_expiry_days()
            is_0dte = (dte <= 0.2)
            trades = eng.run_simulation_ablation(s3_cfg, initial_stop_pct=stop_pct, enable_10pct_breakeven=be_10)

            for i, t in enumerate(trades, 1):
                c_idx = 0
                for k, c in enumerate(eng.spot_candles):
                    if t.entry_time in c["start_time"]:
                        c_idx = k
                        break
                dos = generate_market_dossier(d, eng.spot_candles, c_idx, t.direction, t.symbol, t.strike, t.entry_price, trades[:i-1], dte, is_0dte)
                v = consultant.evaluate(dos)
                if v.is_approved:
                    all_ai_trades.append(t)
                    if idx < 3:
                        w1_3_trades.append(t)
                    else:
                        w4_7_trades.append(t)

    tot = calc_stats(all_ai_trades)
    st_w1_3 = calc_stats(w1_3_trades)
    st_w4_7 = calc_stats(w4_7_trades)

    print(f"\n{name:<48} | Trades: {tot['n']:>2} | WinRate: {tot['wr']:>5.1f}% | Net(1L): Rs {tot['net']:>8.1f} | Net(2L): Rs {tot['net']*2:>8.1f} (ROI: {tot['net']*2/10000*100:>+6.1f}%) | PF: {tot['pf']:>4.2f}")
    print(f"  -> Weeks 1-3 (Summer Chop):  Trades: {st_w1_3['n']:>2} | WinRate: {st_w1_3['wr']:>5.1f}% | Net(1L): Rs {st_w1_3['net']:>8.1f}")
    print(f"  -> Weeks 4-7 (Autumn Trend): Trades: {st_w4_7['n']:>2} | WinRate: {st_w4_7['wr']:>5.1f}% | Net(1L): Rs {st_w4_7['net']:>8.1f} | Net(2L): Rs {st_w4_7['net']*2:>8.1f}")

print("=" * 125)
print("🔬 ABLATION ANALYSIS ACROSS COMPLETE 6 WEEKS (30 SESSIONS)")
print("=" * 125)

evaluate_suite("1. Existing Strategy 3 (Stop=-30%, Ratchet=20%)", 30.0, False)
evaluate_suite("2. S3 + 10% Breakeven Ratchet", 30.0, True)
evaluate_suite("3. S3 + 15% Protective Stop", 15.0, False)
evaluate_suite("4. S3 + 15% Stop + 10% Breakeven Ratchet", 15.0, True)
evaluate_suite("5. S3 + 20% Stop + 10% Breakeven Ratchet", 20.0, True)
print("=" * 125)
