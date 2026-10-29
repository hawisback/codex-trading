#!/usr/bin/env python3
"""
Comprehensive 10-Week Forensic Audit (50 Trading Sessions)
Comparing Raw Strategy 3 vs AI-Assisted Strategy 3 across:
- July & August 2026 (Summer Consolidation Regime)
- September & October 2026 (Trending Expansion Regime)
"""

from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

consultant = AIConsultant(mode="playbook")

jul_aug_weeks = [
    ("Week 1 (Jul 06 - 10)", ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"]),
    ("Week 2 (Jul 13 - 17)", ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17"]),
    ("Week 3 (Jul 20 - 24)", ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24"]),
    ("Week 4 (Aug 10 - 14)", ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]),
    ("Week 5 (Aug 17 - 21)", ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"])
]

sep_oct_weeks = [
    ("Week 6 (Sep 07 - 11)", ["2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11"]),
    ("Week 7 (Sep 14 - 18)", ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]),
    ("Week 8 (Sep 21 - 25)", ["2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25"]),
    ("Week 9 (Sep 28 - Oct 02)", ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]),
    ("Week 10 (Oct 05 - 09)", ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"])
]

s3_cfg = StrategyConfig.load_from_config("institutional_pullback")

def calc_stats(tr):
    n = len(tr)
    w = len([t for t in tr if t.pnl > 0])
    gross = sum(t.pnl for t in tr)
    fee = n * 40.0
    net = gross - fee
    w_s = sum(t.pnl for t in tr if t.pnl > 0)
    l_s = abs(sum(t.pnl for t in tr if t.pnl <= 0))
    pf = (w_s / l_s) if l_s > 0 else 999.0
    wr = (w / n * 100) if n else 0.0
    return {
        "n": n, "w": w, "wr": wr,
        "gross": gross, "fee": fee, "net": net, "pf": pf
    }

def evaluate_period(weeks_list, label):
    raw_all, ai_all = [], []
    print(f"\n--- {label} ---")
    for w_name, dates in weeks_list:
        w_raw, w_ai = [], []
        for d in dates:
            eng = BacktestEngine(d)
            if not eng.spot_candles:
                continue
            dte = eng.get_expiry_days()
            trades = eng.run_simulation(s3_cfg)
            w_raw.extend(trades)
            raw_all.extend(trades)
            for i, t in enumerate(trades, 1):
                idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
                dos = generate_market_dossier(
                    target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
                    direction=t.direction, symbol=t.symbol, strike=t.strike,
                    option_entry_price=t.entry_price, trade_history=trades[:i-1],
                    days_to_expiry=dte, is_expiry_0dte=(dte <= 0.2)
                )
                
                v = consultant.evaluate(dos)
                if v.is_approved:
                    w_ai.append(t)
                    ai_all.append(t)
        
        ws_r = calc_stats(w_raw)
        ws_a = calc_stats(w_ai)
        print(f"  {w_name:<26} | Raw Net: Rs {ws_r['net']:>9.2f} ({ws_r['wr']:4.1f}%) | AI Net: Rs {ws_a['net']:>9.2f} ({ws_a['wr']:4.1f}%) | Alpha: Rs {ws_a['net'] - ws_r['net']:>+9.2f}")
    
    r_s = calc_stats(raw_all)
    a_s = calc_stats(ai_all)
    print(f"  >> Period Total: Raw Net = Rs {r_s['net']:>10,.2f} | AI Net = Rs {a_s['net']:>10,.2f} | Alpha = Rs {a_s['net'] - r_s['net']:>+10,.2f}")
    return r_s, a_s

if __name__ == "__main__":
    r1, a1 = evaluate_period(jul_aug_weeks, "JULY & AUGUST 2026 (SUMMER CONSOLIDATION REGIME - 25 SESSIONS)")
    r2, a2 = evaluate_period(sep_oct_weeks, "SEPTEMBER & OCTOBER 2026 (TRENDING EXPANSION REGIME - 25 SESSIONS)")

    print("\n" + "=" * 90)
    print(" GRAND 10-WEEK CONSOLIDATED MATRIX (50 TRADING SESSIONS)")
    print("=" * 90)
    print(f"{'Strategy Variant':<32} {'Trades':<8} {'Win%':<8} {'Gross P&L':<15} {'Friction':<12} {'Real Net P&L':<15} {'PF'}")
    print("-" * 90)
    
    tot_raw_trades = r1['n'] + r2['n']
    tot_raw_wins = r1['w'] + r2['w']
    tot_raw_gross = r1['gross'] + r2['gross']
    tot_raw_fee = r1['fee'] + r2['fee']
    tot_raw_net = r1['net'] + r2['net']
    tot_raw_pf = ((r1['gross'] + r2['gross']) / abs(r1['gross'] + r2['gross'] - tot_raw_net)) if tot_raw_net < 0 else 1.0 # approx
    
    tot_ai_trades = a1['n'] + a2['n']
    tot_ai_wins = a1['w'] + a2['w']
    tot_ai_gross = a1['gross'] + a2['gross']
    tot_ai_fee = a1['fee'] + a2['fee']
    tot_ai_net = a1['net'] + a2['net']
    
    print(f"{'Raw Strategy 3':<32} {tot_raw_trades:<8} {tot_raw_wins/tot_raw_trades*100:<7.1f}% Rs {tot_raw_gross:<12,.2f} Rs {tot_raw_fee:<9,.2f} Rs {tot_raw_net:<12,.2f}")
    print(f"{'AI-Assisted Strategy 3':<32} {tot_ai_trades:<8} {tot_ai_wins/tot_ai_trades*100:<7.1f}% Rs {tot_ai_gross:<12,.2f} Rs {tot_ai_fee:<9,.2f} Rs {tot_ai_net:<12,.2f}")
    print("-" * 90)
    print(f"NET AI ALPHA GENERATED ACROSS 50 SESSIONS: Rs {tot_ai_net - tot_raw_net:>+12,.2f}")
    print("=" * 90)
