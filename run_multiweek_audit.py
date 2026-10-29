#!/usr/bin/env python3
"""
Comprehensive 5-Week Backtest Audit (July & August 2026)
Across 25 Trading Days comparing:
1. Strategy 1: Legacy Scalper
2. Strategy 2: Structural Runner
3. Strategy 3: Institutional Pullback & ITM (Raw)
4. Strategy 3: AI-Assisted (via AIConsultant Playbook Evaluation)
"""

from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

weeks = [
    ("Week 1 (Jul 06 - 10)", ["2026-07-06", "2026-07-07", "2026-07-08", "2026-07-09", "2026-07-10"]),
    ("Week 2 (Jul 13 - 17)", ["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16", "2026-07-17"]),
    ("Week 3 (Jul 20 - 24)", ["2026-07-20", "2026-07-21", "2026-07-22", "2026-07-23", "2026-07-24"]),
    ("Week 4 (Aug 10 - 14)", ["2026-08-10", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]),
    ("Week 5 (Aug 17 - 21)", ["2026-08-17", "2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21"])
]

s1_cfg = StrategyConfig.load_from_config("legacy_scalper")
s2_cfg = StrategyConfig.load_from_config("structural_runner")
s3_cfg = StrategyConfig.load_from_config("institutional_pullback")
consultant = AIConsultant(mode="playbook")

all_s1, all_s2, all_s3_raw, all_s3_ai = [], [], [], []
week_results = []

def calc_stats(trades):
    n = len(trades)
    wins = len([t for t in trades if t.pnl > 0])
    gross = sum(t.pnl for t in trades)
    fee = n * 40.0
    net = gross - fee
    w_sum = sum(t.pnl for t in trades if t.pnl > 0)
    l_sum = abs(sum(t.pnl for t in trades if t.pnl <= 0))
    pf = (w_sum / l_sum) if l_sum > 0 else 999.0
    wr = (wins / n * 100) if n else 0.0
    return {
        "n": n, "wins": wins, "wr": wr,
        "gross": gross, "fee": fee, "net": net, "pf": pf
    }

print("Executing 25-session backtest across 5 weeks of July & August 2026...\n")

for w_name, dates in weeks:
    w_s1, w_s2, w_s3_r, w_s3_a = [], [], [], []
    for d in dates:
        eng = BacktestEngine(d)
        
        # S1
        t_s1 = eng.run_simulation(s1_cfg)
        w_s1.extend(t_s1)
        all_s1.extend(t_s1)
        
        # S2
        t_s2 = eng.run_simulation(s2_cfg)
        w_s2.extend(t_s2)
        all_s2.extend(t_s2)
        
        # S3 Raw
        t_s3 = eng.run_simulation(s3_cfg)
        w_s3_r.extend(t_s3)
        all_s3_raw.extend(t_s3)
        
        # S3 AI
        for i, t in enumerate(t_s3, 1):
            idx = 0
            for k, c in enumerate(eng.spot_candles):
                if t.entry_time in c["start_time"]:
                    idx = k
                    break
            dossier = generate_market_dossier(
                target_date=d,
                candles=eng.spot_candles,
                current_bar_idx=idx,
                direction=t.direction,
                symbol=t.symbol,
                strike=t.strike,
                option_entry_price=t.entry_price,
                trade_history=t_s3[:i-1],
                days_to_expiry=eng.get_expiry_days(),
                is_expiry_0dte=(eng.get_expiry_days() <= 0.2)
            )
            v = consultant.evaluate(dossier)
            if v.is_approved:
                w_s3_a.append(t)
                all_s3_ai.append(t)

    week_results.append({
        "week": w_name,
        "s1": calc_stats(w_s1),
        "s2": calc_stats(w_s2),
        "s3_raw": calc_stats(w_s3_r),
        "s3_ai": calc_stats(w_s3_a)
    })
    print(f"  Processed {w_name}: Raw S3 Net = ₹{calc_stats(w_s3_r)['net']:+,.2f} | AI Net = ₹{calc_stats(w_s3_a)['net']:+,.2f}")

print("\n" + "=" * 125)
print(" 3-STRATEGY CONSOLIDATED COMPARISON MATRIX: JULY & AUGUST 2026 (25 TRADING DAYS)")
print("=" * 125)
header = f"{'Strategy Name':<42} {'Trades':<8} {'Win%':<8} {'Gross P&L':<15} {'Friction':<12} {'Real Net':<15} {'PF'}"
print(header)
print("-" * 125)

def print_row(name, s):
    print(f"{name:<42} {s['n']:<8} {s['wr']:<8.1f}% ₹{s['gross']:<14,.2f} ₹{s['fee']:<11,.2f} ₹{s['net']:<14,.2f} {s['pf']:.2f}")

s1_tot = calc_stats(all_s1)
s2_tot = calc_stats(all_s2)
s3_r_tot = calc_stats(all_s3_raw)
s3_a_tot = calc_stats(all_s3_ai)

print_row("Strategy 1: Legacy Scalper", s1_tot)
print_row("Strategy 2: Structural Runner", s2_tot)
print_row("Strategy 3: Institutional Pullback (Raw)", s3_r_tot)
print("-" * 125)
print_row("Strategy 3: AI-Assisted (Playbook)", s3_a_tot)
print("=" * 125)

print("\n" + "=" * 125)
print(" WEEK-BY-WEEK BREAKDOWN: RAW STRATEGY 3 vs. AI-ASSISTED STRATEGY 3")
print("=" * 125)
print(f"{'Week':<25} {'Raw Trades':<12} {'Raw Net':<16} {'AI Trades':<12} {'AI Net':<16} {'AI Alpha Improvement':<20}")
print("-" * 125)
for r in week_results:
    w = r["week"]
    sr = r["s3_raw"]
    sa = r["s3_ai"]
    diff = sa["net"] - sr["net"]
    print(f"{w:<25} {sr['n']} ({sr['wr']:.1f}%){'':<4} ₹{sr['net']:>11,.2f}      {sa['n']} ({sa['wr']:.1f}%){'':<4} ₹{sa['net']:>11,.2f}      ₹{diff:>+14,.2f}")

print("=" * 125)
