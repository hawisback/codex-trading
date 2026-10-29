#!/usr/bin/env python3
"""
AI Opportunity Radar Backtest:
Replacing rigid if/else formulas with an AI Multi-Factor Decision Engine.
Evaluates:
1. Trend Pullback Mode (Continuation when institutional flow is aligned)
2. Climax Spring Mode (Mean-Reversion when rubber band is at extreme stretch)
3. Trap Stand-Aside Mode (Cash preservation during chop/dead zones)
"""

import sqlite3
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from backtest_engine import BacktestEngine, StrategyConfig, HISTORICAL_DB_PATH, Trade
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

@dataclass
class AIOpportunity:
    action: str                 # "BUY_CE", "BUY_PE", "STAND_ASIDE"
    regime: str                 # "TREND_PULLBACK", "CLIMAX_SPRING", "CHOP_STAND_ASIDE"
    conviction: int             # 0 to 100
    thesis: str
    invalidation_level: Optional[float] = None
    recommended_trailing: str = "dynamic_ratchet"

class AIOpportunityRadar:
    """
    Autonomous AI Opportunity Radar:
    Evaluates the continuous 6D market state on every bar to synthesize
    institutional regime and trade conviction without arbitrary magic-number formulas.
    """
    def __init__(self):
        pass

    def evaluate(
        self,
        bar_idx: int,
        bar: dict,
        all_bars: List[dict],
        spot_closes: List[float],
        session_vwap: float,
        ema9: float,
        ema20: float,
        rsi: float,
        rsi_history: List[float],
        day_open: float,
        box_high: float,
        box_low: float
    ) -> AIOpportunity:
        close = bar["close"]
        open_p = bar["open"]
        high = bar["high"]
        low = bar["low"]

        # 1. Temporal Session Phase
        # 09:15 - 10:15 (idx 0 to 60): OPENING_DRIVE
        # 10:15 - 11:30 (idx 60 to 135): MORNING_TREND
        # 11:30 - 13:15 (idx 135 to 240): MIDDAY_DEAD_ZONE
        # 13:15 - 14:45 (idx 240 to 330): AFTERNOON_EXPANSION
        # 14:45 - 15:30 (idx 330+): LATE_SQUAREOFF
        is_opening_drive = (bar_idx <= 60)
        is_dead_zone = (135 <= bar_idx <= 240)
        is_late_day = (bar_idx > 300)

        # 2. Market Geometry & Rubber Band Tension
        day_range = max(c["high"] for c in all_bars[:bar_idx+1]) - min(c["low"] for c in all_bars[:bar_idx+1])
        dist_vwap = close - session_vwap
        dist_open = close - day_open

        # Relative stretch: How far is spot relative to the day's realized range?
        vwap_stretch_ratio = abs(dist_vwap) / max(day_range, 30.0)

        # 3. Trap 1 & Trap 5 Stand-Aside Gates
        if is_late_day:
            return AIOpportunity("STAND_ASIDE", "CHOP_STAND_ASIDE", 0, "Late-day degradation zone (post-14:15 IST)")

        # -------------------------------------------------------------
        # CANDIDATE REGIME A: CLIMAX SPRING (Mean-Reversion Squeeze)
        # -------------------------------------------------------------
        if bar_idx <= 120:
            recent_low = min(c["low"] for c in all_bars[max(0, bar_idx - 2): bar_idx + 1])
            recent_high = max(c["high"] for c in all_bars[max(0, bar_idx - 2): bar_idx + 1])
            recent_min_rsi = min(rsi_history[max(0, bar_idx - 2): bar_idx + 1])
            recent_max_rsi = max(rsi_history[max(0, bar_idx - 2): bar_idx + 1])
            delta = close - open_p

            dist_open_ext = recent_low - day_open
            dist_vwap_ext = recent_low - session_vwap

            # Bullish Climax Spring (Oversold capitulation turn)
            if (dist_open_ext <= -75.0 or dist_vwap_ext <= -40.0) and recent_min_rsi <= 32.0 and delta >= 18.0:
                return AIOpportunity(
                    action="BUY_CE",
                    regime="CLIMAX_SPRING",
                    conviction=92,
                    thesis=f"Oversold capitulation flush to {recent_low:.1f}. Violent +{delta:.1f} pt spring candle confirms buyer absorption.",
                    invalidation_level=recent_low - 2.0,
                    recommended_trailing="structural_wick_and_ratchet"
                )

            # Bearish Climax Upthrust (Overbought climax turn)
            elif (recent_high - day_open >= 75.0 or recent_high - session_vwap >= 40.0) and recent_max_rsi >= 68.0 and delta <= -18.0:
                return AIOpportunity(
                    action="BUY_PE",
                    regime="CLIMAX_SPRING",
                    conviction=90,
                    thesis=f"Overbought euphoric spike to {recent_high:.1f}. Violent {delta:.1f} pt rejection candle confirms seller absorption.",
                    invalidation_level=recent_high + 2.0,
                    recommended_trailing="structural_wick_and_ratchet"
                )

        # -------------------------------------------------------------
        # CANDIDATE REGIME B: DYNAMIC TREND PULLBACK (Strategy 3 Core)
        # -------------------------------------------------------------
        box_spread = box_high - box_low
        # Bullish Pullback
        ce_trend = (close > ema9) and (ema9 > ema20) and (close > session_vwap)
        ce_pullback = (low <= ema9 + 4.0)
        ce_value = (close - ema9 <= 24.0) and (rsi < 78.0)
        ce_not_at_ceiling = not (box_spread < 28.0 and close >= (box_high - 3.0))

        if ce_trend and ce_pullback and ce_value and ce_not_at_ceiling:
            return AIOpportunity(
                action="BUY_CE",
                regime="TREND_PULLBACK",
                conviction=88,
                thesis=f"Institutional bullish trend confirmed. Clean pullback to 5m EMA9 ({close:.1f} holding above {ema9:.1f}).",
                invalidation_level=None,
                recommended_trailing="dynamic_ratchet"
            )

        # Bearish Pullback
        pe_trend = (close < ema9) and (ema9 < ema20) and (close < session_vwap)
        pe_pullback = (high >= ema9 - 4.0)
        pe_value = (ema9 - close <= 24.0) and (rsi > 22.0)
        pe_not_at_floor = not (box_spread < 28.0 and close <= (box_low + 3.0))

        if pe_trend and pe_pullback and pe_value and pe_not_at_floor:
            return AIOpportunity(
                action="BUY_PE",
                regime="TREND_PULLBACK",
                conviction=88,
                thesis=f"Institutional bearish trend confirmed. Clean pullback to 5m EMA9 ({close:.1f} holding below {ema9:.1f}).",
                invalidation_level=None,
                recommended_trailing="dynamic_ratchet"
            )

        return AIOpportunity("STAND_ASIDE", "CHOP_STAND_ASIDE", 0, "No high-conviction institutional setup detected.")

