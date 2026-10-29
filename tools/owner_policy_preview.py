"""Read-only CLI to preview owner lot bands without broker/API/order access.

Example:
python -m tools.owner_policy_preview --capital-basis available_margin \
  --bracket-capital 80000 --available-margin 80000 \
  --executable-option-ask 100 --lot-size 65 --broker-order-limit 650
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json

from trading.domain.owner_lot_policy import preview_owner_lot_ceiling


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="OFFLINE R01 sizing preview, never order authorization")
    parser.add_argument("--capital-basis", required=True, choices=("available_margin", "account_equity"),
                        help="Explicit preview choice; live owner policy basis remains unresolved")
    parser.add_argument("--bracket-capital", required=True,
                        help="Broker-derived capital used for ladder lookup; manually supplied for preview")
    parser.add_argument("--available-margin", required=True,
                        help="Broker available purchasing power; manually supplied for preview")
    parser.add_argument("--executable-option-ask", required=True,
                        help="Fresh executable option ASK/approved limit premium, NOT NIFTY spot or historical LTP")
    parser.add_argument("--lot-size", required=True, type=int,
                        help="Contract lot size confirmed from instrument master (e.g. 65 for current reference)")
    parser.add_argument("--broker-order-limit", required=True, type=int,
                        help="Broker-verified maximum contracts per single order; no order splitting")
    args = parser.parse_args(argv)

    preview = preview_owner_lot_ceiling(
        capital_basis=args.capital_basis,
        bracket_capital=args.bracket_capital,
        available_margin=args.available_margin,
        executable_option_ask=args.executable_option_ask,
        lot_size=args.lot_size,
        broker_single_order_quantity_limit=args.broker_order_limit,
    )
    print("OFFLINE POLICY PREVIEW ONLY. Not an approval or a recommendation to trade.")
    print("No broker verification, quote freshness, AI consultation, P&L guard, or OMS risk gate was performed.")
    print(json.dumps(asdict(preview), indent=2))
    return 0 if preview.blocked_reason is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
