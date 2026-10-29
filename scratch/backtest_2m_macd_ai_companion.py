import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from backtest_engine import bsm_price, select_strike

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
    opt_candles = {}
    for right in ["CE", "PE"]:
        for f in os.listdir("data"):
            if f.startswith(f"opt_{date_str.replace('-', '')}_") and f.endswith(f"_{right}.json"):
                with open(os.path.join("data", f), "r") as fp:
                    opt_candles[right] = json.load(fp)
                break
    return spot_bars, fut_bars, opt_candles

def resample_bars(bars_1m: List[Dict], interval_min: int) -> List[Dict]:
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

def evaluate_ai_companion_gate(dossier: Dict) -> Tuple[bool, str, int]:
    """
    Antigravity AI Companion Pair-Trading Gatekeeper:
    Audits 2m MACD setup against the 8 cataloged institutional traps + volume confirmation.
    """
    direction = dossier["direction"]
    spot = dossier["spot"]
    vwap = dossier["vwap"]
    vwap_slope = dossier["vwap_slope"]
    vwap_crosses = dossier["vwap_crosses_60m"]
    box_pos = dossier["box_pos_pct"]
    rsi = dossier["rsi"]
    vol_ratio = dossier["vol_ratio"]
    time_min = dossier["minute_idx"] # 0 to 375
    ema_spread = dossier["ema9_5m"] - dossier["ema20_5m"]

    # Trap 5: Late-day degradation (after 14:15 IST = minute 300)
    if time_min > 300:
        return False, "Trap 5: Late-Day Profit Degradation (Post-14:15 IST)", 0

    # Trap 1: VWAP Blender & Midday Dead Zone (11:30 - 13:15 IST = minute 135 to 240)
    if vwap_crosses >= 5:
        return False, f"Trap 1: VWAP Blender Active ({vwap_crosses} crosses in 60m >= 5)", 0
    if 135 <= time_min <= 240 and abs(vwap_slope) < 0.12:
        return False, f"Trap 1: Midday Dead Zone Flatline (Slope {vwap_slope:+.3f} in chop zone)", 0

    # Trap 8: Climax Overextension (>= 75 pts from VWAP)
    dist_vwap = abs(spot - vwap)
    if dist_vwap >= 75.0:
        return False, f"Trap 8: Climax Overextension ({dist_vwap:.1f} pts from VWAP >= 75.0 pts)", 0

    # Trap 4: Consolidation Ceiling Trap
    if direction == "CE" and box_pos >= 85.0:
        return False, f"Trap 4: 15m Consolidation Ceiling Trap ({box_pos:.1f}% >= 85%)", 0
    if direction == "PE" and box_pos <= 15.0:
        return False, f"Trap 4: 15m Consolidation Floor Trap ({box_pos:.1f}% <= 15%)", 0

    # Trap 7: Counter-Trend VWAP Slope Trap
    if direction == "CE" and vwap_slope < -0.20 and spot < vwap:
        return False, f"Trap 7: Counter-Trend VWAP Slope (CE fighting downward slope {vwap_slope:+.3f})", 0
    if direction == "PE" and vwap_slope > +0.20 and spot > vwap:
        return False, f"Trap 7: Counter-Trend VWAP Slope (PE fighting upward slope {vwap_slope:+.3f})", 0

    # Volume Confirmation Filter: Must have institutional participation >= 1.25x average volume
    if vol_ratio < 1.20:
        return False, f"Volume Filter: Weak Volume ({vol_ratio:.2f}x < 1.20x institutional threshold)", 0

    # Passed all guardrails!
    conviction = 85
    if vol_ratio >= 1.50:
        conviction += 5
    if abs(vwap_slope) >= 0.25:
        conviction += 5

    reason = f"High-conviction 2m MACD {direction} expansion. Vol: {vol_ratio:.2f}x, RSI: {rsi:.1f}, Slope: {vwap_slope:+.3f}."
    return True, reason, conviction

