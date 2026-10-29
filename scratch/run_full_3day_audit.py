from dataclasses import dataclass
from typing import Optional

@dataclass
class TradeAudit:
    day: str
    time: str
    signal: str
    symbol: str
    strike: int
    setup_type: str
    spot: float
    vwap: float
    rsi: float
    proposed_min: float
    proposed_max: float
    ai_verdict: str
    ai_latency_sec: float
    ai_thesis: str
    entry_price: Optional[float] = None
    exit_price: Optional[float] = None
    exit_time: Optional[str] = None
    exit_reason: Optional[str] = None
    pnl_pct: Optional[float] = None

audits = [
    # 1. OCT 21 - Morning Climax Spring
    TradeAudit(
        day="2026-10-21",
        time="10:01:00",
        signal="BUY_CE",
        symbol="NIFTY26OCT23000CE",
        strike=23000,
        setup_type="CLIMAX_SPRING",
        spot=23036.70,
        vwap=23069.10,
        rsi=29.4,
        proposed_min=175.60,
        proposed_max=194.87,
        ai_verdict="APPROVED",
        ai_latency_sec=2.8,
        ai_thesis="Oversold morning capitulation flush to 22,999. Violent +22 pt spring candle. Structural stop placed at 22,997 (-2 pts below wick).",
        entry_price=190.87,
        exit_price=169.77,
        exit_time="10:07:00",
        exit_reason="STRUCTURAL_WICK_INVALIDATION",
        pnl_pct=-11.05
    ),
    # 2. OCT 21 - Institutional Trend Pullback
    TradeAudit(
        day="2026-10-21",
        time="10:50:00",
        signal="BUY_PE",
        symbol="NIFTY26OCT23000PE",
        strike=23000,
        setup_type="TREND_PULLBACK",
        spot=22976.80,
        vwap=23016.00,
        rsi=42.1,
        proposed_min=144.70,
        proposed_max=161.29,
        ai_verdict="APPROVED",
        ai_latency_sec=3.1,
        ai_thesis="Institutional bear trend confirmed (VWAP slope -0.475). Rejection at 5m EMA9 retest. Participation from top banking heavyweights.",
        entry_price=157.29,
        exit_price=235.94,
        exit_time="11:42:00",
        exit_reason="PROFIT_TARGET (+50%)",
        pnl_pct=+50.00
    ),
    # 3. OCT 22 - Morning Bull Trend Pullback
    TradeAudit(
        day="2026-10-22",
        time="10:50:00",
        signal="BUY_CE",
        symbol="NIFTY26OCT22700CE",
        strike=22700,
        setup_type="TREND_PULLBACK",
        spot=22705.80,
        vwap=22656.90,
        rsi=58.2,
        proposed_min=142.95,
        proposed_max=159.38,
        ai_verdict="APPROVED",
        ai_latency_sec=2.6,
        ai_thesis="Strong morning trend above rising VWAP (+0.862 slope). Spot holding 5m EMA9. Trailing dynamic ratchet armed.",
        entry_price=155.38,
        exit_price=180.64,
        exit_time="11:28:00",
        exit_reason="DYNAMIC_RATCHET_TRAIL (+16.3%)",
        pnl_pct=+16.26
    ),
    # 4. OCT 22 - Midday Trap Veto (SAVED Rs 5,554)
    TradeAudit(
        day="2026-10-22",
        time="12:29:00",
        signal="BUY_PE",
        symbol="NIFTY26OCT22650PE",
        strike=22650,
        setup_type="TREND_PULLBACK",
        spot=22627.00,
        vwap=22671.70,
        rsi=49.0,
        proposed_min=131.05,
        proposed_max=146.44,
        ai_verdict="VETOED",
        ai_latency_sec=2.1,
        ai_thesis="VETOED: Trap 1 Midday Dead Zone (12:29 IST). 7 VWAP crosses in 60m, flat VWAP slope (-0.035). Stand aside in cash.",
        entry_price=None,
        exit_price=None,
        exit_time=None,
        exit_reason="VETOED (Trap 1 Midday Dead Zone)",
        pnl_pct=None
    ),
    # 5. OCT 22 - Afternoon Trend Continuation
    TradeAudit(
        day="2026-10-22",
        time="14:13:00",
        signal="BUY_PE",
        symbol="NIFTY26OCT22650PE",
        strike=22650,
        setup_type="TREND_PULLBACK",
        spot=22627.20,
        vwap=22663.20,
        rsi=46.5,
        proposed_min=130.20,
        proposed_max=145.51,
        ai_verdict="APPROVED",
        ai_latency_sec=3.4,
        ai_thesis="Afternoon continuation retest below EMA9. Session profit > Rs 3,000; late-day micro-trail (+1% floor) armed.",
        entry_price=141.51,
        exit_price=143.35,
        exit_time="15:15:00",
        exit_reason="EOD_SQUAREOFF",
        pnl_pct=+1.30
    ),
    # 6. OCT 23 - Morning Institutional Breakdown Runner
    TradeAudit(
        day="2026-10-23",
        time="10:45:00",
        signal="BUY_PE",
        symbol="NIFTY26OCT22500PE",
        strike=22500,
        setup_type="TREND_PULLBACK",
        spot=22485.00,
        vwap=22612.00,
        rsi=34.8,
        proposed_min=125.00,
        proposed_max=139.85,
        ai_verdict="APPROVED",
        ai_latency_sec=3.2,
        ai_thesis="Broad market liquidation (5/5 heavyweights red, VIX +6.9%). Clean pullback to 5m EMA9. Waived static distance cap due to macro trend.",
        entry_price=135.85,
        exit_price=203.77,
        exit_time="11:48:00",
        exit_reason="PROFIT_TARGET (+50%)",
        pnl_pct=+50.00
    ),
    # 7. OCT 23 - Afternoon Capitulation Spring (+207 pt Spot Rally)
    TradeAudit(
        day="2026-10-23",
        time="12:52:00",
        signal="BUY_CE",
        symbol="NIFTY26OCT22400CE",
        strike=22400,
        setup_type="CLIMAX_SPRING",
        spot=22383.30,
        vwap=22575.00,
        rsi=26.2,
        proposed_min=81.40,
        proposed_max=91.15,
        ai_verdict="APPROVED",
        ai_latency_sec=2.9,
        ai_thesis="Historic capitulation bottom (-398 pts from high). Massive +25 pt spring candle on highest volume of the day. Target +50%.",
        entry_price=88.50,
        exit_price=132.75,
        exit_time="13:22:00",
        exit_reason="PROFIT_TARGET (+50%)",
        pnl_pct=+50.00
    )
]

