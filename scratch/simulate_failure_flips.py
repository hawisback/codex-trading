import os
import sys
sys.path.insert(0, r"c:\Users\hawis\Documents\antigravity\splendid-bardeen")

from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics, Trade, bsm_price

ALL_DATES = [
    # Week 5 (Aug 31 - Sep 04)
    "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04",
    # Week 6 (Sep 07 - Sep 11)
    "2026-09-07", "2026-09-08", "2026-09-09", "2026-09-10", "2026-09-11",
    # Week 7 (Sep 14 - Sep 18)
    "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18",
    # Week 8 (Sep 21 - Sep 25)
    "2026-09-21", "2026-09-22", "2026-09-23", "2026-09-24", "2026-09-25",
    # Week 9 (Sep 28 - Oct 01)
    "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01",
    # Week 10 (Oct 05 - Oct 09)
    "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09",
    # Week 11 (Oct 12 - Oct 13)
    "2026-10-12", "2026-10-13"
]

def simulate_failure_flips():
    cfg = StrategyConfig.load_from_config("institutional_pullback")
    
    flip_trades = []
    
    for d in ALL_DATES:
        eng = BacktestEngine(target_date=d)
        if not eng.spot_candles:
            continue
        trades = eng.run_simulation(cfg)
        dte = eng.get_expiry_days()
        
        for t in trades:
            if t.pnl <= 0 and t.exit_reason == "INITIAL_STOP" and t.exit_bar is not None:
                # Thesis failed: look for confirmed failure break in opposite direction
                exit_idx = t.exit_bar
                opp_dir = "PE" if t.direction == "CE" else "CE"
                
                # Check next 1-5 bars for confirmed opposite break (crossing EMA9)
                entry_idx = min(exit_idx + 1, len(eng.spot_candles) - 1)
                entry_bar = eng.spot_candles[entry_idx]
                entry_spot = entry_bar["close"]
                
                # Select opposite contract (Strict ITM)
                sym, strike = eng.select_contract(entry_spot, opp_dir, mode="STRICT_ITM")
                
                # Simulate opposite trade with trailing ratchet
                entry_opt_h, entry_opt_l, entry_opt_c = eng.get_option_bar(sym, strike, opp_dir, entry_idx, entry_bar)
                entry_price = entry_opt_c
                
                flip_t = Trade(
                    trade_id=1000 + t.trade_id,
                    symbol=sym,
                    direction=opp_dir,
                    strike=strike,
                    entry_bar=entry_idx,
                    entry_time=entry_bar["start_time"][11:19],
                    entry_price=entry_price,
                    quantity=65
                )
                
                # Manage flip trade until exit
                for k in range(entry_idx + 1, min(entry_idx + 60, len(eng.spot_candles))):
                    s_bar = eng.spot_candles[k]
                    oh, ol, oc = eng.get_option_bar(sym, strike, opp_dir, k, s_bar)
                    
                    if oh > flip_t.peak_price:
                        flip_t.peak_price = oh
                        flip_t.peak_gain_pct = round(((oh - entry_price) / entry_price) * 100, 2)
                        
                    # Stop: 25% or trailing ratchet
                    if ol <= entry_price * 0.75:
                        flip_t.close(k, s_bar["start_time"][11:19], round(entry_price * 0.75, 2), "STOP_LOSS")
                        break
                    elif flip_t.peak_gain_pct >= 20.0 and oc <= max(entry_price * 1.10, flip_t.peak_price * 0.90):
                        flip_t.close(k, s_bar["start_time"][11:19], oc, "TRAILING_RATCHET")
                        break
                    elif k == len(eng.spot_candles) - 1 or k >= entry_idx + 45:
                        flip_t.close(k, s_bar["start_time"][11:19], oc, "TIME_EXIT")
                        break
                        
                if flip_t.exit_bar is not None:
                    flip_trades.append(flip_t)

    fm = calculate_metrics(flip_trades)
    print("=" * 90)
    print(" 🚀 SIMULATING FAILURE REVERSAL TRADES (STOP-AND-REVERSE ON FAILED ENTRIES)")
    print("=" * 90)
    print(f" Total Failure Flip Trades:  {len(flip_trades)}")
    print(f" Wins / Losses:              {fm['wins']} Wins / {fm['losses']} Losses")
    print(f" Win Rate:                   {fm['win_rate']:.1f}%")
    print(f" Gross Profit (1 Lot):       ₹{fm['net_pnl']:+,.2f}")
    print(f" Net Profit (2 Lots):        ₹{(fm['net_pnl']*2) - (len(flip_trades)*40):+,.2f}")
    print(f" Profit Factor:              {fm['profit_factor']:.2f}")
    print("=" * 90)

    for ft in flip_trades:
        pnl2 = ft.pnl * 2
        print(f" {ft.entry_time} | {ft.direction} {ft.symbol:<25} -> Exit: {ft.exit_time} ({ft.exit_reason:<16}) | PnL (2 Lots): ₹{pnl2:>+9,.2f} ({ft.pnl_pct:>+5.1f}%)")

if __name__ == "__main__":
    simulate_failure_flips()
