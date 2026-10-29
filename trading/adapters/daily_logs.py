"""IST runtime files and an append-only journal with rebuildable daily reports."""

import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import logging
import os
from pathlib import Path
import tempfile
from typing import Any

from execution_safety import TERMINAL, atomic_save, status
from market_clock import IST_TZ

TRADE_FIELDS = (
    "position_id",
    "mode",
    "account_id",
    "symbol",
    "instrument_id",
    "entry_time",
    "closed_observed_at",
    "quantity",
    "entry_order_ids",
    "sell_order_ids",
    "average_entry_price",
    "average_exit_price",
    "gross_pnl",
    "charges",
    "net_pnl",
    "exit_reason",
    "pnl_status",
)


class ISTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):
        instant = datetime.fromtimestamp(record.created, IST_TZ)
        return instant.strftime(datefmt) if datefmt else instant.isoformat(timespec="milliseconds")


class DailyRuntimeHandler(logging.Handler):
    """Route each record using its creation date, including delayed queue records."""

    def __init__(self, directory):
        super().__init__()
        self.directory = Path(directory)
        self.stream = None
        self.day = None

    def emit(self, record):
        day = datetime.fromtimestamp(record.created, IST_TZ).date().isoformat()
        if day != self.day:
            if self.stream is not None:
                self.stream.close()
            self.directory.mkdir(parents=True, exist_ok=True)
            self.stream = (self.directory / f"trader-{day}.log").open("a", encoding="utf-8")
            self.day = day
        assert self.stream is not None
        self.stream.write(self.format(record) + "\n")
        self.stream.flush()

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None
        super().close()


def _number(value):
    try:
        result = Decimal(str(value))
        return result if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def completed_trade(event):
    """Only balanced, terminal, explicitly confirmed fills count as a closed trade."""
    state = event.get("state", {})
    if state.get("quantity") != 0:
        return None
    normalized: dict[str, list[dict[str, Any]]] = {}
    for key in ("entries", "stops", "exits"):
        normalized[key] = []
        for order in state.get(key, []):
            if status(order) not in TERMINAL:
                return None
            raw_qty = order.get("filled_quantity")
            # A definitive rejection with no broker order is a known non-fill.
            qty = _number(0 if raw_qty is None and status(order) == "REJECTED" else raw_qty)
            if qty is None or qty < 0 or qty != qty.to_integral_value():
                return None
            if qty > 0 and not order.get("order_id"):
                return None
            normalized[key].append({**order, "filled_quantity": int(qty)})
    entries = [o for o in normalized["entries"] if o["filled_quantity"] > 0]
    sells = normalized["stops"] + normalized["exits"]
    orders = normalized["entries"] + sells
    confirmed = [o for o in orders if o["filled_quantity"] > 0]
    if not entries or len({o["order_id"] for o in confirmed}) != len(confirmed):
        return None
    quantities = {o["order_id"]: int(o["filled_quantity"]) for o in entries}
    if len(quantities) != len(entries) or any(q < 0 for q in quantities.values()):
        return None
    for order in sells:
        qty = int(order["filled_quantity"])
        ref = order.get("entry_order_id")
        if qty < 0 or (qty and ref not in quantities):
            return None
        if ref in quantities:
            quantities[ref] -= qty
    quantity = sum(int(o["filled_quantity"]) for o in entries)
    if quantity <= 0 or any(quantities.values()):
        return None

    def value(records):
        total = Decimal(0)
        for order in records:
            qty = int(order["filled_quantity"])
            if not qty:
                continue
            price = _number(order.get("average_price"))
            if price is None or price <= 0:
                return None
            total += price * qty
        return total

    cost, proceeds = value(entries), value(sells)
    gross = proceeds - cost if cost is not None and proceeds is not None else None
    charges: Decimal | None = Decimal(0)
    for order in orders:
        fee = _number(order.get("charges"))
        if fee is None and int(order["filled_quantity"]) > 0:
            charges = None
            break
        if fee is not None:
            if fee < 0:
                charges = None
                break
            charges += fee
    scope = state.get("scope", {})
    identity = json.dumps([scope, sorted(o["order_id"] for o in entries)], sort_keys=True)
    key = hashlib.sha256(identity.encode()).hexdigest()[:24]

    def money(value):
        return round(float(value), 2) if value is not None else None

    return {
        "position_id": key,
        "mode": scope.get("mode", "UNKNOWN"),
        "account_id": scope.get("account_id", ""),
        "symbol": state.get("symbol"),
        "instrument_id": state.get("instrument_id"),
        "entry_time": state.get("entry_time"),
        "closed_observed_at": event["timestamp"],
        "quantity": quantity,
        "entry_order_ids": ";".join(sorted(o["order_id"] for o in entries)),
        "sell_order_ids": ";".join(sorted(o["order_id"] for o in sells if int(o["filled_quantity"]) > 0)),
        "average_entry_price": money(cost / quantity) if cost is not None else None,
        "average_exit_price": money(proceeds / quantity) if proceeds is not None else None,
        "gross_pnl": money(gross),
        "charges": money(charges),
        "net_pnl": money(gross - charges) if gross is not None and charges is not None else None,
        "exit_reason": state.get("exit_reason") or "Broker-confirmed flat (stop/manual/recovered)",
        "pnl_status": "COMPLETE"
        if gross is not None and charges is not None
        else ("CHARGES_UNAVAILABLE" if gross is not None else "FILL_PRICES_UNAVAILABLE"),
    }


