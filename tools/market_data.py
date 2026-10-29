"""Read-only six-capability preflight: python -m tools.market_data --broker kite|breeze."""

import argparse
import json

from trading.adapters.market_data import create_market_data
from trading.bootstrap import ensure_environment


def inspect_market_data(provider, timeout=60):
    reports = []
    reads = (
        ("data_quality", lambda: provider.get_data_quality(timeout=timeout)),
        ("snapshot", lambda: provider.get_snapshot(timeout=timeout)),
        ("candles_1m", lambda: provider.get_candles("1m", 375, timeout=timeout)),
        ("candles_5m", lambda: provider.get_candles("5m", 50, timeout=timeout)),
        ("technicals_5m", lambda: provider.get_technicals(timeout=timeout)),
        ("options", lambda: provider.get_options(timeout=timeout)),
        ("heavyweights", lambda: provider.get_heavyweights(timeout=timeout)),
        ("vix", lambda: provider.get_vix(timeout=timeout)),
        ("sectors", lambda: provider.get_sectors(timeout=timeout)),
    )
    for name, read in reads:
        try:
            result = read()
            ready = result.get("quote_ready", True)
            if "candles" in result:
                detail = {"count": len(result["candles"])}
            elif "strikes" in result:
                detail = {"count": len(result["strikes"]), "expiry": result["expiry"]}
            elif "stocks" in result:
                detail = {"count": len(result["stocks"])}
            else:
                detail = result
            reports.append(dict(capability=name, ready=ready, detail=detail))
        except Exception:
            reports.append(dict(capability=name, ready=False, error="MARKET_DATA_UNAVAILABLE"))
    try:
        chain = provider.get_options(strike_window=0, timeout=timeout)
        identity = chain["strikes"][0]["call"]["instrument_id"]
        quote = provider.get_contract_quote(identity, timeout_sec=min(timeout, 1.0))
        reports.append(
            dict(
                capability="option_depth",
                ready=not quote.get("error", False),
                detail={"status": quote.get("status")},
            )
        )
    except Exception:
        reports.append(dict(capability="option_depth", ready=False, error="OPTION_DEPTH_UNAVAILABLE"))
    return {
        "broker": provider.source.broker_name,
        "ready": all(r["ready"] for r in reports),
        "capabilities": reports,
    }


def main(argv=None):
    ensure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", choices=("kite", "breeze"), default=None)
    parser.add_argument("--timeout", type=float, default=60, help="Read budget per capability in seconds")
    args = parser.parse_args(argv)
    if args.timeout <= 0:
        parser.error("Timeout must be positive")
    provider = create_market_data(args.broker)
    try:
        report = inspect_market_data(provider, args.timeout)
        print(json.dumps(report, indent=2, allow_nan=False))
        return 0 if report["ready"] else 1
    finally:
        provider.close()


if __name__ == "__main__":
    raise SystemExit(main())
