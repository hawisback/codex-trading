"""Compatibility entry point for causal hybrid decision research (NO AI/PnL).

The former hardcoded 18% stop simulation is retired. Use the real strategy and
rules consultation; historical companion verdicts and broker fills are unknown.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.replay_hybrid import main


def simulate_hybrid_with_stops():
    return main([])


if __name__ == "__main__":
    raise SystemExit(main())
