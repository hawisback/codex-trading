#!/usr/bin/env python3
"""
AI Context Dossier Generator for NIFTY Options
==============================================
Extracts deep, multi-dimensional market state features for candidate trades.
Delivers a comprehensive intelligence dossier to the AI (Gemini) so it can 
vet setups, detect traps, approve high-conviction runners, and manage risk 
WITHOUT hardcoded entry restrictions.
"""

from dataclasses import dataclass, asdict, field
from datetime import datetime, time, timezone
from typing import Dict, List, Optional, Any
from market_clock import MarketClock
import json
from trading.domain.market_data import resample_two_minutes, resample_rolling_two_minutes


@dataclass
class MarketDossier:
    # 1. Identity & Contract Candidate
    date: str
    time_utc: str
    time_ist: str
    direction: str                     # "CE" or "PE"
    symbol: str
    strike: int
    option_entry_price: float
    spot_price: float
    
    # 2. Session Phase & Temporal Context
    session_phase: str                 # "OPENING_DRIVE", "MORNING_TREND", "MIDDAY_DEAD_ZONE", "AFTERNOON_EXPANSION", "LATE_SQUAREOFF"
    minutes_from_open: int
    minutes_to_close: int
    is_expiry_0dte: bool
    days_to_expiry: float
    gamma_hazard_flag: bool            # True if 0DTE afternoon + low premium
    
    # 3. VWAP Geometry & Regime
    session_vwap: float
    vwap_distance_pts: float           # |spot - vwap|
    vwap_slope_15m: float              # pts/min (+ up, - down)
    vwap_cross_count_60m: int          # times price crossed VWAP in last 60 mins
    vwap_blender_warning: bool         # True if |dist| < 8.0 pts and cross_count >= 3
    
    # 4. Volatility & Consolidation Box
    box_range_15m: float               # High - Low of last 15 mins
    box_range_30m: float               # High - Low of last 30 mins
    box_position_pct: float            # 0% = floor/support, 100% = ceiling/resistance
    compression_hazard: bool           # True if box_range_30m < 20.0 pts
    ceiling_floor_hazard: bool         # True if buying CE at > 85% or PE at < 15%
    
    # 5. Trend Alignment & Pullback Quality
    ema9_5m: float
    ema20_5m: float
    ema_spread_5m: float               # ema9 - ema20
    ribbon_compression_hazard: bool    # True if |ema_spread_5m| < 4.0 pts (sluggish drift)
    pullback_distance_pts: float       # distance from spot to 5m EMA9
    rsi_1m: float
    day_high: float
    day_low: float
    day_range_pts: float
    distance_to_day_extreme: float     # distance to Day High (for CE) or Day Low (for PE)
    
    # 6. Whipsaw & Directional Shift Radar
    last_trade_direction: Optional[str]
    last_trade_pnl: Optional[float]
    minutes_since_last_exit: Optional[int]
    consecutive_losses_today: int
    is_directional_shift: bool         # True if flipping after an opposite-side failure
    
    # 7. Account State & Capital Preservation
    realized_pnl_today: float
    trades_taken_today: int
    capital_preservation_active: bool  # True if daily profit > +₹2,500 and late day
    is_counter_trend_slope: bool = False
    is_climax_extended: bool = False
    is_candle_aligned: bool = True
    is_reversal_inflection: bool = False

    # 8. External News & Macro Intelligence
    global_bias: str = "NEUTRAL"
    news_bias: str = "NEUTRAL"
    news_sentiment_score: int = 0
    catalysts: List[Dict[str, Any]] = field(default_factory=list)
    trap_advisories: List[str] = field(default_factory=list)

    # Execution identity and age are separate from directional-shift trap features.
    instrument_id: str = ""
    setup_type: str = "TREND_PULLBACK"
    candidate_timestamp: Optional[str] = None
    invalidation_level: Optional[float] = None
    vix: Dict[str, Any] = field(default_factory=dict)
    sectors: Dict[str, Any] = field(default_factory=dict)
    sector_divergence: bool = False
    order_flow: Dict[str, Any] = field(default_factory=dict)
    order_book: Dict[str, Any] = field(default_factory=dict)
    risk_policy: Dict[str, Any] = field(default_factory=dict)
    spot_macd_2m: Dict[str, Any] = field(default_factory=dict)
    strike_macd_line: Optional[float] = None
    strike_signal_line: Optional[float] = None
    strike_histogram: Optional[float] = None
    strike_previous_histogram: Optional[float] = None
    strike_histogram_expanding_positive: bool = False
    strike_momentum_status: str = "Unavailable"
    strike_macd_candle_closed_at: Optional[str] = None
    strike_macd_unavailable_reason: str = "Option MACD was not supplied for this dossier"

    def to_markdown(self) -> str:
        """Renders an intuitive, human-and-AI readable executive dossier."""
        g_haz = "⚠️ HIGH GAMMA RISK" if self.gamma_hazard_flag else "✅ NORMAL"
        v_blender = "🚨 CHOP BLENDER ACTIVE" if self.vwap_blender_warning else "✅ HEALTHY RUNWAY"
        c_haz = "⚠️ TIGHT COMPRESSION" if self.compression_hazard else "✅ EXPANDING"
        cf_haz = "⚠️ DIRECTLY AT CEILING/FLOOR" if self.ceiling_floor_hazard else "✅ HEALTHY POSITION"
        r_haz = "⚠️ COMPRESSED DRIFT (|spread| < 4.0 pts)" if self.ribbon_compression_hazard else "✅ EXPANDING TREND"
        cap_pres = "🔒 CAPITAL PRESERVATION (Protect Daily Alpha)" if self.capital_preservation_active else "🟢 ACTIVE TRADING"
        slope_flag = "🚨 FIGHTING INSTITUTIONAL SLOPE" if self.is_counter_trend_slope else "✅ SLOPE ALIGNED"
        climax_flag = "🚨 CLIMAX OVEREXTENSION (> 80 pts)" if self.is_climax_extended else "✅ HEALTHY DISTANCE"

        cat_lines = []
        for c in (self.catalysts or [])[:4]:
            cat_lines.append(f"  * [{c.get('sentiment', 'NEUTRAL')}] {c.get('title', '')[:85]} ({c.get('source', 'News')})")
        cat_str = "\n".join(cat_lines) if cat_lines else "  * No high-impact catalysts tagged."

        adv_str = ", ".join(self.trap_advisories) if self.trap_advisories else "✅ No Divergent Trap Advisories"

        md = f"""### 📋 AI Market State Dossier: {self.direction} Candidate @ {self.time_ist} IST
**Instrument:** `{self.symbol}` | **Strike:** `{self.strike}` | **Est. Entry:** `₹{self.option_entry_price:.2f}` | **Spot:** `{self.spot_price:.2f}`
**Setup:** `{self.setup_type}` | **Contract ID:** `{self.instrument_id or self.symbol}` | **Candidate time:** `{self.candidate_timestamp or 'historical dossier'}`

#### 1. Temporal & Expiry Environment
* **Session Phase:** `{self.session_phase}` ({self.minutes_to_close} mins to close)
* **Expiry Regime:** `{'0DTE EXPIRY DAY' if self.is_expiry_0dte else f'{self.days_to_expiry:.1f} Days to Expiry'}`
* **Gamma Hazard:** {g_haz} (0DTE volatility / cheap options)

#### 2. VWAP Geometry & Quality
* **Session VWAP:** `{self.session_vwap:.2f}` (Spot Distance: `{self.vwap_distance_pts:.1f}` pts)
* **15-Min VWAP Slope:** `{self.vwap_slope_15m:+.3f}` pts/min ({slope_flag})
* **VWAP Crosses (Last 60m):** `{self.vwap_cross_count_60m}` crosses
* **VWAP State Assessment:** {v_blender} | {climax_flag}

#### 3. Volatility & Range Runway
* **30-Min Range (Box Width):** `{self.box_range_30m:.1f}` pts | **15-Min:** `{self.box_range_15m:.1f}` pts
* **Position in 30m Box:** `{self.box_position_pct:.1f}%` (0% = Floor, 100% = Ceiling)
* **Range Assessment:** {c_haz} | {cf_haz}
* **Runway to Day Extreme:** `{self.distance_to_day_extreme:.1f}` pts (Day Range: `{self.day_range_pts:.1f}` pts)

#### 4. Trend & Technical Alignment
* **5m EMA9 / EMA20:** `{self.ema9_5m:.2f}` / `{self.ema20_5m:.2f}` (Spread: `{self.ema_spread_5m:+.2f}` pts)
* **5m Ribbon State:** {r_haz}
* **Pullback Retest Distance:** `{self.pullback_distance_pts:.1f}` pts from 5m EMA9
* **1m RSI:** `{self.rsi_1m:.1f}`

#### 5. Whipsaw Radar & Account Memory
* **Directional Shift:** `{'🔄 SHIFT FROM PREVIOUS SIDE' if self.is_directional_shift else '➡️ CONTINUATION'}`
* **Prior Trade:** Direction: `{self.last_trade_direction or 'None'}` | P&L: `{f'₹{self.last_trade_pnl:+.2f}' if self.last_trade_pnl is not None else 'N/A'}`
* **Consecutive Losses Today:** `{self.consecutive_losses_today}`
* **Account Realized P&L Today:** `₹{self.realized_pnl_today:+,.2f}` across `{self.trades_taken_today}` trades
* **Capital Protection Status:** {cap_pres}

#### 6. Live Financial News & External Market Intelligence
* **Global Macro Bias:** `{self.global_bias}` (Brent/Crude, Dow, Nasdaq, USD/INR)
* **Financial News Bias:** `{self.news_bias}` (Sentiment Score: `{self.news_sentiment_score:+d}`)
* **Trap Advisories:** {adv_str}
* **Top Catalysts:**
{cat_str}
"""
        if self.vix:
            md += f"\n#### India VIX\n* Level: `{self.vix['last_price']:.2f}` | Change: `{self.vix['change_pct']:+.2f}%` | Exchange time: `{self.vix.get('timestamp', 'unavailable')}`\n"
        if self.sectors:
            md += "\n#### Sector Breadth\n"
            for name, quote in self.sectors.items():
                md += f"* {name}: `{quote['last_price']:.2f}` | Change: `{quote['change_pct']:+.2f}%` | Exchange time: `{quote.get('timestamp', 'unavailable')}`\n"
            md += f"* Banking/IT divergence: `{self.sector_divergence}`\n"
        if self.order_flow:
            md += "\n#### Option Chain Positioning (OI, separate from executable depth)\n"
            md += "```json\n" + json.dumps(self.order_flow, indent=2) + "\n```\n"
        if self.order_book:
            md += "\n#### Selected Contract Order Book\n"
            md += "```json\n" + json.dumps(self.order_book, indent=2) + "\n```\n"
            md += "Quantity imbalance is a liquidity snapshot, not a prediction. Revalidate prices before execution.\n"
        if self.risk_policy:
            md += "\n#### Frozen Post-Fill Risk Policy\n```json\n" + json.dumps(self.risk_policy, indent=2) + "\n```\n"
        if self.setup_type == "MACD_2M_MOMENTUM":
            md += "\n#### Strike Premium Momentum (Option MACD)\n"
            md += "* Completed two-minute observations of the selected option premium, in either CE or PE.\n"
            if self.spot_macd_2m:
                spot = self.spot_macd_2m
                sampling = "rolling 2m, evaluated every completed minute" if spot.get("interval") == "rolling_2m" else "stepped 2m"
                md += f"* Sampling: **{sampling}** | MACD periods: `{spot.get('periods', [12, 26, 9])}`.\n"
                md += (f"* Spot 2m MACD / Signal / Histogram: `{spot['macd']:+.4f}` / "
                       f"`{spot['signal']:+.4f}` / `{spot['histogram']:+.4f}` ({spot['momentum_status']}).\n")
            if self.strike_macd_line is None:
                md += f"* Strike momentum: **Unavailable** ({self.strike_macd_unavailable_reason}). No confluence inferred.\n"
            else:
                md += (f"* Strike MACD / Signal: `{self.strike_macd_line:+.4f}` / `{self.strike_signal_line:+.4f}`\n"
                       f"* Strike Histogram / Previous: `{self.strike_histogram:+.4f}` / `{self.strike_previous_histogram:+.4f}`\n"
                       f"* Momentum: **{self.strike_momentum_status}** | Expanding positive: `{self.strike_histogram_expanding_positive}`\n"
                       f"* Both observations closed at: `{self.strike_macd_candle_closed_at}`\n")
        return md


