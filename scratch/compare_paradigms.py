import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()
from scratch.grid_search_macd_rsi_volume import precompute_market_data, run_simulation

def compare_top_paradigms():
    sessions = precompute_market_data()

    print("Deterministic rules comparison (NO AI). Exact contracts only; missing data is excluded.")
    print("OHLC execution estimates and approximate fees; not verified broker fills or live-equivalent returns.")
    # Paradigm A: Full Momentum (Raw 2m MACD)
    p_a = run_simulation(sessions, macd_mode="raw", rsi_mode="none", rsi_tf="2m", vol_mode="none", vol_thresh=1.0)

    # Paradigm B: Sniper Dual-Volume
    p_b = run_simulation(sessions, macd_mode="raw", rsi_mode="none", rsi_tf="2m", vol_mode="either", vol_thresh=1.15)

    # Paradigm C: Balanced Sweet Spot
    p_c = run_simulation(sessions, macd_mode="raw", rsi_mode="sweet_spot", rsi_tf="1m", vol_mode="either", vol_thresh=1.15)

    if not p_a["n"] and p_a["missing_contracts"]:
        print(f"INSUFFICIENT VERIFIED DATA: {p_a['missing_contracts']} candidates lack exact contract history.")
        print("No profit, ROI or win-rate result can be validated from these files.")
        return

    print(f"Candidates without exact contract data: A={p_a['missing_contracts']}, B={p_b['missing_contracts']}, C={p_c['missing_contracts']}")
    print("=" * 115)
    print(" ðŸ”¬ SIDE-BY-SIDE PARADIGM COMPARISON")
    print("=" * 115)
    print(f"{'Paradigm':<40} | {'Trades':<7} | {'Win%':<6} | {'Final Capital':<15} | {'Net Profit':<14} | {'Max DD%':<8} | {'PF':<5}")
    print("-" * 115)
    print(f"{'Paradigm A: Full Momentum (No Vol/RSI)':<40} | {p_a['n']:<7} | {p_a['wr']:<5.1f}% | â‚¹{p_a['capital']:<14,.2f} | â‚¹{p_a['comp_pnl']:<13,.2f} | {p_a['max_dd']:<7.1f}% | {p_a['pf']:<5.2f}")
    print(f"{'Paradigm B: Sniper (Dual Vol >= 1.15x)':<40} | {p_b['n']:<7} | {p_b['wr']:<5.1f}% | â‚¹{p_b['capital']:<14,.2f} | â‚¹{p_b['comp_pnl']:<13,.2f} | {p_b['max_dd']:<7.1f}% | {p_b['pf']:<5.2f}")
    print(f"{'Paradigm C: Sweet-Spot (1m RSI + Dual Vol)':<40} | {p_c['n']:<7} | {p_c['wr']:<5.1f}% | â‚¹{p_c['capital']:<14,.2f} | â‚¹{p_c['comp_pnl']:<13,.2f} | {p_c['max_dd']:<7.1f}% | {p_c['pf']:<5.2f}")

if __name__ == "__main__":
    compare_top_paradigms()
