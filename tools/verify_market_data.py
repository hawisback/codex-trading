"""Strict read-only schema, type and broker-header verification; no trader is started."""

import argparse
import hashlib
import io
import json
import math
import unittest
import urllib.request
from urllib.parse import urlsplit
from unittest.mock import patch

from market_clock import MarketClock
from trading.adapters.market_data import create_market_data
from trading.adapters.market_sources import MarketDataError, workspace_file
from trading.application.market_context import MarketContextService
from trading.bootstrap import ensure_environment
from trading.domain.market_contracts import ContractError, SCHEMAS, validate_market_contract
from tools.checks import forbid_network
from tools.after_hours_market import verify_after_hours


def verify_offline():
    with forbid_network() as attempts:
        suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_api_contracts")
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)
    return dict(
        passed=result.wasSuccessful() and not attempts,
        tests=result.testsRun,
        unexpected_network_attempts=len(attempts),
        failures=[test.id() for test, _ in result.failures + result.errors],
    )


def missing_configuration(provider):
    source = provider.source
    if source.broker_name == "kite":
        stream = getattr(source, "stream", None)
        fields = (
            {"KITE_API_KEY": stream.api_key, "KITE_ACCESS_TOKEN": stream.access_token}
            if stream is not None and stream.transport == "connect"
            else {"KITE_API_KEY": source.api_key, "KITE_ACCESS_TOKEN": source.access_token}
            if getattr(source, "transport", "web") == "connect"
            else {"KITE_ENCTOKEN": source.enctoken, "KITE_ACCOUNT_ID": source.user_id}
        )
    else:
        gateway = source.gateway
        fields = {
            "BREEZE_API_KEY": gateway.api_key,
            "BREEZE_API_SECRET": gateway.api_secret,
            "BREEZE_API_SESSION": gateway.api_session,
            "BREEZE_ACCOUNT_ID": gateway.account_id,
        }
    return [key for key, value in fields.items() if not value]


class BrokerHeaderObserver:
    """Inspect actual REST traffic without recording credential values or response bodies."""

    def __init__(self, opener):
        self.opener, self.provider = opener, None
        self.verified, self.failures = 0, []

    def __call__(self, request, *args, **kwargs):
        try:
            if request.get_method() != "GET":
                raise ContractError("Diagnostic only permits GET")
            url = urlsplit(request.full_url)
            headers = {key.lower(): value for key, value in request.header_items()}
            master = url.hostname == "api.kite.trade" and url.path == "/instruments/NFO"
            if not master:
                if headers.get("accept") != "application/json":
                    raise ContractError("Broker Accept header mismatch")
                source = self.provider.source
                if source.broker_name == "kite":
                    stream = getattr(source, "stream", None)
                    connect_stream = stream is not None and stream.transport == "connect"
                    connect = getattr(source, "transport", "web") == "connect" or connect_stream
                    host = "api.kite.trade" if connect else "kite.zerodha.com"
                    auth = (
                        f"token {stream.api_key if connect_stream else source.api_key}:{stream.access_token if connect_stream else source.access_token}"
                        if connect
                        else "enctoken " + source.enctoken
                    )
                    if (
                        url.hostname != host
                        or headers.get("x-kite-version") != "3"
                        or headers.get("authorization") != auth
                    ):
                        raise ContractError("Kite destination, version or authentication header mismatch")
                else:
                    if (
                        url.hostname != "api.icicidirect.com"
                        or headers.get("content-type") != "application/json"
                    ):
                        raise ContractError("Breeze destination or Content-Type mismatch")
                    if not url.path.endswith("/customerdetails"):
                        gateway = source.gateway
                        checksum = hashlib.sha256(
                            headers.get("x-timestamp", "").encode()
                            + (request.data or b"")
                            + gateway.api_secret.encode()
                        ).hexdigest()
                        if (
                            headers.get("x-appkey") != gateway.api_key
                            or headers.get("x-sessiontoken") != gateway._session_token
                            or headers.get("x-checksum") != "token " + checksum
                        ):
                            raise ContractError("Breeze signed authentication headers mismatch")
            response = self.opener(request, *args, **kwargs)
            allowed = (
                ("text/csv", "text/plain", "application/octet-stream", "application/csv")
                if master
                else ("application/json",)
            )
            if response.status != 200 or response.headers.get_content_type() not in allowed:
                response.close()
                raise ContractError("Broker response status or Content-Type mismatch")
            self.verified += 1
            return response
        except ContractError as exc:
            self.failures.append(str(exc))
            raise


def probe_option_depth(provider, options, timeout):
    """Check the ATM call using the provider's normal entry-read budget.

    The first strike can be deep ITM and unrepresentative of candidate depth.
    Pacing is included in the read budget; the provider still enforces the
    executable quote's unchanged identity, age, tick and liquidity checks.
    """
    atm = options["atm_strike"]
    strike = min(options["strikes"], key=lambda row: abs(row["strike"] - atm))
    return provider.get_contract_quote(strike["call"]["instrument_id"], timeout_sec=min(3.0, timeout))