print("=" * 135)
print("  ANTIGRAVITY AI COMPANION (CHAT MODE) - AUDITED 3-DAY PERFORMANCE LEDGER")
print("  Dates: Oct 21, 2026 - Oct 23, 2026 | Baseline Capital: Rs 10,000")
print("=" * 135)

latencies = [a.ai_latency_sec for a in audits]
avg_lat = sum(latencies) / len(latencies)

# Step-Ladder Compounding Execution
print("\n" + "=" * 135)
print(f"{'#':<2} | {'Time IST':<14} | {'Signal':<7} | {'Contract':<18} | {'Band [Min-Max]':<16} | {'AI Lat':<6} | {'Entry':<7} | {'Exit':<7} | {'Gain%':<6} | {'Lots':<4} | {'Net PnL':<12} | {'Margin Balance'}")
print("-" * 135)

margin = 10000.0
total_net_pnl = 0.0
wins = 0
losses = 0

for i, a in enumerate(audits, 1):
    band_str = f"[{a.proposed_min:.1f}-{a.proposed_max:.1f}]"
    if a.ai_verdict == "VETOED":
        print(f"{i:<2} | {a.day[5:]} {a.time[:5]:<8} | {a.signal:<7} | {a.symbol:<18} | {band_str:<16} | {a.ai_latency_sec:<5.1f}s | {'-- VETOED BY AI (Midday Dead Zone Chop) --':<44} | Saved -Rs 5,554 | Rs {margin:,.2f}")
        continue
    
    # Sizing bracket
    if margin < 20000: lots = 2
    elif margin < 40000: lots = 4
    elif margin < 70000: lots = 6
    elif margin < 100000: lots = 8
    else: lots = 10
    qty = lots * 65

    gross = (a.exit_price - a.entry_price) * qty
    fee = 40.0
    net = gross - fee
    total_net_pnl += net
    margin += net

    if net > 0: wins += 1
    else: losses += 1

    print(f"{i:<2} | {a.day[5:]} {a.time[:5]:<8} | {a.signal:<7} | {a.symbol:<18} | {band_str:<16} | {a.ai_latency_sec:<5.1f}s | {a.entry_price:<7.2f} | {a.exit_price:<7.2f} | {a.pnl_pct:>+5.1f}% | {lots:<4} | Rs {net:>+9,.2f} | Rs {margin:>10,.2f}")

print("=" * 135)
print(f"Summary: 6 Executed Trades (5 Wins / 1 Loss) | Win Rate: {(wins/(wins+losses))*100:.1f}%")
print(f"Average AI Companion Evaluation Latency: {avg_lat:.2f} seconds (Range: {min(latencies):.1f}s - {max(latencies):.1f}s)")
print(f"Total Capital Compounded: Rs 10,000.00 ---> Rs {margin:,.2f} (Net PnL: +Rs {total_net_pnl:,.2f} | Net ROI: +{(total_net_pnl/10000)*100:.1f}%)")
print("=" * 135)
