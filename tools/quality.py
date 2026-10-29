"""Run lint, type and offline regression checks using the pinned development tools."""

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    if Path.cwd().resolve() != ROOT:
        print("Run quality checks from the repository root.", file=sys.stderr)
        return 1
    environment = dict(os.environ)
    vendor = ROOT / ".tools/vendor"
    if vendor.is_dir():
        environment["PYTHONPATH"] = str(vendor) + os.pathsep + environment.get("PYTHONPATH", "")
    commands = (
        ("format", [sys.executable, "-m", "ruff", "format", "--check", "trading", "tools", "tests"]),
        (
            "lint",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "trading",
                "tools",
                "tests",
                "entry_policy.py",
                "execution_safety.py",
            ],
        ),
        (
            "runtime lint",
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                "E9,F63,F7,F82",
                "nifty_trader_scheduler.py",
                "position_lifecycle.py",
                "execution_client.py",
                "ai_consultant.py",
                "market_clock.py",
                "backtest_engine.py",
                "market_intelligence.py",
                "run_market_context.py",
            ],
        ),
        ("types", [sys.executable, "-m", "mypy", "--config-file", "pyproject.toml"]),
        ("offline regression", [sys.executable, "-m", "tools.checks"]),
    )
    for name, command in commands:
        result = subprocess.run(command, env=environment)
        if result.returncode:
            print(f"Quality stage failed: {name}", file=sys.stderr)
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
