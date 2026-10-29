#!/usr/bin/env python3
"""
Compound Simulation Starting with Rs 10,000 Capital
Target Week: October 05 - 09, 2026 (Last Week)
Strategy: Strategy 3 (Institutional Pullback) + AI Risk Gateway + Continuous 1% Trailing
"""

from backtest_engine import BacktestEngine, StrategyConfig
from test_incremental_trailing import IncrementalTrailingEngine
from audit_last_week_deep import PreciseConsultant
from ai_context_dossier import generate_market_dossier

consultant = PreciseConsultant(mode="playbook")
s3 = StrategyConfig.load_from_config("institutional_pullback")

week10 = [
    ("2026-10-05", "Mon Oct 05"),
    ("2026-10-06", "Tue Oct 06 (0DTE)"),
    ("2026-10-07", "Wed Oct 07"),
    ("2026-10-08", "Thu Oct 08"),
    ("2026-10-09", "Fri Oct 09")
]

def run_10k_compound():
    print("=" * 115)
    print(" 🚀 STRATEGY D: SEQUENTIAL COMPOUND SIMULATION STARTING WITH RS 10,000")
    print(" Target Period: Week of October 05 - 09, 2026 (Last Week)")
    print(" Model: Institutional Pullback S3 + AI Risk Gateway + Continuous 1% Incremental Trailing")
    print("=" * 115)

    starting_capital = 10000.0
    capital = starting_capital
    
    print(f"Starting Account Balance: Rs {capital:,.2f}")
    print("-" * 115)
    print(f"{'Trd':<4} {'Date & Time':<20} {'Dir':<4} {'Premium':<9} {'Cost/Lot':<11} {'Lots':<7} {'Deployed':<12} {'Gain%':<7} {'Trade Net':<12} {'New Balance'}")
    print("-" * 115)

    trd_count = 0
    trade_logs = []

    for d, label in week10:
        ei = IncrementalTrailingEngine(d, activation_pct=20.0, trail_offset_pct=10.0)
        tr = ei.run_simulation(s3)
        dte = ei.get_expiry_days()

        for i, t in enumerate(tr, 1):
            idx = [k for k, c in enumerate(ei.spot_candles) if t.entry_time in c["start_time"]][0]
            dos = generate_market_dossier(d, ei.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, tr[:i-1], dte, (dte <= 0.2))
            v = consultant.evaluate(dos)
            if v.is_approved:
                trd_count += 1
                cost_lot = round(t.entry_price * 65.0, 2)
                lots = int(capital // cost_lot)

                if lots < 1:
                    print(f"#{trd_count:<3} {label} {t.entry_time[:5]:<6} {t.direction:<4} Rs {t.entry_price:>6.2f}  Rs {cost_lot:>8.2f}   0 lts  Rs      0.00   (SKIPPED - Capital Rs {capital:,.2f} < 1 Lot Cost Rs {cost_lot:,.2f})")
                    trade_logs.append((label, t, cost_lot, 0, 0.0, 0.0, 0.0, capital, True))
                    continue

                deployed = round(lots * cost_lot, 2)
                pts = t.exit_price - t.entry_price
                gain_pct = (pts / t.entry_price) * 100.0
                
                # Deduct Rs 40 flat brokerage + Rs 25/lot statutory taxes (STT 0.1%, exchange charges, GST, stamp duty)
                fee = 40.0 + (lots * 25.0)
                pnl = round((pts * lots * 65.0) - fee, 2)
                capital = round(capital + pnl, 2)

                print(f"#{trd_count:<3} {label} {t.entry_time[:5]:<6} {t.direction:<4} Rs {t.entry_price:>6.2f}  Rs {cost_lot:>8.2f}  {lots:>2} lts  Rs {deployed:>9.2f}   {gain_pct:>+5.1f}%  Rs {pnl:>+9.2f}   Rs {capital:>10.2f}")
                trade_logs.append((label, t, cost_lot, lots, deployed, gain_pct, pnl, capital, False))

    net_profit = capital - starting_capital
    roi = (net_profit / starting_capital) * 100.0

    print("-" * 115)
    print(" 🏆 FINAL COMPOUNDING RECAP (OCTOBER 05 - 09, 2026):")
    print(f"   Initial Starting Capital:  Rs  {starting_capital:>10,.2f}")
    print(f"   Final Account Balance:     Rs  {capital:>10,.2f}")
    print(f"   Total Net Compounded Gain: Rs  {net_profit:>10,.2f}  ({roi:+.2f}% Weekly ROI)")
    print("=" * 115)

if __name__ == "__main__":
    run_10k_compound()
