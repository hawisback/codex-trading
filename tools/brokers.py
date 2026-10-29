"""Read-only native broker report: python -m tools.brokers --broker both."""

import argparse
import json

from trading.adapters.gateways.factory import create_execution_gateway


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
    reports = [inspect_broker(broker) for broker in brokers]
    print(json.dumps({"brokers": reports}, indent=2))
    return 0 if all(report["ready"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
