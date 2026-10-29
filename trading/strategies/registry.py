"""Strategy selection; strategies propose candidates and never submit orders."""

from trading.models import CandidateSignal
from trading.strategies.legacy import LegacyRuleEvaluator
from trading.strategies.radar import RadarStrategy
from trading.strategies.macd_momentum import MacdMomentumStrategy


class RuleBasedStrategy:
    def __init__(self, strategy_cfg, *, evaluator=None):
        self.evaluator = evaluator if evaluator is not None else LegacyRuleEvaluator(strategy_cfg).evaluate

    def evaluate(self, ctx, intel=None):
        signal, reasons = self.evaluator(ctx, intel=intel)
        return CandidateSignal(
            signal, reasons, "TREND_PULLBACK" if signal in ("BUY_CE", "BUY_PE") else "NONE"
        )


class LegacyScalperStrategy(RuleBasedStrategy):
    """Legacy scalper profile using its existing configured filters."""


class StructuralRunnerStrategy(RuleBasedStrategy):
    """Structural runner profile using its existing configured filters."""


class InstitutionalPullbackStrategy(RuleBasedStrategy):
    """Institutional pullback profile using its existing configured filters."""


class StrategyRegistry:
    def __init__(self):
        self._factories = {
            "legacy_scalper": lambda cfg, radar, evaluator: LegacyScalperStrategy(cfg, evaluator=evaluator),
            "structural_runner": lambda cfg, radar, evaluator: StructuralRunnerStrategy(
                cfg, evaluator=evaluator
            ),
            "institutional_pullback": lambda cfg, radar, evaluator: InstitutionalPullbackStrategy(
                cfg, evaluator=evaluator
            ),
            "ai_opportunity_radar": lambda cfg, radar, evaluator: RadarStrategy(radar),
            "macd_momentum": lambda cfg, radar, evaluator: MacdMomentumStrategy(cfg),
        }

    def register(self, name, factory):
        """Extend selection without adding execution paths or bypassing the common AI gate."""
        self._factories[name] = factory

    def create(self, name, strategy_cfg, radar, *, legacy_evaluator=None):
        factory = self._factories.get(name)
        if factory is None:
            return RuleBasedStrategy(strategy_cfg, evaluator=legacy_evaluator)
        return factory(strategy_cfg, radar, legacy_evaluator)
