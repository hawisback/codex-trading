import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional
from backtest_engine import bsm_price, select_strike
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

        # Stop floor: Initial -20%
        stop_floor_price = entry_price * 0.80

        # Trailing floors
        if peak_gain_pct >= 40.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.30)
        elif peak_gain_pct >= 30.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.20)
        elif peak_gain_pct >= 20.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.10)
        elif peak_gain_pct >= 15.0:
            stop_floor_price = max(stop_floor_price, entry_price * 1.00)

        # Dynamic runner trailing: 10% pullback from highest peak after +20%
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

def run_minute_playback():
    ai = AIConsultant(
        mode="playbook",
        trading_config={"option_selection": {"min_option_premium": 1.0, "max_option_premium": 10000.0}}
    )
    
    print("=" * 115)
    print(" 🤖 REAL-TIME 2-MINUTE MACD BACKTEST WITH ANTIGRAVITY AI CONSULTANT CONFIRMATION")
    print(" Strategy: 2m MACD Cross + Volume Confirmation + AI Playbook Gatekeeper (8 Traps)")
    print(" Dates: Oct 19 - Oct 27, 2026 (6 Sessions) | Risk: Two-Step Model (Initial -20%, Dynamic Trailing)")
    print("=" * 115)

    approved_trades = []
    vetoed_candidates = []
    total_candidates = 0

    for dt_str, dt_label in DATES:
        spot_bars, fut_bars, opt_candles = load_data(dt_str)
        if not spot_bars or not fut_bars or len(spot_bars) < 60:
            continue

        print(f"\n" + "-" * 115)
        print(f" 📅 TRADING SESSION: {dt_label}")
        print("-" * 115)

        res_spot = resample_bars(spot_bars, 2)
        res_fut = resample_bars(fut_bars, 2)

        closes = [b["close"] for b in res_spot]
        macd, sig, hist = calculate_macd(closes)
        vols = [b["volume"] for b in res_fut]
        sma_vols = calculate_sma(vols, 20)

        in_trade_until = -1
        trade_history = []

        for i in range(26, len(res_spot)):
            end_1m = res_spot[i]["minute_idx"]
            if end_1m < in_trade_until:
                continue

            # 2m MACD Cross
            pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
            ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])

            if not (pe_cross or ce_cross):
                continue

            total_candidates += 1
            direction = "PE" if pe_cross else "CE"
            spot_price = res_spot[i]["close"]
            target_strike = int(round(spot_price / 50.0)) * 50
            vr = vols[i] / sma_vols[i] if (i < len(sma_vols) and sma_vols[i] > 0) else 1.0

            # Option price estimate
            target_d = datetime.strptime(dt_str, "%Y-%m-%d").date()
            if target_d.weekday() <= 1:
                expiry_d = target_d + timedelta(days=(1 - target_d.weekday()))
            else:
                expiry_d = target_d + timedelta(days=(8 - target_d.weekday()))
            days_base = max(0.1, float((expiry_d - target_d).days))
            days_rem = days_base - (end_1m / 375.0) * 0.25

            has_real_opt = direction in opt_candles and len(opt_candles[direction]) > end_1m
            if has_real_opt:
                est_opt_price = opt_candles[direction][end_1m]["close"]
            else:
                est_opt_price = bsm_price(spot_price, target_strike, days_rem, is_call=(direction == "CE"))

            is_0dte = (target_d.weekday() == 1)

            # Build formal MarketDossier using ai_context_dossier
            dossier = generate_market_dossier(
                target_date=dt_str,
                candles=spot_bars,
                current_bar_idx=end_1m,
                direction=direction,
                symbol=f"NIFTY_{target_strike}_{direction}",
                strike=target_strike,
                option_entry_price=est_opt_price,
                trade_history=trade_history,
                days_to_expiry=days_rem,
                is_expiry_0dte=is_0dte
            )

            # Volume filter check: must have volume expansion >= 1.2x
            vol_approved = (vr >= 1.20)

            # Consult AI Consultant (Playbook mode)
            verdict: AIVerdict = ai.evaluate(dossier)

            hh = end_1m // 60 + 9
            mm = end_1m % 60
            time_str = f"{hh:02d}:{mm:02d} IST"

            # Combine AI Gatekeeper with Volume confirmation
            final_approved = verdict.is_approved and vol_approved
            if verdict.is_approved and not vol_approved:
                ai_reason = f"Volume Filter VETO: Volume ratio ({vr:.2f}x) is below 1.20x institutional expansion threshold."
            else:
                ai_reason = verdict.reasoning

            if final_approved:
                print(f"  [AI CONSULTATION] {time_str} | Candidate: BUY_{direction} {target_strike} @ Spot {spot_price:.1f} | Vol: {vr:.2f}x | Option: Rs {est_opt_price:.2f}")
                print(f"  --> VERDICT: APPROVED (Confidence: {verdict.confidence_score}%) | Rationale: {verdict.reasoning}")

                # Execute trade
                tr = simulate_trade_lifecycle(end_1m, direction, spot_bars, opt_candles, dt_str, verdict.confidence_score)
                if tr:
                    approved_trades.append(tr)
                    trade_history.append(type('T', (), {'pnl': tr['pnl_inr'], 'direction': tr['direction']})())
                    in_trade_until = tr["exit_idx"]
                    exit_hh = tr["exit_idx"] // 60 + 9
                    exit_mm = tr["exit_idx"] % 60
                    print(f"      [ORDER FILLED] {direction} {tr['strike']} @ Rs {tr['entry_price']:.2f} | Invalidation Spot: {tr['invalidation_spot']}")
                    print(f"      [EXIT FILLED]  {exit_hh:02d}:{exit_mm:02d} IST @ Rs {tr['exit_price']:.2f} ({tr['ret_pct']:+5.1f}%) | Peak: +{tr['peak_gain_pct']}% | PnL: Rs {tr['pnl_inr']:+8.2f} | Reason: {tr['exit_reason']}\n")
            else:
                vetoed_candidates.append((dt_str, time_str, direction, ai_reason, verdict.trap_detected))
                trap_tag = f"[{verdict.trap_detected}] " if verdict.trap_detected else "[Volume Filter] "
                print(f"  [AI CONSULTATION] {time_str} | Candidate: BUY_{direction} {target_strike} @ Spot {spot_price:.1f} | Vol: {vr:.2f}x | Option: Rs {est_opt_price:.2f}")
                print(f"  --> VERDICT: VETOED | {trap_tag}{ai_reason} (Capital Preserved)\n")

    # Summary
    print("\n" + "=" * 115)
    print(" 🏆 FINAL FORENSIC SUMMARY: 2m MACD + ANTIGRAVITY AI COMPANION (OCT 19 - OCT 27, 2026)")
    print("=" * 115)

    tot_app = len(approved_trades)
    tot_veto = len(vetoed_candidates)
    wins = [t for t in approved_trades if t["pnl_inr"] > 0]
    losses = [t for t in approved_trades if t["pnl_inr"] <= 0]
    win_rate = (len(wins) / tot_app * 100.0) if tot_app > 0 else 0.0
    net_pnl = sum(t["pnl_inr"] for t in approved_trades)
    gross_win = sum(t["pnl_inr"] for t in wins)
    gross_loss = abs(sum(t["pnl_inr"] for t in losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else 99.0

    print(f"Total Candidate Signals Generated:           {total_candidates}")
    print(f"Total Vetoed by AI Consultant & Volume:      {tot_veto} ({tot_veto/total_candidates*100:.1f}% filtered)")
    print(f"Total Approved & Broker Executed:            {tot_app}")
    print(f"Winning Trades:                              {len(wins)} / {tot_app} ({win_rate:.1f}% Win Rate)")
    print(f"Gross Profits:                               Rs +{gross_win:,.2f}")
    print(f"Gross Losses:                                Rs -{gross_loss:,.2f}")
    print(f"Net Realized PnL (1 Lot / Rs 10k Margin):    Rs {net_pnl:+,.2f} ({net_pnl/10000.0*100:+.1f}% Net ROI)")
    print(f"Profit Factor:                               {pf:.2f}")

    print("\n" + "=" * 115)
    print(" 📋 ALL APPROVED TRADES JOURNAL")
    print("=" * 115)
    print(f"{'Date':<12} | {'Time':<10} | {'Strike':<16} | {'Entry':<8} | {'Exit':<8} | {'Return %':<10} | {'Peak Gain':<10} | {'Net PnL':<12} | {'Exit Rationale'}")
    print("-" * 115)
    for t in approved_trades:
        hh = t['entry_idx'] // 60 + 9
        mm = t['entry_idx'] % 60
        print(f"{t['date']:<12} | {hh:02d}:{mm:02d} IST | {t['direction']} {t['strike']:<11} | {t['entry_price']:<8.2f} | {t['exit_price']:<8.2f} | {t['ret_pct']:+6.1f}%    | +{t['peak_gain_pct']:<8.1f}% | Rs {t['pnl_inr']:+8.2f}   | {t['exit_reason']}")

if __name__ == "__main__":
    run_minute_playback()
