import os
import json
from backtest_engine import BacktestEngine, StrategyConfig, calculate_metrics, Trade

class PullbackEngine(BacktestEngine):
    def run_simulation(self, cfg):
        trades = []
        current_trade = None
        last_exit_bar = -999
        spot_closes = []
        spot_typicals = []

        for idx, bar in enumerate(self.spot_candles):
            close = bar['close']
            high = bar['high']
            low = bar['low']
            spot_closes.append(close)
            spot_typicals.append((high + low + close) / 3.0)
            session_vwap = sum(spot_typicals) / len(spot_typicals)
            bars_5m = [spot_closes[i] for i in range(4, len(spot_closes), 5)] or [close]
            ema9 = self.calculate_ema(bars_5m, 9)
            ema20 = self.calculate_ema(bars_5m, 20)
            rsi = self.calculate_rsi(spot_closes, 14)

            raw_time = bar['start_time']
            time_str = raw_time[11:19] if len(raw_time) > 19 else raw_time

            if current_trade is not None:
                opt_h, opt_l, opt_close = self.get_option_bar(
                    current_trade.symbol, current_trade.strike, current_trade.direction, idx, bar
                )
                if opt_h > current_trade.peak_price:
                    current_trade.peak_price = opt_h
                    current_trade.peak_gain_pct = round(
                        ((opt_h - current_trade.entry_price) / current_trade.entry_price) * 100, 2
                    )

                exit_reason = None
                exit_price = opt_close

                if opt_l <= current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0):
                    exit_reason = 'INITIAL_STOP'
                    exit_price = round(current_trade.entry_price * (1.0 - cfg.initial_stop_pct / 100.0), 2)
                elif opt_h >= current_trade.entry_price * (1.0 + cfg.target_pct / 100.0):
                    exit_reason = 'PROFIT_TARGET'
                    exit_price = round(current_trade.entry_price * (1.0 + cfg.target_pct / 100.0), 2)
                elif cfg.enable_structural_stops:
                    if current_trade.direction == 'CE':
                        if close < (session_vwap - cfg.vwap_stop_buffer):
                            exit_reason = 'STRUCTURAL_VWAP_STOP'
                        elif cfg.ema20_stop and (close < ema20) and (ema9 < ema20):
                            exit_reason = 'STRUCTURAL_EMA20_STOP'
                        elif cfg.enable_runner_trailing and current_trade.peak_gain_pct >= cfg.runner_activation_pct:
                            if cfg.lock_breakeven_on_runner and opt_close <= current_trade.entry_price * 1.02:
                                exit_reason = 'TRAILING_BREAKEVEN'
                            elif close < (ema9 - cfg.ema9_trailing_buffer):
                                exit_reason = 'TRAILING_EMA9'
                            elif opt_close <= current_trade.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0):
                                exit_reason = 'TRAILING_PEAK'
                    else:
                        if close > (session_vwap + cfg.vwap_stop_buffer):
                            exit_reason = 'STRUCTURAL_VWAP_STOP'
                        elif cfg.ema20_stop and (close > ema20) and (ema9 > ema20):
                            exit_reason = 'STRUCTURAL_EMA20_STOP'
                        elif cfg.enable_runner_trailing and current_trade.peak_gain_pct >= cfg.runner_activation_pct:
                            if cfg.lock_breakeven_on_runner and opt_close <= current_trade.entry_price * 1.02:
                                exit_reason = 'TRAILING_BREAKEVEN'
                            elif close > (ema9 + cfg.ema9_trailing_buffer):
                                exit_reason = 'TRAILING_EMA9'
                            elif opt_close <= current_trade.peak_price * (1.0 - cfg.peak_pullback_pct / 100.0):
                                exit_reason = 'TRAILING_PEAK'

                if idx >= 360 and not exit_reason:
                    exit_reason = 'EOD_SQUAREOFF'

                if exit_reason:
                    current_trade.close(idx, time_str, exit_price, exit_reason)
                    trades.append(current_trade)
                    current_trade = None
                    last_exit_bar = idx
                continue

            if idx < 10 or idx > 330:
                continue
            if (idx - last_exit_bar) < cfg.min_spacing_bars:
                continue

            # TRUE PULLBACK TEST:
            # 1. Price is in trend: close > ema9 > ema20 and close > session_vwap
            # 2. BUT candle low actually touched or retested value (low <= ema9 + 4.0 pts)
            # 3. And RSI is NOT overbought (> 70)
            ce_signal = (close > ema9) and (ema9 > ema20) and (close > session_vwap) and (low <= ema9 + 4.0) and (rsi < 70.0)
            pe_signal = (close < ema9) and (ema9 < ema20) and (close < session_vwap) and (high >= ema9 - 4.0) and (rsi > 30.0)

            direction = 'CE' if ce_signal else ('PE' if pe_signal else None)
            if direction:
                sym, strike = self.select_contract(close, direction)
                _, _, opt_entry = self.get_option_bar(sym, strike, direction, idx, bar)
                current_trade = Trade(len(trades)+1, sym, direction, strike, idx, time_str, opt_entry, 65, peak_price=opt_entry)

        return trades

dates = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-09']
all_trades = []
print(f"{'Date':<12} {'Trades':<8} {'Wins':<6} {'Net P&L':<14} {'Win Rate'}")
print("-" * 55)
for d in dates:
    t = PullbackEngine(d).run_simulation(StrategyConfig())
    m = calculate_metrics(t)
    all_trades.extend(t)
    print(f"{d:<12} {m['total_trades']:<8} {m['wins']:<6} Rs. {m['net_pnl']:<10,.2f} {m['win_rate']:.1f}%")

wm = calculate_metrics(all_trades)
print("-" * 55)
print(f"WEEK TOTAL: {wm['total_trades']} trades | Wins: {wm['wins']} | PnL: Rs. {wm['net_pnl']:+,.2f} | Win%: {wm['win_rate']:.1f}%")
