"""Offline decision replay using the live strategy, sizing, dossier and actual AI policies.

This service has no execution gateway and submits no orders. It reports decisions,
not simulated PnL or a promise of equivalent fills in historical markets.
"""

from ai_consultant import AIConsultant
from market_clock import MarketClock
from trading.application.dossier import DossierService
from trading.application.selection import CandidateSelectionService
from trading.configuration import RuntimeConfiguration, build_radar
from trading.domain.sizing import calculate_compounding_quantity
from trading.strategies.registry import StrategyRegistry
from trading.domain.limits import MAX_DAILY_ENTRIES


class ReplayService:
    def __init__(self, configuration: RuntimeConfiguration, *, quantity=65):
        if configuration.ai_mode.lower() not in ("playbook", "rules"):
            raise ValueError("Offline replay requires deterministic rules consultation (no AI)")
        self.configuration = configuration
        self.quantity = quantity
        self.ai_consultant = AIConsultant(
            mode="playbook",
            timeout_seconds=configuration.ai_timeout,
            trading_config=configuration.trading,
            strategy_config=configuration.strategy,
        )
        self.dossiers = DossierService(configuration.trading, strategy_config=configuration.strategy)
        strategy = StrategyRegistry().create(
            configuration.strategy_name, configuration.strategy, build_radar(configuration.strategy)
        )
        self.selection = CandidateSelectionService(
            configuration.strategy_name,
            configuration.strategy,
            quantity,
            self.calculate_quantity,
            strategy,
            trading_cfg=configuration.trading,
        )

    def calculate_quantity(self, margin, price):
        return calculate_compounding_quantity(
            margin,
            price,
            strategy_cfg=self.configuration.strategy,
            trading_cfg=self.configuration.trading,
            quantity=self.quantity,
        )

    def evaluate(self, context, intelligence, *, now, history=(), today_entries=0):
        with MarketClock.at(now):
            if not intelligence.get("ready", False):
                return {"decision": None, "verdict": None, "blocked": "INTELLIGENCE_UNAVAILABLE"}
            decision = self.selection.analyze(context, intel=intelligence, today_entries=today_entries)
            if decision["signal"] not in ("BUY_CE", "BUY_PE"):
                return {"decision": decision, "verdict": None, "blocked": None}
            if today_entries >= MAX_DAILY_ENTRIES:
                return {"decision": decision, "verdict": None, "blocked": "DAILY_ENTRY_CAP"}
            session = self.configuration.trading.get("session", {})
            allowed, reason = MarketClock.is_new_trade_allowed(
                no_new_trade_before=session.get("no_new_trade_before", "09:20"),
                no_new_trade_after=session.get("no_new_trade_after", "14:45"),
            )
            if not allowed:
                return {"decision": decision, "verdict": None, "blocked": reason}
            dossier = self.dossiers.build_dossier(
                context, decision, list(history), today_entries, intel=intelligence
            )
            try:
                verdict = self.ai_consultant.evaluate(dossier)
            except Exception:
                return {"decision": decision, "verdict": None, "blocked": "AI_UNAVAILABLE"}
            approved = verdict.is_approved and verdict.action == "APPROVED" and not verdict.trap_detected
            return {
                "decision": decision,
                "verdict": verdict.to_dict(),
                "blocked": None if approved else "AI_VETOED",
            }
