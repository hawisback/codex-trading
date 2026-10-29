#!/usr/bin/env python3
"""
Deep-Dive Failure and False-Veto Diagnostics across June 2026
"""

from collections import defaultdict
from backtest_engine import BacktestEngine, StrategyConfig
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

consultant = AIConsultant(mode="playbook")
s3_cfg = StrategyConfig.load_from_config("institutional_pullback")

dates = [
    "2026-06-01", "2026-06-02", "2026-06-03", "2026-06-04", "2026-06-05",
    "2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12",
    "2026-06-15", "2026-06-16", "2026-06-17", "2026-06-18", "2026-06-19"
]

approved_losses = []
vetoed_wins = []

for d in dates:
    eng = BacktestEngine(d)
    trades = eng.run_simulation(s3_cfg)
    dte = eng.get_expiry_days()
    for i, t in enumerate(trades, 1):
        idx = [k for k, c in enumerate(eng.spot_candles) if t.entry_time in c["start_time"]][0]
        dos = generate_market_dossier(
            target_date=d, candles=eng.spot_candles, current_bar_idx=idx,
            direction=t.direction, symbol=t.symbol, strike=t.strike,
            option_entry_price=t.entry_price, trade_history=trades[:i-1],
            days_to_expiry=dte, is_expiry_0dte=(dte <= 0.2)
        )
        v = consultant.evaluate(dos)
        if v.is_approved and t.pnl <= 0:
            approved_losses.append((d, i, t, dos, v))
        elif not v.is_approved and t.pnl > 0:
            vetoed_wins.append((d, i, t, dos, v))

print("=" * 110)
print(f" 🔍 PART 1: FORENSIC ANALYSIS OF APPROVED LOSSES (Total: {len(approved_losses)})")
print("=" * 110)

loss_exit_reasons = defaultdict(list)
for d, i, t, dos, v in approved_losses:
    loss_exit_reasons[t.exit_reason.split()[0]].append(t)

print("\n--- Distribution of Exit Reasons for Losses ---")
for reason, tr_list in sorted(loss_exit_reasons.items(), key=lambda x: len(x[1]), reverse=True):
    tot_loss = sum(t.pnl for t in tr_list)
    avg_loss = tot_loss / len(tr_list)
    avg_hold = sum(t.hold_minutes for t in tr_list) / len(tr_list)
    avg_peak = sum(t.peak_gain_pct for t in tr_list) / len(tr_list)
    print(f"  • {reason:<28}: {len(tr_list):>2} trades | Total PnL: Rs {tot_loss:>9.2f} | Avg: Rs {avg_loss:>7.2f} | Avg Hold: {avg_hold:4.1f}m | Avg Peak: {avg_peak:4.1f}%")

print("\n--- Detailed Trade Log of Approved Losses ---")
print(f"{'Date':<11} {'Trd':<4} {'Dir':<3} {'Entry':<6} {'Exit':<6} {'Hold':<5} {'Peak%':<6} {'Exit Reason':<28} {'PnL (Rs)':<10} {'Key Dossier Metrics'}")
print("-" * 110)

for d, i, t, dos, v in approved_losses:
    reason_short = t.exit_reason[:27]
    metrics = f"VWAP_sl={dos.vwap_slope_15m:+.3f} | VWAP_dist={dos.vwap_distance_pts:.1f} | EMA_sprd={dos.ema_spread_5m:.1f} | BoxPos={dos.box_position_pct:.0f}%"
    print(f"{d:<11} #{i:<3} {t.direction:<3} {t.entry_time[:5]:<6} {t.exit_time[:5]:<6} {t.hold_minutes:<5} {t.peak_gain_pct:>5.1f}% {reason_short:<28} Rs {t.pnl:>8.2f}  {metrics}")

print("\n" + "=" * 110)
print(f" 🎯 PART 2: FORENSIC ANALYSIS OF VETOED WINS (Total: {len(vetoed_wins)})")
print("=" * 110)

veto_trap_breakdown = defaultdict(list)
for d, i, t, dos, v in vetoed_wins:
    veto_trap_breakdown[v.trap_detected or "General"].append(t)

print("\n--- Breakdown of Why Winning Trades Were Vetoed ---")
for trap, tr_list in sorted(veto_trap_breakdown.items(), key=lambda x: len(x[1]), reverse=True):
    tot_pnl = sum(t.pnl for t in tr_list)
    avg_pnl = tot_pnl / len(tr_list)
    print(f"  • {trap:<45}: {len(tr_list):>2} trades | Forgone PnL: Rs {tot_pnl:>9.2f} (Avg: Rs {avg_pnl:>7.2f})")

print("\n--- Detailed Trade Log of Vetoed Wins ---")
print(f"{'Date':<11} {'Trd':<4} {'Dir':<3} {'Entry':<6} {'Exit':<6} {'Hold':<5} {'Peak%':<6} {'PnL (Rs)':<9} {'Trap Triggered':<35} {'Why did it win?'}")
print("-" * 110)

for d, i, t, dos, v in vetoed_wins:
    metrics = f"VWAP_sl={dos.vwap_slope_15m:+.3f}, cross={dos.vwap_cross_count_60m}, dist={dos.vwap_distance_pts:.1f}, spr={dos.ema_spread_5m:.1f}"
    print(f"{d:<11} #{i:<3} {t.direction:<3} {t.entry_time[:5]:<6} {t.exit_time[:5]:<6} {t.hold_minutes:<5} {t.peak_gain_pct:>5.1f}% Rs {t.pnl:>7.2f}  {v.trap_detected:<35} {metrics}")
