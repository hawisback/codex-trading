"""Workspace-local replay/historical inputs. Explicit sources never fall back to a DB."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
from trading.domain.market_data import exchange_time, number

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]


def workspace_path(path, *, root=WORKSPACE_ROOT):
    root = Path(root).resolve()
    path = Path(path)
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("Replay data must stay inside the workspace")
    return resolved


def read_workspace_json(path, *, root=WORKSPACE_ROOT):
    return json.loads(workspace_path(path, root=root).read_text(encoding="utf-8"))


@dataclass(frozen=True)
class HistoricalDay:
    spot_candles: list[dict[str, Any]]
    options_data: dict[str, list[dict[str, Any]]]
    is_synthetic_options: bool = False


class WorkspaceHistoricalSource:
    def __init__(self, path, *, root=WORKSPACE_ROOT):
        self.root = Path(root).resolve()
        self.path = workspace_path(path, root=root)

    def load_day(self, target_date):
        data = read_workspace_json(self.path, root=self.root)
        if data.get("target_date") != target_date:
            raise ValueError("Historical fixture date does not match requested session")
        return HistoricalDay(
            data["spot_candles"], data.get("options_data", {}), data.get("is_synthetic_options", False)
        )


@dataclass
class OptionHistory:
    """Verified contract identity and timestamps; direction alone is never a lookup key."""

    contracts: dict[tuple[int, str], dict[str, dict[str, Any]]]
    excluded_files: list[str]

    def bar(self, strike, direction, timestamp):
        return self.contracts.get((int(strike), direction), {}).get(exchange_time(timestamp).isoformat())

    def series(self, strike, direction):
        return list(self.contracts.get((int(strike), direction), {}).values())


def load_option_history(session, expiry, *, root=WORKSPACE_ROOT):
    """Read exact session/expiry/strike/right histories with explicit provenance.

    Legacy filenames omit expiry. Require an adjacent .meta.json rather than
    silently assuming which expiry was fetched. No synthetic-price fallback.
    """
    folder = workspace_path("data", root=root)
    contracts: dict[tuple[int, str], dict[str, dict[str, Any]]] = {}
    excluded: list[str] = []
    seen: dict[tuple[int, str], str] = {}
    ambiguous: set[tuple[int, str]] = set()
    for path in sorted(folder.glob(f"opt_{session.replace('-', '')}_*.json")):
        if path.name.endswith(".meta.json"):
            continue
        try:
            path = workspace_path(path, root=root)
            meta_path = workspace_path(path.with_suffix(".meta.json"), root=root)
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            _, file_session, file_strike, file_right = path.stem.split("_")
            raw_strike, right = number(meta["strike"], minimum=1), meta["right"]
            strike = int(raw_strike)
            if (
                meta["session"] != session
                or meta["expiry"] != expiry
                or raw_strike != strike
                or strike % 50
                or file_session != session.replace("-", "")
                or int(file_strike) != strike
                or file_right != right
                or right not in ("CE", "PE")
                or not meta.get("symbol")
            ):
                raise ValueError("Option contract metadata mismatch")
            rows = json.loads(path.read_text(encoding="utf-8"))
            indexed = {}
            for row in rows:
                stamp = exchange_time(row["start_time"])
                if stamp.date().isoformat() != session or stamp.second or stamp.microsecond:
                    raise ValueError("Option candle timestamp mismatch")
                if stamp.isoformat() in indexed:
                    raise ValueError("Duplicate option candle timestamp")
                clean = {key: number(row[key], minimum=0.01) for key in ("open", "high", "low", "close")}
                if (
                    not clean["low"]
                    <= min(clean["open"], clean["close"])
                    <= max(clean["open"], clean["close"])
                    <= clean["high"]
                ):
                    raise ValueError("Invalid option candle range")
                clean.update(start_time=stamp.isoformat(), volume=number(row.get("volume", 0), minimum=0))
                indexed[stamp.isoformat()] = clean
            key = (strike, right)
            if key in seen or key in ambiguous:
                contracts.pop(key, None)
                ambiguous.add(key)
                if key in seen and seen[key] not in excluded:
                    excluded.append(seen[key])
                raise ValueError("Ambiguous option history")
            seen[key] = path.name
            contracts[key] = dict(sorted(indexed.items()))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            excluded.append(path.name)
    return OptionHistory(contracts, excluded)
