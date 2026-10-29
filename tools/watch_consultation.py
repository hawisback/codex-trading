#!/usr/bin/env python3
"""Wake the IDE once for an active entry or stop consultation, including on restart.

Rearm after submitting each verdict. Existing, unexpired requests are detected
immediately so a fill during watcher restart cannot be missed.
"""

import json
import math
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PENDING_FILE = PROJECT_ROOT / "logs" / "pending_consultation.json"
PENDING_SL_FILE = PROJECT_ROOT / "logs" / "pending_stop_loss.json"


def read_pending(path, expected_status):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("status") != expected_status or not isinstance(data.get("dossier"), dict):
            return None
        created = datetime.fromisoformat(data["created_at"])
        timeout = float(data["timeout_seconds"])
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
        if not math.isfinite(timeout) or timeout <= 0:
            return None
        age = (datetime.now(timezone.utc) - created).total_seconds()
        if not 0 <= age < timeout:
            return None
        if expected_status == "AWAITING_STOP_LOSS" and not (data.get("request_id") and data.get("trade_id")):
            return None
        if expected_status == "AWAITING_VERDICT" and not (data.get("request_id") and data.get("candidate_id")):
            return None
        return data
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def watch(timeout_seconds=21600):
    deadline = time.monotonic() + timeout_seconds
    print(f"[{time.strftime('%H:%M:%S')}] Antigravity AI Companion Watcher ARMED.")
    print(f"Monitoring entry: {PENDING_FILE}\nMonitoring stop-loss: {PENDING_SL_FILE}", flush=True)
    while time.monotonic() < deadline:
        # Stop consultations concern existing exposure and take priority on restart.
        for path, expected in ((PENDING_SL_FILE, "AWAITING_STOP_LOSS"), (PENDING_FILE, "AWAITING_VERDICT")):
            data = read_pending(path, expected)
            if data is None:
                continue
            dossier = data["dossier"]
            if expected == "AWAITING_STOP_LOSS":
                print("\n>>> POST-FILL STOP-LOSS CONSULTATION REQUIRED <<<")
                print(f"Trade: {data['trade_id']} | Instrument: {dossier.get('symbol', 'UNKNOWN')}")
                print(f"Stop-Loss Dossier: {PENDING_SL_FILE.with_suffix('.md')}")
                print(
                    "Submit via: python ai_consultant.py --set-sl <PRICE> --invalidation <SPOT> "
                    f"--request-id {data['request_id']}"
                )
            else:
                print("\n>>> ENTRY CANDIDATE DETECTED <<<")
                print(f"Signal: BUY_{dossier.get('direction', 'UNKNOWN')} {dossier.get('strike', 0)}")
                print(f"Consultation File: {PENDING_FILE}")
                print(f"Submit: python ai_consultant.py --approve --request-id {data['request_id']} --reason <RATIONALE>")
                print("Use --veto to reject. Read config/rules_playbook.md before deciding.")
            print("Rearm: python tools/watch_consultation.py after submitting this verdict.", flush=True)
            return 0
        time.sleep(0.5)
    print(f"Watcher timed out after {timeout_seconds}s.")
    return 1


if __name__ == "__main__":
    sys.exit(watch())
