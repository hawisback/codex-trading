"""Explicit JSON contracts consumed by the engine; additional fields are allowed."""

from datetime import datetime
import math


class ContractError(ValueError):
    pass


def _check(value, schema, path):
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise ContractError(f"{path}: expected object")
        for key, child in schema.items():
            if key not in value:
                raise ContractError(f"{path}.{key}: missing required field")
            _check(value[key], child, f"{path}.{key}")
        return
    if isinstance(schema, list):
        if not isinstance(value, list) or not value:
            raise ContractError(f"{path}: expected nonempty array")
        for index, item in enumerate(value):
            _check(item, schema[0], f"{path}[{index}]")
        return
    if schema == "bool":
        valid = type(value) is bool
    elif schema in ("number", "positive", "nonnegative", "quantity"):
        valid = type(value) in (int, float) and math.isfinite(value)
        if valid and schema == "positive":
            valid = value > 0
        if valid and schema in ("nonnegative", "quantity"):
            valid = value >= 0
        if valid and schema == "quantity":
            valid = value == int(value)
    elif schema == "timestamp":
        valid = False
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                offset = parsed.utcoffset()
                valid = parsed.tzinfo is not None and offset is not None and offset.total_seconds() == 19800
            except ValueError:
                pass
    elif schema == "date":
        valid = False
        if isinstance(value, str):
            try:
                valid = datetime.strptime(value, "%Y-%m-%d").strftime("%Y-%m-%d") == value
            except ValueError:
                pass
    elif isinstance(schema, tuple):
        valid = value is None and schema[0] == "nullable"
        if not valid:
            _check(value, schema[1], path)
            return
    else:
        valid = isinstance(value, str) and bool(value.strip())
    if not valid:
        raise ContractError(f"{path}: invalid {schema}")


INDEX = {"symbol": "string", "last_price": "positive", "change_pct": "number", "timestamp": "timestamp"}
SECTORS = {key: INDEX for key in ("BANKNIFTY", "NIFTYIT")}
BAR = {
    "start_time": "timestamp",
    **{key: "positive" for key in ("open", "high", "low", "close")},
    "volume": "quantity",
}
LEG = {
    "instrument_id": "string",
    "symbol": "string",
    "ltp": "positive",
    "open_interest": "quantity",
    "oi_change": "number",
}
SCHEMAS = {
    "data_quality": {
        "quote_ready": "bool",
        "market_feed": {
            "status": "string",
            "latency_sec": "nonnegative",
            "last_tick_time": ("nullable", "timestamp"),
        },
    },
    "snapshot": {
        "underlying": {
            "symbol": "string",
            **{key: "positive" for key in ("last_price", "open", "high", "low", "close")},
            "change_pct": "number",
        },
        "vix": INDEX,
        "sectors": SECTORS,
    },
    "candles_1m": {"candles": [BAR]},
    "candles_5m": {"candles": [BAR]},
    "technicals_5m": {
        "metrics": {
            **{key: "positive" for key in ("ema_9", "ema_20", "ema_50")},
            **{key: "number" for key in ("rsi_14", "macd", "macd_histogram")},
            **{
                key: "bool"
                for key in ("macd_histogram_expanding_positive", "macd_histogram_expanding_negative")
            },
        }
    },
    "options": {
        "atm_strike": "positive",
        "expiry": "date",
        "summary": {"pcr_oi": ("nullable", "nonnegative"), "pcr_volume": ("nullable", "nonnegative")},
        "strikes": [{"strike": "positive", "call": LEG, "put": LEG}],
    },
    "heavyweights": {"stocks": [{"symbol": "string", "last_price": "positive", "change_pct": "number"}]},
    "vix": INDEX,
    "sectors": SECTORS,
    "option_depth": {
        "instrument_id": "string",
        "symbol": "string",
        "best_bid": "positive",
        "best_ask": "positive",
        "best_bid_qty": "quantity",
        "best_ask_qty": "quantity",
        "timestamp": "timestamp",
        "status": "string",
        "request_started_monotonic": "nonnegative",
        "received_monotonic": "nonnegative",
        "depth": {side: [{"price": "nonnegative", "quantity": "quantity"}] for side in ("buy", "sell")},
    },
}


def validate_market_contract(name, payload, *, require_live=True):
    """Check every required field/type and selected invariants, without coercion."""
    _check(payload, SCHEMAS[name], name)
    if name == "data_quality" and payload["quote_ready"] and payload["market_feed"]["last_tick_time"] is None:
        raise ContractError("data_quality: ready quotes require an exchange timestamp")
    if name == "snapshot" and payload["underlying"]["symbol"] != "NIFTY 50":
        raise ContractError("snapshot: expected NIFTY 50 spot identity")
    if name in ("snapshot", "vix"):
        vix = payload["vix"] if name == "snapshot" else payload
        if vix["symbol"] != "INDIA VIX":
            raise ContractError("vix: expected INDIA VIX identity")
    if name.startswith("candles_"):
        stamps = [bar["start_time"] for bar in payload["candles"]]
        if stamps != sorted(set(stamps)):
            raise ContractError(f"{name}: candles must be unique and chronological")
        for bar in payload["candles"]:
            if bar["low"] > min(bar["open"], bar["close"]) or bar["high"] < max(bar["open"], bar["close"]):
                raise ContractError(f"{name}: invalid OHLC range")
    if name == "technicals_5m" and not 0 <= payload["metrics"]["rsi_14"] <= 100:
        raise ContractError("technicals_5m: RSI must be within 0..100")
    if name == "heavyweights":
        symbols = [stock["symbol"] for stock in payload["stocks"]]
        if len(symbols) != 5 or set(symbols) != {"HDFCBANK", "RELIANCE", "ICICIBANK", "INFY", "TCS"}:
            raise ContractError("heavyweights: expected exactly the five configured constituents")
    if name == "options":
        strikes = [row["strike"] for row in payload["strikes"]]
        if strikes != sorted(set(strikes)) or payload["atm_strike"] not in strikes:
            raise ContractError("options: invalid strike order or missing ATM")
        for row in payload["strikes"]:
            for side, right in (("call", "CE"), ("put", "PE")):
                leg = row[side]
                expected = f"INST-NIFTY-{payload['expiry']}-{int(row['strike'])}-{right}"
                if leg["instrument_id"] != expected or leg["symbol"].startswith("INST-"):
                    raise ContractError("options: contract identity or native symbol mismatch")
    if name == "option_depth":
        if (
            (require_live and payload["status"] != "LIVE")
            or payload["best_bid"] > payload["best_ask"]
            or min(payload["best_bid_qty"], payload["best_ask_qty"]) <= 0
        ):
            raise ContractError("option_depth: non-executable book")
        for side, prefix in (("buy", "bid"), ("sell", "ask")):
            top = payload["depth"][side][0]
            if top["price"] != payload[f"best_{prefix}"] or top["quantity"] != payload[f"best_{prefix}_qty"]:
                raise ContractError("option_depth: top level differs from executable quote")
    return True
