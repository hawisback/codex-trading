"""Single broker-funded lot policy for every trading strategy (POL-01).

Keep the existing callable signature for strategy/OMS compatibility, but
deprecate old strategy-local compounding milestones as live sizing inputs.
A missing or invalid capital policy returns zero rather than falling back
to a static funding assumption.
"""

from trading.domain.lot_policy import BrokerMarginLotPolicy


def calculate_compounding_quantity(
    available_margin: float,
    contract_price: float,
    *,
    strategy_cfg: dict,
    trading_cfg: dict,
    quantity: int,
    environ=None,
) -> int:
    """Return quantity based on verified broker margin and selected option price.

    Candidate selection uses the quoted option price as an estimate; OMS
    submission recomputes using the validated, final executable limit.
    No assumption about trading account equity or strategy name is applied.
    """
    try:
        policy = BrokerMarginLotPolicy.from_trading_config(trading_cfg)
    except (ValueError, TypeError, AttributeError):
        return 0
    return policy.quantity_for(available_margin, contract_price)