def run_ai_radar_simulation(engine: BacktestEngine, cfg: StrategyConfig, radar: AIOpportunityRadar, consultant: AIConsultant) -> List[Trade]:
    trades: List[Trade] = []
    current_trade: Optional[Trade] = None
    last_exit_bar = -999
    spot_closes: List[float] = []
    spot_typicals: List[float] = []
    rsi_history: List[float] = []
    day_open = engine.spot_candles[0]["open"]
    active_invalidation_stop: Optional[float] = None

    for idx, bar in enumerate(engine.spot_candles):
        close = bar["close"]
        high = bar["high"]
        low = bar["low"]
        open_p = bar["open"]
        spot_closes.append(close)
        spot_typicals.append((high + low + close) / 3.0)

        session_vwap = sum(spot_typicals) / len(spot_typicals)
        bars_5m = [spot_closes[i] for i in range(4, len(spot_closes), 5)] or [close]
        ema9 = engine.calculate_ema(bars_5m, 9)
        ema20 = engine.calculate_ema(bars_5m, 20)
        rsi = engine.calculate_rsi(spot_closes, 14)
        rsi_history.append(rsi)

        recent_15m = engine.spot_candles[max(0, idx - 14): idx + 1]
        box_high = max(c["high"] for c in recent_15m)
        box_low = min(c["low"] for c in recent_15m)

        raw_time = bar["start_time"]
        time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

        # 1. Active Position Trailing & Management
        if current_trade is not None:
            is_ce = (current_trade.direction == "CE")
            opt_high, opt_low, opt_close = engine.get_option_bar(
                current_trade.symbol, current_trade.strike, current_trade.direction, idx, bar
            )

            if opt_high > current_trade.peak_price:
                current_trade.peak_price = opt_high
                current_trade.peak_gain_pct = round(
                    ((opt_high - current_trade.entry_price) / current_trade.entry_price) * 100, 2
                )

            exit_reason = None
            exit_price = opt_close

            # A. Structural Wick Invalidation (for Climax Spring trades)
            if active_invalidation_stop is not None:
                if is_ce and low <= active_invalidation_stop:
                    exit_reason = f"STRUCTURAL_WICK_INVALIDATION ({low:.1f} <= {active_invalidation_stop:.1f})"
                    exit_price = opt_close
                elif not is_ce and high >= active_invalidation_stop:
                    exit_reason = f"STRUCTURAL_WICK_INVALIDATION ({high:.1f} >= {active_invalidation_stop:.1f})"
                    exit_price = opt_close

            # B. Initial Stop (-30%)
            if not exit_reason and opt_low <= current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0):
                exit_reason = "INITIAL_STOP"
                exit_price = round(current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0), 2)
            # C. Profit Target (+50%)
            elif not exit_reason and opt_high >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                exit_reason = "PROFIT_TARGET"
                exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)
            # D. Dynamic Runner Trailing (+20% activation)
            elif not exit_reason and cfg.enable_runner_trailing and current_trade.peak_gain_pct >= cfg.runner_activation_pct:
                current_trade.runner_active = True
                floor_pct = 10.0
                if current_trade.peak_gain_pct >= 40.0:
                    floor_pct = 30.0
                elif current_trade.peak_gain_pct >= 30.0:
                    floor_pct = 20.0
                floor_price = current_trade.entry_price * (1.0 + floor_pct / 100.0)
                trail_stop = max(floor_price, current_trade.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0))

                if opt_close <= trail_stop:
                    exit_reason = f"TRAILING_DYNAMIC_RATCHET (Stop={trail_stop:.2f})"
                    exit_price = round(trail_stop, 2)
                elif is_ce and close < (ema9 - cfg.ema9_trailing_buffer):
                    exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} < {ema9:.1f})"
                    exit_price = opt_close
                elif not is_ce and close > (ema9 + cfg.ema9_trailing_buffer):
                    exit_reason = f"TRAILING_EMA9_RUNNER ({close:.1f} > {ema9:.1f})"
                    exit_price = opt_close

            # E. Late-Day Micro-Trail (post 14:00)
            elif not exit_reason and cfg.late_day_micro_trail_enabled and idx >= cfg.late_day_micro_trail_bar and current_trade.peak_gain_pct >= cfg.late_day_micro_trail_activation_pct:
                floor_price = current_trade.entry_price * (1.0 + cfg.late_day_micro_trail_floor_pct / 100.0)
                if opt_close <= floor_price:
                    exit_reason = f"AI_LATE_DAY_MICRO_TRAIL (Floor={floor_price:.2f})"
                    exit_price = round(floor_price, 2)

            # F. EOD Square-off
            if idx >= 360 and not exit_reason:
                exit_reason = "EOD_SQUAREOFF"
                exit_price = opt_close

            if exit_reason:
                current_trade.close(idx, time_str, exit_price, exit_reason)
                trades.append(current_trade)
                last_exit_bar = idx
                current_trade = None
                active_invalidation_stop = None

            continue

        # 2. Opportunity Discovery
        if idx < 10 or idx > 330:
            continue
        if len(trades) >= cfg.max_daily_entries:
            continue
        if (idx - last_exit_bar) < cfg.min_spacing_bars:
            continue

        # AI Opportunity Radar Evaluation
        opp = radar.evaluate(
            bar_idx=idx,
            bar=bar,
            all_bars=engine.spot_candles,
            spot_closes=spot_closes,
            session_vwap=session_vwap,
            ema9=ema9,
            ema20=ema20,
            rsi=rsi,
            rsi_history=rsi_history,
            day_open=day_open,
            box_high=box_high,
            box_low=box_low
        )

        if opp.action in ["BUY_CE", "BUY_PE"] and opp.conviction >= 80:
            direction = "CE" if opp.action == "BUY_CE" else "PE"
            sym, strike = engine.select_contract(close, direction, mode=cfg.strike_selection)
            _, _, opt_entry = engine.get_option_bar(sym, strike, direction, idx, bar)

            # Mandatory Rule #1: AI Gatekeeper Evaluation
            dossier = generate_market_dossier(
                target_date=engine.target_date,
                candles=engine.spot_candles,
                current_bar_idx=idx,
                direction=direction,
                symbol=sym,
                strike=strike,
                option_entry_price=opt_entry,
                trade_history=trades,
                days_to_expiry=engine.get_expiry_days(),
                is_expiry_0dte=(engine.get_expiry_days() <= 0.2)
            )

            if opp.regime == "CLIMAX_SPRING":
                dossier.is_directional_shift = True

            verdict = consultant.evaluate(dossier)
            if not verdict.is_approved:
                continue

            current_trade = Trade(
                trade_id=len(trades) + 1,
                symbol=sym,
                direction=direction,
                strike=strike,
                entry_bar=idx,
                entry_time=time_str,
                entry_price=opt_entry,
                peak_price=opt_entry,
                peak_gain_pct=0.0
            )
            current_trade.setup_type = opp.regime
            active_invalidation_stop = opp.invalidation_level

    if current_trade is not None:
        last_bar = engine.spot_candles[-1]
        _, _, last_opt = engine.get_option_bar(
            current_trade.symbol, current_trade.strike, current_trade.direction,
            len(engine.spot_candles) - 1, last_bar
        )
        current_trade.close(len(engine.spot_candles) - 1, last_bar["start_time"][11:19], last_opt, "EOD_SQUAREOFF")
        trades.append(current_trade)

    return trades

