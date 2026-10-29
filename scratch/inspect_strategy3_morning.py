import sys
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")
from trading.bootstrap import configure_console
configure_console()

import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

DATES = [
    "2026-09-11", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
    "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-05",
    "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09", "2026-10-12",
    "2026-10-13", "2026-10-14", "2026-10-15", "2026-10-16", "2026-10-19",
    "2026-10-21", "2026-10-22", "2026-10-23", "2026-10-26", "2026-10-27"
]

cfg = StrategyConfig.load_from_config("institutional_pullback")
c_prod = AIConsultant(mode="rules")

app_trades = []
for dt_str in DATES:
    try:
        eng = BacktestEngine(dt_str)
        raw = eng.run_simulation(cfg)
        dte = eng.get_expiry_days()
        is_0dte = (dte <= 0.2)
        for i, t in enumerate(raw, 1):
            matches = [k for k, x in enumerate(eng.spot_candles) if t.entry_time in x["start_time"]]
            if not matches: continue
            idx = matches[0]
            dos = generate_market_dossier(
                dt_str, eng.spot_candles, idx, t.direction, t.symbol, t.strike,
                t.entry_price, raw[:i-1], dte, is_0dte
            )
            verdict = c_prod.evaluate(dos)
            if verdict.is_approved:
                app_trades.append((dt_str, t))
    except Exception:
        continue

print(f"Total Strategy 3 Approved Trades: {len(app_trades)}")
morn = [x for x in app_trades if x[1].entry_time < "11:30"]
print(f"Strategy 3 Morning Trades (< 11:30): {len(morn)}")
morn_w = [x for x in morn if x[1].pnl > 0]
print(f"Strategy 3 Morning Wins: {len(morn_w)} / {len(morn)} ({len(morn_w)/len(morn)*100:.1f}% WR)")

print("\nStrategy 3 Morning Trades Detail:")
for dt, t in morn:
    status = "WIN " if t.pnl > 0 else "LOSS"
    pnl = t.pnl * 2 - 40
    print(f"{dt} {t.entry_time} | {status} | {t.direction} {t.strike} | Entry: {t.entry_price:.2f} Exit: {t.exit_price:.2f} | Peak: +{t.peak_gain_pct:.1f}% | PnL: Rs {pnl:+8.2f} | {t.exit_reason}")
