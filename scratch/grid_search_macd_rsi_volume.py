import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
from types import SimpleNamespace
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
import itertools

import json
from pathlib import Path
from market_clock import MarketClock
from trading.domain.sizing import calculate_compounding_quantity
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
from scratch.deep_dive_trap7 import load_data, resample_bars, calculate_ema, calculate_macd, calculate_sma, calculate_rsi, simulate_trade_raw, DATES

def precompute_market_data():
    """Precomputes 2m indicators across all 6 sessions for fast grid simulation."""
    sessions = []

    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_data(dt_str)
        if not spot_bars or not fut_bars or len(spot_bars) < 60:
            continue

        res_spot = resample_bars(spot_bars, 2)
        res_fut = resample_bars(fut_bars, 2)

        closes = [b["close"] for b in res_spot]
        macd, sig, hist = calculate_macd(closes)
        rsi_2m = calculate_rsi(closes, 14)
        rsi_1m = calculate_rsi([b["close"] for b in spot_bars], 14)

        fut_vols = [b["volume"] for b in res_fut]
        fut_sma_vols = calculate_sma(fut_vols, 20)

        # 2m resampled option candles
        res_opt = {}
        opt_sma_vols = {}
        for key in opt_candles.contracts:
            bars = opt_candles.series(*key)
            if len(bars) >= 60:
                res_opt[key] = resample_bars(bars, 2)
                opt_sma_vols[key] = calculate_sma([b["volume"] for b in res_opt[key]], 20)

        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        if target_d.weekday() <= 1:
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
        else:
            expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)

        sessions.append({
            "date": dt_str,
            "label": dt_label,
            "spot_bars": spot_bars,
            "fut_bars": fut_bars,
            "opt_candles": opt_candles,
            "res_spot": res_spot,
            "res_fut": res_fut,
            "res_opt": res_opt,
            "opt_sma_vols": opt_sma_vols,
            "closes": closes,
            "macd": macd,
            "sig": sig,
            "hist": hist,
            "rsi_2m": rsi_2m,
            "rsi_1m": rsi_1m,
            "fut_vols": fut_vols,
            "fut_sma_vols": fut_sma_vols,
            "days_base": days_base,
            "is_0dte": is_0dte
        })

    return sessions

