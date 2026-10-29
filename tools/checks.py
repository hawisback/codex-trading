"""Run explicit offline regression tests and static checks without optional tools.

Use `python -m tools.checks` from the repository root. Broad root-level test
discovery is deliberately avoided: several legacy test_*.py files are scripts
that perform network or historical-database work as soon as they are imported.
"""

import ast
from contextlib import ExitStack, contextmanager
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OFFLINE_TEST_MODULES = (
    "tests.test_regression",
    "tests.test_architecture",
)
PURE_BOUNDARIES = (
    "entry_policy.py",
    "ai_opportunity_radar.py",
    "ai_context_dossier.py",
    "trading/ports.py",
    "trading/models.py",
    "trading/domain/indicators.py",
    "trading/domain/states.py",
    "trading/domain/sizing.py",
    "trading/domain/intelligence.py",
    "trading/strategies/legacy.py",
    "trading/strategies/radar.py",
    "trading/strategies/registry.py",
    "trading/application/selection.py",
    "trading/replay.py",
    "trading/hybrid_research.py",
    "trading/domain/prices.py",
    "trading/domain/stop_loss.py",
    "trading/domain/order_book.py",
    "trading/domain/historical_execution.py",
    "trading/strategies/macd_momentum.py",
    "trading/domain/trailing.py",
    "trading/domain/market_data.py",
    "trading/domain/market_contracts.py",
    "trading/domain/volatility.py",
    "trading/domain/limits.py",
    "trading/application/position_monitor.py",
)
FORBIDDEN_IMPORTS = (
    "urllib",
    "requests",
    "http",
    "socket",
    "trading.adapters",
    "execution_client",
    "position_lifecycle",
    "nifty_trader_scheduler",
)


@contextmanager
def forbid_network():
    """Fail the overall check even if application code catches a blocked attempt."""
    attempts = []

    def blocked(*args, **kwargs):
        attempts.append(True)
        raise RuntimeError("Real network access is disabled in offline checks")

    with ExitStack() as stack:
        for target in (
            "urllib.request.urlopen",
            "socket.create_connection",
            "socket.socket.connect",
            "socket.socket.connect_ex",
        ):
            stack.enter_context(patch(target, side_effect=blocked))
        yield attempts


def static_checks(root=ROOT):
    errors = []
    files = list(root.glob("*.py"))
    for directory in ("trading", "tools", "tests"):
        files.extend((root / directory).rglob("*.py"))
    for path in sorted(files):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        except (SyntaxError, UnicodeError) as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
            continue
        if path.relative_to(root).as_posix() not in PURE_BOUNDARIES:
            continue
        for node in ast.walk(tree):
            imported = (
                [alias.name for alias in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            for name in imported:
                if any(name == banned or name.startswith(banned + ".") for banned in FORBIDDEN_IMPORTS):
                    errors.append(f"{path.relative_to(root)}:{node.lineno}: forbidden dependency {name}")
    return errors


def main():
    if Path.cwd().resolve() != ROOT:
        print("Run checks from the repository root; working directory was not changed.", file=sys.stderr)
        return 1
    errors = static_checks()
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    with forbid_network() as attempts:
        suite = unittest.defaultTestLoader.loadTestsFromNames(OFFLINE_TEST_MODULES)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    if attempts:
        print(f"Offline checks blocked {len(attempts)} unexpected network attempt(s).", file=sys.stderr)
    return 0 if result.wasSuccessful() and not attempts else 1


if __name__ == "__main__":
    sys.exit(main())