def _atomic_text(path, content):
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def rebuild_reports(directory):
    """Rebuild projections from source events; repeated closures update one row."""
    directory = Path(directory)
    trades = {}
    malformed = 0
    unreportable = 0
    path = directory / "events.jsonl"
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                item = json.loads(line)
                if item.get("event") == "position_closed":
                    trade = completed_trade(item)
                    if trade is not None:
                        trades[trade["position_id"]] = trade
                    else:
                        if any(
                            _number(o.get("filled_quantity"))
                            for o in item.get("state", {}).get("entries", [])
                        ):
                            unreportable += 1
            except (ValueError, TypeError, KeyError, AttributeError):
                malformed += 1
    rows = list(trades.values())
    content = io.StringIO(newline="")
    writer = csv.DictWriter(content, fieldnames=TRADE_FIELDS)
    writer.writeheader()
    writer.writerows(rows)
    _atomic_text(directory / "trades.csv", content.getvalue())
    totals = {}
    for mode in sorted({row["mode"] for row in rows}):
        selected = [r for r in rows if r["mode"] == mode]
        totals[mode] = {
            "completed_positions": len(selected),
            "gross_pnl": round(sum(r["gross_pnl"] for r in selected), 2)
            if all(r["gross_pnl"] is not None for r in selected)
            else None,
            "net_pnl": round(sum(r["net_pnl"] for r in selected), 2)
            if all(r["net_pnl"] is not None for r in selected)
            else None,
            "positions_missing_fill_prices": sum(r["gross_pnl"] is None for r in selected),
            "positions_missing_charges": sum(r["charges"] is None for r in selected),
        }
    summary = {
        "date_ist": directory.name,
        "by_mode": totals,
        "malformed_lines": malformed,
        "unreportable_closures": unreportable,
        "date_basis": "verified_close_observed_ist",
        "source": "events.jsonl",
        "currency": "INR",
    }
    atomic_save(directory / "summary.json", summary)
    return summary


class DailyJournalHandler(logging.Handler):
    def __init__(self, directory):
        super().__init__()
        self.directory = Path(directory)
        self._initialized_dates = set()

    def emit(self, record):
        payload = getattr(record, "audit_event", None)
        if payload is None:
            return
        instant = datetime.fromisoformat(payload["timestamp"])
        if instant.tzinfo is None:
            raise ValueError("Audit timestamp must include its timezone")
        directory = self.directory / "daily" / instant.astimezone(IST_TZ).date().isoformat()
        directory.mkdir(parents=True, exist_ok=True)
        item = {**payload, "run_id": record.run_id}
        # Recover a torn last line after a hard stop without discarding its bytes.
        path = directory / "events.jsonl"
        with path.open("a+b") as stream:
            if stream.tell():
                stream.seek(-1, os.SEEK_END)
                if stream.read(1) != b"\n":
                    stream.write(b"\n")
            stream.write((json.dumps(item, ensure_ascii=False, allow_nan=False, default=str) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        if item["event"] == "position_closed" or directory not in self._initialized_dates:
            rebuild_reports(directory)
            self._initialized_dates.add(directory)
