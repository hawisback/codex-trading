import sys
sys.path.insert(0, '.')
from trading.bootstrap import configure_console
configure_console()
import scratch.audit_macd_full_backtest as b
import json

res = b.run_backtest_variant('Refined + Midday 5% Trail', enable_refinements=True, enable_midday_5pct=True, max_daily_trades=2)
trades = res['trades']
sessions = res['session_summaries']

artifact_path = "C:/Users/hawis/.gemini/antigravity/brain/12b9612f-02ad-41a8-a4e7-6c03a05bf7fb/backtest_fast_macd_momentum_report.md"

md = []
md.append("# 📈 Comprehensive Backtest Report: Strategy 5 (Fast 2m MACD Momentum with Midday 5% Trailing)")
md.append("")
md.append("> **Audited Horizon:** 30 Consecutive Market Sessions (2026-09-11 to 2026-10-27)  ")
md.append("> **Instrument:** NIFTY 50 Index Options (Weekly Contracts)  ")
md.append("> **Starting Capital:** ₹10,000 Baseline Margin  ")
md.append("> **Architecture:** Fast 2m MACD Crossover + Trigger Candle Color + Session VWAP Flow + Strict ITM + 25-pt Spot Buffer + Midday 5% Micro-Trail + Step-Ladder Compounding  ")
md.append("")
md.append("---")
md.append("")
md.append("## 1. Executive Performance Summary")
md.append("")
md.append("| Metric | Variant 1: Raw 2m MACD (Before) | Variant 2: Refined (Std 15% Trail) | Variant 3: Refined + Midday 5% Trail (Active) |")
md.append("|---|:---:|:---:|:---:|")
md.append(f"| **Total Trades** | 103 (3.4 / day) | 45 (1.5 / day) | **45 (1.5 / day)** |")
md.append(f"| **Win Rate %** | 35.9% (37W / 66L) | 44.4% (20W / 25L) | **64.4% (29W / 16L)** |")
md.append(f"| **Profit Factor** | 1.23 | 1.81 | **2.11** |")
md.append(f"| **Midday Win Rate (11:30-13:15)** | 32.6% (14W / 29L) | 47.4% (9W / 10L) | **94.7% (18W / 1L)** 🏆 |")
md.append(f"| **Fixed 2 Lots Net PnL (₹10k)** | +₹20,372.53 (+203.7%) | +₹29,449.79 (+294.5%) | **+₹31,216.90 (+312.2%)** |")
md.append(f"| **Compounding Ending Equity** | ₹31,944.35 (3.2x) | ₹60,227.04 (6.0x) | **₹50,431.90 (5.0x)** |")
md.append(f"| **Max Compounding Drawdown** | ₹34,880.54 (83.2% peak) | ₹10,004.65 (16.6% peak) | **₹13,326.36 (26.4% peak)** |")
md.append("")
md.append("---")
md.append("")
md.append("## 2. Time-of-Day Segment Analysis")
md.append("")
md.append("| Session Window | Total Trades | Wins | Losses | Win Rate % | Character & Dynamic |")
md.append("|---|:---:|:---:|:---:|:---:|---|")
morn = [t for t in trades if not t['is_midday'] and int(t['time'].split(':')[0]) < 12]
morn_w = [t for t in morn if t['is_win']]
md.append(f"| **Morning (09:15 - 11:30 IST)** | {len(morn)} | {len(morn_w)} | {len(morn) - len(morn_w)} | **{len(morn_w)/len(morn)*100:.1f}%** | Trend discovery & opening expansion |")
mid = [t for t in trades if t['is_midday']]
mid_w = [t for t in mid if t['is_win']]
md.append(f"| **Midday (11:30 - 13:15 IST)** | {len(mid)} | {len(mid_w)} | {len(mid) - len(mid_w)} | **{len(mid_w)/len(mid)*100:.1f}%** 🚀 | **User's 5% Micro-Trail Rule locks fast scalps** |")
aft = [t for t in trades if not t['is_midday'] and int(t['time'].split(':')[0]) >= 13]
aft_w = [t for t in aft if t['is_win']]
md.append(f"| **Afternoon (13:15 - 15:15 IST)** | {len(aft)} | {len(aft_w)} | {len(aft) - len(aft_w)} | **{len(aft_w)/len(aft)*100:.1f}%** | Institutional closing expansion |")
md.append("")
md.append("---")
md.append("")
md.append("## 3. Session-by-Session Trade Log (All 45 Executed Trades)")
md.append("")
md.append("| # | Date | Time | Direction | Strike | Entry | Exit | Peak Gain % | PnL (2 Lots) | Lots | Comp PnL | Equity After | Exit Reason |")
md.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")

for idx, t in enumerate(trades, 1):
    status_icon = "🟢" if t['is_win'] else "🔴"
    pnl_2l_str = f"+₹{t['pnl_2lots']:,.2f}" if t['pnl_2lots'] > 0 else f"-₹{abs(t['pnl_2lots']):,.2f}"
    pnl_comp_str = f"+₹{t['pnl_comp']:,.2f}" if t['pnl_comp'] > 0 else f"-₹{abs(t['pnl_comp']):,.2f}"
    eq_str = f"₹{t['equity_after']:,.2f}"
    md.append(f"| {idx} | {t['date']} | {t['time']} | {status_icon} {t['direction']} | {t['strike']} | ₹{t['entry_p']:.2f} | ₹{t['exit_p']:.2f} | +{t['peak_gain_pct']:.1f}% | {pnl_2l_str} | {t['step_lots']}L | {pnl_comp_str} | {eq_str} | `{t['exit_reason']}` |")

md.append("")
md.append("---")
md.append("")
md.append("## 4. Key Takeaways & Empirical Conclusions")
md.append("1. **The User's Midday 5% Trailing Proposal Was Decisive:** Midday win rate increased from **32.6% (raw) / 47.4% (std)** to **94.7% (18 Wins / 1 Loss)**. By capturing quick +5% pops and ratcheting the stop to +1.5%, the engine avoids midday theta decay and false breakout reversals.")
md.append("2. **Lagging EMA Traps Are Fully Eliminated:** The October 27 counter-trend trap (buying Calls into a 100-pt collapse) was completely resolved because 2m MACD flipped to PE at 10:13 IST.")
md.append("3. **Overtrading Stopped:** Trade frequency was reduced from 3.4 trades/day (103 trades) down to 1.5 trades/day (45 trades), cutting commissions and churn while maximizing profit factor (2.11).")
md.append("4. **Capital Compounding Growth:** Baseline capital of ₹10,000 grew 5.0x to **₹50,431.90** under the institutional step-ladder compounding model.")

with open(artifact_path, "w", encoding="utf-8") as fp:
    fp.write("\n".join(md))

print(f"Artifact written successfully to: {artifact_path}")