def generate_market_dossier(
    target_date: str,
    candles: List[Dict[str, Any]],
    current_bar_idx: int,
    direction: str,
    symbol: str,
    strike: int,
    option_entry_price: float,
    trade_history: List[Any],
    days_to_expiry: float,
    is_expiry_0dte: bool,
    intel: Optional[Dict[str, Any]] = None,
    use_rolling_2m: bool = False,
) -> MarketDossier:
    """Computes all forensic features and returns a structured MarketDossier."""
    
    current_bar = candles[current_bar_idx]
    spot = current_bar["close"]
    time_raw = current_bar["start_time"]
    
    # Robust Timezone Parsing with MarketClock
    time_raw = current_bar.get("start_time") or current_bar.get("date") or MarketClock.now_ist().isoformat()
    dt_ist = MarketClock.parse_to_ist(time_raw) or MarketClock.now_ist()
    time_ist = dt_ist.strftime("%H:%M:%S")
    utc_str = dt_ist.astimezone(timezone.utc).strftime("%H:%M:%S") if hasattr(dt_ist, "astimezone") else time_ist

    # Session Phase & Timing
    mins_from_open, mins_to_close = MarketClock.get_session_minutes(dt_ist)
    session_phase = MarketClock.get_session_phase(dt_ist)
        
    # Gamma Hazard on 0DTE (Learned from 0DTE audit: sub-₹30 options suffer 90% instant stopouts)
    gamma_hazard = bool(is_expiry_0dte and (option_entry_price < 30.0 or (mins_from_open >= 180 and option_entry_price < 38.0)))
    
    # Cumulative VWAP
    pv = sum(candles[k]["close"] * (candles[k]["volume"] if candles[k]["volume"] else 1000) for k in range(current_bar_idx + 1))
    v_sum = sum((candles[k]["volume"] if candles[k]["volume"] else 1000) for k in range(current_bar_idx + 1))
    session_vwap = pv / v_sum if v_sum else spot
    vwap_distance_pts = abs(spot - session_vwap)
    
    # VWAP slope over last 15 mins
    prev_15_idx = max(0, current_bar_idx - 15)
    pv_prev = sum(candles[k]["close"] * (candles[k]["volume"] if candles[k]["volume"] else 1000) for k in range(prev_15_idx + 1))
    v_prev = sum((candles[k]["volume"] if candles[k]["volume"] else 1000) for k in range(prev_15_idx + 1))
    vwap_prev = pv_prev / v_prev if v_prev else session_vwap
    vwap_slope_15m = (session_vwap - vwap_prev) / max(1.0, current_bar_idx - prev_15_idx)
    
    # VWAP crosses in last 60 bars
    lookback_60 = max(0, current_bar_idx - 60)
    vwap_crosses = 0
    running_pv = sum(candles[k]["close"] * (candles[k]["volume"] if candles[k]["volume"] else 1000) for k in range(lookback_60 + 1))
    running_v = sum((candles[k]["volume"] if candles[k]["volume"] else 1000) for k in range(lookback_60 + 1))
    prev_v_diff = candles[lookback_60]["close"] - (running_pv / running_v if running_v else spot)
    
    for k in range(lookback_60 + 1, current_bar_idx + 1):
        v = candles[k]["volume"] if candles[k]["volume"] else 1000
        running_pv += candles[k]["close"] * v
        running_v += v
        curr_v = running_pv / running_v
        curr_diff = candles[k]["close"] - curr_v
        if (prev_v_diff > 0 and curr_diff < 0) or (prev_v_diff < 0 and curr_diff > 0):
            vwap_crosses += 1
        prev_v_diff = curr_diff
        
    vwap_blender_warning = bool((vwap_distance_pts < 8.0 and (vwap_crosses >= 3 or abs(vwap_slope_15m) < 0.08)) or vwap_crosses >= 5)
    
    # Volatility & Boxes
    bars_15 = candles[max(0, current_bar_idx - 14):current_bar_idx + 1]
    box_range_15m = max(c["high"] for c in bars_15) - min(c["low"] for c in bars_15)
    
    bars_30 = candles[max(0, current_bar_idx - 29):current_bar_idx + 1]
    box_30_high = max(c["high"] for c in bars_30)
    box_30_low = min(c["low"] for c in bars_30)
    box_range_30m = box_30_high - box_30_low
    box_position_pct = ((spot - box_30_low) / max(1.0, box_range_30m)) * 100.0
    
    compression_hazard = bool(box_range_30m < 20.0)
    ceiling_floor_hazard = bool((direction == "CE" and box_position_pct > 85.0) or (direction == "PE" and box_position_pct < 15.0))
    
    # Day range & extremes
    all_past = candles[:current_bar_idx + 1]
    day_high = max(c["high"] for c in all_past)
    day_low = min(c["low"] for c in all_past)
    day_range_pts = max(1.0, day_high - day_low)
    distance_to_day_extreme = (day_high - spot) if direction == "CE" else (spot - day_low)
    
    # EMA metrics (synthetic 5m)
    closes_5m = []
    for i in range(0, current_bar_idx + 1, 5):
        chunk = candles[i:min(i + 5, current_bar_idx + 1)]
        if chunk:
            closes_5m.append(chunk[-1]["close"])
            
    def calc_ema(arr, period):
        if not arr:
            return spot
        if len(arr) < period:
            return arr[-1]
        k_val = 2.0 / (period + 1)
        e = arr[0]
        for p in arr[1:]:
            e = p * k_val + e * (1 - k_val)
        return e
        
    ema9_5m = calc_ema(closes_5m, 9)
    ema20_5m = calc_ema(closes_5m, 20)
    ema_spread_5m = ema9_5m - ema20_5m
    ribbon_compression_hazard = bool(abs(ema_spread_5m) < 4.0)
    pullback_distance_pts = abs(spot - ema9_5m)
    
    # 1m RSI(14)
    recent_closes = [c["close"] for c in candles[max(0, current_bar_idx - 20):current_bar_idx + 1]]
    if len(recent_closes) > 14:
        gains, losses = [], []
        for i in range(1, len(recent_closes)):
            d = recent_closes[i] - recent_closes[i-1]
            gains.append(max(0.0, d))
            losses.append(max(0.0, -d))
        avg_g = sum(gains[-14:]) / 14.0
        avg_l = sum(losses[-14:]) / 14.0
        rsi_1m = 100.0 - (100.0 / (1.0 + (avg_g / avg_l))) if avg_l > 0 else 100.0
    else:
        rsi_1m = 50.0
        
    # Account & Whipsaw memory
    realized_pnl = sum(t.pnl for t in trade_history if t.pnl is not None)
    trades_count = len(trade_history)
    consecutive_losses = 0
    for t in reversed(trade_history):
        if t.pnl is not None and t.pnl <= 0:
            consecutive_losses += 1
        else:
            break
            
    last_trade = trade_history[-1] if trade_history else None
    last_trade_dir = last_trade.direction if last_trade else None
    last_trade_pnl = last_trade.pnl if last_trade else None
    
    is_directional_shift = bool(last_trade and last_trade.pnl and last_trade.pnl <= 0 and last_trade.direction != direction)
    
    capital_preservation = bool(realized_pnl >= 2500.0 and (mins_to_close <= 75 or consecutive_losses >= 1))
    
    is_counter_trend_slope = bool((direction == "PE" and vwap_slope_15m > 0.10) or (direction == "CE" and vwap_slope_15m < -0.10))
    is_climax_extended = bool(vwap_distance_pts > 80.0)

    # 2m / immediate candle direction alignment
    is_candle_aligned = False
    try:
        sampler = resample_rolling_two_minutes if use_rolling_2m else resample_two_minutes
        trigger_bars = sampler(candles[:current_bar_idx + 1])
        if trigger_bars and trigger_bars[-1]["minute_idx"] == current_bar_idx:
            trigger = trigger_bars[-1]
            is_candle_aligned = bool(trigger["close"] > trigger["open"] if direction == "CE"
                                     else trigger["close"] < trigger["open"])
    except (ValueError, TypeError, KeyError):
        pass  # Missing, incomplete or ambiguous trigger candles cannot grant an exception.
    is_reversal_inflection = bool(
        is_candle_aligned and
        abs(vwap_slope_15m) <= 0.85 and
        vwap_distance_pts <= 140.0
    )

    # Extract external market intelligence if provided
    global_bias = "NEUTRAL"
    news_bias = "NEUTRAL"
    news_score = 0
    catalysts = []
    advisories = []
    if intel:
        global_bias = intel.get("global_cues", {}).get("global_bias", "NEUTRAL")
        news_bias = intel.get("news", {}).get("news_bias", "NEUTRAL")
        news_score = int(intel.get("news", {}).get("sentiment_score", 0))
        catalysts = intel.get("news", {}).get("catalysts", [])
        advisories = intel.get("trap_advisories", [])

    return MarketDossier(
        date=target_date,
        time_utc=utc_str,
        time_ist=time_ist,
        direction=direction,
        symbol=symbol,
        strike=strike,
        option_entry_price=round(option_entry_price, 2),
        spot_price=round(spot, 2),
        session_phase=session_phase,
        minutes_from_open=mins_from_open,
        minutes_to_close=mins_to_close,
        is_expiry_0dte=is_expiry_0dte,
        days_to_expiry=round(days_to_expiry, 2),
        gamma_hazard_flag=gamma_hazard,
        session_vwap=round(session_vwap, 2),
        vwap_distance_pts=round(vwap_distance_pts, 2),
        vwap_slope_15m=round(vwap_slope_15m, 4),
        vwap_cross_count_60m=vwap_crosses,
        vwap_blender_warning=vwap_blender_warning,
        box_range_15m=round(box_range_15m, 2),
        box_range_30m=round(box_range_30m, 2),
        box_position_pct=round(box_position_pct, 1),
        compression_hazard=compression_hazard,
        ceiling_floor_hazard=ceiling_floor_hazard,
        ema9_5m=round(ema9_5m, 2),
        ema20_5m=round(ema20_5m, 2),
        ema_spread_5m=round(ema_spread_5m, 2),
        ribbon_compression_hazard=ribbon_compression_hazard,
        pullback_distance_pts=round(pullback_distance_pts, 2),
        rsi_1m=round(rsi_1m, 1),
        day_high=round(day_high, 2),
        day_low=round(day_low, 2),
        day_range_pts=round(day_range_pts, 2),
        distance_to_day_extreme=round(distance_to_day_extreme, 2),
        last_trade_direction=last_trade_dir,
        last_trade_pnl=round(last_trade_pnl, 2) if last_trade_pnl is not None else None,
        minutes_since_last_exit=None,
        consecutive_losses_today=consecutive_losses,
        is_directional_shift=is_directional_shift,
        realized_pnl_today=round(realized_pnl, 2),
        trades_taken_today=trades_count,
        capital_preservation_active=capital_preservation,
        is_counter_trend_slope=is_counter_trend_slope,
        is_climax_extended=is_climax_extended,
        is_candle_aligned=is_candle_aligned,
        is_reversal_inflection=is_reversal_inflection,
        global_bias=global_bias,
        news_bias=news_bias,
        news_sentiment_score=news_score,
        catalysts=catalysts,
        trap_advisories=advisories
    )
