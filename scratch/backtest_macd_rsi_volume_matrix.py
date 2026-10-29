import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Tuple, Optional
from backtest_engine import BacktestEngine, StrategyConfig, bsm_price, select_strike

DATES = [
    ("2026-10-19", "Mon Oct 19"),
    ("2026-10-21", "Wed Oct 21"),
    ("2026-10-22", "Thu Oct 22"),
    ("2026-10-23", "Fri Oct 23"),
    ("2026-10-26", "Mon Oct 26"),
    ("2026-10-27", "Tue Oct 27 (0DTE)")
]

def load_day_data(date_str: str):
    # Spot candles
    spot_file = f"data/spot_candles_{date_str.replace('-', '')}.json"
    if not os.path.exists(spot_file):
        return None, None, None
    with open(spot_file, "r") as fp:
        spot_bars = json.load(fp)

    # Futures candles
    fut_file = f"data/fut_candles_{date_str.replace('-', '')}.json"
    fut_bars = None
    if os.path.exists(fut_file):
        with open(fut_file, "r") as fp:
            fut_bars = json.load(fp)

    # Option candles cache
    opt_candles = {}
    for right in ["CE", "PE"]:
        for f in os.listdir("data"):
            if f.startswith(f"opt_{date_str.replace('-', '')}_") and f.endswith(f"_{right}.json"):
                with open(os.path.join("data", f), "r") as fp:
                    opt_candles[right] = json.load(fp)
                break

    return spot_bars, fut_bars, opt_candles

def resample_bars(bars_1m: List[Dict], interval_min: int) -> List[Dict]:
    if interval_min == 1:
        for idx, b in enumerate(bars_1m):
            b["minute_idx"] = idx
        return bars_1m
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
            "minute_idx": i + len(group) - 1 # 1m index when this bar closed
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

def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
    res = [50.0] * len(closes)
    if len(closes) <= period:
        return res
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(0.0, d) for d in deltas]
    losses = [max(0.0, -d) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rs = avg_gain / avg_loss if avg_loss > 0 else 100.0
        res[i + 1] = round(100.0 - (100.0 / (1.0 + rs)), 1)
    return res

def calculate_sma(series: List[float], period: int = 20) -> List[float]:
    res = []
    for i in range(len(series)):
        start_idx = max(0, i - period + 1)
        sub = series[start_idx: i + 1]
        res.append(sum(sub) / len(sub) if sub else 0.0)
    return res

def simulate_trade(
    entry_1m_idx: int,
    direction: str,
    spot_bars_1m: List[Dict],
    opt_candles_1m: Dict[str, List[Dict]],
    target_date: str
) -> Optional[Dict]:
    if entry_1m_idx >= 360 or entry_1m_idx >= len(spot_bars_1m) - 1:
        return None

    spot_entry = spot_bars_1m[entry_1m_idx]["close"]
    target_strike = int(round(spot_entry / 50.0)) * 50
    is_call = (direction == "CE")

    # Expiry days
    target_d = datetime.strptime(target_date, "%Y-%m-%d").date()
    # NIFTY weekly options expire on Tuesdays (weekday 1)
    if target_d.weekday() <= 1:
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
    else:
        expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
    days_base = max(0.1, float((expiry_d - target_d).days))

    # Option price helper
    has_real_opt = direction in opt_candles_1m and len(opt_candles_1m[direction]) > entry_1m_idx
    if has_real_opt:
        entry_price = opt_candles_1m[direction][entry_1m_idx]["close"]
    else:
        days_rem = days_base - (entry_1m_idx / 375.0) * 0.25
        entry_price = bsm_price(spot_entry, target_strike, days_rem, is_call=is_call)

    if entry_price <= 1.0:
        return None

    peak_price = entry_price
    peak_gain_pct = 0.0
    exit_price = entry_price
    exit_reason = "EOD_SQUAREOFF"
    exit_1m_idx = entry_1m_idx
    opt_close = entry_price

    # Simulate minute by minute
    for m in range(entry_1m_idx + 1, min(360, len(spot_bars_1m))):
        exit_1m_idx = m
        sb = spot_bars_1m[m]
        if has_real_opt and m < len(opt_candles_1m[direction]):
            ob = opt_candles_1m[direction][m]
            opt_high = ob["high"]
            opt_low = ob["low"]
            opt_close = ob["close"]
        else:
            days_rem = days_base - (m / 375.0) * 0.25
            c_close = bsm_price(sb["close"], target_strike, days_rem, is_call=is_call)
            c_high = bsm_price(sb["high"] if is_call else sb["low"], target_strike, days_rem, is_call=is_call)
            c_low = bsm_price(sb["low"] if is_call else sb["high"], target_strike, days_rem, is_call=is_call)
            opt_high, opt_low, opt_close = max(c_close, c_high), min(c_close, c_low), c_close

        if opt_high > peak_price:
            peak_price = opt_high
            peak_gain_pct = ((peak_price - entry_price) / entry_price) * 100.0

        # Two-Step Risk Model:
        # Initial stop: -20%
        stop_floor_price = entry_price * 0.80

        # Trailing ratchets
        if peak_gain_pct >= 40.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.30)
        elif peak_gain_pct >= 30.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.20)
        elif peak_gain_pct >= 20.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.10)
        elif peak_gain_pct >= 15.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.00) # Breakeven

        # Dynamic runner trailing: 10% pullback from highest peak after +20% gain
        if peak_gain_pct >= 20.0:
            peak_trailing_stop = peak_price * 0.90
            stop_floor_price = max(stop_floor_price, peak_trailing_stop)

        # Check if stop breached
        if opt_low <= stop_floor_price:
            exit_price = stop_floor_price
            exit_reason = "STOP_OR_TRAILING" if stop_floor_price > entry_price else "INITIAL_STOP"
            break
    else:
        # 15:15 IST square-off
        exit_price = opt_close
        exit_reason = "INTRADAY_CLOSE"

    pnl_pts = exit_price - entry_price
    pnl_inr = pnl_pts * 65 # 1 Lot = 65 qty
    ret_pct = (pnl_pts / entry_price) * 100.0

    return {
        "date": target_date,
        "entry_idx": entry_1m_idx,
        "exit_idx": exit_1m_idx,
        "direction": direction,
        "strike": target_strike,
        "entry_price": round(entry_price, 2),
        "exit_price": round(exit_price, 2),
        "peak_price": round(peak_price, 2),
        "peak_gain_pct": round(peak_gain_pct, 1),
        "pnl_pts": round(pnl_pts, 2),
        "pnl_inr": round(pnl_inr, 2),
        "ret_pct": round(ret_pct, 1),
        "exit_reason": exit_reason
    }