def run_simulation(sessions, macd_mode: str, rsi_mode: str, rsi_tf: str, vol_mode: str, vol_thresh: float) -> Dict:
    trading_cfg = json.loads(Path("config/trading.json").read_text(encoding="utf-8"))
    strategy_cfg = json.loads(Path("config/strategies.json").read_text(encoding="utf-8"))["strategies"]["macd_momentum"]
    ai = AIConsultant(mode="rules", trading_config=trading_cfg)
    all_trades = []
    capital = peak_capital = 10000.0
    max_drawdown_pct = 0.0
    missing_contracts = 0

    for s in sessions:
        dt_str = s["date"]
        spot_bars = s["spot_bars"]
        opt_candles = s["opt_candles"]
        res_spot = s["res_spot"]
        macd = s["macd"]
        sig = s["sig"]
        hist = s["hist"]
        rsi_series = s["rsi_2m"] if rsi_tf == "2m" else s["rsi_1m"]
        fut_vols = s["fut_vols"]
        fut_sma_vols = s["fut_sma_vols"]
        res_opt = s["res_opt"]
        opt_sma_vols = s["opt_sma_vols"]
        days_base = s["days_base"]
        is_0dte = s["is_0dte"]

        daily_trades = []
        busy_until_1m_idx = -1

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]

            if end_1m <= busy_until_1m_idx:
                continue

            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])

            if not (pe_cross or ce_cross):
                continue

            direction = "PE" if pe_cross else "CE"
            spot_price = res_spot[i]["close"]
            target_strike = int(round(spot_price / 50.0)) * 50
            selected_bar = opt_candles.bar(target_strike, direction, spot_bars[end_1m]["start_time"])
            if selected_bar is None:
                missing_contracts += 1
                continue

            # -------------------------------------------------------------
            # 1. MACD Rule Filter
            # -------------------------------------------------------------
            if macd_mode == "raw":
                pass
            elif macd_mode == "hist_accel":
                # For CE, histogram must be expanding upward; for PE, expanding downward
                if direction == "CE" and hist[i] <= hist[i - 1]:
                    continue
                if direction == "PE" and hist[i] >= hist[i - 1]:
                    continue
            elif macd_mode == "reversal_bias":
                # CE must cross below zero line (inflection), PE must cross above zero line
                if direction == "CE" and macd[i] > 2.0:
                    continue
                if direction == "PE" and macd[i] < -2.0:
                    continue

            # -------------------------------------------------------------
            # 2. RSI Rule Filter
            # -------------------------------------------------------------
            rsi_val = rsi_series[i] if rsi_tf == "2m" else (rsi_series[end_1m] if end_1m < len(rsi_series) else 50.0)

            if rsi_mode == "none":
                pass
            elif rsi_mode == "midline_50":
                # CE requires RSI >= 50, PE requires RSI <= 50
                if direction == "CE" and rsi_val < 50.0:
                    continue
                if direction == "PE" and rsi_val > 50.0:
                    continue
            elif rsi_mode == "sweet_spot":
                # CE between 40 and 68 (not overbought top), PE between 32 and 60 (not oversold bottom)
                if direction == "CE" and not (40.0 <= rsi_val <= 68.0):
                    continue
                if direction == "PE" and not (32.0 <= rsi_val <= 60.0):
                    continue
            elif rsi_mode == "momentum_band":
                # CE between 50 and 70, PE between 30 and 50
                if direction == "CE" and not (50.0 <= rsi_val <= 70.0):
                    continue
                if direction == "PE" and not (30.0 <= rsi_val <= 50.0):
                    continue

            # -------------------------------------------------------------
            # 3. Volume Rule Filter
            # -------------------------------------------------------------
            f_vr = fut_vols[i] / fut_sma_vols[i] if (i < len(fut_sma_vols) and fut_sma_vols[i] > 0) else 1.0

            o_vr = 0.0
            key = (target_strike, direction)
            if key in res_opt:
                oi = next((j for j, b in enumerate(res_opt[key])
                           if b["start_time"] == res_spot[i]["start_time"]), None)
                if oi is not None and opt_sma_vols[key][oi] > 0:
                    o_vr = res_opt[key][oi]["volume"] / opt_sma_vols[key][oi]

            if vol_mode == "none":
                pass
            elif vol_mode == "futures":
                if f_vr < vol_thresh:
                    continue
            elif vol_mode == "option":
                if o_vr < vol_thresh:
                    continue
            elif vol_mode == "either":
                if f_vr < vol_thresh and o_vr < vol_thresh:
                    continue
            elif vol_mode == "both":
                if f_vr < vol_thresh or o_vr < vol_thresh:
                    continue

            # -------------------------------------------------------------
            # 4. Pricing & Gatekeeper Evaluation
            # -------------------------------------------------------------
            spot_price = res_spot[i]["close"]
            target_strike = int(round(spot_price / 50.0)) * 50
            days_rem = days_base - (end_1m / 375.0) * 0.25

            est_opt_price = selected_bar["close"]

            dossier = generate_market_dossier(
                target_date=dt_str,
                candles=spot_bars,
                current_bar_idx=end_1m,
                direction=direction,
                symbol=f"NIFTY_{target_strike}_{direction}",
                strike=target_strike,
                option_entry_price=est_opt_price,
                trade_history=daily_trades,
                days_to_expiry=days_rem,
                is_expiry_0dte=is_0dte
            )

            signal_time = MarketClock.parse_to_ist(spot_bars[end_1m]["start_time"]) + timedelta(minutes=1)
            if signal_time.strftime("%H:%M") >= "14:15":
                continue
            with MarketClock.at(signal_time):
                verdict: AIVerdict = ai.evaluate(dossier)

            if verdict.is_approved and verdict.action == "APPROVED" and not verdict.trap_detected:
                tr_sim = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)
                if tr_sim:
                    if not verdict.min_entry_price <= tr_sim["entry_price"] <= verdict.max_entry_price:
                        continue
                    qty = calculate_compounding_quantity(capital, tr_sim["entry_price"],
                        strategy_cfg=strategy_cfg, trading_cfg=trading_cfg, quantity=130)
                    if qty <= 0:
                        continue
                    lots = qty // 65
                    net = tr_sim["pnl_pts"] * qty - (40.0 + lots * 25.0)
                    capital += net
                    peak_capital = max(peak_capital, capital)
                    max_drawdown_pct = max(max_drawdown_pct, (peak_capital - capital) / peak_capital * 100)
                    busy_until_1m_idx = tr_sim["exit_idx"]
                    daily_trades.append(SimpleNamespace(
                        direction=direction,
                        pnl=net,
                        exit_price=tr_sim["exit_price"]
                    ))
                    all_trades.append({
                        "date": dt_str,
                        "entry_idx": end_1m,
                        "direction": direction,
                        "strike": target_strike,
                        "entry_price": tr_sim["entry_price"],
                        "exit_price": tr_sim["exit_price"],
                        "cost_per_lot": tr_sim["entry_price"] * 65.0,
                        "pts": tr_sim["exit_price"] - tr_sim["entry_price"],
                        "pnl_2l": tr_sim["pnl_pts"] * 130,
                        "net_pnl": net
                    })

    n = len(all_trades)
    if n == 0:
        return {
            "n": 0, "wr": 0.0, "net_2l": 0.0, "capital": 10000.0,
            "comp_pnl": 0.0, "roi": 0.0, "pf": 0.0, "max_dd": 0.0,
            "missing_contracts": missing_contracts, "ai_used": False
        }

    wins = [t for t in all_trades if t["net_pnl"] > 0]
    losses = [t for t in all_trades if t["net_pnl"] <= 0]
    w_pnl = sum(t["net_pnl"] for t in wins)
    l_pnl = sum(abs(t["net_pnl"]) for t in losses)
    pf = (w_pnl / l_pnl) if l_pnl > 0 else 99.9
    net_2l = sum(t["pnl_2l"] for t in all_trades)
    comp_pnl = capital - 10000.0
    roi = (comp_pnl / 10000.0) * 100.0
    wr = (len(wins) / n) * 100.0

    return {
        "n": n,
        "wins": len(wins),
        "losses": len(losses),
        "wr": round(wr, 1),
        "net_2l": round(net_2l, 2),
        "capital": round(capital, 2),
        "comp_pnl": round(comp_pnl, 2),
        "roi": round(roi, 1),
        "pf": round(pf, 2),
        "max_dd": round(max_drawdown_pct, 1),
        "missing_contracts": missing_contracts, "ai_used": False
    }

