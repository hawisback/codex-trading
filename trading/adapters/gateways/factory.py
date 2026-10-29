"""Broker Execution Gateway Factory.

Instantiates native Kite, native Breeze, or the existing proxy.
"""

import logging
import os
from typing import Optional

from execution_client import AIExecutionClient
from trading.adapters.gateways.kite import KiteExecutionGateway
from trading.adapters.gateways.breeze import BreezeExecutionGateway
from trading.ports import ExecutionGateway

logger = logging.getLogger("GatewayFactory")


def create_execution_gateway(
    broker: str = "proxy",
    *,
    api_key: Optional[str] = None,
    api_secret: Optional[str] = None,
    access_token: Optional[str] = None,
    api_session: Optional[str] = None,
    account_id: Optional[str] = None,
    journal_path=None,
    **kwargs,
) -> ExecutionGateway:
    """Factory to create the designated execution gateway.

    Args:
        broker: Broker name ('kite', 'breeze', 'proxy'). Defaults to 'proxy'.
        api_key: Optional broker API key.
        api_secret: Optional Breeze API secret (not used by Kite).
        access_token: Optional broker session token.
        api_session: Explicit Breeze login API_Session (alias of access_token).
        account_id: Optional account identifier.
        **kwargs: Additional parameters passed to the gateway constructor.

    Returns:
        Instance implementing ExecutionGateway protocol.
    """
    broker_norm = (broker or os.getenv("EXECUTION_BROKER", "proxy")).lower().strip()

    if broker_norm == "kite":
        logger.info("[GatewayFactory] Creating native KiteExecutionGateway")
        return KiteExecutionGateway(
            api_key=api_key,
            access_token=access_token,
            account_id=account_id,
            journal_path=journal_path,
            **kwargs,
        )
    elif broker_norm == "breeze":
        if api_session and access_token and api_session != access_token:
            raise ValueError("Conflicting Breeze API session arguments")
        logger.info("[GatewayFactory] Creating native BreezeExecutionGateway")
        return BreezeExecutionGateway(
            api_key=api_key,
            api_secret=api_secret,
            api_session=api_session or access_token,
            account_id=account_id,
            journal_path=journal_path,
            **kwargs,
        )
    elif broker_norm in ("proxy", "api", "local"):
        logger.info("[GatewayFactory] Creating AIExecutionClient (HTTP proxy to port 8000)")
        return AIExecutionClient(**kwargs)
    else:
        raise ValueError(f"Unsupported broker gateway: '{broker}'. Options: 'kite', 'breeze', 'proxy'")
