"""Shared live/replay dossier and expiry policy, preserving current calculation semantics."""

import logging
import copy
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional
from ai_context_dossier import MarketDossier, generate_market_dossier
from market_clock import MarketClock
from trading.domain.market_data import exchange_time, number, two_minute_macd_metrics, macd_observation_bars, prior_session_warmup
from trading.domain.order_book import order_book_snapshot
from entry_policy import EntryPolicy
from trading.domain.stop_loss import configured_stop_policy, positive_price

logger = logging.getLogger("NiftyAI")


class DossierService:
    def __init__(self, trading_cfg, expiry_resolver=None, *, strategy_config=None, market_data=None):
        self.trading_cfg = trading_cfg
        self.market_data = market_data
        self.macd_entry = (strategy_config or {}).get("entry", {})
        self.stop_policy = configured_stop_policy(strategy_config or {})
        self.expiry_resolver = expiry_resolver if expiry_resolver is not None else self.get_days_to_expiry

    def get_days_to_expiry(self, expiry_str: Optional[str] = None) -> float:
        today = MarketClock.now_ist().date()
        if expiry_str:
            try:
                s = str(expiry_str).strip()
                if len(s) == 10:
                    exp_d = datetime.strptime(s, "%Y-%m-%d").date()
                else:
                    dt = MarketClock.parse_to_ist(s)
                    exp_d = dt.date() if dt else today
                return float(max(0, (exp_d - today).days))
            except Exception as e:
                logger.debug(f"Failed to parse expiry_str {expiry_str}: {e}")

        # Check trading config exchange holidays
        holidays = set(self.trading_cfg.get("option_selection", {}).get("exchange_holidays", []))

        # NIFTY weekly options expire on Tuesdays (weekday 1)
        if today.weekday() <= 1:
            expiry_d = today + timedelta(days=(1 - today.weekday()))
        else:
            expiry_d = today + timedelta(days=(7 - (today.weekday() - 1)))

        # If expiry date falls on an exchange holiday, advance backward to preceding working day
        while expiry_d.strftime("%Y-%m-%d") in holidays:
            expiry_d -= timedelta(days=1)

        return float(max(0, (expiry_d - today).days))

    def build_dossier(
        self,
        ctx: dict,
        decision: Mapping[str, Any],
        open_trades: list,
        today_entries: int,
        intel: dict | None = None,
    ) -> MarketDossier:
        today_str = MarketClock.today_ist_str()
        direction = decision["signal"].replace("BUY_", "")
        symbol = decision.get("symbol") or f"NIFTY_{direction}"
        strike = decision.get("target_strike") or int(round(ctx["spot"] / 50.0)) * 50
        entry_price = float(decision.get("ltp") or 0)

        candles = ctx.get("candles_1m") or []
        if not candles:
            candles = [
                {
                    "start_time": datetime.now().isoformat(),
                    "open": ctx["spot"],
                    "high": ctx.get("day_high", ctx["spot"]),
                    "low": ctx.get("day_low", ctx["spot"]),
                    "close": ctx["spot"],
                    "volume": 1000,
                }
            ]

        days_exp = self.expiry_resolver(ctx.get("expiry"))
        is_0dte = days_exp == 0.0

        dossier = generate_market_dossier(
            target_date=today_str,
            candles=candles,
            current_bar_idx=len(candles) - 1,
            direction=direction,
            symbol=symbol,
            strike=strike,
            option_entry_price=entry_price,
            trade_history=open_trades,
            days_to_expiry=days_exp,
            is_expiry_0dte=is_0dte,
            intel=intel,
            use_rolling_2m=self.macd_entry.get("use_rolling_2m", False),
        )
        dossier.instrument_id = decision.get("instrument_id", "")
        dossier.setup_type = decision.get("setup_type", "TREND_PULLBACK")
        dossier.candidate_timestamp = decision.get("candidate_timestamp") or MarketClock.now_ist().isoformat()
        dossier.invalidation_level = decision.get("invalidation_level")
        # Preserve exactly the candidate's deterministic signal evidence in
        # the Chat Companion dossier, including crossover age/continuation,
        # countertrend VWAP/EMA observations and structural invalidation.
        if dossier.setup_type == "MACD_2M_MOMENTUM":
            reasons = decision.get("reasons") or []
            dossier.trap_advisories.extend(
                "MACD CANDIDATE EVIDENCE (not an approval): " + str(reason)
                for reason in reasons if isinstance(reason, str)
            )
        dossier.risk_policy = dict(self.stop_policy)
        if dossier.setup_type == "MACD_2M_MOMENTUM":
            # Match the completed 5m EMAs used by the strategy, rather than the
            # generic dossier's synthetic, potentially partial 5m candles.
            dossier.ema9_5m = positive_price(ctx.get("ema_9"))
            dossier.ema20_5m = positive_price(ctx.get("ema_20"))
            dossier.ema_spread_5m = dossier.ema9_5m - dossier.ema20_5m
            dossier.ribbon_compression_hazard = abs(dossier.ema_spread_5m) < 4
            dossier.pullback_distance_pts = abs(positive_price(ctx.get("spot")) - dossier.ema9_5m)
            self._attach_macd(dossier, candles, ctx.get("expiry"), ctx)
        dossier.order_flow = copy.deepcopy(ctx.get("order_flow", {}))
        if ctx.get("option_quote") is not None:
            dossier.order_book = order_book_snapshot(
                ctx["option_quote"], dossier.instrument_id, EntryPolicy.from_config(self.trading_cfg))
        dossier.vix = copy.deepcopy(ctx.get("vix", {}))
        dossier.sectors = copy.deepcopy(ctx.get("sectors", {}))
        for quote in ([dossier.vix] if dossier.vix else []) + list(dossier.sectors.values()):
            stamp = exchange_time(quote["timestamp"])
            now = MarketClock.now_ist()
            if stamp.date() != now.date() or not 0 <= (now - stamp).total_seconds() < 20:
                raise ValueError("VIX or sector context expired before AI consultation")
        if {"BANKNIFTY", "NIFTYIT"}.issubset(dossier.sectors):
            banking = dossier.sectors["BANKNIFTY"]["change_pct"]
            technology = dossier.sectors["NIFTYIT"]["change_pct"]
            threshold = number(
                self.trading_cfg.get("ai_context", {}).get("sector_divergence_threshold_pct", 0.5),
                minimum=0.000001,
            )
            dossier.sector_divergence = (
                banking * technology < 0 and min(abs(banking), abs(technology)) >= threshold
            )
            if dossier.sector_divergence:
                dossier.trap_advisories.append(
                    f"SECTOR DIVERGENCE: BANKNIFTY {banking:+.2f}%, NIFTYIT {technology:+.2f}%"
                )
        if decision.get("setup_type") == "CLIMAX_SPRING":
            dossier.is_directional_shift = True
        return dossier

    def _attach_macd(self, dossier, candles, expiry, ctx):
        """Publish synchronized Spot/selected-premium evidence, with explicit gaps."""
        try:
            now = MarketClock.now_ist()
            rolling = self.macd_entry.get("use_rolling_2m", False)
            warmup = self.macd_entry.get("prior_session_warmup_enabled", False)
            holidays = self.trading_cfg.get("option_selection", {}).get("exchange_holidays", [])
            prior = prior_session_warmup(ctx.get("prior_session_warmup_candles") or [], now,
                                        holidays=holidays) if warmup else []
            periods = tuple(int(number(self.macd_entry.get(k, self.macd_entry.get(alias, default)), minimum=1)) for k, alias, default in (
                ("macd_fast", "fast_period", 12), ("macd_slow", "slow_period", 26), ("macd_signal", "signal_period", 9)))
            bars = macd_observation_bars(candles, prior=prior, as_of=now, rolling=rolling)
            spot = two_minute_macd_metrics(bars, periods=periods, rolling=rolling)
            cutoff = exchange_time(spot["candle_closed_at"])
            if now - cutoff >= timedelta(minutes=3):
                raise ValueError("Spot two-minute MACD observation is stale")
            dossier.spot_macd_2m = spot
            reader = getattr(self.market_data, "get_strike_macd", None)
            if reader is None:
                raise ValueError("Selected-contract MACD history provider is unavailable")
            options = dict(use_rolling_2m=rolling, warmup_enabled=warmup, holidays=holidays, periods=periods) if rolling or warmup else {}
            metrics = reader(dossier.instrument_id, as_of=cutoff, timeout=5.0, **options)
            if (metrics["instrument_id"] != dossier.instrument_id or metrics["right"] != dossier.direction
                    or number(metrics["strike"]) != dossier.strike or metrics["expiry"] != expiry
                    or metrics["candle_closed_at"] != spot["candle_closed_at"]
                    or metrics.get("interval") != spot["interval"] or metrics.get("periods") != spot["periods"]):
                raise ValueError("Option MACD contract identity or observation does not match Spot dossier")
            line, signal, histogram, previous = [number(metrics[key]) for key in
                                                 ("macd", "signal", "histogram", "previous_histogram")]
            momentum_status = metrics["momentum_status"]
            if not isinstance(momentum_status, str) or not momentum_status:
                raise ValueError("Option MACD momentum status is missing")
            dossier.strike_macd_line = line
            dossier.strike_signal_line = signal
            dossier.strike_histogram = histogram
            dossier.strike_previous_histogram = previous
            dossier.strike_histogram_expanding_positive = histogram > 0 and histogram > previous
            dossier.strike_momentum_status = momentum_status
            dossier.strike_macd_candle_closed_at = metrics["candle_closed_at"]
            dossier.strike_macd_unavailable_reason = ""
        except Exception as exc:
            dossier.strike_macd_unavailable_reason = str(exc)
            logger.warning("Strike premium MACD unavailable: %s", exc)