def main():
    print("Precomputing indicators for 6 trading sessions...")
    sessions = precompute_market_data()
    print(f"Loaded {len(sessions)} sessions successfully.\n")

    macd_options = [
        ("raw", "Raw Cross"),
        ("hist_accel", "Hist Expanding")
    ]

    rsi_options = [
        ("none", "2m", "No RSI"),
        ("midline_50", "2m", "2m RSI > 50 (CE) / < 50 (PE)"),
        ("sweet_spot", "2m", "2m RSI 40-68 (CE) / 32-60 (PE)"),
        ("momentum_band", "2m", "2m RSI 50-70 (CE) / 30-50 (PE)"),
        ("midline_50", "1m", "1m RSI > 50 (CE) / < 50 (PE)"),
        ("sweet_spot", "1m", "1m RSI 40-68 (CE) / 32-60 (PE)")
    ]

    vol_options = [
        ("none", 1.0, "No Volume Filter"),
        ("futures", 1.15, "Fut Vol >= 1.15x"),
        ("futures", 1.30, "Fut Vol >= 1.30x"),
        ("option", 1.15, "Opt Vol >= 1.15x"),
        ("option", 1.30, "Opt Vol >= 1.30x"),
        ("either", 1.15, "Either Fut/Opt >= 1.15x"),
        ("either", 1.25, "Either Fut/Opt >= 1.25x"),
        ("both", 1.15, "Both Fut & Opt >= 1.15x")
    ]

    results = []

    print(f"Executing Grid Search across {len(macd_options) * len(rsi_options) * len(vol_options)} combinations...")
    for (m_code, m_lbl) in macd_options:
        for (r_code, r_tf, r_lbl) in rsi_options:
            for (v_code, v_th, v_lbl) in vol_options:
                res = run_simulation(sessions, m_code, r_code, r_tf, v_code, v_th)
                results.append({
                    "macd": m_lbl,
                    "rsi": r_lbl,
                    "volume": v_lbl,
                    **res
                })

    # Sort by Compounding Net P&L descending
    results.sort(key=lambda x: x["comp_pnl"], reverse=True)

    print("\n" + "=" * 135)
    print(" 🏆 TOP 15 MATHEMATICALLY OPTIMAL COMBINATIONS (OCT 19 - OCT 27, 2026)")
    print("=" * 135)
    print(f"{'#':<3} | {'MACD Rule':<16} | {'RSI Rule':<33} | {'Volume Rule':<25} | {'Trades':<6} | {'Win%':<6} | {'Comp PnL (₹)':<14} | {'ROI %':<9} | {'Max DD%':<8} | {'PF':<5}")
    print("-" * 135)

    for i, r in enumerate(results[:15], 1):
        print(f"{i:<3} | {r['macd']:<16} | {r['rsi']:<33} | {r['volume']:<25} | {r['n']:<6} | {r['wr']:<5.1f}% | ₹{r['comp_pnl']:<13,.2f} | {r['roi']:<+8.1f}% | {r['max_dd']:<7.1f}% | {r['pf']:<5.2f}")

    print("\n" + "=" * 135)
    print(" 📊 WORST 5 COMBINATIONS (WHAT OVER-FILTERING OR UNDER-FILTERING CAUSES)")
    print("=" * 135)
    print(f"{'#':<3} | {'MACD Rule':<16} | {'RSI Rule':<33} | {'Volume Rule':<25} | {'Trades':<6} | {'Win%':<6} | {'Comp PnL (₹)':<14} | {'ROI %':<9} | {'Max DD%':<8} | {'PF':<5}")
    print("-" * 135)
    for i, r in enumerate(results[-5:], 1):
        print(f"{i:<3} | {r['macd']:<16} | {r['rsi']:<33} | {r['volume']:<25} | {r['n']:<6} | {r['wr']:<5.1f}% | ₹{r['comp_pnl']:<13,.2f} | {r['roi']:<+8.1f}% | {r['max_dd']:<7.1f}% | {r['pf']:<5.2f}")

    # Dimension Sensitivity Summary
    print("\n" + "=" * 80)
    print(" 🔬 DIMENSION SENSITIVITY BREAKDOWN (AVERAGE PERFORMANCE BY FILTER)")
    print("=" * 80)

    def print_avg_group(group_key, title):
        print(f"\n--- {title} ---")
        grouped = {}
        for r in results:
            k = r[group_key]
            if k not in grouped:
                grouped[k] = []
            grouped[k].append(r)

        print(f"{'Variant':<35} | {'Avg Trades':<11} | {'Avg Win%':<9} | {'Avg Comp PnL (₹)':<18} | {'Avg PF':<7}")
        print("-" * 80)
        for k, items in sorted(grouped.items(), key=lambda x: sum(y['comp_pnl'] for y in x[1])/len(x[1]), reverse=True):
            avg_n = sum(y['n'] for y in items) / len(items)
            avg_wr = sum(y['wr'] for y in items) / len(items)
            avg_pnl = sum(y['comp_pnl'] for y in items) / len(items)
            avg_pf = sum(y['pf'] for y in items) / len(items)
            print(f"{k:<35} | {avg_n:<11.1f} | {avg_wr:<8.1f}% | ₹{avg_pnl:<17,.2f} | {avg_pf:<6.2f}")

    print_avg_group("macd", "MACD Rule Impact")
    print_avg_group("rsi", "RSI Rule Impact")
    print_avg_group("volume", "Volume Rule Impact")

if __name__ == "__main__":
    main()
