"""Process-exit simulation for gateways backed exclusively by offline transports."""


def end_gateway_process(gateway):
    """Disarm a fixture and release the OS lease as process termination would.

    Production deliberately retains its lease when switching to PAPER. Restart
    tests must end the old simulated process before arming its replacement.
    This helper is only for fixtures; it does not reconcile broker exposure.
    """
    gateway.set_mode("PAPER")
    lease = gateway._account_lease
    if lease is not None:
        lease.__exit__(None, None, None)
        gateway._account_lease = None
        gateway._leased_account = None
