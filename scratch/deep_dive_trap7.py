import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from backtest_engine import bsm_price
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
from pathlib import Path
from market_clock import MarketClock
from trading.adapters.historical import load_option_history, OptionHistory
from trading.application.dossier import DossierService
from trading.domain.historical_execution import simulate_option_path
from trading.domain.market_data import resample_two_minutes

DATES = [
    ("2026-10-19", "Mon Oct 19"),
    ("2026-10-21", "Wed Oct 21"),
    ("2026-10-22", "Thu Oct 22"),
    ("2026-10-23", "Fri Oct 23"),
    ("2026-10-26", "Mon Oct 26"),
    ("2026-10-27", "Tue Oct 27 (0DTE)")
]

def load_data(date_str: str):
    spot_file = f"data/spot_candles_{date_str.replace('-', '')}.json"
    fut_file = f"data/fut_candles_{date_str.replace('-', '')}.json"
    if not os.path.exists(spot_file) or not os.path.exists(fut_file):
        return None, None, None
    with open(spot_file, "r") as fp:
        spot_bars = json.load(fp)
    with open(fut_file, "r") as fp:
        fut_bars = json.load(fp)
    cfg = json.loads(Path("config/trading.json").read_text(encoding="utf-8"))
    with MarketClock.at(date_str + "T09:15:00+05:30"):
        expiry = (MarketClock.now_ist().date() + timedelta(days=DossierService(cfg).get_days_to_expiry())).isoformat()
    opt_candles = load_option_history(date_str, expiry)
    if opt_candles.excluded_files:
        print(f"{date_str}: excluded {len(opt_candles.excluded_files)} option files without verified contract metadata")
    return spot_bars, fut_bars, opt_candles


def resample_bars(bars_1m: List[Dict], interval_min: int) -> List[Dict]:
    if interval_min == 2:
        return resample_two_minutes(bars_1m)
    resampled = []
    for i in range(0, len(bars_1m), interval_min):
        group = bars_1m[i:i + interval_min]
        if not group:
            continue
        resampled.append({
            "start_time": group[0]["start_time"],
            "open": group[0]["open"],
            "high": max(b["high"] for b in group),
            "low": min(b["low"] for b in group),
            "close": group[-1]["close"],
            "volume": sum(b.get("volume", 0.0) for b in group),
            "minute_idx": i + len(group) - 1
        })
    return resampled

def calculate_ema(series: List[float], period: int) -> List[float]:
    if not series:
        return []
    res = [series[0]]
    mult = 2.0 / (period + 1.0)
    for v in series[1:]:
        res.append(v * mult + res[-1] * (1.0 - mult))
    return res

def calculate_macd(closes: List[float]) -> Tuple[List[float], List[float], List[float]]:
    if len(closes) < 26:
        zeros = [0.0] * len(closes)
        return zeros, zeros, zeros
    fast = calculate_ema(closes, 12)
    slow = calculate_ema(closes, 26)
    macd_line = [f - s for f, s in zip(fast, slow)]
    signal_line = calculate_ema(macd_line, 9)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist

def calculate_sma(series: List[float], period: int = 20) -> List[float]:
    res = []
    for i in range(len(series)):
        start_idx = max(0, i - period + 1)
        sub = series[start_idx: i + 1]
        res.append(sum(sub) / len(sub) if sub else 0.0)
    return res

def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
    if len(closes) <= period:
        return [50.0] * len(closes)
    gains = []
    losses = []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))

    rsi_vals = [50.0] * (period)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_vals.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
    rsi_vals.insert(0, 50.0)
    return rsi_vals

def simulate_trade_raw(entry_1m_idx, direction, spot_bars_1m, opt_candles_1m, target_date):
    """Exact-contract OHLC estimate; caller must first obtain consultant approval."""
    if not isinstance(opt_candles_1m, OptionHistory):
        raise ValueError("Use load_data() and verified option metadata; direction-only histories are unsupported")
    strike = int(round(spot_bars_1m[entry_1m_idx]["close"] / 50.0)) * 50
    config = json.loads(Path("config/strategies.json").read_text(encoding="utf-8"))["strategies"]["macd_momentum"]
    trade = simulate_option_path(entry_1m_idx, direction, spot_bars_1m, opt_candles_1m, strike, config["exit"])
    return dict(trade, date=target_date) if trade else None


