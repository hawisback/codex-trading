"""Retired experimental hybrid PnL simulation; use causal decision review."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.replay_hybrid import main


def simulate_hybrid_ema9_trail():
    return main([])


if __name__ == "__main__":
    raise SystemExit(main())
