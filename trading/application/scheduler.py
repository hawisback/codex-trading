"""CLI session scheduling and teardown; trading decisions live in application services."""

import argparse
import json
import logging
import os
import time
from pathlib import Path
from market_clock import MarketClock
from trading.bootstrap import ensure_environment

logger = logging.getLogger("NiftyAI")


def cycle_sleep_delay(started, interval):
    return max(0.0, interval - (time.monotonic() - started))


def run_scheduler(trader_factory, *, default_interval=60, default_quantity=65):
    ensure_environment()
    parser = argparse.ArgumentParser(description="NIFTY Contextual AI Options Trading Engine")
    parser.add_argument("--once", action="store_true", help="Run a single analysis cycle and exit")
    parser.add_argument(
        "--interval",
        type=int,
        default=default_interval,
        help="Interval in seconds for candle entry analysis (default: 60)",
    )
    parser.add_argument(
        "--trailing-interval",
        type=int,
        default=5,
        help="Fast interval in seconds for active position stop trailing (default: 5)",
    )
    parser.add_argument(
        "--quantity",
        type=int,
        default=None,
        help="Contract quantity (default: dynamic via compounding, or calculated from --lots)",
    )
    parser.add_argument(
        "--lots", type=int, default=1, help="Baseline number of NIFTY lots to trade (default: 1 lot = 65 qty)"
    )
    parser.add_argument(
        "--ignore-feed-health", action="store_true", help="Bypass feed health check for off-market dry-runs"
    )
    parser.add_argument(
        "--wait-until-market-open", action="store_true", help="Wait until 09:15:00 IST before starting cycles"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        choices=[
            "legacy_scalper",
            "structural_runner",
            "institutional_pullback",
            "ai_opportunity_radar",
            "macd_momentum",
        ],
        help="Strategy profile to run (default: active_strategy from config/strategies.json)",
    )
    parser.add_argument(
        "--ai-mode",
        type=str,
        default=None,
        choices=["rules", "playbook", "chat", "interactive"],
        help="AI Consultation mode (default: from config/strategies.json)",
    )
    parser.add_argument(
        "--broker",
        type=str,
        default=os.getenv("EXECUTION_BROKER", "proxy"),
        choices=["kite", "breeze", "proxy"],
        help="Broker gateway to use: 'kite' (direct Zerodha Kite), 'breeze' (direct ICICI Breeze), or 'proxy' (local REST API gateway)",
    )
    parser.add_argument(
        "--market-data-broker",
        default=os.getenv("MARKET_DATA_BROKER", "kite"),
        choices=["kite", "breeze"],
        help="Direct market-data broker, independent of the execution broker (default: kite)",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Arm LIVE broker execution (required for native Kite/Breeze; proxy defaults to PAPER)",
    )
    parser.add_argument(
        "--list-strategies", action="store_true", help="List available strategy profiles and exit"
    )
    args = parser.parse_args()
    if args.interval <= 0 or args.trailing_interval <= 0:
        parser.error("Scheduler intervals must be positive")

    if args.list_strategies:
        cfg_path = Path("config/strategies.json")
        if cfg_path.exists():
            with open(cfg_path, "r", encoding="utf-8") as f:
                d = json.load(f)
            print("\n" + "=" * 65)
            print(f"  NIFTY AI STRATEGY PROFILES (Active: {d.get('active_strategy')})")
            print("=" * 65)
            for k, v in d.get("strategies", {}).items():
                active_flag = " [ACTIVE]" if k == d.get("active_strategy") else ""
                print(f"\n* {k}{active_flag}:")
                print(f"    Display Name:       {v.get('display_name')}")
                print(f"    Description:        {v.get('description')}")
                print(f"    Strike Selection:   {v.get('entry', {}).get('strike_selection')}")
                print(f"    Require Pullback:   {v.get('entry', {}).get('require_pullback')}")
                hold_sec = v.get("exit", {}).get("max_hold_seconds", 0)
                print(f"    Max Hold Duration:  {hold_sec}s ({hold_sec // 60}m)")
                print(
                    f"    Initial Stop / Tgt: -{v.get('exit', {}).get('initial_stop_pct')}% / +{v.get('exit', {}).get('target_pct')}%"
                )
                print(f"    Structural Stops:   {v.get('exit', {}).get('structural_stops_enabled')}")
                print(f"    Runner Trailing:    {v.get('exit', {}).get('runner_trailing_enabled')}")
            print("\n" + "=" * 65 + "\n")
        return

    if args.broker in ("kite", "breeze") and not args.live:
        parser.error("Native Kite/Breeze requires --live. Use --broker proxy for paper execution.")

    qty = args.quantity if args.quantity is not None else (args.lots * default_quantity)
    logger.info(f"Execution Sizing Armed: {args.lots} lot(s) ({qty} contracts)")
    trader = trader_factory(
        quantity=qty,
        strategy=args.strategy,
        ai_mode=args.ai_mode,
        broker=args.broker,
        market_data_broker=args.market_data_broker,
    )

    try:
        prepare = getattr(trader, "prepare_strategy_warmup", None)
        if prepare is not None:
            prepare()  # Read-only warmup before market-open waiting; no execution.
        if args.live:
            logger.warning(
                "🚨 [LIVE EXECUTION MODE] Switching to LIVE real-money execution via %s!", args.broker
            )
            res = trader.client.set_mode("LIVE")
            if res.get("error") or res.get("mode") != "LIVE" or not res.get("live_authorized"):
                raise RuntimeError("Broker LIVE authorization failed; scheduler will not trade")
            logger.warning(
                f"🚨 Mode switched: {res.get('mode')} (Live Authorized: {res.get('live_authorized')})"
            )
        else:
            status = trader.client.get_status()
            logger.info(
                f"Execution Mode: {status.get('mode')} (Live Capability: {status.get('live_capability_enabled')})"
            )

        if args.once:
            trader.run_cycle(ignore_feed_health=args.ignore_feed_health)
            return

        startup_trades, _ = trader.get_trades_state()
        if (
            args.wait_until_market_open
            and not MarketClock.is_market_open()
            and not args.ignore_feed_health
            and trader.state_verified
            and not startup_trades
        ):
            sec_to_open = MarketClock.get_seconds_until_next_open()
            next_open_dt = MarketClock.get_next_open_datetime()
            hrs = sec_to_open / 3600.0
            phase = MarketClock.get_session_phase()
            logger.info(f"Market is currently CLOSED ({phase} | {MarketClock.now_ist_str()}).")
            logger.info(f"Next trading session opens: {next_open_dt.strftime('%A %Y-%m-%d %H:%M:%S IST')}.")
            logger.info(f"Waiting {int(sec_to_open)}s ({hrs:.1f} hours) until market open...")
            while not MarketClock.is_market_open():
                sec = MarketClock.get_seconds_until_next_open()
                if sec <= 0:
                    break
                time.sleep(min(30.0, sec))
            logger.info("Market is OPEN (09:15:00 IST)! Commencing trading loop.")

        logger.info(
            f"Starting NIFTY Contextual AI loop: Signal Discovery={args.interval}s | Active Trailing Guard={args.trailing_interval}s..."
        )
        logger.info("Press Ctrl+C to terminate.")
        try:
            while True:
                # Check market open status (handles EOD transition to next morning cleanly)
                if (
                    args.wait_until_market_open
                    and not MarketClock.is_market_open()
                    and not args.ignore_feed_health
                ):
                    guard_started = time.monotonic()
                    unresolved, _ = trader.get_trades_state()
                    if unresolved or not trader.state_verified:
                        trader.run_monitor_cycle(unresolved)
                        time.sleep(cycle_sleep_delay(guard_started, args.trailing_interval))
                        continue
                    sec_to_open = MarketClock.get_seconds_until_next_open()
                    next_open_dt = MarketClock.get_next_open_datetime()
                    hrs = sec_to_open / 3600.0
                    phase = MarketClock.get_session_phase()
                    logger.info(
                        f"Market session ended / closed ({phase} | {MarketClock.now_ist_str()}). "
                        f"Next session opens: {next_open_dt.strftime('%A %Y-%m-%d %H:%M:%S IST')}. "
                        f"Entering hibernation for {hrs:.1f} hours ({int(sec_to_open)}s)..."
                    )
                    while not MarketClock.is_market_open():
                        sec = MarketClock.get_seconds_until_next_open()
                        if sec <= 0:
                            break
                        time.sleep(min(60.0, sec))
                    logger.info("Market is OPEN (09:15:00 IST)! Resuming trading loop.")

                cycle_started = time.monotonic()
                try:
                    res = trader.run_cycle(ignore_feed_health=args.ignore_feed_health)
                except Exception:
                    logger.exception(
                        "Cycle failed; retaining durable state and blocking entries until reconciliation"
                    )
                    trader.state_verified = False
                    res = {"has_open_trades": True}
                has_open = res.get("has_open_trades", False) if isinstance(res, dict) else False
                sleep_sec = args.trailing_interval if has_open else args.interval
                if has_open:
                    logger.info(
                        f"⚡ [FAST TRAILING GUARD] Active position in flight. Polling every {sleep_sec}s for continuous stop protection."
                    )
                delay = cycle_sleep_delay(cycle_started, sleep_sec)
                elapsed = time.monotonic() - cycle_started
                if elapsed > sleep_sec:
                    logger.warning(
                        "[MONITOR OVERRUN] work_sec=%.3f target_sec=%s; no catch-up backlog",
                        elapsed,
                        sleep_sec,
                    )
                time.sleep(delay)
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user.")
    finally:
        market = getattr(trader, "market_data", None)
        if market is not None and hasattr(market, "close"):
            try:
                market.close()
            except Exception:
                logger.warning("Market-data stream shutdown did not complete cleanly")
        if not trader.intelligence.stop_worker():
            logger.warning("Intelligence worker still finishing an in-flight request at shutdown")
