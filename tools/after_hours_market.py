"""Read-only closed-market schema checks; never relax the engine's freshness gates."""

import math
import time

from market_clock import MarketClock
from trading.adapters.market_sources import HEAVYWEIGHTS, SECTORS, SPOT, VIX, ReadBudget, MarketDataError
from trading.domain.market_contracts import ContractError, validate_market_contract
from trading.domain.market_data import (
    completed_spot_bars,
    exchange_time,
    number,
    resample_five_minutes,
    technical_metrics,
)


def _index(symbol, quote):
    price, close = number(quote["last_price"], minimum=0.01), number(quote["close"], minimum=0.01)
    return dict(
        symbol=symbol,
        last_price=price,
        change_pct=round((price / close - 1) * 100, 4),
        timestamp=exchange_time(quote["timestamp"]).isoformat(),
    )


def verify_after_hours(provider, observer, timeout):
    if MarketClock.is_market_open():
        raise ValueError("After-hours diagnostics are only available while the market is closed")
    if provider.source.broker_name != "kite":
        return dict(
            broker=provider.source.broker_name,
            passed=False,
            checks=[
                dict(
                    name="after_hours",
                    status="BLOCKED",
                    reason="Closed-market REST diagnostics currently support Kite",
                )
            ],
        )
    source = provider.source
    if source.stream is not None:
        return dict(
            broker="kite",
            passed=False,
            checks=[
                dict(
                    name="after_hours",
                    status="BLOCKED",
                    reason="Use MARKET_DATA_STREAMING=off for closed-market REST diagnostics",
                )
            ],
        )
    rows, payloads, state = [], {}, {}

    def check(name, read, schema=None):
        try:
            payload, detail = read()
            if schema:
                validate_market_contract(schema, payload, require_live=False)
                payloads[schema] = payload
            rows.append(dict(name=name, status="PASS", detail=detail))
        except ContractError as exc:
            rows.append(dict(name=name, status="FAIL", reason=str(exc)))
        except MarketDataError as exc:
            rows.append(dict(name=name, status="BLOCKED", reason=str(exc)))
        except Exception:
            rows.append(dict(name=name, status="BLOCKED", reason="Broker data unavailable"))

    def profile():
        result = source._get("/user/profile", {}, ReadBudget(timeout))
        if result.get("user_id") != source.user_id:
            raise ContractError("Kite profile does not match configured account")
        return result, {"authenticated": True, "configured_account_matches": True}

    check("broker_profile", profile)
    if rows[-1]["status"] != "PASS":
        return dict(broker="kite", passed=False, checks=rows)

    def master():
        state["instruments"] = provider.master.options(ReadBudget(timeout))
        return {}, dict(nifty_option_contracts=len(state["instruments"]))

    check("instrument_master", master)

    def snapshot():
        quotes = source.quotes([SPOT, VIX, *SECTORS.values(), *HEAVYWEIGHTS], ReadBudget(timeout))
        state["quotes"] = quotes
        spot = quotes[SPOT]
        underlying = {
            k: number(spot[k], minimum=0.01) for k in ("last_price", "open", "high", "low", "close")
        }
        underlying.update(symbol=SPOT, change_pct=_index(SPOT, spot)["change_pct"])
        result = dict(
            underlying=underlying,
            vix=_index(VIX, quotes[VIX]),
            sectors={key: _index(symbol, quotes[symbol]) for key, symbol in SECTORS.items()},
        )
        return result, dict(
            spot=underlying["last_price"],
            exchange_timestamp=_index(SPOT, spot)["timestamp"],
            market_status="CLOSED",
            quote_ready=False,
        )

    check("snapshot", snapshot, "snapshot")
    for name in ("vix", "sectors"):
        check(name, lambda name=name: (payloads["snapshot"][name], payloads["snapshot"][name]), name)

    def heavyweights():
        stocks = [
            {k: v for k, v in _index(symbol, state["quotes"][symbol]).items() if k != "timestamp"}
            for symbol in HEAVYWEIGHTS
        ]
        return {"stocks": stocks}, {"count": len(stocks)}

    check("heavyweights", heavyweights, "heavyweights")

    def candles():
        from datetime import timedelta

        now = MarketClock.now_ist()
        start = now.replace(hour=9, minute=15, second=0, microsecond=0) - timedelta(days=10)
        state["bars"] = completed_spot_bars(source.history(start, now, ReadBudget(timeout)), now)
        today = [bar for bar in state["bars"] if bar["start_time"].startswith(now.date().isoformat())]
        if len(today) != 375:
            raise MarketDataError("A complete current-day 375-minute spot session is unavailable")
        return {"candles": today}, dict(
            count=len(today), first=today[0]["start_time"], last=today[-1]["start_time"]
        )

    check("candles_1m", candles, "candles_1m")

    def five():
        bars = resample_five_minutes(state["bars"])[-50:]
        return {"candles": bars}, {"count": len(bars)}

    check("candles_5m", five, "candles_5m")
    check(
        "technicals_5m",
        lambda: (
            {"metrics": technical_metrics(payloads["candles_5m"]["candles"])},
            {"basis": "completed_5m_spot"},
        ),
        "technicals_5m",
    )

    def options():
        instruments = state["instruments"]
        expiry = min(c["expiry"] for c in instruments)
        atm = int(math.floor(payloads["snapshot"]["underlying"]["last_price"] / 50 + 0.5)) * 50
        contracts = [c for c in instruments if c["expiry"] == expiry and abs(c["strike"] - atm) <= 500]
        if len(contracts) != 42:
            raise MarketDataError("The requested 21-strike window is incomplete")
        quotes = source.option_quotes(contracts, expiry, ReadBudget(timeout))
        strikes = {strike: {"strike": strike} for strike in range(atm - 500, atm + 501, 50)}
        totals = {side: dict(oi=0.0, volume=0.0) for side in ("CE", "PE")}
        for contract in contracts:
            raw = quotes[contract["symbol"]]
            leg = dict(
                instrument_id=f"INST-NIFTY-{expiry}-{int(contract['strike'])}-{contract['right']}",
                symbol=contract["symbol"],
                ltp=number(raw["ltp"]),
                open_interest=number(raw["open_interest"]),
                oi_change=number(raw["oi_change"]),
            )
            strikes[contract["strike"]]["call" if contract["right"] == "CE" else "put"] = leg
            totals[contract["right"]]["oi"] += leg["open_interest"]
            totals[contract["right"]]["volume"] += number(raw["volume"])
        call, put = totals["CE"], totals["PE"]
        state["contracts"] = contracts
        result = dict(
            atm_strike=atm,
            expiry=expiry,
            strikes=[strikes[s] for s in sorted(strikes)],
            summary=dict(
                pcr_oi=put["oi"] / call["oi"] if call["oi"] else None,
                pcr_volume=put["volume"] / call["volume"] if call["volume"] else None,
            ),
        )
        return result, dict(expiry=expiry, atm_strike=atm, strikes=len(strikes))

    check("options", options, "options")

    def depth():
        started = time.monotonic()
        contract = state["contracts"][0]
        raw = source.depth(contract, ReadBudget(timeout))
        book = {
            side: [
                dict(price=number(level["price"]), quantity=number(level["quantity"]))
                for level in raw["depth"][side][:5]
            ]
            for side in ("buy", "sell")
        }
        bid, ask = book["buy"][0], book["sell"][0]
        if min(bid["price"], ask["price"], bid["quantity"], ask["quantity"]) <= 0:
            raise MarketDataError("Closed-market option book has no executable liquidity")
        result = dict(
            instrument_id=f"INST-NIFTY-{contract['expiry']}-{int(contract['strike'])}-{contract['right']}",
            symbol=contract["symbol"],
            best_bid=bid["price"],
            best_ask=ask["price"],
            best_bid_qty=bid["quantity"],
            best_ask_qty=ask["quantity"],
            depth=book,
            timestamp=exchange_time(raw["timestamp"]).isoformat(),
            status="CLOSED",
            request_started_monotonic=started,
            received_monotonic=time.monotonic(),
        )
        return result, dict(status="CLOSED", levels=len(book["buy"]))

    check("option_depth", depth, "option_depth")
    health = provider.get_data_quality(timeout=timeout)
    check(
        "data_quality",
        lambda: (health, dict(quote_ready=health["quote_ready"], status=health["market_feed"]["status"])),
        "data_quality",
    )
    if health["quote_ready"]:
        rows.append(
            dict(name="closed_market_entry_lock", status="FAIL", reason="Closed market reported quote-ready")
        )
    else:
        rows.append(
            dict(name="closed_market_entry_lock", status="PASS", detail={"new_entries_enabled": False})
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
        broker="kite",
        passed=all(row["status"] == "PASS" for row in rows),
        checks=rows,
        quote_ready=False,
        live_verified=False,
        diagnostic_mode="after_hours",
    )
