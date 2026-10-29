"""Inspect existing trading configuration without creating a trader or broker.

Usage: python -m tools.policy_report [--format json] [--validate-config]
The report is a diagnostic INVENTORY, not a live safety authorization.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from trading.policy_snapshot import build_policy_snapshot


ROOT = Path(__file__).resolve().parents[1]


def _invalid_json_constant(value: str) -> None:
    raise ValueError(f"non-finite numeric constant {value}")


def read_json(path: Path) -> dict:
    """Read only repository-owned configuration; reject malformed JSON for THIS report."""
    with path.open("r", encoding="utf-8") as stream:
        content = json.load(stream, parse_constant=_invalid_json_constant)
    if not isinstance(content, dict):
        raise ValueError("expected a JSON object")
    return content


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only policy source/provenance inventory (does NOT arm a broker)."
    )
    parser.add_argument("--strategy", help="Preview an existing strategy profile; never runs it")
    parser.add_argument("--ai-mode", help="Preview a consultation mode; never starts a consultation")
    parser.add_argument("--broker", choices=("proxy", "kite", "breeze"),
                        help="Preview execution selection; no broker object is created")
    parser.add_argument("--market-data-broker", choices=("kite", "breeze"),
                        help="Preview market-data selection; no network reads")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--validate-config", action="store_true",
                        help="Check a subset of inventoried fields only; not full runtime certification")
    args = parser.parse_args(argv)

    try:
        trading = read_json(ROOT / "config/trading.json")
        strategies = read_json(ROOT / "config/strategies.json")
        # Only these allowlisted nonsecret settings participate in the snapshot.
        environ = {key: os.environ[key] for key in (
            "STRATEGY_MODE", "AI_CONSULTATION_MODE", "EXECUTION_BROKER",
            "MARKET_DATA_BROKER",
        ) if key in os.environ}
        snapshot = build_policy_snapshot(
            trading, strategies, strategy=args.strategy, ai_mode=args.ai_mode,
            execution_broker=args.broker, market_data_broker=args.market_data_broker,
            environ=environ,
        )
    except (OSError, ValueError, TypeError) as exc:
        # Don't include user-provided JSON content or secrets in an error report.
        parser.exit(2, f"Cannot inspect configuration: {type(exc).__name__} (report only; live code unchanged)\n")

    if args.format == "json":
        print(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False, allow_nan=False))
    else:
        print("READ-ONLY trading policy INVENTORY; not broker authorization or full validation")
        print(f"Strategy: {snapshot.strategy_name} [{snapshot.strategy_source}]")
        print(f"Consultation mode: {snapshot.ai_mode} [{snapshot.ai_mode_source}]")
        print(f"Execution broker: {snapshot.execution_broker} [{snapshot.execution_broker_source}]")
        print(f"Market-data broker: {snapshot.market_data_broker} [{snapshot.market_data_broker_source}]")
        print(f"Inventory SHA256: {snapshot.inventory_sha256} (not a live effective-policy hash)")
        for field in snapshot.observations:
            print(f"\n{field.key} = {field.configured!r} [{field.source}]")
            print(f"  Observed code: {field.runtime_rule}")
            print(f"  Evidence: {field.runtime_source}")
            print(f"  Caveat: {field.assessment}")
        if snapshot.diagnostics:
            print("\nReview diagnostics:")
            for issue in snapshot.diagnostics:
                print(f"- {issue}")
    if args.validate_config:
        print("Validation scope: selected inventoried keys only, NOT every strategy or live preflight.",
              file=__import__("sys").stderr)
    return 1 if snapshot.diagnostics else 0


if __name__ == "__main__":
    raise SystemExit(main())
