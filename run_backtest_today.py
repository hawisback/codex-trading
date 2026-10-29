import json
import urllib.request
from datetime import datetime, timezone, timedelta

def load_data():
    with open("option_candles_today.json", "r", encoding="utf-8") as f:
        option_data = json.load(f)

    # Fetch 1m spot candles
    res_1m = json.loads(urllib.request.urlopen("http://localhost:8000/api/v1/ai/nifty/candles?interval=1m&limit=400").read().decode("utf-8"))
    spot_1m = [c for c in res_1m.get("candles", []) if c["start_time"].startswith("2026-10-09")]

    return option_data, spot_1m

def calculate_ema(prices, period):
    if len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema

def run():
    option_data, spot_1m = load_data()
    print(f"Loaded {len(spot_1m)} 1m Spot candles.")

    # 1. First, analyze the 6 MAX_HOLD_TIME trades specifically:
    # What would their P&L have been if held under 5m EMA9 trailing stop?
    res_trades = json.loads(urllib.request.urlopen("http://localhost:8000/api/v1/ai/trades?limit=100").read().decode("utf-8"))
    today_trades = [t for t in res_trades if t.get("entry_time") and t.get("entry_time").startswith("2026-10-09")]
    today_trades.reverse()

    max_hold_trades = [t for t in today_trades if t.get("exit_reason") == "MAX_HOLD_TIME"]
    print("\n" + "=" * 90)
    print("ANALYSIS OF THE 6 TRADES TRUNCATED BY 8-MIN 'MAX_HOLD_TIME'")
    print("=" * 90)

    for t in max_hold_trades:
        sym = t.get("symbol")
        entry_t_str = t.get("entry_time")[11:19]
        exit_t_str = t.get("exit_time")[11:19]
        entry_p = t.get("entry_price")
        actual_exit_p = t.get("exit_price")
        actual_pnl = t.get("pnl")

        # Find entry index in 375 candles (09:15 = 0)
        h, m, s = map(int, entry_t_str.split(":"))
        entry_idx = (h - 9) * 60 + m - 15

        c_list = option_data.get(sym, [])
        if not c_list:
            continue

        # See what happened over next 45 minutes
        future_candles = c_list[entry_idx : min(len(c_list), entry_idx + 45)]
        peak_future = max([c["high"] for c in future_candles]) if future_candles else entry_p
        final_future = future_candles[-1]["close"] if future_candles else entry_p

        max_potential_pnl = (peak_future - entry_p) * 65
        pnl_at_45m = (final_future - entry_p) * 65

        print(f"Trade: {sym} (In: {entry_t_str} @ {entry_p:.2f})")
        print(f"  - Actual Exit at 8m: {actual_exit_p:.2f} -> Actual PnL: Rs. {actual_pnl:+.2f}")
        print(f"  - Peak in next 45m: {peak_future:.2f} -> Max Potential PnL: Rs. {max_potential_pnl:+.2f}")
        print(f"  - Price after 45m:   {final_future:.2f} -> 45m PnL: Rs. {pnl_at_45m:+.2f}")
        print("-" * 90)

    # 2. FULL DAY SIMULATION COMPARISON
    # Compare:
    # Baseline: Actual (34 trades, 6% stop, 7% target, 8m hold)
    # Proposed Strategy:
    # - Enter when Spot > 5m EMA9 > 5m EMA20 and Spot > Session VWAP
    # - Anti-churn: Minimum 10-minute spacing between trades
    # - Structural Stop: Spot < Session VWAP - 15 pts or Spot < 5m EMA20
    # - Dynamic Trailing: Once in profit (>= +15%), trail using 5m EMA9
    # - Disaster Option Stop: -30%
    # - Max Hold: None during active trend (square-off at 15:15)

    spot_prices = []
    current_position = None
    trades_sim = []
    last_exit_idx = -999

    for idx, c in enumerate(spot_1m):
        spot = c["close"]
        spot_prices.append(spot)

        # Session VWAP
        session_vwap = sum(spot_prices) / len(spot_prices)

        # 5m EMA9 & EMA20
        bars_5m = [spot_prices[i] for i in range(4, len(spot_prices), 5)]
        if not bars_5m:
            bars_5m = [spot]
        ema9 = calculate_ema(bars_5m, 9)
        ema20 = calculate_ema(bars_5m, 20)

        # Time
        hour_ist = 9 + (idx + 15) // 60
        min_ist = (idx + 15) % 60
        time_display = f"{hour_ist:02d}:{min_ist:02d}"

        # Strike selection
        atm_strike = round(spot / 50.0) * 50
        sym_call = f"NIFTY26O13{atm_strike}CE"
        if sym_call not in option_data:
            avail = [s for s in option_data.keys() if s.endswith("CE")]
            sym_call = min(avail, key=lambda s: abs(int(s[10:15]) - spot))

        c_opt = option_data[sym_call][idx] if sym_call in option_data and idx < len(option_data[sym_call]) else None

        # Position management
        if current_position is not None:
            pos_sym = current_position["symbol"]
            pos_idx = current_position["entry_idx"]
            held_mins = idx - pos_idx
            entry_p = current_position["entry_price"]

            held_c = option_data[pos_sym][idx]
            cur_p = held_c["close"]
            cur_h = held_c["high"]
            cur_l = held_c["low"]

            current_position["peak_price"] = max(current_position["peak_price"], cur_h)
            peak_p = current_position["peak_price"]

            gain_pct = ((cur_p - entry_p) / entry_p) * 100.0
            peak_gain_pct = ((peak_p - entry_p) / entry_p) * 100.0

            exit_reason = None
            exit_price = cur_p

            # Exits:
            if idx >= 360: # 15:15 IST
                exit_reason = "EOD_SQUAREOFF (15:15 IST)"
            elif cur_l <= entry_p * 0.70:
                exit_reason = "DISASTER_STOP (-30% on Option)"
                exit_price = round(entry_p * 0.70, 2)
            elif spot < (session_vwap - 15.0):
                exit_reason = f"STRUCTURAL_VWAP_STOP (Spot {spot:.1f} < VWAP {session_vwap:.1f})"
            elif spot < ema20 and ema9 < ema20:
                exit_reason = f"TREND_EMA20_STOP (Spot < 5m EMA20 {ema20:.1f})"
            elif peak_gain_pct >= 15.0:
                # Dynamic Trailing Stop
                if spot < (ema9 - 4.0):
                    exit_reason = f"TRAILING_EMA9_EXIT (Locked at +{gain_pct:.1f}%)"
                elif cur_p <= peak_p * 0.88: # 12% off peak
                    exit_reason = f"TRAILING_PEAK_EXIT (Peak: {peak_p:.1f} -> Exit: {cur_p:.1f})"

            if exit_reason:
                pnl = round((exit_price - entry_p) * 65, 2)
                current_position.update({
                    "exit_idx": idx,
                    "exit_time": time_display,
                    "exit_price": exit_price,
                    "exit_reason": exit_reason,
                    "held_mins": held_mins,
                    "pnl": pnl
                })
                trades_sim.append(current_position)
                current_position = None
                last_exit_idx = idx

        elif current_position is None and idx < 345: # Before 15:00
            # Entry conditions:
            # 1. 10m spacing after last exit
            if (idx - last_exit_idx) >= 10:
                # 2. Skip opening 10 mins (shakeout)
                if idx >= 10:
                    # 3. Trend Alignment
                    if spot > ema9 and ema9 > ema20 and spot > session_vwap:
                        current_position = {
                            "trade_no": len(trades_sim) + 1,
                            "symbol": sym_call,
                            "entry_idx": idx,
                            "entry_time": time_display,
                            "entry_price": c_opt["close"],
                            "peak_price": c_opt["high"],
                            "entry_spot": spot
                        }

    print("\n" + "=" * 90)
    print("PROPOSED STRATEGY BACKTEST RESULTS (OCTOBER 9, 2026)")
    print("=" * 90)

    total_sim_pnl = 0.0
    sim_wins = 0
    sim_losses = 0

    for t in trades_sim:
        total_sim_pnl += t["pnl"]
        if t["pnl"] > 0:
            sim_wins += 1
        else:
            sim_losses += 1
        print(f"Trade #{t['trade_no']:02d} | {t['symbol']} | In: {t['entry_time']} @ {t['entry_price']:6.2f} -> "
              f"Out: {t['exit_time']} @ {t['exit_price']:6.2f} (Held {t['held_mins']:2d}m) | "
              f"Peak: {t['peak_price']:6.2f} | PnL: Rs. {t['pnl']:+8.2f} | {t['exit_reason']}")

    print("=" * 90)
    print("HEAD-TO-HEAD COMPARISON: ACTUAL TODAY VS. PROPOSED STRATEGY")
    print("=" * 90)
    avg_hold = sum(t["held_mins"] for t in trades_sim) / len(trades_sim) if trades_sim else 0.0
    max_gain = max(t["pnl"] for t in trades_sim) if trades_sim else 0.0
    win_pct = sim_wins / len(trades_sim) * 100 if trades_sim else 0.0

    print(f"{'Metric':<25} | {'Actual (What Ran)':<25} | {'Proposed (New Strategy)':<25}")
    print("-" * 80)
    print(f"{'Total Trades':<25} | {'34 trades':<25} | {f'{len(trades_sim)} trades':<25}")
    print(f"{'Winning Trades':<25} | {'15 wins (44.1%)':<25} | {f'{sim_wins} wins ({win_pct:.1f}%)':<25}")
    print(f"{'Losing Trades':<25} | {'19 losses':<25} | {f'{sim_losses} losses':<25}")
    print(f"{'Average Hold Duration':<25} | {'~3.5 minutes':<25} | {f'{avg_hold:.1f} minutes':<25}")
    print(f"{'Max Single Trade Gain':<25} | {'+Rs. 867.75 (+9.2%)':<25} | {f'+Rs. {max_gain:.2f}':<25}")
    print(f"{'Total Net PnL':<25} | {'-Rs. 2,645.50':<25} | {f'+Rs. {total_sim_pnl:.2f}':<25}")
    print("=" * 90)

if __name__ == "__main__":
    from trading.bootstrap import configure_console
    configure_console()
    run()
