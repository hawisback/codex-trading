import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from trading.bootstrap import configure_console
configure_console()

from trading.domain.market_data import resample_two_minutes, exchange_time
from trading.strategies.macd_momentum import calculate_macd
from ai_context_dossier import generate_market_dossier, MarketDossier
from trading.adapters.historical import load_option_history, OptionHistory
from trading.domain.historical_execution import simulate_option_path
from trading.domain.sizing import calculate_compounding_quantity
from ai_consultant import AIConsultant, AIVerdict

def run_backtest_today():
    date_str = "2026-10-27"
    spot_file = f"data/spot_candles_{date_str.replace('-', '')}.json"
    fut_file = f"data/fut_candles_{date_str.replace('-', '')}.json"
    
    with open(spot_file, "r") as fp:
        spot_bars = json.load(fp)
    with open(fut_file, "r") as fp:
        fut_bars = json.load(fp)
        
    opt_history = load_option_history(date_str, date_str)
    
    with open("config/strategies.json", "r") as fp:
        strategies_cfg = json.load(fp)
    with open("config/trading.json", "r") as fp:
        trading_cfg = json.load(fp)
        
    strat_cfg = strategies_cfg["strategies"]["macd_momentum"]
    exit_cfg = strat_cfg["exit"]
    comp_cfg = strat_cfg["compounding"]
    
    ai = AIConsultant(
        mode="playbook",
        trading_config=trading_cfg
    )
    
    res_spot = resample_two_minutes(spot_bars)
    closes = [b["close"] for b in res_spot]
    macd, sig, hist = calculate_macd(closes)
    
    print("=" * 115)
    print(f" 🚀 IN-DEPTH BACKTEST & AUDIT FOR TODAY: {date_str} (NIFTY 0DTE EXPIRY)")
    print(f" Strategy: {strat_cfg['display_name']}")
    print(f" Risk Management: Two-Step Model (Initial Stop: {exit_cfg['initial_stop_pct']}%, Trailing: Progressive Ratchet)")
    print(f" Sizing Model: Step-Ladder Compounding (Baseline Margin: Rs 10,000 | 2-10 Lots)")
    print("=" * 115)
    
    candidates = []
    trade_history = []
    executed_trades = []
    vetoed_list = []
    
    current_available_margin = float(comp_cfg.get("baseline_capital", 10000.0))
    peak_equity = current_available_margin
    in_trade_until = -1
    
    for i in range(26, len(res_spot)):
        pe_cross = (macd[i] < sig[i]) and (macd[i - 1] >= sig[i - 1])
        ce_cross = (macd[i] > sig[i]) and (macd[i - 1] <= sig[i - 1])
        
        if not (pe_cross or ce_cross):
            continue
            
        end_1m = res_spot[i]["minute_idx"]
        direction = "PE" if pe_cross else "CE"
        strike = 22750 # ATM
        spot_price = res_spot[i]["close"]
        bar_time = exchange_time(spot_bars[end_1m]["start_time"])
        time_str = bar_time.strftime("%H:%M:%S")
        
        # Check option price at candidate time
        opt_b = opt_history.bar(strike, direction, spot_bars[end_1m]["start_time"])
        opt_price = opt_b["close"] if opt_b else 0.0
        
        # Build dossier
        dossier = generate_market_dossier(
            target_date=date_str,
            candles=spot_bars,
            current_bar_idx=end_1m,
            direction=direction,
            symbol=f"NIFTY_{strike}_{direction}",
            strike=strike,
            option_entry_price=opt_price,
            trade_history=trade_history,
            days_to_expiry=0.05,
            is_expiry_0dte=True
        )
        
        # AI Companion Consultation Gatekeeper
        verdict: AIVerdict = ai.evaluate(dossier)
        
        # Position check: only 1 concurrent trade
        is_in_position = (end_1m <= in_trade_until)
        
        cand_info = {
            "index_2m": i,
            "minute_1m": end_1m,
            "time_ist": time_str,
            "direction": direction,
            "strike": strike,
            "spot": spot_price,
            "opt_price": opt_price,
            "dossier": dossier,
            "verdict": verdict,
            "in_position": is_in_position
        }
        candidates.append(cand_info)
        
        print(f"\n[{time_str} IST] CANDIDATE #{len(candidates)}: 2m MACD BUY_{direction} @ Spot {spot_price:.2f} (ATM {strike})")
        print(f"  • Option Close @ Signal: Rs {opt_price:.2f} | VWAP: {dossier.session_vwap:.2f} (Dist: {dossier.vwap_distance_pts:.1f} pts, Slope: {dossier.vwap_slope_15m:+.3f})")
        print(f"  • 5m Ribbon: EMA9 {dossier.ema9_5m:.2f} / EMA20 {dossier.ema20_5m:.2f} (Spread: {dossier.ema_spread_5m:+.2f} pts) | 1m RSI: {dossier.rsi_1m:.1f}")
        print(f"  • Box 30m: {dossier.box_range_30m:.1f} pts (Pos: {dossier.box_position_pct:.1f}%) | 2m Hist: {hist[i]:+.2f} (prev: {hist[i-1]:+.2f})")
        
        if is_in_position:
            print(f"  --> ENGINE STANDS ASIDE: Already in an open position until bar {in_trade_until}.")
            continue
            
        if not verdict.is_approved:
            print(f"  --> VERDICT: VETOED by AI Companion | Trap: {verdict.trap_detected}")
            print(f"      Rationale: {verdict.reasoning}")
            vetoed_list.append(cand_info)
            continue
            
        print(f"  --> VERDICT: APPROVED (Confidence: {verdict.confidence_score}%) | Trailing: {verdict.recommended_trailing}")
        print(f"      Rationale: {verdict.reasoning}")
        
        # Calculate dynamic compounding lots and quantity based on verified margin
        order_qty = calculate_compounding_quantity(
            current_available_margin,
            opt_price,
            strategy_cfg=strat_cfg,
            trading_cfg=trading_cfg,
            quantity=65
        )
        lots = order_qty // 65
        
        # Simulate execution path using trading/domain/historical_execution.py
        # Enters at next minute's OPEN (end_1m + 1)
        sim = simulate_option_path(
            signal_index=end_1m,
            direction=direction,
            spot_bars=spot_bars,
            options=opt_history,
            strike=strike,
            exit_config=exit_cfg
        )
        
        if not sim:
            print("  --> EXECUTION: Unable to execute simulation (missing candle or post-signal boundary).")
            continue
            
        entry_time = exchange_time(spot_bars[sim["entry_idx"]]["start_time"]).strftime("%H:%M:%S")
        exit_time = exchange_time(spot_bars[sim["exit_idx"]]["start_time"]).strftime("%H:%M:%S")
        
        pnl_single_contract = sim["pnl_pts"]
        total_pnl_inr = pnl_single_contract * order_qty
        trade_ret_pct = sim["ret_pct"]
        
        # Update capital & compounding
        current_available_margin += total_pnl_inr
        peak_equity = max(peak_equity, current_available_margin)
        in_trade_until = sim["exit_idx"]
        
        record = {
            "trade_num": len(executed_trades) + 1,
            "direction": direction,
            "strike": strike,
            "lots": lots,
            "quantity": order_qty,
            "entry_time": entry_time,
            "entry_price": sim["entry_price"],
            "exit_time": exit_time,
            "exit_price": sim["exit_price"],
            "peak_price": sim["peak_price"],
            "peak_gain_pct": sim["peak_gain_pct"],
            "pnl_pts": sim["pnl_pts"],
            "pnl_inr": total_pnl_inr,
            "ret_pct": trade_ret_pct,
            "exit_reason": sim["exit_reason"],
            "invalidation_spot": sim["invalidation_spot"],
            "equity_after": current_available_margin
        }
        executed_trades.append(record)
        trade_history.append(type('T', (), {'pnl': total_pnl_inr, 'direction': direction})())
        
        print(f"      [ORDER FILLED] {direction} {strike} x {order_qty} ({lots} lots) @ Rs {sim['entry_price']:.2f} at {entry_time} IST")
        print(f"      [INITIAL STOP] Rs {sim['entry_price'] * (1 - exit_cfg['initial_stop_pct']/100):.2f} (-{exit_cfg['initial_stop_pct']}%) | Spot Invalidation: {sim['invalidation_spot']:.1f}")
        print(f"      [EXIT FILLED]  Rs {sim['exit_price']:.2f} at {exit_time} IST ({trade_ret_pct:+5.1f}%) | Peak: +{sim['peak_gain_pct']:.1f}%")
        print(f"      [TRADE PNL]    Rs {total_pnl_inr:+,.2f} | Reason: {sim['exit_reason']}")
        print(f"      [ACCOUNT BAL]  Available Margin: Rs {current_available_margin:,.2f}")

    # Comprehensive Session Summary
    print("\n" + "=" * 115)
    print(f" 🏆 SUMMARY PERFORMANCE AUDIT FOR TODAY: {date_str} (NIFTY 0DTE)")
    print("=" * 115)
    
    total_proposed = len(candidates)
    total_approved = len(executed_trades)
    total_vetoed = len(vetoed_list)
    wins = [t for t in executed_trades if t["pnl_inr"] > 0]
    losses = [t for t in executed_trades if t["pnl_inr"] <= 0]
    win_rate = (len(wins) / total_approved * 100.0) if total_approved > 0 else 0.0
    net_pnl = sum(t["pnl_inr"] for t in executed_trades)
    gross_win = sum(t["pnl_inr"] for t in wins)
    gross_loss = abs(sum(t["pnl_inr"] for t in losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else 99.0
    net_roi = (net_pnl / float(comp_cfg.get("baseline_capital", 10000.0))) * 100.0
    
    print(f"Total 2m MACD Candidates Proposed:            {total_proposed}")
    print(f"Total Vetoed by AI Gatekeeper (Traps/Safety):  {total_vetoed} ({total_vetoed/total_proposed*100:.1f}% filtered)")
    print(f"Total Trades Executed:                         {total_approved}")
    print(f"Winning Trades:                                {len(wins)} / {total_approved} ({win_rate:.1f}% Win Rate)")
    print(f"Gross Profits:                                 Rs +{gross_win:,.2f}")
    print(f"Gross Losses:                                  Rs -{gross_loss:,.2f}")
    print(f"Net Realized Session PnL:                      Rs {net_pnl:+,.2f} ({net_roi:+.1f}% ROI on Rs 10k margin)")
    print(f"Profit Factor:                                 {profit_factor:.2f}")
    print(f"Peak Account Equity:                           Rs {peak_equity:,.2f}")
    print(f"Ending Available Margin:                       Rs {current_available_margin:,.2f}")
    
    print("\n" + "=" * 115)
    print(" 📋 DETAILED TRADE LEDGER")
    print("=" * 115)
    print(f"{'#':<3} | {'Dir':<4} | {'Lots':<4} | {'Entry Time':<10} | {'Entry':<8} | {'Exit Time':<10} | {'Exit':<8} | {'Peak%':<8} | {'Return%':<9} | {'Net PnL':<12} | {'Exit Rationale'}")
    print("-" * 115)
    for t in executed_trades:
        print(f"{t['trade_num']:<3} | {t['direction']:<4} | {t['lots']:<4} | {t['entry_time']:<10} | Rs {t['entry_price']:<5.2f} | {t['exit_time']:<10} | Rs {t['exit_price']:<5.2f} | +{t['peak_gain_pct']:<6.1f}% | {t['ret_pct']:+6.1f}%   | Rs {t['pnl_inr']:+8.2f}   | {t['exit_reason']}")

    print("\n" + "=" * 115)
    print(" 🛡️ CATALOG OF VETOED CANDIDATES (CAPITAL PRESERVATION)")
    print("=" * 115)
    for v in vetoed_list:
        ver = v["verdict"]
        print(f"[{v['time_ist']} IST] BUY_{v['direction']} {v['strike']} @ Spot {v['spot']:.2f} | VETO: {ver.trap_detected}")
        print(f"  --> Rationale: {ver.reasoning}\n")

if __name__ == "__main__":
    run_backtest_today()
