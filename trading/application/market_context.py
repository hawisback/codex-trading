"""Market collection and context assembly with the original read order and formulas."""

import logging
import time
from typing import Any, Callable
from market_clock import MarketClock
from trading.domain.indicators import exponential_average, simple_rsi
from trading.ports import MarketReader

logger = logging.getLogger("NiftyAI")


class MarketContextService:
    def __init__(
        self,
        read_market: MarketReader,
        read_funds: Callable[[], dict],
        *,
        clock=MarketClock,
        monotonic: Callable[[], float] | None = None,
    ):
        self.read_market = read_market
        self.read_funds = read_funds
        self.clock = clock
        self.monotonic = monotonic if monotonic is not None else time.monotonic

    def health(self) -> dict:
        """Verify market data quality and feed freshness."""
        try:
            dq = self.read_market("/data-quality")
            feed_status = dq.get("market_feed", {}).get("status", "UNKNOWN")
            latency = dq.get("market_feed", {}).get("latency_sec", 999.0)
            quote_ready = dq.get("quote_ready", False)
            is_healthy = quote_ready and (feed_status == "LIVE" or latency < 20.0)
            return {"healthy": is_healthy, "status": feed_status, "latency_sec": latency, "raw": dq}
        except Exception as e:
            logger.error(f"Failed to check data quality: {e}")
            return {"healthy": False, "status": "ERROR", "error": str(e)}

    def fetch(self, monitor_only=False) -> dict:
        """
        Fetch multi-timeframe candles, technical indicators, option chain, and heavyweight quotes.
        Calculates 15-minute Range Box, Order Flow pressure, and Value Proximity.
        """
        deadline = self.monotonic() + 4 if monitor_only else None

        def read(path):
            if deadline is None:
                return self.read_market(path)
            available = deadline - self.monotonic()
            if available <= 0:
                raise TimeoutError("Structural monitor read budget exhausted")
            return self.read_market(path, timeout=min(2, available))

        snapshot_path = "/nifty/snapshot"
        if monitor_only and getattr(self.read_market, "requires_complete_context", False):
            snapshot_path += "?scope=vix"
        snapshot = read(snapshot_path)
        technicals_5m = read("/nifty/technicals?interval=5m&limit=50")
        candles_1m = read("/nifty/candles?interval=1m&limit=375")
        options = {} if monitor_only else read("/nifty/options?strike_window=10")
        try:
            heavyweights = read("/heavyweights")
        except Exception as e:
            if not monitor_only and getattr(self.read_market, "requires_complete_context", False):
                raise
            logger.debug(f"Failed to fetch heavyweights: {e}")
            heavyweights = {"available": False, "stocks": []}

        try:
            funds = {} if monitor_only else self.read_funds()
            available_margin = float(funds.get("available_margin") or 0.0)
        except Exception as e:
            logger.error(f"Failed to fetch live margin from broker: {e}")
            available_margin = 0.0

        spot_price = snapshot.get("underlying", {}).get("last_price")
        day_open = snapshot.get("underlying", {}).get("open")
        day_high = snapshot.get("underlying", {}).get("high")
        day_low = snapshot.get("underlying", {}).get("low")
        day_change = snapshot.get("underlying", {}).get("change_pct", 0.0)

        tech_metrics = technicals_5m.get("metrics", {})
        ema_9 = tech_metrics.get("ema_9")
        ema_20 = tech_metrics.get("ema_20")
        ema_50 = tech_metrics.get("ema_50")
        rsi_14 = tech_metrics.get("rsi_14")
        macd = tech_metrics.get("macd")
        macd_hist = tech_metrics.get("macd_histogram")
        hist_expanding_pos = tech_metrics.get("macd_histogram_expanding_positive", False)
        hist_expanding_neg = tech_metrics.get("macd_histogram_expanding_negative", False)
        # Process 1-minute microstructure, Spot Session VWAP & 15-minute Consolidation Box
        candles_list = (
            candles_1m.get("candles", [])
            if isinstance(candles_1m, dict)
            else (candles_1m if isinstance(candles_1m, list) else [])
        )
        now_date_str = self.clock.today_ist_str()
        today_candles = []
        for c in candles_list:
            raw_t = c.get("start_time") or c.get("date") or ""
            dt_c = self.clock.parse_to_ist(raw_t)
            if dt_c is not None:
                if dt_c.strftime("%Y-%m-%d") == now_date_str:
                    today_candles.append(c)
            elif raw_t.startswith(now_date_str):
                today_candles.append(c)

        # True Spot Session VWAP calculation (strictly Spot Index, NEVER Futures VWAP)
        if today_candles:
            spot_typicals = [
                (
                    c.get("high", c.get("close", spot_price))
                    + c.get("low", c.get("close", spot_price))
                    + c.get("close", spot_price)
                )
                / 3.0
                for c in today_candles
            ]
            session_vwap = round(sum(spot_typicals) / len(spot_typicals), 2)
            session_vwap_basis = "NIFTY_SPOT_INTRADAY"

            # Recompute RSI-14 from spot candle closes if candles present
            closes = [c.get("close", spot_price) for c in today_candles]
            if len(closes) > 14:
                rsi_14 = round(simple_rsi(closes, 14), 1)
        else:
            session_vwap = spot_price
            session_vwap_basis = "NIFTY_SPOT_FALLBACK"

        # Robust 5m EMA9 and EMA20: Use official 50-bar Kite spot indicators; fallback to 50-bar candles only if missing
        if ema_9 is None or ema_20 is None:
            try:
                candles_5m_resp = read("/nifty/candles?interval=5m&limit=50")
                candles_5m = candles_5m_resp.get("candles", []) if isinstance(candles_5m_resp, dict) else []
                if candles_5m:
                    closes_5m = [c.get("close", spot_price) for c in candles_5m]

                    def _calc_ema_50(prices: list, period: int) -> float:
                        if not prices:
                            return spot_price
                        return round(exponential_average(prices, period), 2)

                    ema_9 = _calc_ema_50(closes_5m, 9)
                    ema_20 = _calc_ema_50(closes_5m, 20)
            except Exception as e:
                logger.error(f"Fallback 5m EMA calculation failed: {e}")

        recent_1m = today_candles[-15:] if today_candles else []
        box_high_15m = max((c["high"] for c in recent_1m), default=spot_price)
        box_low_15m = min((c["low"] for c in recent_1m), default=spot_price)
        box_spread_15m = round(box_high_15m - box_low_15m, 2)
        is_consolidation_box = box_spread_15m < 28.0 and len(recent_1m) >= 10

        last_1m = recent_1m[-1] if recent_1m else {}
        last_1m_high = last_1m.get("high", spot_price)
        last_1m_low = last_1m.get("low", spot_price)

        opt_summary = options.get("summary", {})
        atm_strike = options.get("atm_strike")
        pcr_oi = opt_summary.get("pcr_oi")
        pcr_vol = opt_summary.get("pcr_volume")
        strikes = options.get("strikes", [])

        # Process Strike-Level Order Flow (ATM and next OTM Call/Put)
        atm_call_oi = 0
        atm_call_oi_chg = 0
        atm_put_oi = 0
        atm_put_oi_chg = 0
        next_call_strike = (atm_strike + 50) if atm_strike else 0
        next_call_oi = 0
        next_call_oi_chg = 0
        next_put_strike = (atm_strike - 50) if atm_strike else 0
        next_put_oi = 0
        next_put_oi_chg = 0

        for s in strikes:
            stk = s.get("strike", 0)
            if abs(stk - (atm_strike or 0)) < 1.0:
                atm_call = s.get("call") or {}
                atm_put = s.get("put") or {}
                atm_call_oi = atm_call.get("open_interest") or 0
                atm_call_oi_chg = atm_call.get("oi_change") or 0
                atm_put_oi = atm_put.get("open_interest") or 0
                atm_put_oi_chg = atm_put.get("oi_change") or 0
            elif abs(stk - next_call_strike) < 1.0:
                c = s.get("call") or {}
                next_call_oi = c.get("open_interest") or 0
                next_call_oi_chg = c.get("oi_change") or 0
            elif abs(stk - next_put_strike) < 1.0:
                p = s.get("put") or {}
                next_put_oi = p.get("open_interest") or 0
                next_put_oi_chg = p.get("oi_change") or 0

        # Process heavyweights breadth & leadership
        stocks = heavyweights.get("stocks", [])
        hw_advancing = sum(1 for s in stocks if (s.get("change_pct") or 0.0) > 0.05)
        hw_declining = sum(1 for s in stocks if (s.get("change_pct") or 0.0) < -0.05)
        hw_hdfc: dict[str, Any] = next((s for s in stocks if s.get("symbol") == "HDFCBANK"), {})
        hw_reliance: dict[str, Any] = next((s for s in stocks if s.get("symbol") == "RELIANCE"), {})
        hw_icici: dict[str, Any] = next((s for s in stocks if s.get("symbol") == "ICICIBANK"), {})

        return {
            **({"vix": snapshot["vix"]} if "vix" in snapshot else {}),
            **({"sectors": snapshot["sectors"]} if "sectors" in snapshot else {}),
            "spot": spot_price,
            "last_1m_high": last_1m_high,
            "last_1m_low": last_1m_low,
            "day_open": day_open,
            "day_high": day_high,
            "day_low": day_low,
            "day_change": day_change,
            "ema_9": ema_9,
            "ema_20": ema_20,
            "ema_50": ema_50,
            "rsi_14": rsi_14,
            "macd": macd,
            "macd_hist": macd_hist,
            "hist_expanding_pos": hist_expanding_pos,
            "hist_expanding_neg": hist_expanding_neg,
            "session_vwap": session_vwap,
            "session_vwap_basis": session_vwap_basis,
            "atm_strike": atm_strike,
            "pcr_oi": pcr_oi,
            "pcr_vol": pcr_vol,
            "box_high_15m": box_high_15m,
            "box_low_15m": box_low_15m,
            "box_spread_15m": box_spread_15m,
            "is_consolidation_box": is_consolidation_box,
            "order_flow": {
                "atm_call_oi": atm_call_oi,
                "atm_call_oi_chg": atm_call_oi_chg,
                "atm_put_oi": atm_put_oi,
                "atm_put_oi_chg": atm_put_oi_chg,
                "next_call_strike": next_call_strike,
                "next_call_oi": next_call_oi,
                "next_call_oi_chg": next_call_oi_chg,
                "next_put_strike": next_put_strike,
                "next_put_oi": next_put_oi,
                "next_put_oi_chg": next_put_oi_chg,
            },
            "strikes": strikes,
            "heavyweights": {
                "stocks": stocks,
                "advancing": hw_advancing,
                "declining": hw_declining,
                "hdfc_chg": hw_hdfc.get("change_pct", 0.0) or 0.0,
                "reliance_chg": hw_reliance.get("change_pct", 0.0) or 0.0,
                "icici_chg": hw_icici.get("change_pct", 0.0) or 0.0,
            },
            "candles_1m": today_candles,
            "available_margin": available_margin,
            "expiry": options.get("expiry") or opt_summary.get("expiry"),
        }
