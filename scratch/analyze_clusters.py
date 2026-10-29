import sys
import os
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
import json
from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

def analyze_losses_vs_wins():
    s3 = StrategyConfig.load_from_config("institutional_pullback")
    c = AIConsultant(mode="playbook")

    weeks = [
        ("Week 8", ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]),
        ("Week 9", ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]),
        ("Week 10", ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]),
    ]

    wins = []
    losses = []

    for w_name, days in weeks:
        for d in days:
            eng = BacktestEngine(d)
            raw = eng.run_simulation(s3)
            dte = eng.get_expiry_days()
            for i, t in enumerate(raw, 1):
                idx = [k for k, x in enumerate(eng.spot_candles) if t.entry_time in x["start_time"]][0]
                dos = generate_market_dossier(d, eng.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, raw[:i-1], dte, (dte <= 0.2))
                v = c.evaluate(dos)
                if v.is_approved:
                    rec = {
                        "date": d,
                        "trade": t,
                        "dossier": dos,
                        "verdict": v,
                        "pnl": t.pnl,
                        "pnl_pct": t.pnl_pct,
                        "dir": t.direction
                    }
                    if t.pnl <= 0:
                        losses.append(rec)
                    else:
                        wins.append(rec)

    print("=" * 100)
    print(f" TOTAL APPROVED TRADES: {len(wins) + len(losses)} | WINS: {len(wins)} | LOSSES: {len(losses)}")
    print("=" * 100)

    # Let's inspect the key clusters of losses:
    # 1. Friday Sep 25 (Chop massacre: 5 losses, -₹3,444 PnL!)
    # 2. Midday Dead Zone (11:30 - 13:15) entries
    # 3. Consecutive losses rule (e.g. max 2 consecutive losses per day circuit breaker)
    # 4. Ribbon compression (EMA spread < 4 pts)
    # 5. Distance to VWAP / extreme extension

    print("\n--- CLUSTER 1: SESSION PHASE DISTRIBUTION ---")
    loss_phases = {}
    win_phases = {}
    for l in losses:
        p = l["dossier"].session_phase.split(" (")[0]
        loss_phases[p] = loss_phases.get(p, 0) + 1
    for w in wins:
        p = w["dossier"].session_phase.split(" (")[0]
        win_phases[p] = win_phases.get(p, 0) + 1

    all_phases = set(list(loss_phases.keys()) + list(win_phases.keys()))
    for p in sorted(all_phases):
        w_cnt = win_phases.get(p, 0)
        l_cnt = loss_phases.get(p, 0)
        tot = w_cnt + l_cnt
        wr = (w_cnt / tot * 100) if tot else 0
        print(f"  {p:<25}: {w_cnt:>2} Wins / {l_cnt:>2} Losses (Win Rate: {wr:5.1f}%)")

    print("\n--- CLUSTER 2: CONSECUTIVE LOSSES ON SAME DAY ---")
    for l in losses:
        dos = l["dossier"]
        t = l["trade"]
        print(f"  {l['date']} {t.direction} @ {dos.time_ist}: Consecutive Prev Losses = {dos.consecutive_losses_today}, Prev Realized PnL = ₹{dos.realized_pnl_today:,.2f}, PnL = ₹{t.pnl:.2f}")

    print("\n--- CLUSTER 3: RIBBON COMPRESSION (abs(ema_spread_5m) < 4.0) ---")
    for l in losses:
        dos = l["dossier"]
        t = l["trade"]
        print(f"  {l['date']} {t.direction} @ {dos.time_ist}: EMA spread = {dos.ema_spread_5m:+.2f} pts, Comp Hazard = {dos.ribbon_compression_hazard}, PnL = ₹{t.pnl:.2f}")

    print("\n--- CHECKING CANDIDATE FILTERS ---")
    # Candidate Filter A: Daily Max 2 Consecutive Losses Circuit Breaker (stop trading for day after 2 consecutive losses)
    # Candidate Filter B: Strict Ribbon Compression Hazard (never trade when abs(ema_spread) < 4.0 even if directional shift)
    # Candidate Filter C: Midday Dead Zone tighter VWAP slope
    
if __name__ == "__main__":
    analyze_losses_vs_wins()