def verify_live(broker, timeout, *, after_hours=False):
    rows, payloads = [], {}
    observer = BrokerHeaderObserver(urllib.request.urlopen)
    with patch("urllib.request.urlopen", side_effect=observer):
        provider = create_market_data(broker)
        observer.provider = provider
        try:
            missing = missing_configuration(provider)
            if missing:
                return dict(
                    broker=provider.source.broker_name,
                    passed=False,
                    missing_configuration=missing,
                    checks=[
                        dict(name=name, status="BLOCKED", reason="Missing broker configuration")
                        for name in (*SCHEMAS, "engine_consumer", "broker_rest_headers")
                    ],
                )
            if after_hours:
                return verify_after_hours(provider, observer, timeout)
            reads = {
                "data_quality": lambda: provider.get_data_quality(timeout=timeout),
                "snapshot": lambda: provider.get_snapshot(timeout=timeout),
                "candles_1m": lambda: provider.get_candles("1m", 375, timeout=timeout),
                "candles_5m": lambda: provider.get_candles("5m", 50, timeout=timeout),
                "technicals_5m": lambda: provider.get_technicals("5m", 50, timeout=timeout),
                "options": lambda: provider.get_options(10, timeout=timeout),
                "heavyweights": lambda: provider.get_heavyweights(timeout=timeout),
                "vix": lambda: provider.get_vix(timeout=timeout),
                "sectors": lambda: provider.get_sectors(timeout=timeout),
            }

            def book():
                if "options" not in payloads:
                    raise MarketDataError("Option chain unavailable")
                return probe_option_depth(provider, payloads["options"], timeout)

            reads["option_depth"] = book
            for name, read in reads.items():
                try:
                    payload = read()
                    if payload.get("error") or (name == "data_quality" and not payload.get("quote_ready")):
                        raise MarketDataError("Broker capability unavailable")
                    validate_market_contract(name, payload)
                    payloads[name] = payload
                    rows.append(dict(name=name, status="PASS"))
                except ContractError as exc:
                    rows.append(dict(name=name, status="FAIL", reason=str(exc)))
                except Exception:
                    rows.append(dict(name=name, status="BLOCKED", reason="Broker data unavailable"))
            try:
                if any(row["status"] != "PASS" for row in rows):
                    raise MarketDataError("A required capability is unverified")
                ctx = MarketContextService(provider, lambda: {}).fetch()
                candles = ctx["candles_1m"]
                expected = round(
                    sum((b["high"] + b["low"] + b["close"]) / 3 for b in candles) / len(candles), 2
                )
                if ctx["session_vwap"] != expected or ctx["session_vwap_basis"] != "NIFTY_SPOT_INTRADAY":
                    raise ContractError("Engine spot VWAP formula mismatch")
                if not all(
                    type(ctx[key]) in (int, float) and math.isfinite(ctx[key])
                    for key in (
                        "spot",
                        "ema_9",
                        "ema_20",
                        "ema_50",
                        "rsi_14",
                        "macd",
                        "box_high_15m",
                        "box_low_15m",
                    )
                ):
                    raise ContractError("Engine context requires finite numeric values")
                rows.append(dict(name="engine_consumer", status="PASS"))
            except ContractError as exc:
                rows.append(dict(name="engine_consumer", status="FAIL", reason=str(exc)))
            except Exception:
                rows.append(
                    dict(name="engine_consumer", status="BLOCKED", reason="Complete live context unavailable")
                )
            rows.append(
                dict(
                    name="broker_rest_headers",
                    status="FAIL" if observer.failures else ("PASS" if observer.verified else "BLOCKED"),
                    verified_responses=observer.verified,
                    failures=observer.failures,
                )
            )
            return dict(
                broker=provider.source.broker_name,
                passed=all(row["status"] == "PASS" for row in rows),
                checks=rows,
            )
        finally:
            provider.close()


def main(argv=None):
    ensure_environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker", choices=("kite", "breeze", "both"), default=None)
    parser.add_argument(
        "--offline", action="store_true", help="Only fixture schemas/types and broker request headers"
    )
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument(
        "--after-hours",
        action="store_true",
        help="Check closed-market REST data without claiming live freshness",
    )
    parser.add_argument("--report", default="logs/api_contract_verification.json")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("Timeout must be finite and positive")
    if args.after_hours and (args.offline or MarketClock.is_market_open()):
        parser.error("--after-hours requires a closed market and cannot be combined with --offline")
    report_path = workspace_file(args.report)
    offline = verify_offline()
    live = (
        []
        if args.offline
        else [
            verify_live(broker, args.timeout, after_hours=args.after_hours)
            for broker in (("kite", "breeze") if args.broker == "both" else (args.broker,))
        ]
    )
    passed = offline["passed"] and (args.offline or all(result["passed"] for result in live))
    report = dict(
        timestamp=MarketClock.now_ist().isoformat(),
        scope="offline"
        if args.offline
        else "offline_and_after_hours"
        if args.after_hours
        else "offline_and_live",
        passed=passed,
        live_verified=not args.after_hours and bool(live) and all(result["passed"] for result in live),
        offline=offline,
        live=live,
        limits=[
            "In-process calls have no HTTP headers; broker REST headers are checked separately.",
            "WebSocket handshake headers, order execution and future broker behavior are outside this report.",
        ],
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    print(
        f"[{'PASS' if offline['passed'] else 'FAIL'}] Offline contract/type/header tests: {offline['tests']}"
    )
    for result in live:
        mode = "after-hours" if args.after_hours else "live"
        print(f"[{'PASS' if result['passed'] else 'NOT VERIFIED'}] {result['broker']} {mode} checks")
        if result.get("missing_configuration"):
            print("  Missing: " + ", ".join(result["missing_configuration"]))
        for row in result["checks"]:
            print(f"  {row['status']}: {row['name']}")
    print("Live verification: " + ("PASS" if report["live_verified"] else "NOT COMPLETE"))
    print("Report: " + str(report_path))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
