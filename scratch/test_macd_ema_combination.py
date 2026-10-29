import json
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from trading.bootstrap import configure_console
configure_console()

from trading.domain.market_data import resample_two_minutes, resample_five_minutes
from trading.adapters.historical import load_option_history, OptionHistory
from trading.domain.historical_execution import simulate_option_path
from ai_opportunity_radar import AIOpportunityRadar

DATES = [
    ("2026-10-19", "Mon Oct 19"),
    ("2026-10-21", "Wed Oct 21"),
    ("2026-10-22", "Thu Oct 22"),
    ("2026-10-23", "Fri Oct 23"),
    ("2026-10-26", "Mon Oct 26"),
    ("2026-10-27", "Tue Oct 27 (0DTE)")
]

def calculate_ema(series: List[float], period: int) -> List[float]:
    if not series:
        return []
    res = [series[0]]
    mult = 2.0 / (period + 1.0)
    for v in series[1:]:
        res.append(v * mult + res[-1] * (1.0 - mult))
    return res

def calculate_macd(closes: List[float]) -> Tuple[List[float], List[float], List[float]]:
    if len(closes) < 26:
        zeros = [0.0] * len(closes)
        return zeros, zeros, zeros
    fast = calculate_ema(closes, 12)
    slow = calculate_ema(closes, 26)
    macd_line = [f - s for f, s in zip(fast, slow)]
    signal_line = calculate_ema(macd_line, 9)
    hist = [m - s for m, s in zip(macd_line, signal_line)]
    return macd_line, signal_line, hist

def calculate_rsi(closes: List[float], period: int = 14) -> List[float]:
    if len(closes) <= period:
        return [50.0] * len(closes)
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(0.0, diff))
        losses.append(max(0.0, -diff))
    rsi_vals = [50.0] * period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_vals.append(100.0)
        else:
            rs = avg_gain / avg_loss
            rsi_vals.append(100.0 - (100.0 / (1.0 + rs)))
    rsi_vals.insert(0, 50.0)
    return rsi_vals

def load_session(date_str: str):
    spot_file = f"data/spot_candles_{date_str.replace('-', '')}.json"
    if not os.path.exists(spot_file):
        return None
    with open(spot_file, "r") as fp:
        spot_bars = json.load(fp)
    return spot_bars

def run_backtest():
    """Retired forward-looking simulation; use causal decision review (NO AI/PnL)."""
    from tools.replay_hybrid import main
    return main()

if __name__ == "__main__":
    run_backtest()
