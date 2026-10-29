"""Deterministic market scenarios shared by characterization and replay tests."""

import copy
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from market_clock import MarketClock
from nifty_trader_scheduler import NiftyOptionsTrader
from test_self_healing_exit import Broker
from trading.adapters.position_store import JsonPositionStore

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-10-19T10:00:00+05:30"
STRATEGIES = ("legacy_scalper", "structural_runner", "institutional_pullback", "ai_opportunity_radar")
INTELLIGENCE = dict(
    ready=True,
    status="FRESH",
    trap_advisories=[],
    global_cues={"global_bias": "NEUTRAL"},
    news={"news_bias": "NEUTRAL", "sentiment_score": 0, "catalysts": []},
    composite_bias="NEUTRAL",
)


def market_responses():
    start = MarketClock.parse_to_ist(NOW).replace(hour=9, minute=15)
    candles = [
        dict(
            start_time=(start + timedelta(minutes=i)).isoformat(),
            open=22992 + i * 0.2,
            high=23004 + i * 0.2,
            low=22980 + i * 0.2,
            close=22992 + i * 0.2 + (2 if i % 2 else -2),
            volume=1000,
        )
        for i in range(46)
    ]
    strikes = [
        dict(
            strike=strike,
            call=dict(
                instrument_id=f"TEST-{strike}-CE",
                symbol=f"NIFTY-TEST-{strike}-CE",
                ltp=67,
                open_interest=100000,
                oi_change=0,
            ),
            put=dict(
                instrument_id=f"TEST-{strike}-PE",
                symbol=f"NIFTY-TEST-{strike}-PE",
                ltp=67,
                open_interest=100000,
                oi_change=0,
            ),
        )
        for strike in (22950, 23000, 23050)
    ]
    return {
        "/nifty/snapshot": {
            "underlying": dict(last_price=23004, open=22985, high=23080, low=22900, change_pct=0.1)
        },
        "/nifty/technicals?interval=5m&limit=50": {
            "metrics": dict(
                ema_9=23000,
                ema_20=22994,
                ema_50=22980,
                rsi_14=55,
                macd=3,
                macd_histogram=1,
                macd_histogram_expanding_positive=True,
            )
        },
        "/nifty/candles?interval=1m&limit=375": {"candles": candles},
        "/nifty/candles?interval=5m&limit=50": {"candles": candles[::5]},
        "/nifty/options?strike_window=10": {
            "atm_strike": 23000,
            "expiry": "2026-10-22",
            "strikes": strikes,
            "summary": {"pcr_oi": 1.1, "pcr_volume": 1.2},
        },
        "/heavyweights": {
            "stocks": [dict(symbol=s, change_pct=0.1) for s in ("HDFCBANK", "RELIANCE", "ICICIBANK")]
        },
    }


def make_trader(path, strategy="institutional_pullback"):
    broker = Broker()
    return NiftyOptionsTrader(
        strategy=strategy,
        ai_mode="playbook",
        client=broker,
        quote_reader=broker,
        intelligence=SimpleNamespace(
            get_market_intelligence=lambda **kw: copy.deepcopy(INTELLIGENCE), stop_worker=lambda **kw: True
        ),
        state_store=JsonPositionStore(path),
    )


def context_variants(context):
    variants = {"bull": copy.deepcopy(context)}
    bear = copy.deepcopy(context)
    bear.update(
        spot=22996,
        ema_9=23000,
        ema_20=23006,
        rsi_14=45,
        session_vwap=23010,
        last_1m_high=23002,
        last_1m_low=22990,
    )
    variants["bear"] = bear
    for name, changes in {
        "missing_indicators": {"ema_9": None, "ema_20": None, "session_vwap": None},
        "unaffordable": {"available_margin": 100},
        "overextended": {"spot": 23120, "rsi_14": 85},
        "box_ceiling": {
            "is_consolidation_box": True,
            "box_spread_15m": 15,
            "box_high_15m": 23006,
            "box_low_15m": 22991,
        },
        "no_contracts": {"strikes": []},
    }.items():
        variant = copy.deepcopy(context)
        variant.update(changes)
        variants[name] = variant
    return variants


def normalize_verdict(verdict):
    result = verdict.to_dict()
    result["timestamp"] = "<host-wall-clock>"
    return result


def extra_contexts(context):
    variants = {}
    for name, bullish in (("climax_spring", True), ("climax_upthrust", False)):
        variant = copy.deepcopy(context)
        start = MarketClock.parse_to_ist(NOW).replace(hour=9, minute=30)
        candles = [
            dict(
                start_time=(start + timedelta(minutes=i)).isoformat(),
                open=23000,
                high=23014,
                low=22994,
                close=23000 + (10 if i % 2 else 0),
                volume=1000,
            )
            for i in range(15)
        ]
        candles[-1].update(
            open=22984 if bullish else 23024,
            close=23004,
            high=23012 if bullish else 23060,
            low=22940 if bullish else 22998,
        )
        variant.update(
            candles_1m=candles,
            rsi_14=30 if bullish else 70,
            day_open=23100 if bullish else 22900,
            session_vwap=23020 if bullish else 22980,
        )
        variants[name] = variant
    margin = copy.deepcopy(context)
    for strike in margin["strikes"]:
        for leg in ("call", "put"):
            strike[leg]["ltp"] = 30 if strike["strike"] == 23050 else 200
    margin["available_margin"] = 5000
    variants["margin_fallback"] = margin
    return variants


def approved_contexts(context):
    variants = {}
    start = MarketClock.parse_to_ist(NOW).replace(hour=9, minute=15)
    for name, bullish in (("approved_bull", True), ("approved_bear", False)):
        variant = copy.deepcopy(context)
        closes = [
            (22951 + i * 1.1 + (3 if i % 2 else 0)) if bullish else (23049 - i * 1.1 - (3 if i % 2 else 0))
            for i in range(46)
        ]
        variant["candles_1m"] = [
            dict(
                start_time=(start + timedelta(minutes=i)).isoformat(),
                open=close - 1 if bullish else close + 1,
                high=close + 5,
                low=close - 5,
                close=close,
                volume=1000,
            )
            for i, close in enumerate(closes)
        ]
        variant.update(
            spot=23004 if bullish else 22996,
            ema_9=23000,
            ema_20=22994 if bullish else 23006,
            rsi_14=68.3 if bullish else 31.7,
            session_vwap=22976 if bullish else 23024,
            day_open=22950 if bullish else 23050,
            last_1m_high=closes[-1] + 5,
            last_1m_low=closes[-1] - 5,
            is_consolidation_box=False,
            box_high_15m=23050,
            box_low_15m=22950,
            box_spread_15m=100,
        )
        variants[name] = variant
    return variants
