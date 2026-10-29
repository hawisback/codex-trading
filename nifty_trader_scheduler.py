#!/usr/bin/env python3
"""
NIFTY Options Contextual AI Trading Engine & 1-Minute Scheduler
Ingests:
1. Multi-Timeframe Structure (1m microstructure, 15m Box consolidation, 5m trend)
2. Institutional Order Flow (Kite strike-wise OI changes, call walls, put baselines, PCR)
3. True Spot Session VWAP
4. Heavyweight Constituent Leadership (HDFC, Reliance, ICICI, Infosys, TCS breadth)
5. Macro & Financial News Intelligence (Crude, Currency, Dow, Nasdaq, live RSS headlines)
6. Thesis-Based Position Management (No arbitrary stopwatch timers, 5m EMA9 trailing runners)
"""

from trading.domain.limits import HARD_SQUARE_OFF, LOT_SIZE, MAX_DAILY_ENTRIES
from trading.domain.states import is_exiting

import os
import sys


import time
import json
import uuid
import logging
import argparse
import urllib.request
import urllib.error
import math
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List, Tuple
from pathlib import Path
from market_clock import MarketClock
from market_intelligence import MarketIntelligence
from ai_context_dossier import MarketDossier, generate_market_dossier
from ai_consultant import AIConsultant, AIVerdict
from execution_client import AIExecutionClient, round_tick
from execution_safety import SchedulerLock, ReconciliationError
from position_lifecycle import PositionLifecycle
from ai_opportunity_radar import AIOpportunityRadar, AIOpportunity
from trading.adapters.gateways import create_execution_gateway
from trading.adapters.market_data import create_market_data
from trading.ports import ExecutionGateway, IntelligenceSource, PositionStore, MarketReader, QuoteReader
from trading.application.market_context import MarketContextService
from trading.application.dossier import DossierService
from trading.domain.order_book import order_book_snapshot
from trading.domain.market_data import prior_session_warmup
from trading.application.selection import CandidateSelectionService
from trading.application.position_monitor import PositionMonitor
from trading.application.workflows import CycleWorkflow
from trading.strategies.legacy import LegacyRuleEvaluator
from trading.strategies.registry import StrategyRegistry
from trading.domain.sizing import calculate_compounding_quantity
from trading.configuration import load_configuration, build_radar
from trading.application.scheduler import run_scheduler, cycle_sleep_delay
from trading.bootstrap import configure_console, ensure_environment
from trading.logging_setup import configure_logging
from trading import audit

# Paths & Defaults
DEFAULT_INTERVAL_SEC = 60
DEFAULT_QUANTITY = LOT_SIZE  # 1 lot NIFTY
LOG_DIR = Path(__file__).resolve().parent / "logs"

logger = logging.getLogger("NiftyAI")


def setup_logging():
    configure_console()
    return configure_logging(LOG_DIR, console=sys.stdout)