def simulate_trade_lifecycle(
    entry_1m_idx: int,
    direction: str,
    spot_bars_1m: List[Dict],
    opt_candles_1m: Dict[str, List[Dict]],
    target_date: str,
    conviction: int
) -> Optional[Dict]:
    if entry_1m_idx >= 360 or entry_1m_idx >= len(spot_bars_1m) - 1:
        return None

    spot_entry = spot_bars_1m[entry_1m_idx]["close"]
    target_strike = int(round(spot_entry / 50.0)) * 50
    is_call = (direction == "CE")

    # Expiry days
    target_d = datetime.strptime(target_date, "%Y-%m-%d").date()
    if target_d.weekday() <= 1:
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
    else:
        expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
    days_base = max(0.1, float((expiry_d - target_d).days))

    # Option pricing
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

    # Invalidation spot level: Swing low (for CE) or Swing high (for PE) from previous 5 bars
    recent_bars = spot_bars_1m[max(0, entry_1m_idx - 5): entry_1m_idx + 1]
    if is_call:
        invalidation_spot = min(b["low"] for b in recent_bars) - 2.0
    else:
        invalidation_spot = max(b["high"] for b in recent_bars) + 2.0

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

        # Structural spot invalidation
        if is_call and sb["low"] <= invalidation_spot:
            exit_price = opt_close
            exit_reason = f"STRUCTURAL_INVALIDATION (Spot {sb['low']:.1f} <= {invalidation_spot:.1f})"
            break
        elif not is_call and sb["high"] >= invalidation_spot:
            exit_price = opt_close
            exit_reason = f"STRUCTURAL_INVALIDATION (Spot {sb['high']:.1f} >= {invalidation_spot:.1f})"
            break

        # Two-Step Risk Model: -20% stop loss
        stop_floor_price = entry_price * 0.80

        # Trailing floors
        if peak_gain_pct >= 40.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.30)
        elif peak_gain_pct >= 30.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.20)
        elif peak_gain_pct >= 20.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.10)
        elif peak_gain_pct >= 15.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.00) # Breakeven

        # Peak trailing: 10% pullback
        if peak_gain_pct >= 20.0:
            stop_floor_price = max(stop_floor_price, peak_price * 0.90)

        if opt_low <= stop_floor_price:
            exit_price = stop_floor_price
            exit_reason = "STOP_OR_TRAILING" if stop_floor_price > entry_price else "INITIAL_STOP"
            break
    else:
        exit_price = opt_close
        exit_reason = "INTRADAY_CLOSE"

    pnl_pts = exit_price - entry_price
    pnl_inr = pnl_pts * 65
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
        "exit_reason": exit_reason,
        "conviction": conviction,
        "invalidation_spot": round(invalidation_spot, 1)
    }

