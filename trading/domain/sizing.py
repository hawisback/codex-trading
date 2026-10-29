"""Current compounding and quantity policy; values are deliberately unchanged."""

import os
from trading.domain.limits import FEE_RESERVE, LOT_SIZE
from trading.domain.owner_ladder import owner_ladder_decision


def calculate_compounding_quantity(
    available_margin: float,
    contract_price: float,
    *,
    strategy_cfg: dict,
    trading_cfg: dict,
    quantity: int,
    environ=None,
) -> int:
    """
    Calculate dynamic order quantity based on Step-Ladder Milestone Compounding:
    - Evaluates verified broker available margin against milestone brackets.
    - De-escalates safely during drawdowns to protect principal.
    - Enforces strict margin buffer (₹150 for statutory fees/STT).
    - Respects maximum lots cap and broker platform single-order ceiling (default 65 contracts / 1 lot)
      to ensure 100% compatibility with broker execution limits (avoids QUANTITY_LIMIT_EXCEEDED).
    """
    comp_cfg = strategy_cfg.get("compounding", {})
    platform_max_qty = int(
        comp_cfg.get("max_order_quantity")
        or trading_cfg.get("risk", {}).get("max_order_quantity")
        or (os.environ if environ is None else environ).get("MAX_ORDER_QUANTITY", 65)
    )

    if not comp_cfg.get("enabled", False):
        return min(quantity, platform_max_qty)

    # Explicit opt-in only. No existing strategy currently selects this mode.
    # available_margin is broker-verified at entry submission, and contract_price
    # is the approved limit computed from a fresh executable option quote.
    if comp_cfg.get("mode") == "owner_capital_ladder_v1":
        return owner_ladder_decision(
            available_margin,
            contract_price,
            max_lots_cap=comp_cfg.get("max_lots_cap", 10),
            max_order_quantity=platform_max_qty,
        ).quantity

    milestones = comp_cfg.get(
        "milestones",
        [
            {"min_capital": 0.0, "lots": 1},
            {"min_capital": 20000.0, "lots": 1},
            {"min_capital": 40000.0, "lots": 1},
            {"min_capital": 70000.0, "lots": 1},
            {"min_capital": 100000.0, "lots": 1},
        ],
    )
    max_lots_cap = int(comp_cfg.get("max_lots_cap", 1))

    # 1. Determine target lots from highest qualified capital milestone
    target_lots = 1
    for m in sorted(milestones, key=lambda x: x["min_capital"], reverse=True):
        if available_margin >= float(m["min_capital"]):
            target_lots = int(m["lots"])
            break

    target_lots = min(target_lots, max_lots_cap)

    # 2. Reconcile with actual purchasing power (Zero-Shortfall margin check)
    lot_size = LOT_SIZE
    cost_per_lot = float(contract_price or 100.0) * lot_size
    safe_cash = max(0.0, float(available_margin or 0.0) - FEE_RESERVE)

    if cost_per_lot > 0:
        affordable_lots = int(safe_cash // cost_per_lot)
        effective_lots = min(target_lots, affordable_lots)
    else:
        effective_lots = target_lots

    # Minimum 1 lot if affordable, else effective_lots
    final_lots = (
        max(1, effective_lots) if (cost_per_lot > 0 and safe_cash >= cost_per_lot) else effective_lots
    )
    calculated_qty = final_lots * lot_size
    return min(calculated_qty, platform_max_qty)
