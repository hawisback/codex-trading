from trading.adapters.market_data import create_market_data
from trading.adapters.market_sources import ReadBudget

md = create_market_data("kite")
symbols = ["NIFTY 50", "INDIA VIX", "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS"]
quotes = md.source.quotes(symbols, ReadBudget(5.0))

print(f"{'Symbol':<16} | {'LTP':>8} | {'Close':>8} | {'Change%':>8} | {'Timestamp'}")
print("-" * 65)
for sym in symbols:
    q = quotes.get(sym, {})
    ltp = q.get("last_price")
    ohlc = q.get("ohlc", {})
    close = q.get("close") or ohlc.get("close") or 1.0
    ts = q.get("timestamp")
    chg = ((ltp / close) - 1) * 100 if ltp and close else 0.0
    print(f"{sym:<16} | {ltp:>8.2f} | {close:>8.2f} | {chg:>+7.2f}% | {ts}")
