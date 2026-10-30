"""Read-only native broker report: python -m tools.brokers --broker both."""

import argparse
import json
from pathlib import Path

from trading.adapters.gateways.factory import create_execution_gateway
from trading.domain.pretrade_evidence import entry_control_block

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/trading.json"


def inspect_configuration(path=CONFIG_PATH):
    """Report only public execution controls; never arm a gateway or infer runtime state."""
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("Configuration must be an object")
        r01 = config.get("r01_policy")
        if not isinstance(r01, dict):
            r01 = {}
        errors = []
        mode = config.get("mode")
        if mode not in ("LIVE", "PAPER"):
            errors.append("MODE_INVALID")
            mode = None
        controls = {}
        for key in ("auto_trade_enabled", "system_armed", "kill_switch"):
            value = config.get(key)
            controls[key] = value if type(value) is bool else None
            if type(value) is not bool:
                errors.append(key.upper() + "_INVALID")
        policy = {}
        for key in ("enabled", "unified_stop_enabled"):
            value = r01.get(key)
            policy[key] = value if type(value) is bool else None
            if type(value) is not bool:
                errors.append("R01_" + key.upper() + "_INVALID")
        if policy["enabled"] is True and policy["unified_stop_enabled"] is not True:
            errors.append("R01_UNIFIED_STOP_REQUIRED")
        blocked = entry_control_block(config)
        if errors:
            blocked = "CONFIGURATION_INVALID"
        elif mode != "LIVE":
            blocked = "CONFIGURED_MODE_NOT_LIVE"
        return {
            "valid": not errors,
            "configured_mode": mode,
            **controls,
            "r01_policy": policy,
            "new_entries_enabled_by_config": blocked is None,
            "entry_block_reason": blocked,
            "errors": errors,
        }
    except (OSError, ValueError, UnicodeError):
        # Do not echo file contents or parser errors, which may contain secrets.
        return {"valid": False, "errors": ["CONFIGURATION_UNREADABLE"]}


def inspect_broker(broker):
    try:
        gateway = create_execution_gateway(broker)
        status = gateway.get_status()
        if status.get("error") or not status.get("connected"):
            return {"broker": broker, "ready": False, "error": status.get("detail", "BROKER_UNAVAILABLE")}
        funds = gateway.get_funds()
        positions = gateway.get_positions()
        orders = gateway.get_orders()
        responses = {"funds": funds, "positions": positions, "orders": orders}
        errors = [name for name, response in responses.items() if response.get("error")]
        return {
            "broker": broker,
            "ready": not errors,
            "ready_scope": "BROKER_READS_ONLY",
            "mode_scope": "DIAGNOSTIC_GATEWAY_ONLY",
            "mode": status["mode"],
            "live_authorized": status["live_authorized"],
            "available_margin": funds.get("available_margin"),
            "open_positions": len(positions["positions"]) if "positions" in positions else None,
            "orders": len(orders["orders"]) if "orders" in orders else None,
            "failed_reads": errors,
        }
    except Exception:
        # Configuration and broker exception messages can contain credentials.
        return {"broker": broker, "ready": False, "error": "BROKER_DIAGNOSTIC_FAILED"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", choices=("kite", "breeze", "both"), default="both")
    args = parser.parse_args(argv)
    brokers = ("kite", "breeze") if args.broker == "both" else (args.broker,)
    configuration = inspect_configuration()
    reports = [inspect_broker(broker) for broker in brokers]
    print(
        json.dumps(
            {
                "read_only": True,
                "configuration": configuration,
                "scheduler_execution_status": "NOT_OBSERVED",
                "note": "Broker mode/live_authorized describe this command's new unarmed diagnostic gateway, "
                "not a running scheduler. Configured LIVE does not arm this gateway.",
                "brokers": reports,
            },
            indent=2,
        )
    )
    return 0 if configuration["valid"] and all(report["ready"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