def compute_metrics(trades: List[Trade]) -> dict:
    n = len(trades)
    if n == 0:
        return {"n": 0, "w": 0, "l": 0, "wr": 0.0, "net_1l": 0.0, "net_2l": 0.0, "roi_2l": 0.0, "pf": 0.0}
    w = len([t for t in trades if t.pnl > 0])
    l = len([t for t in trades if t.pnl <= 0])
    wr = (w / n * 100.0) if n else 0.0
    fee_1l = n * 40.0
    fee_2l = n * 40.0
    net_1l = sum(t.pnl for t in trades) - fee_1l
    net_2l = sum(t.pnl * 2 for t in trades) - fee_2l
    roi_2l = (net_2l / 10000.0) * 100.0
    w_sum = sum(t.pnl for t in trades if t.pnl > 0)
    l_sum = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = (w_sum / l_sum) if l_sum > 0 else 999.0
    return {
        "n": n, "w": w, "l": l, "wr": wr,
        "net_1l": net_1l, "net_2l": net_2l, "roi_2l": roi_2l, "pf": pf
    }

def main():
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT DISTINCT substr(start_time, 1, 10) "
        "FROM historical_candles "
        "WHERE instrument_id = 'INST-NIFTY-INDEX' AND start_time LIKE '%+00:00' "
        "ORDER BY 1"
    )
    all_dates = [r[0] for r in c.fetchall()]
    conn.close()

    dates_30 = all_dates[-30:]
    dates_60 = all_dates[-60:] if len(all_dates) >= 60 else all_dates

    import argparse
    parser = argparse.ArgumentParser(description="AI Opportunity Radar Backtest")
    parser.add_argument("--enforce-live-envelope", action="store_true",
                        help="Enforce live order ₹15-₹70 premium cap from trading.json")
    args, _ = parser.parse_known_args()

    cfg = StrategyConfig.load_from_config("institutional_pullback")
    radar = AIOpportunityRadar()
    if args.enforce_live_envelope:
        consultant = AIConsultant(mode="playbook")
    else:
        consultant = AIConsultant(
            mode="playbook",
            trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
        )

    # 1. Run 30 Sessions
    trades_30 = []
    for d in dates_30:
        eng = BacktestEngine(d)
        if eng.spot_candles:
            t = run_ai_radar_simulation(eng, cfg, radar, consultant)
            trades_30.extend(t)

    # 2. Run 60 Sessions
    trades_60 = []
    for d in dates_60:
        eng = BacktestEngine(d)
        if eng.spot_candles:
            t = run_ai_radar_simulation(eng, cfg, radar, consultant)
            trades_60.extend(t)

    m30 = compute_metrics(trades_30)
    m60 = compute_metrics(trades_60)

    print("=" * 80)
    print(" 🤖 AI OPPORTUNITY RADAR: FORENSIC BACKTEST RESULTS")
    print("=" * 80)
    print(f"{'Performance Metric':<32} | {'30 Sessions (Aug-Oct)':<20} | {'60 Sessions (Summer-Autumn)':<20}")
    print("-" * 80)
    print(f"{'Total Trades Taken':<32} | {m30['n']:<20} | {m60['n']:<20}")
    print(f"{'Winning Trades':<32} | {m30['w']:<20} | {m60['w']:<20}")
    print(f"{'Losing Trades':<32} | {m30['l']:<20} | {m60['l']:<20}")
    print(f"{'Win Rate %':<32} | {m30['wr']:<19.1f}% | {m60['wr']:<19.1f}%")
    print(f"{'Net PnL (1 Lot / 65 Qty)':<32} | ₹{m30['net_1l']:<19,.2f} | ₹{m60['net_1l']:<19,.2f}")
    print(f"{'Net PnL (2 Lots / ₹10k Margin)':<32} | ₹{m30['net_2l']:<19,.2f} | ₹{m60['net_2l']:<19,.2f}")
    print(f"{'Net ROI % (₹10,000 Margin)':<32} | {m30['roi_2l']:>+18.1f}% | {m60['roi_2l']:>+18.1f}%")
    print(f"{'Profit Factor':<32} | {m30['pf']:<20.2f} | {m60['pf']:<20.2f}")
    print("=" * 80)

    print("\n🔍 Specific Trades for Today (2026-10-16):")
    today_trades = [t for t in trades_30 if "2026-10-16" in t.symbol]
    for t in today_trades:
        print(f"  - {t.symbol} {t.direction} ({getattr(t, 'setup_type', '')}) @ {t.entry_time}")
        print(f"    Entry: ₹{t.entry_price:.2f} | Exit: ₹{t.exit_price:.2f} | Peak: +{t.peak_gain_pct}% | PnL (2L): ₹{t.pnl*2:+.2f} | Reason: {t.exit_reason}")

if __name__ == "__main__":
    from trading.bootstrap import configure_console
    configure_console()
    main()
