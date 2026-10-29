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

def calculate_sma(series: List[float], period: int = 20) -> List[float]:
    res = []
    for i in range(len(series)):
        start_idx = max(0, i - period + 1)
        sub = series[start_idx: i + 1]
        res.append(sum(sub) / len(sub) if sub else 0.0)
    return res

def simulate_trade_raw(
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

    target_d = datetime.strptime(target_date, "%Y-%m-%d").date()
    if target_d.weekday() <= 1:
        expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
    else:
        expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
    days_base = max(0.1, float((expiry_d - target_d).days))

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

        if is_call and sb["low"] <= invalidation_spot:
            exit_price = opt_close
            exit_reason = f"STRUCTURAL_INVALIDATION (Spot {sb['low']:.1f} <= {invalidation_spot:.1f})"
            break
        elif not is_call and sb["high"] >= invalidation_spot:
            exit_price = opt_close
            exit_reason = f"STRUCTURAL_INVALIDATION (Spot {sb['high']:.1f} >= {invalidation_spot:.1f})"
            break

        stop_floor_price = entry_price * 0.80

        if peak_gain_pct >= 40.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.30)
        elif peak_gain_pct >= 30.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.20)
        elif peak_gain_pct >= 20.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.10)
        elif peak_gain_pct >= 15.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.00)

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
        "exit_reason": exit_reason
    }

def audit_all_candidates():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )

    all_dossiers = []

    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_data(dt_str)
        if not spot_bars or not fut_bars or len(spot_bars) < 60:
            continue

        res_spot = resample_bars(spot_bars, 2)
        res_fut = resample_bars(fut_bars, 2)

        closes = [b["close"] for b in res_spot]
        macd, sig, hist = calculate_macd(closes)
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

            has_real_opt = direction in opt_candles and len(opt_candles[direction]) > end_1m
            if has_real_opt:
                est_opt_price = opt_candles[direction][end_1m]["close"]
            else:
                est_opt_price = bsm_price(spot_price, target_strike, days_rem, is_call=(direction == "CE"))

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
            vol_approved = (vr >= 1.20)

            # Determine why it was vetoed or approved
            if not verdict.is_approved:
                primary_rule = verdict.trap_detected or "Consultant Veto"
                reason_detail = verdict.reasoning
            elif not vol_approved:
                primary_rule = "Volume Filter (< 1.20x)"
                reason_detail = f"Volume {vr:.2f}x below 1.20x"
            else:
                primary_rule = "APPROVED"
                reason_detail = "All gates passed"

            # Simulate outcome regardless of veto
            tr_sim = simulate_trade_raw(end_1m, direction, spot_bars, opt_candles, dt_str)

            hh = end_1m // 60 + 9
            mm = end_1m % 60
            time_str = f"{hh:02d}:{mm:02d}"

            all_dossiers.append({
                "date": dt_str,
                "time": time_str,
                "direction": direction,
                "strike": target_strike,
                "spot": spot_price,
                "vol_ratio": round(vr, 2),
                "opt_price": round(est_opt_price, 2),
                "primary_rule": primary_rule,
                "reason_detail": reason_detail,
                "is_approved": (primary_rule == "APPROVED"),
                "sim_pnl": tr_sim["pnl_inr"] if tr_sim else 0.0,
                "sim_ret_pct": tr_sim["ret_pct"] if tr_sim else 0.0,
                "sim_peak_gain": tr_sim["peak_gain_pct"] if tr_sim else 0.0,
                "sim_exit_reason": tr_sim["exit_reason"] if tr_sim else "N/A"
            })

    print("=" * 115)
    print(" 🔬 COMPREHENSIVE BOTTLENECK AUDIT ACROSS ALL 75 CANDIDATES (OCT 19 - OCT 27, 2026)")
    print("=" * 115)

    # Group by primary_rule
    rule_stats = {}
    for d in all_dossiers:
        r = d["primary_rule"]
        if r not in rule_stats:
            rule_stats[r] = {
                "total": 0,
                "wins": 0,
                "losses": 0,
                "gross_win_pnl": 0.0,
                "gross_loss_pnl": 0.0,
                "net_pnl": 0.0,
                "missed_winners": []
            }
        rule_stats[r]["total"] += 1
        pnl = d["sim_pnl"]
        rule_stats[r]["net_pnl"] += pnl
        if pnl > 0:
            rule_stats[r]["wins"] += 1
            rule_stats[r]["gross_win_pnl"] += pnl
            rule_stats[r]["missed_winners"].append(d)
        else:
            rule_stats[r]["losses"] += 1
            rule_stats[r]["gross_loss_pnl"] += abs(pnl)

    print(f"{'Veto Gatekeeper Rule / Trap':<45} | {'Candidates':<10} | {'Wins':<5} | {'Losses':<6} | {'Win PnL (₹)':<13} | {'Saved Loss (₹)':<14} | {'Net Impact'}")
    print("-" * 115)

    for rule, st in sorted(rule_stats.items(), key=lambda x: x[1]['total'], reverse=True):
        win_pnl = st['gross_win_pnl']
        loss_pnl = st['gross_loss_pnl']
        net = win_pnl - loss_pnl
        net_impact_str = f"Lost Opportunity: +₹{win_pnl:,.1f}" if net > 0 and rule != "APPROVED" else (f"Saved Capital: -₹{loss_pnl:,.1f}" if rule != "APPROVED" else f"Realized Net: +₹{net:,.1f}")
        print(f"{rule:<45} | {st['total']:<10} | {st['wins']:<5} | {st['losses']:<6} | ₹{win_pnl:<12,.2f} | ₹{loss_pnl:<13,.2f} | {net_impact_str}")

    print("\n" + "=" * 115)
    print(" 🚨 MISSED WINNERS AUDIT: THE TOP 10 PROFITABLE TRADES VETOED BY BOTTLENECKS")
    print("=" * 115)
    print(f"{'Date':<12} | {'Time':<6} | {'Trade':<10} | {'Spot':<8} | {'Opt Price':<10} | {'Peak Gain':<10} | {'Potential PnL':<14} | {'Bottleneck Rule That Vetoed It'}")
    print("-" * 115)

    # Find all vetoed candidates that would have been profitable
    vetoed_wins = [d for d in all_dossiers if not d["is_approved"] and d["sim_pnl"] > 0]
    vetoed_wins.sort(key=lambda x: x["sim_pnl"], reverse=True)

    for w in vetoed_wins[:15]:
        print(f"{w['date']:<12} | {w['time']:<6} | {w['direction']} {w['strike']:<5} | {w['spot']:<8.1f} | Rs {w['opt_price']:<7.2f} | +{w['sim_peak_gain']:<8.1f}% | Rs {w['sim_pnl']:<11.2f} | {w['primary_rule']}")

if __name__ == "__main__":
    audit_all_candidates()
