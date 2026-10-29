import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

def audit_week6_and_7():
    s3 = StrategyConfig.load_from_config("institutional_pullback")
    c = AIConsultant(mode="playbook")

    days = [
        ("Mon Sep 07", "2026-09-07"),
        ("Tue Sep 08", "2026-09-08"),
        ("Wed Sep 09", "2026-09-09"),
        ("Thu Sep 10", "2026-09-10"),
        ("Fri Sep 11", "2026-09-11"),
        ("Tue Sep 15", "2026-09-15"),
        ("Wed Sep 16", "2026-09-16"),
        ("Thu Sep 17", "2026-09-17"),
        ("Fri Sep 18", "2026-09-18"),
    ]

    print("=" * 125)
    print(" 🔬 MACRO MARKET FORENSIC AUDIT: WEEKS 6 & 7 (SEP 07 - SEP 18, 2026)")
    print("=" * 125)

    for day_label, d in days:
        eng = BacktestEngine(d)
        candles = eng.spot_candles
        if not candles:
            print(f"\n{day_label} ({d}): NO DATA (Market Holiday)")
            continue

        o = candles[0]["open"]
        h = max(c["high"] for c in candles)
        l = min(c["low"] for c in candles)
        cl = candles[-1]["close"]
        day_range = h - l

        # VWAP crossings analysis (The Chop / Blender Index)
        vwap_crossings = 0
        vwap_arr = []
        cum_vol = 0
        cum_tp_vol = 0
        for i, c_bar in enumerate(candles):
            tp = (c_bar["high"] + c_bar["low"] + c_bar["close"]) / 3.0
            v = c_bar.get("volume", 1000) or 1000
            cum_vol += v
            cum_tp_vol += tp * v
            vw = cum_tp_vol / cum_vol
            vwap_arr.append(vw)
            if i > 0:
                prev_c = candles[i-1]["close"]
                prev_vw = vwap_arr[i-1]
                curr_c = c_bar["close"]
                if (prev_c < prev_vw and curr_c > vw) or (prev_c > prev_vw and curr_c < vw):
                    vwap_crossings += 1

        raw = eng.run_simulation(s3)
        dte = eng.get_expiry_days()
        app = []
        for i, t in enumerate(raw, 1):
            idx = [k for k, x in enumerate(candles) if t.entry_time in x["start_time"]][0]
            dos = generate_market_dossier(d, candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, (dte <= 0.2))
            v = c.evaluate(dos)
            if v.is_approved:
                app.append((t, dos, v))

        m = calculate_metrics([x[0] for x in app])
        net2 = (m["net_pnl"] * 2) - len(app) * 40.0

        print(f"\n📅 {day_label} ({d}) | Open: {o:.1f} | High: {h:.1f} | Low: {l:.1f} | Close: {cl:.1f} | Day Range: {day_range:.1f} pts")
        print(f"   • VWAP Crossings (Chop Index): {vwap_crossings} crosses | Trend Direction: {'Bull (+)' if cl > o else 'Bear (-)'} ({cl - o:+.1f} pts)")
        print(f"   • Approved Trades: {len(app)} | Wins: {m['wins']} | Net PnL (2 Lots): ₹{net2:>+9.2f}")
        for t, dos, v in app:
            print(f"     -> {t.direction} @ {dos.time_ist} -> Exit {t.exit_time} | Entry ₹{t.entry_price:.2f} -> Exit ₹{t.exit_price:.2f} | PnL: ₹{t.pnl:>8.2f} ({t.pnl_pct:>5.1f}%) | Exit: {t.exit_reason}")
            print(f"        Indicators at Entry: Slope={dos.vwap_slope_15m:+.4f}, DistVWAP={dos.vwap_distance_pts:+.1f} pts, EMA Spread={dos.ema_spread_5m:+.2f} pts, RSI={dos.rsi_1m:.1f}, BoxSpread={dos.box_range_30m:.1f} pts")

if __name__ == "__main__":
    audit_week6_and_7()