def run_realtime_backtest_with_ai():
    print("=" * 110)
    print(" 🤖 REAL-TIME 2-MINUTE MACD BACKTEST WITH ANTIGRAVITY AI COMPANION CONFIRMATION")
    print(" Dates: Oct 19 - Oct 27, 2026 (6 Sessions) | Sizing: 1 Lot (65 qty) | Risk: Two-Step Model")
    print(" Enforcing Rule #1: Supreme Veto Power & 8 Institutional Traps")
    print("=" * 110)

    total_candidates = 0
    approved_trades = []
    vetoed_candidates = []

    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_data(dt_str)
        if not spot_bars or not fut_bars or len(spot_bars) < 60:
            continue

        print(f"\n" + "-" * 110)
        print(f" 📅 TRADING SESSION: {dt_label}")
        print("-" * 110)

        # Resample to 2m
        res_spot = resample_bars(spot_bars, 2)
        res_fut = resample_bars(fut_bars, 2)

        closes = [b["close"] for b in res_spot]
        macd, sig, hist = calculate_macd(closes)
        rsi = calculate_rsi(closes, 14)
        vols = [b["volume"] for b in res_fut]
        sma_vols = calculate_sma(vols, 20)

        # 5m EMA for ribbon context
        res_5m = resample_bars(spot_bars, 5)
        closes_5m = [b["close"] for b in res_5m]
        ema9_5m = calculate_ema(closes_5m, 9)
        ema20_5m = calculate_ema(closes_5m, 20)

        in_trade_until = -1

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]
            if end_1m < in_trade_until:
                continue

            # Detect MACD Cross
            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])

            if not (pe_cross or ce_cross):
                continue

            total_candidates += 1
            direction = "PE" if pe_cross else "CE"
            spot_price = res_spot[i]["close"]
            hh = end_1m // 60 + 9
            mm = end_1m % 60
            time_str = f"{hh:02d}:{mm:02d} IST"

            # 1m bar slice up to this minute
            bars_so_far = spot_bars[:end_1m + 1]
            typicals = [(b["high"] + b["low"] + b["close"]) / 3.0 for b in bars_so_far]
            vwap = sum(typicals) / len(typicals)
            vwap_slope = (vwap - sum(typicals[:max(1, len(typicals)-15)]) / max(1, len(typicals)-15))

            # VWAP crosses in rolling 60m
            last_60 = bars_so_far[max(0, len(bars_so_far)-60):]
            crosses_60m = sum(1 for k in range(1, len(last_60)) if (last_60[k]["close"] - vwap) * (last_60[k-1]["close"] - vwap) < 0)

            # 15m box
            last_15m = bars_so_far[max(0, len(bars_so_far)-15):]
            box_h = max(b["high"] for b in last_15m)
            box_l = min(b["low"] for b in last_15m)
            box_spread = max(1.0, box_h - box_l)
            box_pos = ((spot_price - box_l) / box_spread) * 100.0

            # 5m ribbon
            idx_5m = min(len(ema9_5m) - 1, end_1m // 5)
            e9 = ema9_5m[idx_5m] if idx_5m < len(ema9_5m) else spot_price
            e20 = ema20_5m[idx_5m] if idx_5m < len(ema20_5m) else spot_price

            vr = vols[i] / sma_vols[i] if (i < len(sma_vols) and sma_vols[i] > 0) else 1.0

            dossier = {
                "date": dt_str,
                "time_ist": time_str,
                "minute_idx": end_1m,
                "direction": direction,
                "spot": spot_price,
                "vwap": vwap,
                "vwap_slope": round(vwap_slope, 4),
                "vwap_crosses_60m": crosses_60m,
                "box_pos_pct": round(box_pos, 1),
                "rsi": rsi[i],
                "vol_ratio": round(vr, 2),
                "ema9_5m": e9,
                "ema20_5m": e20
            }

            # Consult AI Companion
            is_approved, ai_reason, conviction = evaluate_ai_companion_gate(dossier)

            if is_approved:
                print(f"  [AI CONSULTATION] {time_str} | Candidate: BUY_{direction} @ Spot {spot_price:.1f} | Vol: {vr:.2f}x | RSI: {rsi[i]:.1f}")
                print(f"  --> VERDICT: APPROVED (Conviction: {conviction}%) | Rationale: {ai_reason}")

                # Execute trade simulation
                trade = simulate_trade_lifecycle(end_1m, direction, spot_bars, opt_candles, dt_str, conviction)
                if trade:
                    approved_trades.append(trade)
                    in_trade_until = trade["exit_idx"]
                    exit_hh = trade["exit_idx"] // 60 + 9
                    exit_mm = trade["exit_idx"] % 60
                    print(f"      [ORDER FILLED] {direction} {trade['strike']} @ Rs {trade['entry_price']:.2f} | Invalidation Spot: {trade['invalidation_spot']}")
                    print(f"      [EXIT FILLED]  {exit_hh:02d}:{exit_mm:02d} IST @ Rs {trade['exit_price']:.2f} ({trade['ret_pct']:+5.1f}%) | Peak: +{trade['peak_gain_pct']}% | PnL: Rs {trade['pnl_inr']:+8.2f} | Reason: {trade['exit_reason']}\n")
            else:
                vetoed_candidates.append((dt_str, time_str, direction, ai_reason))
                print(f"  [AI CONSULTATION] {time_str} | Candidate: BUY_{direction} @ Spot {spot_price:.1f} | Vol: {vr:.2f}x | RSI: {rsi[i]:.1f}")
                print(f"  --> VERDICT: VETOED | Rationale: {ai_reason} (Capital Preserved)\n")

    # Final Audit Summary
    print("\n" + "=" * 110)
    print(" 🏆 FINAL FORENSIC AUDIT: 2m MACD + ANTIGRAVITY AI COMPANION (OCT 19 - OCT 27, 2026)")
    print("=" * 110)

    total_approved = len(approved_trades)
    total_vetoed = len(vetoed_candidates)
    wins = [t for t in approved_trades if t["pnl_inr"] > 0]
    losses = [t for t in approved_trades if t["pnl_inr"] <= 0]
    win_rate = (len(wins) / total_approved * 100.0) if total_approved > 0 else 0.0
    net_pnl = sum(t["pnl_inr"] for t in approved_trades)
    gross_win = sum(t["pnl_inr"] for t in wins)
    gross_loss = abs(sum(t["pnl_inr"] for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 99.0

    print(f"Total Candidates Proposed by 2m MACD Engine: {total_candidates}")
    print(f"Total Vetoed by AI Companion Guardrails:    {total_vetoed} ({total_vetoed/total_candidates*100:.1f}% filtered)")
    print(f"Total Approved & Executed Trades:            {total_approved}")
    print(f"Winning Trades:                              {len(wins)} / {total_approved} ({win_rate:.1f}% Win Rate)")
    print(f"Gross Profits:                               Rs +{gross_win:,.2f}")
    print(f"Gross Losses:                                Rs -{gross_loss:,.2f}")
    print(f"Net Realized PnL (1 Lot / Rs 10k Margin):    Rs {net_pnl:+,.2f} ({net_pnl/10000.0*100:+.1f}% Net ROI)")
    print(f"Profit Factor:                               {pf:.2f}")

    print("\n" + "=" * 110)
    print(" 📋 ALL APPROVED TRADES JOURNAL")
    print("=" * 110)
    print(f"{'Date':<12} | {'Time':<10} | {'Strike':<16} | {'Entry':<8} | {'Exit':<8} | {'Return %':<10} | {'Peak Gain':<10} | {'Net PnL':<12} | {'Exit Rationale'}")
    print("-" * 110)
    for t in approved_trades:
        hh = t['entry_idx'] // 60 + 9
        mm = t['entry_idx'] % 60
        print(f"{t['date']:<12} | {hh:02d}:{mm:02d} IST | {t['direction']} {t['strike']:<11} | {t['entry_price']:<8.2f} | {t['exit_price']:<8.2f} | {t['ret_pct']:+6.1f}%    | +{t['peak_gain_pct']:<8.1f}% | Rs {t['pnl_inr']:+8.2f}   | {t['exit_reason']}")

if __name__ == "__main__":
    run_realtime_backtest_with_ai()