def analyze_trap7_trades():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    trap7_trades = []

    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_data(dt_str)
        if not spot_bars or not fut_bars or len(spot_bars) < 60:
            continue

        res_spot = resample_bars(spot_bars, 2)
        res_fut = resample_bars(fut_bars, 2)

        closes = [b["close"] for b in res_spot]
        macd, sig, hist = calculate_macd(closes)
        rsi_2m = calculate_rsi(closes, 14)
        vols = [b["volume"] for b in res_fut]
        sma_vols = calculate_sma(vols, 20)

        target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
        if target_d.weekday() <= 1:
            expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
        else:
            expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
        days_base = max(0.1, float((expiry_d - target_d).days))
        is_0dte = (target_d.weekday() == 1)

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]

            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])

            if not (pe_cross or ce_cross):
                continue

            direction = "PE" if pe_cross else "CE"
            spot_price = res_spot[i]["close"]
            target_strike = int(round(spot_price / 50.0)) * 50
            vr = vols[i] / sma_vols[i] if (i < len(sma_vols) and sma_vols[i] > 0) else 1.0
            days_rem = days_base - (end_1m / 375.0) * 0.25

            selected_bar = opt_candles.bar(target_strike, direction, spot_bars[end_1m]["start_time"])
            if selected_bar is None:
                continue  # Never substitute a different strike or synthetic option price.
            est_opt_price = selected_bar["close"]

            # Build dossier
            dossier = generate_market_dossier(
                target_date=dt_str,
                candles=spot_bars,
                current_bar_idx=end_1m,
                direction=direction,
                symbol=f"NIFTY_{target_strike}_{direction}",
                strike=target_strike,
                option_entry_price=est_opt_price,
                trade_history=[],
                days_to_expiry=days_rem,
                is_expiry_0dte=is_0dte
            )

            # Evaluate AI consultant
            verdict: AIVerdict = ai.evaluate(dossier)

            # Check if this trade was vetoed by Trap 7
            if verdict.trap_detected and "Trap 7" in verdict.trap_detected:
                tr_sim = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)
                hh = end_1m // 60 + 9
                mm = end_1m % 60
                time_str = f"{hh:02d}:{mm:02d}"

                trap7_trades.append({
                    "date": dt_str,
                    "time": time_str,
                    "direction": direction,
                    "strike": target_strike,
                    "spot": spot_price,
                    "opt_price": est_opt_price,
                    "vwap": dossier.session_vwap,
                    "vwap_slope_15m": dossier.vwap_slope_15m,
                    "vwap_distance_pts": dossier.vwap_distance_pts,
                    "spot_minus_vwap": spot_price - dossier.session_vwap,
                    "ema_spread_5m": dossier.ema_spread_5m,
                    "rsi_1m": dossier.rsi_1m,
                    "rsi_2m": rsi_2m[i] if i < len(rsi_2m) else 50.0,
                    "macd_hist": hist[i],
                    "macd_hist_delta": hist[i] - hist[i-1],
                    "vol_ratio_fut": vr,
                    "pnl_inr": tr_sim["pnl_inr"] if tr_sim else 0.0,
                    "ret_pct": tr_sim["ret_pct"] if tr_sim else 0.0,
                    "peak_gain_pct": tr_sim["peak_gain_pct"] if tr_sim else 0.0,
                    "exit_reason": tr_sim["exit_reason"] if tr_sim else "N/A"
                })

    print(f"\nAUDITED {len(trap7_trades)} CANDIDATES VETOED BY TRAP 7:\n")
    winners = [t for t in trap7_trades if t["pnl_inr"] > 0]
    losers = [t for t in trap7_trades if t["pnl_inr"] <= 0]

    print(f"WINNERS ({len(winners)} trades, Total PnL: Rs {sum(w['pnl_inr'] for w in winners):,.2f}):")
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'Spot':<8} | {'VWAP':<8} | {'Slope':<7} | {'Spot-VWAP':<9} | {'V-Dist':<6} | {'EMA-Sprd':<8} | {'RSI-1m':<6} | {'RSI-2m':<6} | {'Fut-Vol':<7} | {'Peak%':<6} | {'PnL (Rs)':<9}")
    print("-" * 135)
    for w in sorted(winners, key=lambda x: x["pnl_inr"], reverse=True):
        print(f"{w['date']:<10} | {w['time']:<5} | {w['direction']:<3} | {w['spot']:<8.1f} | {w['vwap']:<8.1f} | {w['vwap_slope_15m']:<+7.3f} | {w['spot_minus_vwap']:<+9.1f} | {w['vwap_distance_pts']:<6.1f} | {w['ema_spread_5m']:<+8.1f} | {w['rsi_1m']:<6.1f} | {w['rsi_2m']:<6.1f} | {w['vol_ratio_fut']:<6.2f}x | +{w['peak_gain_pct']:<5.1f}% | Rs {w['pnl_inr']:<8.1f}")

    print(f"\nLOSERS ({len(losers)} trades, Total Loss: Rs {sum(l['pnl_inr'] for l in losers):,.2f}):")
    print(f"{'Date':<10} | {'Time':<5} | {'Dir':<3} | {'Spot':<8} | {'VWAP':<8} | {'Slope':<7} | {'Spot-VWAP':<9} | {'V-Dist':<6} | {'EMA-Sprd':<8} | {'RSI-1m':<6} | {'RSI-2m':<6} | {'Fut-Vol':<7} | {'Peak%':<6} | {'PnL (Rs)':<9}")
    print("-" * 135)
    for l in sorted(losers, key=lambda x: x["pnl_inr"]):
        print(f"{l['date']:<10} | {l['time']:<5} | {l['direction']:<3} | {l['spot']:<8.1f} | {l['vwap']:<8.1f} | {l['vwap_slope_15m']:<+7.3f} | {l['spot_minus_vwap']:<+9.1f} | {l['vwap_distance_pts']:<6.1f} | {l['ema_spread_5m']:<+8.1f} | {l['rsi_1m']:<6.1f} | {l['rsi_2m']:<6.1f} | {l['vol_ratio_fut']:<6.2f}x | +{l['peak_gain_pct']:<5.1f}% | Rs {l['pnl_inr']:<8.1f}")

    # Summary statistics comparison
    print("\n" + "=" * 80)
    print(" STATISTICAL FEATURE COMPARISON: WINNERS vs LOSERS")
    print("=" * 80)
    def avg(lst, key):
        return sum(x[key] for x in lst) / len(lst) if lst else 0.0

    print(f"{'Feature':<30} | {'Winners (N=' + str(len(winners)) + ')':<20} | {'Losers (N=' + str(len(losers)) + ')':<20}")
    print("-" * 80)
    print(f"{'Avg |VWAP Slope|':<30} | {avg(winners, 'vwap_slope_15m'):<+20.3f} | {avg(losers, 'vwap_slope_15m'):<+20.3f}")
    print(f"{'Avg Absolute Slope |slope|':<30} | {sum(abs(x['vwap_slope_15m']) for x in winners)/len(winners):<20.3f} | {sum(abs(x['vwap_slope_15m']) for x in losers)/len(losers):<20.3f}")
    print(f"{'Avg Spot Distance to VWAP':<30} | {avg(winners, 'vwap_distance_pts'):<20.1f} pts | {avg(losers, 'vwap_distance_pts'):<20.1f} pts")
    print(f"{'Avg Futures Vol Ratio':<30} | {avg(winners, 'vol_ratio_fut'):<20.2f}x | {avg(losers, 'vol_ratio_fut'):<20.2f}x")
    print(f"{'Avg 1m RSI':<30} | {avg(winners, 'rsi_1m'):<20.1f} | {avg(losers, 'rsi_1m'):<20.1f}")
    print(f"{'Avg 2m RSI':<30} | {avg(winners, 'rsi_2m'):<20.1f} | {avg(losers, 'rsi_2m'):<20.1f}")
    print(f"{'Avg MACD Hist Delta':<30} | {avg(winners, 'macd_hist_delta'):<+20.3f} | {avg(losers, 'macd_hist_delta'):<+20.3f}")

if __name__ == "__main__":
    analyze_trap7_trades()
