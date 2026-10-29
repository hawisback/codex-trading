import os
import sys

sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import math
import copy
from typing import List, Dict, Tuple, Optional
from datetime import datetime
from backtest_engine import BacktestEngine, StrategyConfig, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

weeks = [
    ("Week 1 (Aug 31 - Sep 04)", ["2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]),
    ("Week 2 (Sep 07 - Sep 11)", ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]),
    ("Week 3 (Sep 14 - Sep 18)", ["2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]), # Sep 14 holiday
    ("Week 4 (Sep 21 - Sep 25)", ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]),
    ("Week 5 (Sep 28 - Oct 02)", ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]), # Oct 02 holiday
    ("Week 6 (Oct 05 - Oct 09)", ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]),
    ("Current (Oct 12 - Oct 13)", ["2026-10-12", "2026-10-13"])
]

# Baseline Strategy Config
base_s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
consultant = AIConsultant(mode="playbook")


class EnhancedComparisonEngine(BacktestEngine):
    def select_contract_deep_itm(self, spot: float, direction: str, is_0dte: bool = False) -> Tuple[str, int]:
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

    def run_proposed_strategy(
        self,
        initial_stop_pct: float = 12.0,
        enable_boundary_turns: bool = True,
        enable_10pct_breakeven: bool = True
    ) -> List[Trade]:
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

            # Intraday day range and range position
            prior_bars = self.spot_candles[:idx + 1]
            dh = max(b["high"] for b in prior_bars)
            dl = min(b["low"] for b in prior_bars)
            drange = dh - dl
            range_pos_pct = ((close - dl) / drange * 100.0) if drange > 0 else 50.0

            # 15m consolidation box
            recent_15m = self.spot_candles[max(0, idx - 14): idx + 1]
            box_high = max(c["high"] for c in recent_15m)
            box_low = min(c["low"] for c in recent_15m)
            box_spread = box_high - box_low

            raw_time = bar["start_time"]
            time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

            # -------------------------------------------------------------
            # POSITION MANAGEMENT & EXIT RULES
            # -------------------------------------------------------------
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

                # Dynamic Trailing Ratchet Calculation
                ratchet_stop = current_trade.entry_price * (1.0 - initial_stop_pct / 100.0)
                if current_trade.peak_gain_pct >= 40.0:
                    ratchet_stop = max(current_trade.entry_price * 1.30, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 30.0:
                    ratchet_stop = max(current_trade.entry_price * 1.20, current_trade.peak_price * 0.90)
                elif current_trade.peak_gain_pct >= 20.0:
                    ratchet_stop = max(current_trade.entry_price * 1.10, current_trade.peak_price * 0.90)
                elif enable_10pct_breakeven and current_trade.peak_gain_pct >= 10.0:
                    # Breakeven lock + 10% peak offset
                    ratchet_stop = max(current_trade.entry_price * 1.00, current_trade.peak_price * 0.90)

                # 1. Profit Target Cap (+50%)
                if opt_high >= current_trade.entry_price * 1.50:
                    exit_reason = "PROFIT_TARGET (+50%)"
                    exit_price = round(current_trade.entry_price * 1.50, 2)

                # 2. Ratchet / Protective Stop Hit (Trailing Priority)
                elif opt_low <= ratchet_stop:
                    exit_price = round(ratchet_stop, 2)
                    if current_trade.peak_gain_pct >= 10.0:
                        exit_reason = f"RATCHET_LOCK (Stop={exit_price:.2f}, Peak=+{current_trade.peak_gain_pct:.1f}%)"
                    else:
                        exit_reason = f"PROTECTIVE_STOP (-{initial_stop_pct:.0f}%)"

                # 3. Structural Stops if Not Yet in Profit (< 10%)
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

            # -------------------------------------------------------------
            # ENTRY EVALUATION
            # -------------------------------------------------------------
            if idx < 15 or idx > 330:
                continue
            if len(trades) >= 6:
                continue
            if (idx - last_exit_bar) < 10:
                continue

            direction = None

            # PILLAR 1: BOUNDARY TURNS (Trade the Mean-Reversion from Extremes)
            # When spot is at Day Extremes and fails to expand, trade the turn back to VWAP
            if enable_boundary_turns and drange >= 80.0:
                # Top Boundary Reversal: Spot at Day High (Range Pos >= 75%), extended from VWAP, 1m rejection
                if range_pos_pct >= 75.0 and (close - session_vwap) >= 25.0:
                    if close < self.spot_candles[idx - 1]["low"] and rsi >= 58.0:
                        direction = "PE"

                # Bottom Boundary Reversal: Spot at Day Low (Range Pos <= 25%), extended from VWAP, 1m bounce
                elif range_pos_pct <= 25.0 and (session_vwap - close) >= 25.0:
                    if close > self.spot_candles[idx - 1]["high"] and rsi <= 42.0:
                        direction = "CE"

            # PILLAR 2: TREND CONTINUATION (Only in the "Meat of the Move": 25% to 75% Range)
            if not direction:
                ce_pullback = (low <= ema9 + 12.0)
                pe_pullback = (high >= ema9 - 12.0)

                ce_trend = (close > ema9) and (ema9 > ema20) and (close > session_vwap) and ce_pullback
                pe_trend = (close < ema9) and (ema9 < ema20) and (close < session_vwap) and pe_pullback

                # Only allow trend if NOT at extreme boundary!
                if ce_trend and range_pos_pct < 75.0 and (close - ema9) <= 24.0 and rsi <= 70.0:
                    if not (box_spread < 28.0 and close >= (box_high - 3.0)):
                        direction = "CE"
                elif pe_trend and range_pos_pct > 25.0 and (ema9 - close) <= 24.0 and rsi >= 30.0:
                    if not (box_spread < 28.0 and close <= (box_low + 3.0)):
                        if rsi <= 50.0 or close <= ema9:  # prevent v-reversal counter trades
                            direction = "PE"

            if direction:
                sym, strike = self.select_contract_deep_itm(close, direction, is_0dte=is_0dte)
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


def calc_metrics(trades: List[Trade]) -> dict:
    n = len(trades)
    if not n:
        return {
            "n": 0, "wins": 0, "losses": 0, "wr": 0.0,
            "gross": 0.0, "fee": 0.0, "net": 0.0, "pf": 0.0,
            "max_dd": 0.0, "avg_win": 0.0, "avg_loss": 0.0
        }
    wins = len([t for t in trades if t.pnl > 0])
    losses = len([t for t in trades if t.pnl <= 0])
    gross = sum(t.pnl for t in trades)
    fee = n * 40.0
    net = gross - fee
    w_sum = sum(t.pnl for t in trades if t.pnl > 0)
    l_sum = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = (w_sum / l_sum) if l_sum > 0 else (999.0 if w_sum > 0 else 0.0)
    wr = (wins / n * 100.0)
    avg_w = (w_sum / wins) if wins else 0.0
    avg_l = (l_sum / losses) if losses else 0.0

    # Max Drawdown calculation
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        cum += (t.pnl - 40.0)
        if cum > peak:
            peak = cum
        dd = peak - cum
        if dd > max_dd:
            max_dd = dd

    return {
        "n": n, "wins": wins, "losses": losses, "wr": wr,
        "gross": gross, "fee": fee, "net": net, "pf": pf,
        "max_dd": max_dd, "avg_win": avg_w, "avg_loss": avg_l
    }


def run_full_6week_audit():
    print("=" * 130)
    print(" 🔬 COMPREHENSIVE 6-WEEK AUDIT: EXISTING PRODUCTION STRATEGY VS PROPOSED BOUNDARY-TURN STRATEGY")
    print(" (August 31, 2026 - October 13, 2026 | 30 Completed Trading Sessions)")
    print("=" * 130)

    weekly_data = []

    all_exist_raw = []
    all_exist_ai = []
    all_proposed = []
    all_proposed_ai = []

    for w_name, dates in weeks:
        w_exist_raw, w_exist_ai = [], []
        w_prop, w_prop_ai = [], []

        for d in dates:
            eng = EnhancedComparisonEngine(d)
            if not eng.spot_candles:
                continue
            dte = eng.get_expiry_days()
            is_0dte = (dte <= 0.2)

            # 1. Existing Strategy (Current Production)
            tr_exist = eng.run_simulation(base_s3_cfg)
            w_exist_raw.extend(tr_exist)
            all_exist_raw.extend(tr_exist)

            for i, t in enumerate(tr_exist, 1):
                idx = 0
                for k, c in enumerate(eng.spot_candles):
                    if t.entry_time in c["start_time"]:
                        idx = k
                        break
                dos = generate_market_dossier(
                    d, eng.spot_candles, idx, t.direction, t.symbol, t.strike,
                    t.entry_price, tr_exist[:i - 1], dte, is_0dte
                )
                v = consultant.evaluate(dos)
                if v.is_approved:
                    w_exist_ai.append(t)
                    all_exist_ai.append(t)

            # 2. Proposed Strategy (Boundary Turns + Range Matrix + 10% Ratchet + 12% Stop)
            tr_prop = eng.run_proposed_strategy(
                initial_stop_pct=12.0,
                enable_boundary_turns=True,
                enable_10pct_breakeven=True
            )
            w_prop.extend(tr_prop)
            all_proposed.extend(tr_prop)

            for i, t in enumerate(tr_prop, 1):
                idx = 0
                for k, c in enumerate(eng.spot_candles):
                    if t.entry_time in c["start_time"]:
                        idx = k
                        break
                dos = generate_market_dossier(
                    d, eng.spot_candles, idx, t.direction, t.symbol, t.strike,
                    t.entry_price, tr_prop[:i - 1], dte, is_0dte
                )
                range_pos = ((dos.spot_price - dos.day_low) / dos.day_range_pts * 100.0) if dos.day_range_pts > 0 else 50.0
                if (t.direction == "PE" and range_pos >= 75.0) or (t.direction == "CE" and range_pos <= 25.0):
                    dos.is_directional_shift = True
                v = consultant.evaluate(dos)
                if v.is_approved:
                    w_prop_ai.append(t)
                    all_proposed_ai.append(t)

        m_exist_ai = calc_metrics(w_exist_ai)
        m_prop = calc_metrics(w_prop)
        m_prop_ai = calc_metrics(w_prop_ai)

        weekly_data.append((w_name, m_exist_ai, m_prop, m_prop_ai))

    # Print Table
    print(f"\n{'Week / Period':<26} | {'Existing Strategy (Prod AI)':<30} | {'Proposed Strategy (Full Execution)':<30} | {'Proposed + AI Screened':<30}")
    print(f"{'':<26} | {'Tr':<4} {'Win%':<6} {'Net (1L)':<9} {'Net (2L)':<9} | {'Tr':<4} {'Win%':<6} {'Net (1L)':<9} {'Net (2L)':<9} | {'Tr':<4} {'Win%':<6} {'Net (1L)':<9} {'Net (2L)':<9}")
    print("-" * 130)

    for w_name, me, mp, mpa in weekly_data:
        print(f"{w_name:<26} | {me['n']:>2}  {me['wr']:>4.1f}%  Rs{me['net']:>7.1f} Rs{me['net']*2:>7.1f} | {mp['n']:>2}  {mp['wr']:>4.1f}%  Rs{mp['net']:>7.1f} Rs{mp['net']*2:>7.1f} | {mpa['n']:>2}  {mpa['wr']:>4.1f}%  Rs{mpa['net']:>7.1f} Rs{mpa['net']*2:>7.1f}")

    tot_exist = calc_metrics(all_exist_ai)
    tot_prop = calc_metrics(all_proposed)
    tot_prop_ai = calc_metrics(all_proposed_ai)

    print("=" * 130)
    print(f"{'CONSOLIDATED 30 SESSIONS':<26} | {tot_exist['n']:>2}  {tot_exist['wr']:>4.1f}%  Rs{tot_exist['net']:>7.1f} Rs{tot_exist['net']*2:>7.1f} | {tot_prop['n']:>2}  {tot_prop['wr']:>4.1f}%  Rs{tot_prop['net']:>7.1f} Rs{tot_prop['net']*2:>7.1f} | {tot_prop_ai['n']:>2}  {tot_prop_ai['wr']:>4.1f}%  Rs{tot_prop_ai['net']:>7.1f} Rs{tot_prop_ai['net']*2:>7.1f}")
    print(f"{'PROFIT FACTOR (PF)':<26} |           {tot_exist['pf']:>6.2f}                   |           {tot_prop['pf']:>6.2f}                   |           {tot_prop_ai['pf']:>6.2f}")
    print(f"{'MAX DRAWDOWN (1 LOT)':<26} |       -Rs {tot_exist['max_dd']:>7.2f}                   |       -Rs {tot_prop['max_dd']:>7.2f}                   |       -Rs {tot_prop_ai['max_dd']:>7.2f}")
    print(f"{'NET ROI ON ₹10K MARGIN':<26} |          {tot_exist['net']*2/10000*100:>+7.1f}%                   |          {tot_prop['net']*2/10000*100:>+7.1f}%                   |          {tot_prop_ai['net']*2/10000*100:>+7.1f}%")
    print("=" * 130)


if __name__ == "__main__":
    run_full_6week_audit()