class NiftyOptionsTrader(PositionLifecycle):
    def __init__(self, quantity: int = DEFAULT_QUANTITY, strategy: str | None = None, ai_mode: str | None = None,
                 *, client: ExecutionGateway | None = None, intelligence: IntelligenceSource | None = None,
                 state_store: PositionStore | None = None, strategy_registry: StrategyRegistry | None = None,
                 broker: str | None = None, market_data: MarketReader | None = None,
                 market_data_broker: str | None = None, quote_reader: QuoteReader | None = None):
        ensure_environment()
        state_path = state_store.path if state_store is not None else LOG_DIR / "active_position.json"
        self.initialize_safety(state_path, store=state_store)
        self.quantity = quantity
        self.strategy_registry = strategy_registry if strategy_registry is not None else StrategyRegistry()
        if client is not None:
            self.client = client
        elif broker:
            self.client = create_execution_gateway(broker, journal_path=state_path.parent / "broker_intents.json")
        else:
            self.client = AIExecutionClient()
        self.market_data = market_data if market_data is not None else create_market_data(
            market_data_broker, gateway=self.client)
        self.quote_reader = quote_reader if quote_reader is not None else (
            self.market_data if hasattr(self.market_data, "get_contract_quote") else self.client)
        self.load_strategy_config(strategy, ai_mode=ai_mode)
        self.intelligence = intelligence if intelligence is not None else MarketIntelligence(
            cache_ttl_seconds=120, refresh_interval_seconds=60, snapshot_dir=LOG_DIR)


    def load_strategy_config(self, strategy_name: str | None = None, ai_mode: str | None = None):
        settings = load_configuration(strategy_name, ai_mode)
        self.configuration = settings
        self.strategy_mode = settings.strategy_name
        self.strategy_cfg = settings.strategy
        self.trading_cfg = settings.trading
        self.ai_consultant = AIConsultant(mode=settings.ai_mode, timeout_seconds=settings.ai_timeout,
                                          trading_config=self.trading_cfg, strategy_config=self.strategy_cfg)
        self.opportunity_radar = build_radar(self.strategy_cfg)

    def get_days_to_expiry(self, expiry_str: Optional[str] = None) -> float:
        return DossierService(self.trading_cfg).get_days_to_expiry(expiry_str)

    def build_dossier(self, ctx: dict, decision: dict, open_trades: list, today_entries: int, intel: dict = None) -> MarketDossier:
        dossier = DossierService(self.trading_cfg, self.get_days_to_expiry, strategy_config=self.strategy_cfg,
                                 market_data=self.market_data).build_dossier(
            ctx, decision, open_trades, today_entries, intel=intel)
        if self.ai_consultant.mode == "chat":
            # History may take seconds; obtain executable depth only after it completes.
            policy = self.ai_consultant.entry_policy
            quote = self.quote_reader.get_contract_quote(decision["instrument_id"], timeout_sec=policy.quote_timeout)
            dossier.order_book = order_book_snapshot(quote, dossier.instrument_id, policy)
        return dossier

    def check_feed_health(self) -> dict:
        return MarketContextService(self.market_data, self.client.get_funds).health()


    def fetch_market_context(self, monitor_only=False) -> dict:
        ctx = MarketContextService(self.market_data, self.client.get_funds).fetch(monitor_only=monitor_only)
        if not monitor_only and self.strategy_mode == "macd_momentum":
            self.prepare_strategy_warmup()
            ctx["prior_session_warmup_candles"] = [dict(row) for row in getattr(self, "prior_session_warmup_candles", [])]
            ctx["exchange_holidays"] = self.trading_cfg.get("option_selection", {}).get("exchange_holidays", [])
        return ctx

    def prepare_strategy_warmup(self):
        if (self.strategy_mode != "macd_momentum" or not
                self.strategy_cfg.get("entry", {}).get("prior_session_warmup_enabled", False)):
            return
        try:
            holidays = self.trading_cfg.get("option_selection", {}).get("exchange_holidays", [])
            cached = getattr(self, "prior_session_warmup_candles", [])
            try:
                prior_session_warmup(cached, MarketClock.now_ist(), holidays=holidays)
                return
            except (ValueError, TypeError, KeyError):
                pass
            rows = self.market_data.get_prior_session_warmup(holidays=holidays, timeout=20)
            self.prior_session_warmup_candles = prior_session_warmup(rows, MarketClock.now_ist(), holidays=holidays)
        except Exception:
            self.prior_session_warmup_candles = []
            logger.warning("Prior-session MACD warmup unavailable; new strategy entries remain blocked")

    def _evaluate_legacy_signal(self, ctx: dict, intel: dict = None) -> tuple[str, list[str]]:
        return LegacyRuleEvaluator(self.strategy_cfg).evaluate(ctx, intel=intel)

    def calculate_compounding_quantity(self, available_margin: float, contract_price: float) -> int:
        return calculate_compounding_quantity(available_margin, contract_price,
            strategy_cfg=self.strategy_cfg, trading_cfg=self.trading_cfg, quantity=self.quantity)

    def analyze(self, ctx: dict, intel: dict = None, today_entries: int = 0) -> dict:
        registry = getattr(self, "strategy_registry", None)
        if registry is None:
            self.strategy_registry = registry = StrategyRegistry()
        strategy = registry.create(self.strategy_mode, self.strategy_cfg, self.opportunity_radar,
                                   legacy_evaluator=self._evaluate_legacy_signal)
        return CandidateSelectionService(self.strategy_mode, self.strategy_cfg, self.quantity,
            self.calculate_compounding_quantity, strategy, trading_cfg=self.trading_cfg).analyze(ctx, intel=intel, today_entries=today_entries)


    def manage_open_trades(self, open_trades: list, ctx: dict, intel: dict) -> list:
        return PositionMonitor(self.strategy_cfg, self.state_verified, self.exit_trade,
                               self.ratchet_stops, save_position=self.save_active_position).manage(open_trades, ctx, intel)


    def _timed_call(self, stage, function, *args, **kwargs):
        started = time.perf_counter()
        try:
            return function(*args, **kwargs)
        finally:
            timings = getattr(self, "_cycle_timings", {})
            timings[stage] = round(timings.get(stage, 0) + time.perf_counter() - started, 6)
            self._cycle_timings = timings

    def run_cycle(self, ignore_feed_health=False):
        self._cycle_sequence = getattr(self, "_cycle_sequence", 0) + 1
        self._cycle_timings = {}
        started = time.perf_counter()
        try:
            return self._run_cycle(ignore_feed_health=ignore_feed_health)
        finally:
            logger.info("[CYCLE TIMING] id=%s-%s elapsed_sec=%.3f stages=%s", os.getpid(),
                        self._cycle_sequence, time.perf_counter() - started,
                        json.dumps(self._cycle_timings, sort_keys=True))

    def run_monitor_cycle(self, open_trades=None):
        """Prioritize exposure management; never wait for news, entry AI or feed readiness."""
        if open_trades is None:
            open_trades, _ = self._timed_call("broker_reconciliation", self.get_trades_state)
        if not self.state_verified:
            return {"has_open_trades": True, "blocked": self.last_reconciliation_error}
        if not open_trades:
            return {"has_open_trades": False}
        if is_exiting(open_trades[0]) or open_trades[0].get("risk_exit_required"):
            self._timed_call("exit_execution", self.exit_trade, open_trades[0].get("trade_id"), open_trades[0].get("risk_exit_required") or "Resume pending exit")
        elif MarketClock.now_ist().strftime("%H:%M") >= HARD_SQUARE_OFF:
            self._timed_call("exit_execution", self.exit_trade, open_trades[0].get("trade_id"), "Mandatory 15:15 IST square-off")
        else:
            try:
                ctx = self._timed_call("structural_context", self.fetch_market_context, monitor_only=True)
            except Exception as exc:
                logger.error("Structural context unavailable; retaining broker/price guards: %s", exc)
                ctx = {}
            self._timed_call("monitor_quote", self.refresh_monitor_quote, open_trades[0], reuse=True)
            self.save_active_position(open_trades[0])
            try:
                self._timed_call("ai_stop_loss_check", self._check_ai_stop_loss, open_trades[0], ctx)
            except Exception:
                logger.exception("Stop consultation failed; continuing position management with existing protection")
            self._timed_call("position_management", self.manage_open_trades, open_trades, ctx, {})
        return {"has_open_trades": self.position_store.exists()}

    def _check_ai_stop_loss(self, trade: dict, ctx: dict):
        """Asynchronous Two-Step Stop Loss check called on monitoring ticks."""
        if not trade or trade.get("status") != "OPEN" or getattr(self, "ai_consultant", None) is None:
            return
        status = trade.get("ai_stop_status")
        if status is None:
            # Step 2: Post-fill consultation request (entry already filled and safe)
            self.ai_consultant.request_stop_loss_consultation(
                trade, ctx, ratchet_callback=self.ratchet_stops, save_callback=self.save_active_position
            )
        elif status == "PENDING":
            # Next call: check if AI verdict has arrived
            self.ai_consultant.poll_stop_loss_verdict(
                trade, ratchet_callback=self.ratchet_stops, save_callback=self.save_active_position
            )
        elif status == "APPLYING":
            self.ratchet_stops(trade, trade["ai_stop_price"])
            self.ai_consultant.confirm_stop_loss(trade, self.save_active_position)

    def _run_cycle(self, ignore_feed_health: bool = False):
        return CycleWorkflow(LOG_DIR, MAX_DAILY_ENTRIES).run(self, ignore_feed_health=ignore_feed_health)


def _main():
    return run_scheduler(NiftyOptionsTrader, default_interval=DEFAULT_INTERVAL_SEC,
                         default_quantity=DEFAULT_QUANTITY)


def main():
    log_session = setup_logging()
    try:
        with SchedulerLock(LOG_DIR / "scheduler.lock"):
            try:
                audit.event("session_started")
                _main()
            except RuntimeError as exc:
                logger.critical("Scheduler cannot start: %s", exc)
                return 1
            finally:
                audit.event("session_stopped")
                # Drain observational writes before releasing process ownership.
                log_session.close()
    except RuntimeError as exc:
        logger.critical("Scheduler cannot start: %s", exc)
        return 1
    finally:
        log_session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
