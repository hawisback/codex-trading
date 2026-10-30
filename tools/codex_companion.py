"""Persistent Codex companion for chat-mode entry and stop consultations.

Run --check or --self-test first. Neither consumes the live consultation inbox.
Normal worker startup publishes validated judgments only; the OMS owns orders.
"""

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import threading
import time

from execution_safety import SchedulerLock
from market_clock import MarketClock
from trading.adapters.codex_judgment import CodexJudgment
from trading.application.companion_worker import CompanionWorker, read_json
from trading.domain.companion_contract import (
    judgment_schema,
    pending_consultation,
    strict_json,
    validate_judgment,
)

ROOT = Path(__file__).resolve().parents[1]


def check(root, backend):
    trading = read_json(root / "config/trading.json")
    strategies = read_json(root / "config/strategies.json")
    policy_ready = (
        trading["risk"]["option_hard_stop_pct"] == 25
        and strategies["strategies"]["macd_momentum"]["exit"]["initial_stop_pct"] == 25
        and strategies["ai_consultation"]["timeout_seconds"] == 45
        and trading["execution"]["ai_approval_ttl_seconds"] == 15
    )
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    auth = subprocess.run(
        [backend.executable, "login", "status"],
        capture_output=True,
        timeout=10,
        text=True,
        creationflags=flags,
    )
    logged_in = auth.returncode == 0 and "ChatGPT" in auth.stdout + auth.stderr
    version = subprocess.run(
        [backend.executable, "--version"], capture_output=True, timeout=10, text=True, creationflags=flags
    )
    report = dict(
        ready=bool(policy_ready and logged_in and version.returncode == 0),
        codex_version=version.stdout.strip(),
        chatgpt_login_verified=logged_in,
        policy_ready=policy_ready,
        consultation_seconds=45,
        approval_ttl_seconds=15,
        initial_stop_pct=25,
        live_orders_executed=False,
    )
    return report


def self_test(root, backend):
    """A nontradable canary: invoke Codex, never read/write live inbox files."""
    now = MarketClock.now_ist()
    payload = dict(
        status="AWAITING_VERDICT",
        request_id="SYNTHETIC_TRANSPORT_TEST",
        candidate_id="SYNTHETIC_NOT_A_TRADE",
        created_at=now.isoformat(),
        timeout_seconds=45,
        dossier={"synthetic": True, "do_not_trade": True},
        authoritative_risk_policy={"initial_stop_pct": 25, "synthetic_only": True},
        evaluation_rubric="Transport canary only. Always return VETOED. No market evaluation or order is requested.",
    )
    request = pending_consultation("ENTRY", payload, now)
    worker = CompanionWorker(root, backend)
    try:
        packet, _ = worker.packet(request)
        started = time.monotonic()
        raw = backend.generate(packet, judgment_schema("ENTRY"), started + 43, threading.Event())
        result = validate_judgment(request, strict_json(raw))
        return dict(
            passed=result["action"] == "VETOED",
            elapsed_seconds=round(time.monotonic() - started, 3),
            synthetic_only=True,
            live_inbox_consumed=False,
            verdict_published=False,
            live_orders_executed=False,
        )
    finally:
        worker.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="Check CLI login/config only; no inference/inbox processing"
    )
    mode.add_argument(
        "--self-test", action="store_true", help="Run a nontradable model canary; never publish a verdict"
    )
    parser.add_argument("--codex", default="codex", help="Installed Codex CLI executable")
    parser.add_argument(
        "--model", default=None, help="Optional explicit model; otherwise use the CLI default"
    )
    parser.add_argument("--poll-seconds", type=float, default=0.2)
    parser.add_argument(
        "--run-seconds", type=float, default=None, help="Optional worker lifetime; default stays armed"
    )
    args = parser.parse_args(argv)
    if not math.isfinite(args.poll_seconds) or not 0 < args.poll_seconds <= 1:
        parser.error("Poll interval must be positive and at most one second")
    if args.run_seconds is not None and (not math.isfinite(args.run_seconds) or args.run_seconds <= 0):
        parser.error("Worker duration must be finite and positive")
    try:
        backend = CodexJudgment(ROOT, executable=args.codex, model=args.model)
        readiness = check(ROOT, backend)
        print(json.dumps(readiness, indent=2), flush=True)
        if not readiness["ready"]:
            return 2
        if args.check:
            return 0
        if args.self_test:
            report = self_test(ROOT, backend)
            destination = ROOT / ".tools/tmp/codex-companion-selftest.json"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print(json.dumps(report, indent=2), flush=True)
            return 0 if report["passed"] else 2
        with SchedulerLock(ROOT / "logs/codex_companion.lock"):
            worker = CompanionWorker(ROOT, backend)
            print(
                "Codex companion ARMED: entry and stop requests; application owns verdict publication.",
                flush=True,
            )
            deadline = time.monotonic() + args.run_seconds if args.run_seconds else float("inf")
            try:
                while time.monotonic() < deadline:
                    worker.tick()
                    time.sleep(args.poll_seconds)
            finally:
                worker.close()
        return 0
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        # Never echo credentials, dossiers or raw model output into diagnostics.
        print(json.dumps({"status": "FAILED_CLOSED", "error_type": type(exc).__name__}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
