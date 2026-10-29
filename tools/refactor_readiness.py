"""Read-only refactor release preflight: NEVER arms brokers or places orders.

This deliberately cannot output a READY verdict without separately supplied,
reviewed offline regression, broker UAT and operational sign-off evidence.
"""

import argparse
import json
from pathlib import Path

from trading.domain.limits import HARD_ENTRY_CUTOFF, HARD_SQUARE_OFF


def inspect_configuration(path: Path) -> dict:
    errors = []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Top-level JSON is not an object")
    except (OSError, ValueError, UnicodeError):
        return {
            "release_ready": False, "status": "CONFIG_UNREADABLE",
            "blockers": ["CONFIG_UNREADABLE"],
        }

    mode = data.get("mode")
    session = data.get("session", {})
    r01 = data.get("r01_policy", {})
    if mode not in ("LIVE", "PAPER"):
        errors.append("MODE_UNRECOGNIZED")
    if not isinstance(session, dict):
        errors.append("SESSION_POLICY_INVALID")
    else:
        if session.get("no_new_trade_after") != HARD_ENTRY_CUTOFF:
            errors.append("ENTRY_CUTOFF_MISMATCH")
        if session.get("force_exit_time") != HARD_SQUARE_OFF:
            errors.append("SQUAREOFF_TIME_MISMATCH")
    if not isinstance(r01, dict) or type(r01.get("enabled")) is not bool:
        errors.append("R01_FLAG_INVALID")
    elif r01["enabled"] is True:
        errors.append("R01_ENABLED_REQUIRES_BROKER_UAT")
    errors.extend((
        "REGRESSION_EVIDENCE_NOT_PROVIDED",
        "BROKER_CONFORMANCE_EVIDENCE_NOT_PROVIDED",
        "OMS_CRASH_RECOVERY_EVIDENCE_NOT_PROVIDED",
        "SUPERVISED_LIVE_APPROVAL_NOT_PROVIDED",
    ))
    return {
        "release_ready": False,
        "status": "BLOCKED",
        "mode_configured": mode,
        "r01_enabled": r01.get("enabled") if isinstance(r01, dict) else None,
        "blockers": errors,
        "note": "Read-only report; no broker, AI, filesystem mutations or trading performed.",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Read-only safety preflight; never arms LIVE trading")
    parser.add_argument("--trading-config", type=Path,
                        default=Path("config/trading.json"))
    args = parser.parse_args(argv)
    print(json.dumps(inspect_configuration(args.trading_config), indent=2))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
