import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

def inspect_vwap_crosses():
    s3 = StrategyConfig.load_from_config("institutional_pullback")
    c = AIConsultant(mode="playbook")

    all_days = [
        "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
        "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
        "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
        "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01",
        "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
        "2026-10-12", "2026-10-13"
    ]

    header = f"{'Date':<10} | {'Dir':<3} @ {'Time':<8} | {'PnL ₹':<9} | {'Win?':<4} | {'Exit Reason':<25} | {'VWAP Crosses':<12} | {'Dist VWAP':<10} | {'Day Range'}"
    print(header)
    print("-" * 110)

    for d in all_days:
        eng = BacktestEngine(d)
        raw = eng.run_simulation(s3)
        dte = eng.get_expiry_days()
        candles = eng.spot_candles

        cum_v = 0; cum_tp_v = 0; vwap_arr = []
        for c_b in candles:
            tp = (c_b["high"] + c_b["low"] + c_b["close"])/3.0
            v = c_b.get("volume", 1000) or 1000
            cum_v += v; cum_tp_v += tp * v
            vwap_arr.append(cum_tp_v / cum_v)

        for i, t in enumerate(raw, 1):
            idx = [k for k, x in enumerate(candles) if t.entry_time in x["start_time"]][0]
            dos = generate_market_dossier(d, candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, (dte<=0.2))
            verdict = c.evaluate(dos)
            if verdict.is_approved:
                crosses = 0
                for j in range(1, idx + 1):
                    p_c = candles[j-1]["close"]; p_vw = vwap_arr[j-1]
                    c_c = candles[j]["close"]; c_vw = vwap_arr[j]
                    if (p_c < p_vw and c_c > c_vw) or (p_c > p_vw and c_c < c_vw):
                        crosses += 1
                range_so_far = max(c_b["high"] for c_b in candles[:idx+1]) - min(c_b["low"] for c_b in candles[:idx+1])
                is_win = "WIN" if t.pnl > 0 else "LOSS"
                print(f"{d} | {t.direction} @ {dos.time_ist} | ₹{t.pnl:>8.2f} | {is_win:<4} | {t.exit_reason[:24]:<25} | {crosses:>2} crosses   | {dos.vwap_distance_pts:>+5.1f} pts  | {range_so_far:>5.1f} pts")

if __name__ == "__main__":
    inspect_vwap_crosses()