def run_matrix_backtest(
    timeframe_min: int,
    volume_mode: str, # "NONE", "FUTURES"
    reversal_mode: bool = True # True: PE requires RSI > 50, CE requires RSI < 50
) -> Dict:
    all_trades = []
    
    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_day_data(dt_str)
        if not spot_bars or len(spot_bars) < 60:
            continue

        res_spot = resample_bars(spot_bars, timeframe_min)
        spot_closes = [b["close"] for b in res_spot]
        macd_line, sig_line, hist = calculate_macd(spot_closes)
        rsi_line = calculate_rsi(spot_closes, 14)

        # Volume series depending on volume_mode
        vol_ratios = [1.0] * len(res_spot)
        ce_vol_ratios = [1.0] * len(res_spot)
        pe_vol_ratios = [1.0] * len(res_spot)

        if volume_mode == "FUTURES" and fut_bars:
            res_fut = resample_bars(fut_bars, timeframe_min)
            fut_vols = [b.get("volume", 0.0) for b in res_fut]
            sma_fut_vols = calculate_sma(fut_vols, 20)
            vol_ratios = [
                fut_vols[i] / sma_fut_vols[i] if (i < len(sma_fut_vols) and sma_fut_vols[i] > 0) else 1.0
                for i in range(len(res_fut))
            ]
        elif volume_mode == "OPTIONS" and opt_candles:
            if "CE" in opt_candles:
                res_ce = resample_bars(opt_candles["CE"], timeframe_min)
                ce_vols = [b.get("volume", 0.0) for b in res_ce]
                sma_ce = calculate_sma(ce_vols, 20)
                ce_vol_ratios = [
                    ce_vols[i] / sma_ce[i] if (i < len(sma_ce) and sma_ce[i] > 0) else 1.0
                    for i in range(len(res_ce))
                ]
            if "PE" in opt_candles:
                res_pe = resample_bars(opt_candles["PE"], timeframe_min)
                pe_vols = [b.get("volume", 0.0) for b in res_pe]
                sma_pe = calculate_sma(pe_vols, 20)
                pe_vol_ratios = [
                    pe_vols[i] / sma_pe[i] if (i < len(sma_pe) and sma_pe[i] > 0) else 1.0
                    for i in range(len(res_pe))
                ]

        in_trade_until_1m = -1

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]
            if end_1m < in_trade_until_1m:
                continue # Already in a position

            # Signals
            pe_cross = (macd_line[i] < sig_line[i]) and (macd_line[i - 1] >= sig_line[i - 1])
            ce_cross = (macd_line[i] > sig_line[i]) and (macd_line[i - 1] <= sig_line[i - 1])

            # RSI conditions
            if reversal_mode:
                pe_rsi_ok = (rsi_line[i] > 50.0) # Bearish rollover off high
                ce_rsi_ok = (rsi_line[i] < 50.0) # Bullish spring off low
            else:
                pe_rsi_ok = (rsi_line[i] < 50.0) # Bearish momentum
                ce_rsi_ok = (rsi_line[i] > 50.0) # Bullish momentum

            # Volume condition
            pe_vol_ok = True
            ce_vol_ok = True
            if volume_mode == "FUTURES":
                vr = vol_ratios[i] if i < len(vol_ratios) else 1.0
                pe_vol_ok = (vr >= 1.5)
                ce_vol_ok = (vr >= 1.5)
            elif volume_mode == "OPTIONS":
                pvr = pe_vol_ratios[i] if i < len(pe_vol_ratios) else 1.0
                cvr = ce_vol_ratios[i] if i < len(ce_vol_ratios) else 1.0
                pe_vol_ok = (pvr >= 1.5)
                ce_vol_ok = (cvr >= 1.5)

            signal = None
            if pe_cross and pe_rsi_ok and pe_vol_ok:
                signal = "PE"
            elif ce_cross and ce_rsi_ok and ce_vol_ok:
                signal = "CE"

            if signal is not None:
                tr = simulate_trade(end_1m, signal, spot_bars, opt_candles, dt_str)
                if tr:
                    all_trades.append(tr)
                    in_trade_until_1m = tr["exit_idx"]

    total_trades = len(all_trades)
    wins = [t for t in all_trades if t["pnl_inr"] > 0]
    losses = [t for t in all_trades if t["pnl_inr"] <= 0]
    win_rate = (len(wins) / total_trades * 100.0) if total_trades > 0 else 0.0
    net_pnl = sum(t["pnl_inr"] for t in all_trades)
    gross_win = sum(t["pnl_inr"] for t in wins)
    gross_loss = abs(sum(t["pnl_inr"] for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (99.0 if gross_win > 0 else 0.0)

    return {
        "timeframe": f"{timeframe_min}m",
        "volume_mode": volume_mode,
        "reversal_mode": "Reversal (PE: RSI>50)" if reversal_mode else "Trend (PE: RSI<50)",
        "total_trades": total_trades,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "net_pnl": round(net_pnl, 2),
        "profit_factor": round(pf, 2),
        "trades": all_trades
    }

# Execute full matrix
results = []
print("=" * 105)
print(" RUNNING MATRIX BACKTEST: MACD CROSS + RSI + VOLUME EXPANSION")
print(" Dates: Oct 19 - Oct 27, 2026 (6 Sessions) | Sizing: 1 Lot (65 qty) | Risk: Two-Step Model")
print("=" * 105)

timeframes = [1, 2]
vol_modes = ["NONE", "FUTURES", "OPTIONS"]
modes = [True, False] # Reversal vs Trend

print(f"{'Timeframe':<10} | {'Volume Filter':<15} | {'RSI Logic':<24} | {'Trades':<8} | {'Win Rate':<10} | {'Net PnL (INR)':<14} | {'Profit Factor'}")
print("-" * 105)

for tf in timeframes:
    for vm in vol_modes:
        for rev in modes:
            res = run_matrix_backtest(tf, vm, rev)
            results.append(res)
            print(f"{res['timeframe']:<10} | {res['volume_mode']:<15} | {res['reversal_mode']:<24} | {res['total_trades']:<8} | {res['win_rate']:<9}% | INR {res['net_pnl']:<9.2f} | {res['profit_factor']}")

# Save detailed results to JSON
with open("scratch/matrix_backtest_results.json", "w") as fp:
    json.dump([{k: v for k, v in r.items() if k != "trades"} for r in results], fp, indent=2)

print("\nMatrix Backtest Complete. Results saved to scratch/matrix_backtest_results.json")
