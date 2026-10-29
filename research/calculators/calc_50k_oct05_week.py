#!/usr/bin/env python3
"""
Lot Sizing and Profit Calculation for Rs 50,000 Capital
Target Week: October 05 - 09, 2026 (Last Week)
Strategy: Strategy 3 (Institutional Pullback) + AI Consultant + Continuous 1% Trailing
"""

from backtest_engine import BacktestEngine, StrategyConfig
from test_incremental_trailing import IncrementalTrailingEngine
from audit_last_week_deep import PreciseConsultant
from ai_context_dossier import generate_market_dossier

consultant = PreciseConsultant(mode="playbook")
s3 = StrategyConfig.load_from_config("institutional_pullback")

week10 = [
    ("Monday, Oct 05", "2026-10-05"),
    ("Tuesday, Oct 06 (0DTE)", "2026-10-06"),
    ("Wednesday, Oct 07", "2026-10-07"),
    ("Thursday, Oct 08", "2026-10-08"),
    ("Friday, Oct 09", "2026-10-09")
]

def run_calculation():
    print("=" * 115)
    print(" 💰 CAPITAL & LOT SIZING SIMULATION: RS 50,000 TRADING ACCOUNT")
    print(" Target Period: Week of October 05 - 09, 2026 (5 Sessions)")
    print(" Model: Institutional Pullback S3 + AI Risk Gateway + Continuous 1% Incremental Trailing")
    print("=" * 115)

    starting_capital = 50000.0
    
    # We will track 3 Sizing Scenarios:
    # Scenario A: Baseline 1 Lot (Conservative baseline, 65 qty)
    # Scenario B: Fixed Sizing - Max lots you can buy with Rs 50,000 (re-evaluated per trade based on premium)
    # Scenario C: Fixed Risk Allocation (Max 50% capital per trade = Rs 25,000 max deployed per trade for safety)
    # Scenario D: Compounded Account (Capital grows/draws down as trades execute)

    trades_data = []

    for label, d in week10:
        ei = IncrementalTrailingEngine(d, activation_pct=20.0, trail_offset_pct=10.0)
        tr_i = ei.run_simulation(s3)
        dte = ei.get_expiry_days()

        for i, t in enumerate(tr_i, 1):
            idx = [k for k, c in enumerate(ei.spot_candles) if t.entry_time in c["start_time"]][0]
            dos = generate_market_dossier(d, ei.spot_candles, idx, t.direction, t.symbol, t.strike, t.entry_price, tr_i[:i-1], dte, (dte <= 0.2))
            v = consultant.evaluate(dos)
            if v.is_approved:
                trades_data.append((label, d, t, v))

    print(f"\nTotal AI Approved Trades Taken: {len(trades_data)}")
    print("-" * 115)
    print(f"{'#':<3} {'Day & Date':<15} {'Dir':<4} {'Time':<6} {'Premium':<9} {'Cost/Lot':<10} {'Max Lots':<9} {'Cap Deployed':<13} {'Gain%':<7} {'1-Lot PnL':<11} {'50k Net PnL'}")
    print("-" * 115)

    tot_1lot_net = 0.0
    tot_50k_net = 0.0
    tot_safe_net = 0.0

    current_compound_cap = starting_capital

    for idx, (label, d, t, v) in enumerate(trades_data, 1):
        prem = t.entry_price
        cost_1lot = prem * 65.0
        
        # Max lots under Rs 50,000
        max_lots = int(50000.0 // cost_1lot) if cost_1lot > 0 else 0
        max_lots = max(1, max_lots) # At least 1 lot if cost <= 50,000
        if cost_1lot > 50000.0:
            max_lots = 0 # Cannot afford
            
        cap_deployed = max_lots * cost_1lot
        
        # Safe Sizing: Max 50% capital = Rs 25,000 per trade
        safe_lots = int(25000.0 // cost_1lot) if cost_1lot > 0 else 0
        safe_lots = max(1, safe_lots) if cost_1lot <= 50000.0 else 0

        pts_gain = t.exit_price - t.entry_price
        pct_gain = (pts_gain / t.entry_price) * 100.0

        # PnL Scenario A: 1 Lot
        pnl_1lot = (pts_gain * 65.0) - 40.0 # Rs 40 fee
        tot_1lot_net += pnl_1lot

        # PnL Scenario B: Max Lots with Rs 50,000
        # Brokerage in India (Zerodha/Groww/Angel) is Rs 20 buy + Rs 20 sell = Rs 40 flat per order!
        # Statutory charges (STT 0.1% on sell side, exchange turnover 0.05%, GST) scale with volume ~ Rs 15-20 per lot
        # Let's conservatively deduct Rs 40 flat brokerage + Rs 25/lot statutory taxes
        fee_max_lots = 40.0 + (max_lots * 25.0)
        pnl_50k = (pts_gain * max_lots * 65.0) - fee_max_lots
        tot_50k_net += pnl_50k

        # Safe lots PnL
        fee_safe = 40.0 + (safe_lots * 25.0)
        pnl_safe = (pts_gain * safe_lots * 65.0) - fee_safe
        tot_safe_net += pnl_safe

        print(f"#{idx:<2} {label[:14]:<15} {t.direction:<4} {t.entry_time[:5]:<6} Rs {prem:>6.2f}  Rs {cost_1lot:>7.2f}  {max_lots:>2} lots   Rs {cap_deployed:>9.2f}   {pct_gain:>+5.1f}%  Rs {pnl_1lot:>8.2f}   Rs {pnl_50k:>10.2f}")

    print("-" * 115)
    print(f"SUMMARY TOTALS (WEEK OF OCT 05 - 09, 2026):")
    print(f"  1. Starting Capital:                       Rs  50,000.00")
    print(f"  2. Scenario 1 (Fixed 1 Lot Conservative):  Rs {tot_1lot_net:>10.2f}  ({(tot_1lot_net / starting_capital) * 100:+.2f}% ROI on 50k)")
    print(f"  3. Scenario 2 (Safe 50% Cap / 25k limit):  Rs {tot_safe_net:>10.2f}  ({(tot_safe_net / starting_capital) * 100:+.2f}% ROI on 50k)")
    print(f"  4. Scenario 3 (Max Lots under Rs 50k Cap): Rs {tot_50k_net:>10.2f}  ({(tot_50k_net / starting_capital) * 100:+.2f}% ROI on 50k)")
    print("=" * 115)

if __name__ == "__main__":
    run_calculation()
