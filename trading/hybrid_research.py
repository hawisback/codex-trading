"""Causal hybrid decision research using the actual strategy and rules consultant.

No execution gateway, synthetic prices, invented companion decisions, or PnL.
Historical macro/news and executable depth are not reconstructed by this service.
"""

from ai_consultant import AIConsultant
from market_clock import MarketClock
from trading.application.dossier import DossierService
from trading.domain.indicators import select_strike
from trading.domain.market_data import causal_hybrid_context, prior_session_warmup, completed_spot_bars
from trading.strategies.macd_momentum import MacdMomentumStrategy


class HybridHistoricalReview:
    def __init__(self, strategy_config, trading_config):
        self.strategy = MacdMomentumStrategy(strategy_config)
        self.strike_selection = strategy_config.get("entry", {}).get("strike_selection", "STRICT_ITM")
        self.warmup_enabled = strategy_config.get("entry", {}).get("prior_session_warmup_enabled", False)
        self.holidays = trading_config.get("option_selection", {}).get("exchange_holidays", [])
        self.consultant = AIConsultant(mode="rules", trading_config=trading_config,
                                      strategy_config=strategy_config)
        self.dossiers = DossierService(trading_config, strategy_config=strategy_config)

    def evaluate(self, rows, *, now, expiry, options, prior_rows=()):
        with MarketClock.at(now):
            try:
                ctx = causal_hybrid_context(rows, now, expiry=expiry, prior_rows=prior_rows)
                if self.warmup_enabled:
                    ctx["prior_session_warmup_candles"] = prior_session_warmup(
                        completed_spot_bars(prior_rows, now), now, holidays=self.holidays)
                ctx["exchange_holidays"] = self.holidays
            except (ValueError, TypeError, KeyError) as exc:
                return dict(signal=None, verdict=None, blocked="CONTEXT_UNAVAILABLE", reason=str(exc))
            candidate = self.strategy.evaluate(ctx)
            result = dict(signal=candidate.signal, verdict=None, blocked=None, reasons=candidate.reasons,
                          ema_observed_through=ctx["ema_observed_through"])
            if candidate.signal == "NEUTRAL":
                return result
            direction = candidate.signal.replace("BUY_", "")
            strike = select_strike(ctx["spot"], direction, self.strike_selection)
            if self.strike_selection == "STRICT_ITM" and strike == ctx["spot"]:
                strike += -50 if direction == "CE" else 50
            bar = options.bar(strike, direction, ctx["candles_1m"][-1]["start_time"])
            if bar is None:
                return dict(result, blocked="EXACT_OPTION_HISTORY_UNAVAILABLE", strike=strike)
            identity = f"INST-NIFTY-{expiry}-{strike}-{direction}"
            decision = dict(signal=candidate.signal, instrument_id=identity, symbol=identity, ltp=bar["close"],
                            target_strike=strike, setup_type=candidate.setup_type,
                            invalidation_level=candidate.invalidation_level,
                            candidate_timestamp=MarketClock.now_ist().isoformat())
            dossier = self.dossiers.build_dossier(ctx, decision, [], 0)
            try:
                verdict = self.consultant.evaluate(dossier)
            except Exception as exc:
                return dict(result, blocked="CONSULTANT_UNAVAILABLE", reason=str(exc))
            approved = verdict.is_approved and verdict.action == "APPROVED" and not verdict.trap_detected
            return dict(result, verdict=verdict.to_dict(), blocked=None if approved else "CONSULTANT_VETOED",
                        decision=decision)
