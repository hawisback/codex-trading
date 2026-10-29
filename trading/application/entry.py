"""The single mandatory AI gate shared by every candidate strategy."""

from trading.domain.intelligence import intelligence_context
from trading.domain.stop_loss import stop_loss_context
import logging
import copy
from market_clock import MarketClock
from trading import audit

logger = logging.getLogger("NiftyAI")


class EntryWorkflow:
    def run(self, trader, ctx, decision, open_trades, today_entries, intel, ignore_feed_health=False):
        session_cfg = trader.trading_cfg.get("session", {})
        no_new_before = session_cfg.get("no_new_trade_before", "09:20")
        no_new_after = session_cfg.get("no_new_trade_after", "14:45")
        trade_allowed, trade_block_reason = MarketClock.is_new_trade_allowed(
            no_new_trade_before=no_new_before, no_new_trade_after=no_new_after
        )
        if not trade_allowed and not ignore_feed_health:
            audit.event("entry_blocked", trader, reason=trade_block_reason)
            logger.warning(f"🚫 [SESSION TIME GATE BLOCKED] {trade_block_reason}. Order submission blocked.")
            return {"has_open_trades": False, "open_trades_count": 0}
        elif not trade_allowed and ignore_feed_health:
            logger.info(f"⚡ [OFF-MARKET SIMULATION] {trade_block_reason} Bypassing block for dry run.")

        # Generate AI Market State Dossier
        try:
            dossier = trader.build_dossier(ctx, decision, open_trades, today_entries, intel=intel)
        except Exception as exc:
            logger.error("Consultation context unavailable; preserving cash: %s", exc)
            audit.event("entry_blocked", trader, reason="CONSULTATION_CONTEXT_UNAVAILABLE")
            return {"has_open_trades": False, "blocked": "CONSULTATION_CONTEXT_UNAVAILABLE"}
        logger.info(f"\n{dossier.to_markdown()}")
        audit.consultation(trader, dossier)

        # Submit to AI Consultation Gate
        try:
            verdict = trader._timed_call("ai_consultation", trader.ai_consultant.evaluate, dossier)
        except Exception as exc:
            logger.error("AI consultation failed; preserving cash: %s", exc)
            audit.event("ai_error", trader, reason=str(exc))
            return {"has_open_trades": False, "blocked": "AI_UNAVAILABLE"}
        decision["ai_verdict"] = verdict.to_dict()
        audit.event("ai_verdict", trader, decision=decision, verdict=decision["ai_verdict"])

        exec_res = None
        if verdict.is_approved and verdict.action == "APPROVED" and not verdict.trap_detected:
            logger.info(
                f"✅ AI Consultation APPROVED: {verdict.reasoning} (Confidence: {verdict.confidence_score}%)"
            )
            latest_intel = trader._timed_call(
                "intelligence_recheck",
                trader.intelligence.get_market_intelligence,
                spot_change_pct=ctx.get("day_change", 0.0),
            )
            if not latest_intel.get("ready", False):
                logger.warning("Intelligence expired during AI consultation; preserving cash")
                audit.event("entry_blocked", trader, reason="INTELLIGENCE_UNAVAILABLE")
                return {"has_open_trades": False, "blocked": "INTELLIGENCE_UNAVAILABLE"}
            if intelligence_context(latest_intel) != intelligence_context(intel):
                audit.event("entry_blocked", trader, reason="INTELLIGENCE_CHANGED_DURING_CONSULTATION")
                logger.warning(
                    "Macro/news context changed during AI consultation; requesting a fresh decision next cycle"
                )
                return {"has_open_trades": False, "blocked": "INTELLIGENCE_CHANGED_DURING_CONSULTATION"}
            decision["stop_loss_context"] = stop_loss_context(ctx)
            if dossier.risk_policy:
                decision["stop_loss_policy"] = copy.deepcopy(dossier.risk_policy)
            if decision["stop_loss_context"] is not None:
                decision["stop_loss_context"]["observed_at"] = (
                    ctx.get("observed_at")
                    or decision.get("candidate_timestamp")
                    or dossier.candidate_timestamp
                )
            exec_res = trader._timed_call("entry_execution", trader.execute_trade, decision)
            audit.event("entry_result", trader, decision=decision, result=exec_res)
        else:
            logger.warning(
                f"🚫 AI Consultation VETOED: {verdict.reasoning} (Trap: {verdict.trap_detected or 'Risk Limit'})"
            )
            logger.info("Capital preserved. Standing aside.")

        return None
