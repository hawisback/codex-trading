import os
import sys
import json
import urllib.request
from datetime import datetime

sys.path.insert(0, ".")

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics
from ai_context_dossier import generate_market_dossier
from ai_consultant import AIConsultant

def main():
    target_date = "2026-10-14"
    save_path = f"data/spot_candles_{target_date.replace('-', '')}.json"
    
    # 1. Fetch candles from API and save
    print(f"Fetching today's ({target_date}) 1m candles from localhost:8000...")
    url = "http://localhost:8000/api/v1/ai/nifty/candles?interval=1m&limit=375"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        candles = data.get("candles", [])

    print(f"Loaded {len(candles)} candles. Saving to {save_path}...")
    with open(save_path, "w", encoding="utf-8") as f:
        json.dump(candles, f, indent=2)

    # 2. Run BacktestEngine for all three strategies
    print("\n" + "=" * 90)
    print(f" RUNNING BACKTEST ENGINE ON TODAY'S COMPLETE DATASET ({target_date})")
    print(f" Dataset Size: {len(candles)} 1-minute bars (09:15 to 15:29 IST)")
    print("=" * 90)

    engine = BacktestEngine(target_date=target_date)
    ai_consultant = AIConsultant(mode="playbook")
    strategies = ["legacy_scalper", "structural_runner", "institutional_pullback"]

    results = {}
    for strat_key in strategies:
        cfg = StrategyConfig.load_from_config(strat_key)
        all_trades = engine.run_simulation(cfg)

        approved = []
        vetoed = []

        for idx, trade in enumerate(all_trades, 1):
            bar_idx = trade.entry_bar
            hist = engine.spot_candles[:bar_idx + 1]

            dossier = generate_market_dossier(
                target_date=target_date,
                candles=hist,
                current_bar_idx=len(hist) - 1,
                direction=trade.direction,
                symbol=trade.symbol,
                strike=trade.strike,
                option_entry_price=trade.entry_price,
                trade_history=approved,
                days_to_expiry=5.0,  # Wednesday -> Tuesday expiry = 5 days
                is_expiry_0dte=False
            )

            verdict = ai_consultant.evaluate(dossier)
            trade.ai_verdict = verdict

            if verdict.is_approved:
                approved.append(trade)
            else:
                vetoed.append(trade)

        results[strat_key] = {
            "name": cfg.name,
            "raw_trades": all_trades,
            "approved": approved,
            "vetoed": vetoed,
            "raw_metrics": calculate_metrics(all_trades),
            "ai_metrics": calculate_metrics(approved)
        }

    # Print summary table
    print("\n" + "=" * 105)
    print(f" SUMMARY OF TODAY'S STRATEGY BACKTEST RESULTS ({target_date})")
    print("=" * 105)
    print(f"{'Strategy Profile':<38} | {'Raw Cand':<8} | {'AI Appr':<7} | {'Win%':<7} | {'Gross PnL':<14} | {'Net PnL (1 Lot)':<16}")
    print("-" * 105)

    for k, res in results.items():
        m = res["ai_metrics"]
        name = res["name"]
        raw_c = len(res["raw_trades"])
        app_c = len(res["approved"])
        win_pct = f"{m['win_rate']:.1f}%" if app_c > 0 else "N/A"
        friction = app_c * 40.0
        net = m["net_pnl"] - friction
        print(f"{name:<38} | {raw_c:<8} | {app_c:<7} | {win_pct:<7} | ₹{m['net_pnl']:+12,.2f} | ₹{net:+14,.2f}")

    print("\n" + "=" * 105)
    print(" DETAILED TRADE-BY-TRADE AUDIT ACROSS STRATEGIES:")
    print("=" * 105)

    for k, res in results.items():
        print(f"\n--- {res['name']} ---")
        if not res["raw_trades"]:
            print("  No trade candidates triggered.")
            continue
        for t in res["raw_trades"]:
            v = t.ai_verdict
            v_str = f"APPROVED ({getattr(v, 'confidence_score', 0)}%)" if (v and v.is_approved) else f"VETOED ({getattr(v, 'trap_detected', 'VETO')})"
            pnl_1lot = (t.exit_price - t.entry_price) * 65.0 if t.exit_price else 0.0
            print(f"  Bar {t.entry_bar:<3} ({t.entry_time[-14:-6]} IST) | {t.direction:<2} {t.strike} @ ₹{t.entry_price:<6.2f} -> Exit @ ₹{t.exit_price or 0:<6.2f} | PnL: ₹{pnl_1lot:+8.2f} ({t.pnl_pct:+5.1f}%) | Reason: {t.exit_reason} | AI: {v_str}")
            if v and not v.is_approved:
                print(f"    -> Veto Reason: {getattr(v, 'reasoning', '')}")

if __name__ == "__main__":
    main()
