"""Entry-cycle orchestration. All candidate execution passes the actual AI gate."""

import json
import logging
from datetime import datetime
from market_clock import MarketClock
from trading.application.entry import EntryWorkflow
from trading import audit

logger = logging.getLogger("NiftyAI")


class CycleWorkflow:
    def __init__(self, log_dir, max_daily_entries):
        self.log_dir = log_dir
        self.max_daily_entries = max_daily_entries

    def run(self, trader, ignore_feed_health: bool = False):
        """Execute one complete 1-minute cycle."""
        logger.info("=" * 60)
        logger.info(MarketClock.get_market_clock_hud())
        logger.info(
            f"Cycle Start: {MarketClock.now_ist_str()} | "
            f"Strategy: {trader.strategy_cfg.get('display_name')} ({trader.strategy_mode})"
        )

        open_trades, today_entries = trader._timed_call("broker_reconciliation", trader.get_trades_state)
        if not trader.state_verified:
            return {"has_open_trades": True, "blocked": trader.last_reconciliation_error}
        if open_trades:
            return trader.run_monitor_cycle(open_trades)
        control_check = getattr(trader, "_entry_control_block", None)
        blocked = control_check() if control_check is not None else None
        if blocked:
            audit.event("entry_blocked", trader, reason=blocked)
            return {"has_open_trades": False, "blocked": blocked}
        if getattr(trader, "strategy_mode", None) == "macd_momentum":
            blocked = trader._entry_limit_block(today_entries)
            if blocked:
                audit.event("entry_blocked", trader, reason=blocked)
                return {"has_open_trades": False, "blocked": blocked}

        # 1. Check data quality
        if not ignore_feed_health or getattr(
            getattr(trader, "market_data", None), "requires_complete_context", False
        ):
            feed = trader._timed_call("feed_health", trader.check_feed_health)
            if not feed.get("healthy"):
                logger.warning(f"Feed not healthy ({feed.get('status')}). Skipping cycle.")
                return {"has_open_trades": False}
        else:
            logger.info("Feed health check bypassed (Dry-run / Off-market mode).")

        # 2. Ingest multi-timeframe market context & order flow
        try:
            ctx = trader._timed_call("entry_context", trader.fetch_market_context)
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            return {"has_open_trades": False}

        hw_stocks = ctx.get("heavyweights", {}).get("stocks", [])
        hw_summary = ", ".join(f"{s['symbol']}: {s.get('change_pct', 0):+.2f}%" for s in hw_stocks[:3])
        vwap_display = f"{ctx['session_vwap']:.1f}" if ctx.get("session_vwap") else "N/A"
        box_display = (
            f"{ctx['box_low_15m']:.1f} - {ctx['box_high_15m']:.1f} (Spread: {ctx['box_spread_15m']:.1f} pts)"
        )

        logger.info(
            f"Spot: {ctx['spot']} (Change: {ctx['day_change']:.2f}%) | "
            f"5m EMA9: {ctx['ema_9']:.1f} | EMA20: {ctx['ema_20']:.1f} | "
            f"VWAP: {vwap_display} | 15m Box: [{box_display}]"
        )
        if hw_summary:
            logger.info(
                f"Heavyweights -> Adv: {ctx.get('heavyweights', {}).get('advancing')}/5, "
                f"Dec: {ctx.get('heavyweights', {}).get('declining')}/5 | ({hw_summary})"
            )

        flow = ctx.get("order_flow", {})
        pcr_val = ctx.get("pcr_oi")
        pcr_str = f"{pcr_val:.2f}" if isinstance(pcr_val, (int, float)) else "N/A"
        atm_put_chg = flow.get("atm_put_oi_chg")
        next_call_chg = flow.get("next_call_oi_chg")
        put_chg_str = f"{atm_put_chg:+d}" if isinstance(atm_put_chg, int) else "0"
        call_chg_str = f"{next_call_chg:+d}" if isinstance(next_call_chg, int) else "0"
        logger.info(
            f"Order Flow -> ATM {ctx.get('atm_strike', 'N/A')}: Put OI Chg: {put_chg_str} | "
            f"Next Call {flow.get('next_call_strike', 'N/A')}: Call OI Chg: {call_chg_str} | PCR: {pcr_str}"
        )

        # 3. Ingest external market intelligence & news
        intel = trader._timed_call(
            "intelligence_cache",
            trader.intelligence.get_market_intelligence,
            spot_change_pct=ctx.get("day_change", 0.0),
        )
        if not intel.get("ready", False):
            logger.warning(
                "[INTELLIGENCE GATE] New entries blocked: status=%s worker=%s sources=%s",
                intel.get("status"),
                intel.get("worker"),
                intel.get("sources"),
            )
            return {"has_open_trades": False, "blocked": "INTELLIGENCE_UNAVAILABLE"}
        logger.info(
            f"External Intel -> Global: {intel['global_cues']['global_bias']} | "
            f"News: {intel['news']['news_bias']} (Score: {intel['news']['sentiment_score']}) | "
            f"Composite: {intel['composite_bias']}"
        )
        for adv in intel.get("trap_advisories", []):
            logger.warning(f"  [TRAP ADVISORY] {adv}")
        for cat in intel.get("news", {}).get("catalysts", [])[:2]:
            logger.info(f"  [CATALYST] {cat['title'][:80]} ({cat['sentiment']})")

        exec_res = None

        # 5. Contextual AI Analysis
        decision = trader._timed_call("analysis", trader.analyze, ctx, intel, today_entries=today_entries)
        decision["candidate_timestamp"] = MarketClock.now_ist().isoformat()
        if decision["signal"] in ("BUY_CE", "BUY_PE"):
            audit.candidate(trader, decision, ctx, intel)
        else:
            audit.event("decision", trader, decision=decision)
        logger.info(f"Analysis -> Decision: {decision['signal']}")
        for r in decision["reasons"]:
            logger.info(f"  - {r}")

        # Save latest decision snapshot with intelligence
        with open(self.log_dir / "latest_decision.json", "w", encoding="utf-8") as f:
            json.dump(
                {
                    "timestamp": datetime.now().isoformat(),
                    "strategy": trader.strategy_mode,
                    "strategy_display_name": trader.strategy_cfg.get("display_name"),
                    "open_trades_count": len(open_trades),
                    "today_entries": today_entries,
                    "market": {
                        "spot": ctx["spot"],
                        "day_change": ctx["day_change"],
                        "session_vwap": ctx["session_vwap"],
                        "box_15m": {
                            "high": ctx["box_high_15m"],
                            "low": ctx["box_low_15m"],
                            "spread": ctx["box_spread_15m"],
                            "is_consolidation": ctx["is_consolidation_box"],
                        },
                        "order_flow": ctx["order_flow"],
                        "pcr_oi": ctx["pcr_oi"],
                    },
                    "intelligence": {
                        "composite_bias": intel.get("composite_bias"),
                        "composite_score": intel.get("composite_score"),
                        "global_bias": intel.get("global_cues", {}).get("global_bias"),
                        "news_bias": intel.get("news", {}).get("news_bias"),
                        "trap_advisories": intel.get("trap_advisories", []),
                    },
                    "decision": decision,
                },
                f,
                indent=2,
            )

        # 6. Execute if high-conviction signal and no position in flight
        if open_trades:
            logger.info("Active trade in progress; letting thesis unfold. No duplicate trade placed.")
        elif today_entries >= self.max_daily_entries:
            logger.info(
                f"Daily entry cap reached ({today_entries}/{self.max_daily_entries}). Standing aside."
            )
        elif decision["signal"] in ["BUY_CE", "BUY_PE"]:
            # Check session trading allowed gate from config/trading.json
            blocked = EntryWorkflow().run(
                trader,
                ctx,
                decision,
                open_trades,
                today_entries,
                intel,
                ignore_feed_health=ignore_feed_health,
            )
            if blocked is not None:
                return blocked
        else:
            logger.info("No high-conviction setup. Standing aside.")

        # An error response can still leave a filled BUY or an unknown submission.
        # Durable pending exposure must retain the fast monitoring cadence.
        has_open = bool(open_trades) or trader.position_store.exists() or not trader.state_verified
        return {"has_open_trades": has_open, "open_trades_count": len(open_trades)}
